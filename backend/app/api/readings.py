from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Asset, Channel, Plant, Reading, User
from app.schemas.reading import ReadingCreate, ReadingResponse, PowerReadingResponse
from app.schemas.reading_summary import QCStatsResponse, ReadingSummaryResponse
from app.schemas.reading_aggregate import ReadingAggregateResponse
from app.api.deps import get_current_user, require_role, enforce_org_access


def normalize_power_value(raw_value: float, receive_unit: str | None) -> float:
    if raw_value is None:
        return 0.0
    u = (receive_unit or "").strip().lower()
    if u in ("w", "watt", "watts"):
        return raw_value / 1000.0
    if u in ("mw", "megawatt", "megawatts"):
        return raw_value * 1000.0
    # Heuristic for string inverter raw values > 500 stored as W despite kW label
    if raw_value > 500.0:
        return raw_value / 1000.0
    return raw_value



router = APIRouter(
    prefix="/readings",
    tags=["Readings"],
)


@router.get(
    "/qc",
    response_model=QCStatsResponse,
)
def get_qc_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve database Quality Check (QC) metrics for the user's organization."""
    active_channels_count = db.scalar(
        select(func.count(Channel.id))
        .join(Asset, Channel.asset_id == Asset.id)
        .join(Plant, Asset.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    ) or 0

    total_readings_count = db.scalar(
        select(func.count(Reading.ts))
        .join(Channel, Reading.channel_id == Channel.id)
        .join(Asset, Channel.asset_id == Asset.id)
        .join(Plant, Asset.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    ) or 0

    out_of_bounds_count = db.scalar(
        select(func.count(Reading.ts))
        .join(Channel, Reading.channel_id == Channel.id)
        .join(Asset, Channel.asset_id == Asset.id)
        .join(Plant, Asset.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id, Reading.value < 0)
    ) or 0

    return QCStatsResponse(
        total_readings=total_readings_count,
        active_channels=active_channels_count,
        cadence_integrity="15 Min" if active_channels_count > 0 else "N/A",
        ingestion_quality=100.0 if total_readings_count > 0 else 0.0,
        duplicates_count=0,
        out_of_bounds_count=out_of_bounds_count,
        hypertable_active=True,
    )


@router.post(
    "",
    response_model=ReadingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reading(
    reading: ReadingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    channel = db.get(Channel, reading.channel_id)
    if channel is None:
        channel = db.get(Channel, str(reading.channel_id))

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    if channel.asset and channel.asset.plant:
        enforce_org_access(current_user, channel.asset.plant.org_id)

    new_reading = Reading(
        channel_id=str(reading.channel_id),
        ts=reading.ts,
        value=reading.value,
        quality=reading.quality,
        ingestion_job_id=(
            str(reading.ingestion_job_id)
            if reading.ingestion_job_id is not None
            else None
        ),
    )

    db.add(new_reading)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reading already exists for this channel and timestamp",
        )

    db.refresh(new_reading)

    return ReadingResponse(
        channel_id=reading.channel_id,
        ts=new_reading.ts,
        value=float(new_reading.value),
        quality=new_reading.quality,
        ingestion_job_id=reading.ingestion_job_id,
    )


@router.get(
    "/summary",
    response_model=ReadingSummaryResponse,
)
def get_readings_summary(
    channel_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = db.get(Channel, channel_id)
    if channel is None:
        channel = db.get(Channel, str(channel_id))

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    if channel.asset and channel.asset.plant:
        enforce_org_access(current_user, channel.asset.plant.org_id)

    if start is not None and end is not None and start >= end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start must be before end",
        )

    query = select(
        func.count(Reading.value).label("reading_count"),
        func.avg(Reading.value).label("average_value"),
        func.min(Reading.value).label("minimum_value"),
        func.max(Reading.value).label("maximum_value"),
    ).where(
        (Reading.channel_id == channel_id) | (Reading.channel_id == str(channel_id))
    )

    if start is not None:
        query = query.where(
            Reading.ts >= start
        )

    if end is not None:
        query = query.where(
            Reading.ts <= end
        )

    result = db.execute(query).one()

    return ReadingSummaryResponse(
        channel_id=channel_id,
        start=start,
        end=end,
        reading_count=result.reading_count,
        average_value=(
            float(result.average_value)
            if result.average_value is not None
            else None
        ),
        minimum_value=(
            float(result.minimum_value)
            if result.minimum_value is not None
            else None
        ),
        maximum_value=(
            float(result.maximum_value)
            if result.maximum_value is not None
            else None
        ),
    )


@router.get(
    "/aggregate",
    response_model=list[ReadingAggregateResponse],
)
def get_readings_aggregate(
    channel_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    interval: str = "hour",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = db.get(Channel, channel_id)
    if channel is None:
        channel = db.get(Channel, str(channel_id))

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    if channel.asset and channel.asset.plant:
        enforce_org_access(current_user, channel.asset.plant.org_id)

    if start is None or end is None:
        min_max = db.execute(
            select(func.min(Reading.ts), func.max(Reading.ts)).where(
                (Reading.channel_id == channel_id) | (Reading.channel_id == str(channel_id))
            )
        ).first()
        if min_max and min_max[0] and min_max[1]:
            start = start or min_max[0]
            end = end or min_max[1]
        else:
            return []

    allowed_intervals = {
        "5min": 5,
        "15min": 15,
        "hour": 60,
        "day": 1440,
        "week": 10080,
    }

    if interval not in allowed_intervals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid interval. Use one of: 5min, 15min, hour, day, week",
        )

    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start must be before or equal to end",
        )

    view_map = {
        "5min": "readings_5min",
        "15min": "readings_15min",
        "hour": "readings_1hour",
        "day": "readings_1day",
        "week": "readings_1week",
    }

    dialect_name = db.bind.dialect.name
    results = None

    if dialect_name == "postgresql" and interval in view_map:
        view_name = view_map[interval]
        try:
            cagg_query = text(f"""
                SELECT bucket, reading_count, average_value, minimum_value, maximum_value
                FROM {view_name}
                WHERE (channel_id = :cid_uuid OR channel_id = :cid_str)
                  AND bucket >= :start
                  AND bucket <= :end
                ORDER BY bucket ASC
            """)
            cagg_res = db.execute(cagg_query, {
                "cid_uuid": channel_id,
                "cid_str": str(channel_id),
                "start": start,
                "end": end,
            }).all()
            if cagg_res:
                results = [
                    ReadingAggregateResponse(
                        channel_id=channel_id,
                        interval=interval,
                        start=row.bucket,
                        end=row.bucket,
                        reading_count=row.reading_count,
                        average_value=float(row.average_value) if row.average_value is not None else None,
                        minimum_value=float(row.minimum_value) if row.minimum_value is not None else None,
                        maximum_value=float(row.maximum_value) if row.maximum_value is not None else None,
                    )
                    for row in cagg_res
                ]
        except Exception:
            results = None

    if results is None:
        bucket_minutes = allowed_intervals[interval]
        if dialect_name == "postgresql":
            try:
                bucket_expression = func.time_bucket(
                    literal_column(f"INTERVAL '{bucket_minutes} minutes'"),
                    Reading.ts,
                )
            except Exception:
                bucket_seconds = bucket_minutes * 60
                bucket_expression = func.to_timestamp(
                    func.floor(func.extract("epoch", Reading.ts) / bucket_seconds) * bucket_seconds
                )
        else:
            bucket_seconds = bucket_minutes * 60
            bucket_expression = func.datetime(
                (func.strftime("%s", Reading.ts) / bucket_seconds) * bucket_seconds,
                "unixepoch",
            )

        query = (
            select(
                bucket_expression.label("bucket"),
                func.count(Reading.value).label("reading_count"),
                func.avg(Reading.value).label("average_value"),
                func.min(Reading.value).label("minimum_value"),
                func.max(Reading.value).label("maximum_value"),
            )
            .where(
                (Reading.channel_id == channel_id) | (Reading.channel_id == str(channel_id)),
                Reading.ts >= start,
                Reading.ts <= end,
            )
            .group_by(bucket_expression)
            .order_by(bucket_expression.asc())
        )

        rows = db.execute(query).all()
        results = [
            ReadingAggregateResponse(
                channel_id=channel_id,
                interval=interval,
                start=row.bucket,
                end=row.bucket,
                reading_count=row.reading_count,
                average_value=float(row.average_value) if row.average_value is not None else None,
                minimum_value=float(row.minimum_value) if row.minimum_value is not None else None,
                maximum_value=float(row.maximum_value) if row.maximum_value is not None else None,
            )
            for row in rows
        ]

    return results


@router.get(
    "/latest",
    response_model=ReadingResponse,
)
def get_latest_reading(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = db.get(Channel, channel_id)
    if channel is None:
        channel = db.get(Channel, str(channel_id))

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    if channel.asset and channel.asset.plant:
        enforce_org_access(current_user, channel.asset.plant.org_id)

    latest_reading = db.execute(
        select(Reading)
        .where(
            (Reading.channel_id == channel_id) | (Reading.channel_id == str(channel_id))
        )
        .order_by(Reading.ts.desc())
        .limit(1)
    ).scalars().first()

    if latest_reading is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No readings found for this channel",
        )

    return ReadingResponse(
        channel_id=UUID(str(latest_reading.channel_id)),
        ts=latest_reading.ts,
        value=float(latest_reading.value),
        quality=latest_reading.quality,
        ingestion_job_id=(
            UUID(str(latest_reading.ingestion_job_id))
            if latest_reading.ingestion_job_id
            else None
        ),
    )


@router.post(
    "/latest-batch",
    response_model=dict[str, ReadingResponse],
)
def get_latest_readings_batch(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve latest reading for multiple channel IDs in a single query."""
    raw_ids = body.get("channel_ids", [])
    if not raw_ids:
        return {}

    uuid_ids = []
    str_ids = []
    for cid in raw_ids:
        str_ids.append(str(cid))
        try:
            uuid_ids.append(UUID(str(cid)))
        except ValueError:
            pass

    subq = (
        select(
            Reading,
            func.row_number()
            .over(partition_by=Reading.channel_id, order_by=Reading.ts.desc())
            .label("rn"),
        )
        .where(
            (Reading.channel_id.in_(uuid_ids)) | (Reading.channel_id.in_(str_ids))
        )
        .subquery()
    )

    query = select(subq).where(subq.c.rn == 1)
    results = db.execute(query).all()

    response_map = {}
    for r in results:
        ch_id_str = str(r.channel_id)
        response_map[ch_id_str] = ReadingResponse(
            channel_id=UUID(ch_id_str),
            ts=r.ts,
            value=float(r.value),
            quality=r.quality,
            ingestion_job_id=UUID(str(r.ingestion_job_id)) if r.ingestion_job_id else None,
        )

    return response_map


@router.get(
    "/latest-power",
    response_model=PowerReadingResponse,
)
def get_latest_power_reading(
    channel_id: UUID,
    non_zero: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve the latest power telemetry reading, prioritizing useful non-zero daytime readings if requested."""
    channel = db.get(Channel, channel_id)
    if channel is None:
        channel = db.get(Channel, str(channel_id))

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    if channel.asset and channel.asset.plant:
        enforce_org_access(current_user, channel.asset.plant.org_id)

    query = select(Reading).where(
        (Reading.channel_id == channel_id) | (Reading.channel_id == str(channel_id)),
        Reading.quality == 0,
    )

    reading = None
    if non_zero:
        reading = db.execute(
            query.where(Reading.value > 0).order_by(Reading.ts.desc()).limit(1)
        ).scalars().first()

    if reading is None:
        reading = db.execute(
            query.order_by(Reading.ts.desc()).limit(1)
        ).scalars().first()

    if reading is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No readings found for this channel",
        )

    raw_val = float(reading.value)
    val_kw = normalize_power_value(raw_val, channel.receive_unit)

    return PowerReadingResponse(
        channel_id=UUID(str(channel.id)),
        timestamp=reading.ts,
        raw_value=raw_val,
        raw_unit=channel.receive_unit or "kW",
        value_kw=val_kw,
        value=val_kw,
        quality=reading.quality,
        source="database",
    )


@router.post(
    "/latest-power-batch",
    response_model=dict[str, PowerReadingResponse],
)
def get_latest_power_readings_batch(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve latest power telemetry readings for multiple channel IDs in batch."""
    raw_ids = body.get("channel_ids", [])
    non_zero = body.get("non_zero", True)
    if not raw_ids:
        return {}

    uuid_ids = []
    str_ids = []
    for cid in raw_ids:
        str_ids.append(str(cid))
        try:
            uuid_ids.append(UUID(str(cid)))
        except ValueError:
            pass

    channels = db.scalars(
        select(Channel).where(
            (Channel.id.in_(uuid_ids)) | (Channel.id.in_(str_ids))
        )
    ).all()

    response_map = {}
    for ch in channels:
        query = select(Reading).where(
            (Reading.channel_id == ch.id) | (Reading.channel_id == str(ch.id)),
            Reading.quality == 0,
        )

        reading = None
        if non_zero:
            reading = db.execute(
                query.where(Reading.value > 0).order_by(Reading.ts.desc()).limit(1)
            ).scalars().first()

        if reading is None:
            reading = db.execute(
                query.order_by(Reading.ts.desc()).limit(1)
            ).scalars().first()

        if reading is not None:
            raw_val = float(reading.value)
            val_kw = normalize_power_value(raw_val, ch.receive_unit)
            response_map[str(ch.id)] = PowerReadingResponse(
                channel_id=UUID(str(ch.id)),
                timestamp=reading.ts,
                raw_value=raw_val,
                raw_unit=ch.receive_unit or "kW",
                value_kw=val_kw,
                value=val_kw,
                quality=reading.quality,
                source="database",
            )

    return response_map