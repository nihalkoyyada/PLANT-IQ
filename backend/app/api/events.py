import csv
import io
import json
from datetime import datetime
from uuid import UUID
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Event, Plant, Asset, User
from app.schemas.event import EventCreate, EventResponse, EventImportSummary
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/events",
    tags=["Events"],
)


def parse_datetime_safe(dt_str: str) -> datetime:
    """Parse string datetime cleanly with multiple ISO and fallback formats."""
    s = dt_str.strip()
    if not s:
        raise ValueError("Empty timestamp string")
    
    # Try Python ISO format parsing first
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass

    raise ValueError(f"Invalid timestamp format: '{dt_str}'")


@router.get(
    "",
    response_model=List[EventResponse],
)
def get_events(
    plant_id: Optional[UUID] = Query(None, description="Filter events by plant ID"),
    asset_id: Optional[UUID] = Query(None, description="Filter events by asset ID"),
    severity: Optional[str] = Query(None, description="Filter events by severity"),
    event_type: Optional[str] = Query(None, description="Filter events by event type"),
    source: Optional[str] = Query(None, description="Filter events by source"),
    start_time_gte: Optional[datetime] = Query(None, description="Start time greater than or equal to"),
    end_time_lte: Optional[datetime] = Query(None, description="End time less than or equal to"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve operational events with org-scoped filtering."""
    query = (
        select(Event)
        .join(Plant, Event.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    )

    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plant not found",
            )
        enforce_org_access(current_user, plant.org_id)
        query = query.where(Event.plant_id == plant_id)

    if asset_id is not None:
        query = query.where(Event.asset_id == asset_id)

    if severity is not None:
        query = query.where(Event.severity == severity.lower())

    if event_type is not None:
        query = query.where(Event.event_type == event_type.lower())

    if source is not None:
        query = query.where(Event.source == source.lower())

    if start_time_gte is not None:
        query = query.where(Event.start_time >= start_time_gte)

    if end_time_lte is not None:
        query = query.where(Event.start_time <= end_time_lte)

    query = query.order_by(Event.start_time.desc()).offset(offset).limit(limit)

    results = db.execute(query).scalars().all()
    return results


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event(
    event_in: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Create a new operational event record."""
    plant = db.get(Plant, event_in.plant_id)
    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )
    enforce_org_access(current_user, plant.org_id)

    if event_in.asset_id is not None:
        asset = db.get(Asset, event_in.asset_id)
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Asset not found",
            )
        if asset.plant_id != event_in.plant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Asset does not belong to the specified plant",
            )

    new_event = Event(
        plant_id=event_in.plant_id,
        asset_id=event_in.asset_id,
        source=event_in.source.lower(),
        event_type=event_in.event_type.lower(),
        severity=event_in.severity.lower(),
        start_time=event_in.start_time,
        end_time=event_in.end_time,
        code=event_in.code,
        message=event_in.message,
        metadata_json=event_in.metadata,
    )

    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    return new_event


