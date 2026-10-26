from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Detector, Plant, CanonicalSignal, User
from app.schemas.detector import DetectorCreate, DetectorUpdate, DetectorResponse
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/detectors",
    tags=["Detectors"],
)


@router.get(
    "",
    response_model=List[DetectorResponse],
)
def get_detectors(
    plant_id: Optional[UUID] = Query(default=None, description="Optional plant filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List anomaly detectors for user organization."""
    query = (
        select(Detector)
        .join(Plant, Detector.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    )
    if plant_id is not None:
        query = query.where(Detector.plant_id == plant_id)

    result = db.execute(query.order_by(Detector.created_at.desc()))
    return result.scalars().all()


@router.get(
    "/{detector_id}",
    response_model=DetectorResponse,
)
def get_detector(
    detector_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a specific anomaly detector configuration."""
    detector = db.get(Detector, detector_id)
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detector not found",
        )

    enforce_org_access(current_user, detector.plant.org_id)
    return detector


@router.post(
    "",
    response_model=DetectorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_detector(
    detector_in: DetectorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Create a new anomaly detector configuration."""
    plant = db.get(Plant, detector_in.plant_id)
    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    canonical_signal = db.get(CanonicalSignal, detector_in.canonical_key)
    if canonical_signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canonical signal not found",
        )

    new_detector = Detector(
        plant_id=detector_in.plant_id,
        name=detector_in.name,
        method=detector_in.method,
        canonical_key=detector_in.canonical_key,
        asset_scope=detector_in.asset_scope,
        parameters=detector_in.parameters,
        condition_text=detector_in.condition_text,
        enabled=detector_in.enabled,
    )

    db.add(new_detector)
    db.commit()
    db.refresh(new_detector)
    return new_detector


@router.put(
    "/{detector_id}",
    response_model=DetectorResponse,
)
@router.patch(
    "/{detector_id}",
    response_model=DetectorResponse,
)
def update_detector(
    detector_id: UUID,
    detector_update: DetectorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Update an existing anomaly detector configuration."""
    detector = db.get(Detector, detector_id)
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detector not found",
        )

    enforce_org_access(current_user, detector.plant.org_id)

    update_data = detector_update.model_dump(exclude_unset=True)

    if "canonical_key" in update_data and update_data["canonical_key"] is not None:
        canonical_signal = db.get(CanonicalSignal, update_data["canonical_key"])
        if canonical_signal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical signal not found",
            )

    for field, value in update_data.items():
        if hasattr(detector, field) and value is not None:
            setattr(detector, field, value)

    db.commit()
    db.refresh(detector)
    return detector


@router.delete(
    "/{detector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_detector(
    detector_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Delete an anomaly detector configuration."""
    detector = db.get(Detector, detector_id)
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detector not found",
        )

    enforce_org_access(current_user, detector.plant.org_id)

    db.delete(detector)
    db.commit()
    return None


@router.post(
    "/{detector_id}/run",
    status_code=status.HTTP_200_OK,
)
def run_detector(
    detector_id: UUID,
    window_hours: int = Query(default=24, ge=1, le=168),
    is_backfill: bool = Query(default=False, description="Explicit historical backfill/replay mode"),
    dry_run: bool = Query(default=False, description="Preview candidates without committing database changes"),
    start_time: Optional[datetime] = Query(default=None, description="Explicit scan start time"),
    end_time: Optional[datetime] = Query(default=None, description="Explicit scan end time"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Execute on-demand anomaly detection scan for a specific detector."""
    from datetime import datetime, timedelta, timezone
    from app.ai.anomaly_dedup import persist_and_deduplicate_anomalies
    from app.ai.detector_registry import DetectorContext, DetectorRegistry
    from app.models.entities import Asset, Channel, Reading

    detector = db.get(Detector, detector_id)
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detector not found",
        )

    enforce_org_access(current_user, detector.plant.org_id)

    if not DetectorRegistry.has_detector(detector.method):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Method '{detector.method}' is not registered in detector engine",
        )

    detector_instance = DetectorRegistry.get(detector.method)
    from sqlalchemy import func
    from app.ai.anomaly_service import AnomalyCalculationService

    now_utc = datetime.now(timezone.utc)
    max_ts = db.execute(
        select(func.max(Reading.ts))
        .join(Channel, Reading.channel_id == Channel.id)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(Asset.plant_id == detector.plant_id)
    ).scalar()
    if max_ts and max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    # Telemetry data freshness & staleness check
    is_stale = False
    stale_days = None
    if max_ts:
        stale_days = (now_utc - max_ts).days
        is_stale = stale_days > 7
    else:
        is_stale = True

    # Window Selection:
    if start_time is not None and end_time is not None:
        start_window = start_time.replace(tzinfo=timezone.utc) if start_time.tzinfo is None else start_time
        anchor_time = end_time.replace(tzinfo=timezone.utc) if end_time.tzinfo is None else end_time
    elif is_backfill is True:
        anchor_time = end_time if end_time is not None else (max_ts if max_ts else now_utc)
        start_window = start_time if start_time is not None else (anchor_time - timedelta(hours=window_hours))
    elif is_backfill is False:
        if is_stale:
            return {
                "detector_id": str(detector_id),
                "detector_name": detector.name,
                "method": detector.method,
                "status": "stale_data",
                "data_freshness": "stale",
                "latest_telemetry_ts": max_ts.isoformat() if max_ts else None,
                "stale_days": stale_days,
                "message": "Routine scan aborted: latest telemetry is older than 7 days. Use is_backfill=true to scan historical telemetry.",
                "assets_scanned": 0,
                "anomalies_detected": 0,
                "anomalies_created": 0,
                "anomalies_merged": 0,
            }
        anchor_time = now_utc
        start_window = now_utc - timedelta(hours=window_hours)
    else:
        anchor_time = max_ts if (max_ts and (now_utc - max_ts).days > 7) else now_utc
        start_window = anchor_time - timedelta(hours=window_hours)

    # Fetch irradiance weather reference if available
    irradiance_map = {}
    weather_channel_keys = [
        "irradiance_poa",
        "poa_irradiance",
        "irradiance_ghi",
        "ghi_irradiance",
        "irradiation",
        "irradiance",
        "weather_irradiance",
    ]
    weather_channels = (
        db.execute(
            select(Channel)
            .join(Asset, Channel.asset_id == Asset.id)
            .where(
                Asset.plant_id == detector.plant_id,
                Channel.canonical_key.in_(weather_channel_keys),
            )
        )
        .scalars()
        .all()
    )
    if weather_channels:
        chosen_channel = None
        for ch in weather_channels:
            if "poa" in ch.canonical_key.lower():
                chosen_channel = ch
                break
        if not chosen_channel:
            chosen_channel = weather_channels[0]

        irr_readings = (
            db.execute(
                select(Reading)
                .where(
                    Reading.channel_id == chosen_channel.id,
                    Reading.ts >= start_window,
                )
                .order_by(Reading.ts.asc())
            )
            .scalars()
            .all()
        )
        for r in irr_readings:
            ts_utc = r.ts.replace(tzinfo=timezone.utc) if r.ts.tzinfo is None else r.ts
            val = float(r.value)
            if 0.0 < val <= 2.5 or (chosen_channel.receive_unit and "kw" in chosen_channel.receive_unit.lower()):
                val *= 1000.0
            irradiance_map[ts_utc] = val

    scope = detector.asset_scope or {}
    target_asset_type = scope.get("asset_type", "inverter")

    assets_query = select(Asset).where(Asset.plant_id == detector.plant_id)
    if target_asset_type:
        assets_query = assets_query.where(Asset.asset_type == target_asset_type)
    if "asset_ids" in scope and scope["asset_ids"]:
        assets_query = assets_query.where(Asset.id.in_([UUID(a) for a in scope["asset_ids"]]))

    assets = db.execute(assets_query).scalars().all()

    total_detected = 0
    total_created = 0
    total_merged = 0
    evaluated_asset_ids: set[UUID] = set()

    for asset in assets:
        channel = (
            db.execute(
                select(Channel).where(
                    Channel.asset_id == asset.id,
                    Channel.canonical_key == detector.canonical_key,
                )
            )
            .scalars()
            .first()
        )
        if not channel:
            continue

        readings = (
            db.execute(
                select(Reading)
                .where(
                    Reading.channel_id == channel.id,
                    Reading.ts >= start_window,
                )
                .order_by(Reading.ts.asc())
            )
            .scalars()
            .all()
        )
        if len(readings) < 4:
            continue

        observations = [(r.ts, float(r.value)) for r in readings]
        asset_rated_kw = AnomalyCalculationService.resolve_asset_rated_kw(db, asset, detector.plant)

        context = DetectorContext(
            plant_id=detector.plant_id,
            asset_id=asset.id,
            channel_id=channel.id,
            canonical_key=detector.canonical_key,
            plant_name=detector.plant.name,
            asset_name=asset.name,
            asset_type=asset.asset_type,
            rated_kw=asset_rated_kw,
            capacity_dc_kwp=detector.plant.capacity_dc_kwp,
            expected_pr=detector.plant.expected_pr or 0.80,
            tariff_inr_per_kwh=detector.plant.tariff_inr_per_kwh,
            irradiance_reference=irradiance_map,
            latitude=detector.plant.latitude,
            longitude=detector.plant.longitude,
        )

        evaluated_asset_ids.add(asset.id)

        candidates = detector_instance.detect(
            observations=observations,
            parameters=detector.parameters or {},
            context=context,
        )

        if candidates:
            _, created, merged = persist_and_deduplicate_anomalies(
                db=db,
                candidates=candidates,
                context=context,
                detector_id=detector.id,
            )
            total_detected += len(candidates)
            total_created += created
            total_merged += merged

    if dry_run:
        db.rollback()

    return {
        "detector_id": str(detector_id),
        "detector_name": detector.name,
        "method": detector.method,
        "status": "dry_run" if dry_run else "success",
        "is_dry_run": dry_run,
        "data_freshness": "stale" if is_stale else "fresh",
        "latest_telemetry_ts": max_ts.isoformat() if max_ts else None,
        "scan_start": start_window.isoformat(),
        "scan_end": anchor_time.isoformat(),
        "assets_scanned": len(evaluated_asset_ids),
        "anomalies_detected": total_detected,
        "anomalies_created": total_created,
        "anomalies_merged": total_merged,
    }