@router.post(
    "/import-csv",
    response_model=EventImportSummary,
    status_code=status.HTTP_200_OK,
)
async def import_events_csv(
    file: UploadFile = File(...),
    default_plant_id: Optional[UUID] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Bulk import events from a CSV file."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a CSV file",
        )

    content_bytes = await file.read()
    try:
        content_text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        content_text = content_bytes.decode("latin-1")

    stream = io.StringIO(content_text)
    reader = csv.DictReader(stream)

    if not reader.fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file is empty or missing headers",
        )

    # Normalize header names (lowercase, stripped)
    headers = [h.strip().lower() for h in reader.fieldnames if h]

    if "start_time" not in headers and "timestamp" not in headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file missing required column: 'start_time' or 'timestamp'",
        )

    if "message" not in headers and "description" not in headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file missing required column: 'message' or 'description'",
        )

    total_rows = 0
    imported_rows = 0
    failed_rows = 0
    validation_errors: List[dict] = []
    events_to_create: List[Event] = []

    # Pre-cache plant org validation to avoid repeated DB lookups
    validated_plants: dict[UUID, bool] = {}

    for row_idx, raw_row in enumerate(reader, start=2):
        total_rows += 1
        # Normalize row keys
        row = {k.strip().lower(): v.strip() for k, v in raw_row.items() if k and v is not None}

        row_errors: List[str] = []

        # 1. Resolve plant_id
        plant_id_str = row.get("plant_id")
        row_plant_id: Optional[UUID] = None
        if plant_id_str:
            try:
                row_plant_id = UUID(plant_id_str)
            except ValueError:
                row_errors.append(f"Invalid plant_id UUID: '{plant_id_str}'")
        elif default_plant_id is not None:
            row_plant_id = default_plant_id
        else:
            row_errors.append("Missing plant_id in CSV row and no default_plant_id provided")

        if row_plant_id is not None and row_plant_id not in validated_plants:
            plant = db.get(Plant, row_plant_id)
            if plant is None:
                validated_plants[row_plant_id] = False
                row_errors.append(f"Plant ID {row_plant_id} not found")
            elif plant.org_id != current_user.org_id:
                validated_plants[row_plant_id] = False
                row_errors.append(f"Plant ID {row_plant_id} belongs to a different organization")
            else:
                validated_plants[row_plant_id] = True

        if row_plant_id is not None and not validated_plants.get(row_plant_id, False):
            if not any("Plant ID" in e or "different organization" in e for e in row_errors):
                row_errors.append(f"Unauthorized or invalid plant_id: {row_plant_id}")

        # 2. Resolve asset_id (optional)
        asset_id_str = row.get("asset_id")
        row_asset_id: Optional[UUID] = None
        if asset_id_str:
            try:
                row_asset_id = UUID(asset_id_str)
                asset = db.get(Asset, row_asset_id)
                if asset is None:
                    row_errors.append(f"Asset ID {row_asset_id} not found")
                elif row_plant_id and asset.plant_id != row_plant_id:
                    row_errors.append(f"Asset {row_asset_id} does not belong to plant {row_plant_id}")
            except ValueError:
                row_errors.append(f"Invalid asset_id UUID: '{asset_id_str}'")

        # 3. Resolve start_time
        start_time_raw = row.get("start_time") or row.get("timestamp")
        start_dt: Optional[datetime] = None
        if not start_time_raw:
            row_errors.append("Missing required start_time or timestamp")
        else:
            try:
                start_dt = parse_datetime_safe(start_time_raw)
            except ValueError as e:
                row_errors.append(str(e))

        # 4. Resolve end_time (optional)
        end_time_raw = row.get("end_time")
        end_dt: Optional[datetime] = None
        if end_time_raw:
            try:
                end_dt = parse_datetime_safe(end_time_raw)
            except ValueError as e:
                row_errors.append(f"End time error: {e}")

        # 5. Resolve message
        message = row.get("message") or row.get("description")
        if not message:
            row_errors.append("Missing required message or description")

        if row_errors:
            failed_rows += 1
            validation_errors.append({
                "row": row_idx,
                "error": "; ".join(row_errors),
                "data": row,
            })
            continue

        # Build metadata dict for extra fields
        known_keys = {
            "plant_id", "asset_id", "source", "event_type", "severity",
            "start_time", "timestamp", "end_time", "code", "message",
            "description", "metadata"
        }
        metadata_dict = {}
        
        # Check if explicit metadata JSON column was provided
        if "metadata" in row and row["metadata"]:
            try:
                metadata_dict = json.loads(row["metadata"])
            except Exception:
                metadata_dict = {"raw": row["metadata"]}

        # Add extra unparsed columns to metadata
        for k, v in row.items():
            if k not in known_keys and v:
                metadata_dict[k] = v

        event = Event(
            plant_id=row_plant_id,
            asset_id=row_asset_id,
            source=row.get("source", "scada").lower(),
            event_type=row.get("event_type", "fault").lower(),
            severity=row.get("severity", "info").lower(),
            start_time=start_dt,
            end_time=end_dt,
            code=row.get("code"),
            message=message,
            metadata_json=metadata_dict,
        )
        events_to_create.append(event)
        imported_rows += 1

    if events_to_create:
        db.add_all(events_to_create)
        db.commit()

    return EventImportSummary(
        total_rows=total_rows,
        imported_rows=imported_rows,
        failed_rows=failed_rows,
        validation_errors=validation_errors,
    )
