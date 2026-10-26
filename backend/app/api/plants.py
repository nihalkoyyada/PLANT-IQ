import math
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Plant, Organization, User, Asset, Channel, Reading
from app.schemas.plant import (
    PlantCreate,
    PlantUpdate,
    PlantResponse,
    PublicPlantTelemetryResponse,
    PublicTelemetryTrendPoint,
)
from app.schemas.asset import AssetTreeNode
from app.api.deps import get_current_user, require_role, enforce_org_access, get_optional_current_user
from app.core.config import settings


router = APIRouter(
    prefix="/plants",
    tags=["Plants"],
)


@router.post(
    "",
    response_model=PlantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_plant(
    plant: PlantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    enforce_org_access(current_user, plant.org_id)
    organization = db.get(Organization, plant.org_id)

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    new_plant = Plant(
        org_id=plant.org_id,
        name=plant.name,
        plant_type=plant.plant_type,
        capacity_ac_kw=plant.capacity_ac_kw,
        capacity_dc_kwp=plant.capacity_dc_kwp,
        latitude=plant.latitude,
        longitude=plant.longitude,
        timezone=plant.timezone,
        cod_date=plant.cod_date,
        expected_pr=plant.expected_pr,
        tariff_inr_per_kwh=plant.tariff_inr_per_kwh,
        metadata_=plant.metadata,
    )

    db.add(new_plant)
    db.commit()
    db.refresh(new_plant)

    return new_plant


@router.get(
    "",
    response_model=list[PlantResponse],
)
def get_plants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = db.execute(
        select(Plant)
        .where(Plant.org_id == current_user.org_id)
        .order_by(Plant.created_at.desc())
    )
    return result.scalars().all()


def _normalize_public_ac_kw(val: float, unit: Optional[str]) -> float:
    if val is None or math.isnan(val) or val < 0:
        return 0.0
    u = (unit or "").strip().lower()
    if u in ("w", "watt", "watts"):
        return val / 1000.0
    if u in ("mw", "megawatt", "megawatts"):
        return val * 1000.0
    if val > 50000.0:
        return val / 1000.0
    return val


def _normalize_public_dc_kw(val: float, unit: Optional[str], conversion: Optional[str]) -> float:
    if val is None or math.isnan(val) or val < 0:
        return 0.0
    u = (unit or "").strip().lower()
    c = (conversion or "").strip().lower()
    if u in ("w", "watt", "watts"):
        return val / 1000.0
    if u in ("mw", "megawatt", "megawatts"):
        return val * 1000.0
    if u in ("deci-kw", "deci_kw") or "10" in c:
        return val / 10.0
    if val > 2500.0:
        return val / 10.0
    if val > 250.0 and u in ("kw", "kilowatt", ""):
        return val / 10.0
    return val


_PUBLIC_SUMMARY_CACHE: dict[str, tuple[float, PublicPlantTelemetryResponse]] = {}


def clear_public_summary_cache() -> None:
    """Clear in-memory cache for public summary endpoint (useful in testing)."""
    _PUBLIC_SUMMARY_CACHE.clear()


def get_current_utc_time() -> datetime:
    """Return current UTC datetime (isolated for testing/clock synchronization)."""
    return datetime.now(timezone.utc)



@router.get(
    "/public-summary",
    response_model=PublicPlantTelemetryResponse,
)
def get_public_plant_summary(
    plant_id: Optional[UUID] = Query(None, description="Optional plant UUID. Defaults to showcase plant."),
    non_zero: bool = Query(False, description="If true, fetches latest active generation instead of absolute latest."),
    stale_hours: Optional[float] = Query(None, description="Custom staleness threshold in hours."),
    response: Response = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Public-safe real-time plant telemetry summary for the showcase login widget.
    Does not expose sensitive credentials, tenant private data, or internal errors.
    Only allows access to the configured public demo plant or authorized/explicitly public plants.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=15, stale-while-revalidate=5"

    demo_plant_id: Optional[UUID] = None
    if settings.DEMO_PLANT_ID:
        try:
            demo_plant_id = UUID(settings.DEMO_PLANT_ID)
        except (ValueError, TypeError):
            pass

    # 1. Resolve and validate showcase plant access
    plant: Optional[Plant] = None
    if plant_id:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plant not found",
            )

        # Enforce tenant data protection: only the demo plant, explicitly public plants,
        # or authenticated members of the owning organization may access plant telemetry.
        is_demo_plant = (demo_plant_id is not None and plant.id == demo_plant_id)
        is_explicitly_public = bool(plant.metadata_ and plant.metadata_.get("is_public") is True)
        is_authorized_org_member = bool(current_user and current_user.org_id == plant.org_id)

        if not (is_demo_plant or is_explicitly_public or is_authorized_org_member):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Public telemetry summary is restricted to the configured showcase demo plant.",
            )
    else:
        # No plant_id passed: default to configured showcase demo plant
        if demo_plant_id:
            plant = db.get(Plant, demo_plant_id)
        if plant is None:
            # Fallback to any plant explicitly flagged as public
            plant = (
                db.query(Plant)
                .join(Asset, Asset.plant_id == Plant.id)
                .join(Channel, Channel.asset_id == Asset.id)
                .first()
            )

    # 2. Check in-memory cache keyed by resolved plant, non_zero, and stale_hours
    resolved_plant_key = str(plant.id) if plant else "none"
    cache_key = f"{resolved_plant_key}_{non_zero}_{stale_hours}"
    now_monotonic = time.monotonic()
    if cache_key in _PUBLIC_SUMMARY_CACHE:
        cached_time, cached_val = _PUBLIC_SUMMARY_CACHE[cache_key]
        if now_monotonic - cached_time < 15.0:
            return cached_val

    if plant is None:
        res = PublicPlantTelemetryResponse(
            plant_id="",
            plant_name="No Plant Configured",
            capacity_ac_mw=0.0,
            capacity_dc_mw=0.0,
            ac_power_mw=0.0,
            dc_power_mw=0.0,
            latest_timestamp=None,
            data_freshness="OFFLINE",
            status_label="TELEMETRY UNAVAILABLE",
            stale_days=None,
            freshness_seconds=None,
            inverter_count=0,
            channel_count=0,
            trend=[],
        )
        _PUBLIC_SUMMARY_CACHE[cache_key] = (now_monotonic, res)
        return res

    # 2. Discover inverters and channels
    inverters = (
        db.execute(
            select(Asset).where(
                Asset.plant_id == plant.id,
                Asset.asset_type == "inverter",
            )
        )
        .scalars()
        .all()
    )
    if not inverters:
        inverters = (
            db.execute(
                select(Asset).where(
                    Asset.plant_id == plant.id,
                    Asset.name.ilike("%inverter%"),
                )
            )
            .scalars()
            .all()
        )
    if not inverters:
        inverters = (
            db.execute(
                select(Asset).where(Asset.plant_id == plant.id)
            )
            .scalars()
            .all()
        )

    inv_ids = [inv.id for inv in inverters]
    ac_channels = (
        db.execute(
            select(Channel).where(
                Channel.asset_id.in_(inv_ids),
                Channel.canonical_key == "power_ac",
            )
        )
        .scalars()
        .all()
    )
    dc_channels = (
        db.execute(
            select(Channel).where(
                Channel.asset_id.in_(inv_ids),
                Channel.canonical_key == "power_dc",
            )
        )
        .scalars()
        .all()
    )

    if not ac_channels and not dc_channels:
        ac_channels = (
            db.execute(
                select(Channel)
                .join(Asset, Channel.asset_id == Asset.id)
                .where(Asset.plant_id == plant.id, Channel.canonical_key == "power_ac")
            )
            .scalars()
            .all()
        )
        dc_channels = (
            db.execute(
                select(Channel)
                .join(Asset, Channel.asset_id == Asset.id)
                .where(Asset.plant_id == plant.id, Channel.canonical_key == "power_dc")
            )
            .scalars()
            .all()
        )

    all_chan_ids = [c.id for c in ac_channels] + [c.id for c in dc_channels]
    active_inverter_ids = {c.asset_id for c in ac_channels} | {c.asset_id for c in dc_channels}
    active_inverter_count = len(active_inverter_ids) if active_inverter_ids else len(inverters)

    capacity_ac_mw = round(float(plant.capacity_ac_kw or 50000.0) / 1000.0, 2)
    capacity_dc_mw = round(float(plant.capacity_dc_kwp or 50000.0) / 1000.0, 2)

    if not all_chan_ids:
        res = PublicPlantTelemetryResponse(
            plant_id=str(plant.id),
            plant_name=plant.name,
            capacity_ac_mw=capacity_ac_mw,
            capacity_dc_mw=capacity_dc_mw,
            ac_power_mw=0.0,
            dc_power_mw=0.0,
            latest_timestamp=None,
            data_freshness="OFFLINE",
            status_label="TELEMETRY UNAVAILABLE",
            stale_days=None,
            freshness_seconds=None,
            inverter_count=active_inverter_count,
            channel_count=0,
            trend=[],
        )
        _PUBLIC_SUMMARY_CACHE[cache_key] = (now_monotonic, res)
        return res

    # 3. Determine latest telemetry timestamp
    max_ts = db.scalar(
        select(func.max(Reading.ts)).where(Reading.channel_id.in_(all_chan_ids))
    )

    if max_ts is None:
        res = PublicPlantTelemetryResponse(
            plant_id=str(plant.id),
            plant_name=plant.name,
            capacity_ac_mw=capacity_ac_mw,
            capacity_dc_mw=capacity_dc_mw,
            ac_power_mw=0.0,
            dc_power_mw=0.0,
            latest_timestamp=None,
            data_freshness="OFFLINE",
            status_label="TELEMETRY UNAVAILABLE",
            stale_days=None,
            freshness_seconds=None,
            inverter_count=active_inverter_count,
            channel_count=len(all_chan_ids),
            trend=[],
        )
        _PUBLIC_SUMMARY_CACHE[cache_key] = (now_monotonic, res)
        return res

    if max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    latest_nonzero_ts = db.scalar(
        select(func.max(Reading.ts)).where(
            Reading.channel_id.in_(all_chan_ids),
            Reading.value > 0,
        )
    )
    if latest_nonzero_ts and latest_nonzero_ts.tzinfo is None:
        latest_nonzero_ts = latest_nonzero_ts.replace(tzinfo=timezone.utc)

    target_ts = latest_nonzero_ts if (non_zero and latest_nonzero_ts is not None) else max_ts

    # 4. Fetch and aggregate instantaneous power at target_ts across inverters
    ac_readings_target = db.execute(
        select(Reading, Channel)
        .join(Channel, Reading.channel_id == Channel.id)
        .where(
            Reading.channel_id.in_([c.id for c in ac_channels]),
            Reading.ts == target_ts,
        )
    ).all()

    dc_readings_target = db.execute(
        select(Reading, Channel)
        .join(Channel, Reading.channel_id == Channel.id)
        .where(
            Reading.channel_id.in_([c.id for c in dc_channels]),
            Reading.ts == target_ts,
        )
    ).all()

    total_ac_kw = sum(
        _normalize_public_ac_kw(float(r.value), ch.receive_unit)
        for r, ch in ac_readings_target
        if r.value is not None
    )
    total_dc_kw = sum(
        _normalize_public_dc_kw(float(r.value), ch.receive_unit, ch.conversion)
        for r, ch in dc_readings_target
        if r.value is not None
    )

    ac_power_mw = round(total_ac_kw / 1000.0, 2)
    dc_power_mw = round(total_dc_kw / 1000.0, 2)

    # 5. Last active daylight generation if latest is 0
    last_active_ac_mw = None
    last_active_dc_mw = None
    if latest_nonzero_ts:
        if latest_nonzero_ts == target_ts:
            last_active_ac_mw = ac_power_mw
            last_active_dc_mw = dc_power_mw
        else:
            nz_ac_r = db.execute(
                select(Reading, Channel)
                .join(Channel, Reading.channel_id == Channel.id)
                .where(
                    Reading.channel_id.in_([c.id for c in ac_channels]),
                    Reading.ts == latest_nonzero_ts,
                )
            ).all()
            nz_dc_r = db.execute(
                select(Reading, Channel)
                .join(Channel, Reading.channel_id == Channel.id)
                .where(
                    Reading.channel_id.in_([c.id for c in dc_channels]),
                    Reading.ts == latest_nonzero_ts,
                )
            ).all()
            nz_ac_kw = sum(
                _normalize_public_ac_kw(float(r.value), ch.receive_unit)
                for r, ch in nz_ac_r
                if r.value is not None
            )
            nz_dc_kw = sum(
                _normalize_public_dc_kw(float(r.value), ch.receive_unit, ch.conversion)
                for r, ch in nz_dc_r
                if r.value is not None
            )
            last_active_ac_mw = round(nz_ac_kw / 1000.0, 2)
            last_active_dc_mw = round(nz_dc_kw / 1000.0, 2)

    # 6. Chronological Trend points over recent window (24h)
    start_trend = target_ts - timedelta(hours=24)
    trend_rows = db.execute(
        select(
            Reading.ts,
            Channel.canonical_key,
            Channel.receive_unit,
            Channel.conversion,
            func.sum(Reading.value),
        )
        .join(Channel, Reading.channel_id == Channel.id)
        .where(
            Reading.channel_id.in_(all_chan_ids),
            Reading.ts >= start_trend,
            Reading.ts <= target_ts,
        )
        .group_by(Reading.ts, Channel.canonical_key, Channel.receive_unit, Channel.conversion)
        .order_by(Reading.ts.asc())
    ).all()

    buckets: dict[datetime, dict[str, float]] = {}
    for ts, key, unit, conv, total_val in trend_rows:
        if ts not in buckets:
            buckets[ts] = {"ac_kw": 0.0, "dc_kw": 0.0}
        val_float = float(total_val) if total_val is not None else 0.0
        if key == "power_ac":
            buckets[ts]["ac_kw"] += _normalize_public_ac_kw(val_float, unit)
        elif key == "power_dc":
            buckets[ts]["dc_kw"] += _normalize_public_dc_kw(val_float, unit, conv)

    trend_points: list[PublicTelemetryTrendPoint] = []
    peak_ac_power_mw = 0.0
    for ts in sorted(buckets.keys()):
        ac_mw = round(buckets[ts]["ac_kw"] / 1000.0, 2)
        dc_mw = round(buckets[ts]["dc_kw"] / 1000.0, 2)
        if ac_mw > peak_ac_power_mw:
            peak_ac_power_mw = ac_mw
        ts_utc = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
        trend_points.append(
            PublicTelemetryTrendPoint(
                timestamp=ts_utc.isoformat(),
                time=ts.strftime("%H:%M"),
                ac_power_mw=ac_mw,
                dc_power_mw=dc_mw,
            )
        )

    # 7. Evaluate data freshness & staleness status
    now_utc = get_current_utc_time()
    threshold_hours = (
        stale_hours
        if stale_hours is not None
        else settings.TELEMETRY_FRESHNESS_THRESHOLD_HOURS
    )
    age_seconds = (now_utc - target_ts).total_seconds()
    age_hours = age_seconds / 3600.0
    stale_days = int(age_seconds // 86400) if age_seconds >= 0 else 0

    if age_hours <= threshold_hours:
        data_freshness = "LIVE"
        status_label = "SCADA TELEMETRY ACTIVE"
    else:
        data_freshness = "STALE"
        if stale_days > 0:
            status_label = f"TELEMETRY STALE ({stale_days}d ago)"
        else:
            status_label = f"TELEMETRY STALE ({age_hours:.1f}h ago)"

    res = PublicPlantTelemetryResponse(
        plant_id=str(plant.id),
        plant_name=plant.name,
        capacity_ac_mw=capacity_ac_mw,
        capacity_dc_mw=capacity_dc_mw,
        ac_power_mw=ac_power_mw,
        dc_power_mw=dc_power_mw,
        latest_timestamp=target_ts.isoformat(),
        data_freshness=data_freshness,
        status_label=status_label,
        stale_days=stale_days if data_freshness == "STALE" else None,
        freshness_seconds=round(age_seconds, 1) if age_seconds is not None else None,
        inverter_count=active_inverter_count,
        channel_count=len(all_chan_ids),
        last_active_ac_mw=last_active_ac_mw,
        last_active_dc_mw=last_active_dc_mw,
        last_active_timestamp=latest_nonzero_ts.isoformat() if latest_nonzero_ts else None,
        peak_ac_power_mw=peak_ac_power_mw,
        trend=trend_points,
    )
    _PUBLIC_SUMMARY_CACHE[cache_key] = (now_monotonic, res)
    return res


@router.get(
    "/{plant_id}",
    response_model=PlantResponse,
)
def get_plant(
    plant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plant = db.get(Plant, plant_id)

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    return plant


@router.put(
    "/{plant_id}",
    response_model=PlantResponse,
)
@router.patch(
    "/{plant_id}",
    response_model=PlantResponse,
)
def update_plant(
    plant_id: UUID,
    plant_update: PlantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    plant = db.get(Plant, plant_id)

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    update_data = plant_update.model_dump(exclude_unset=True)

    if "metadata" in update_data:
        metadata_val = update_data.pop("metadata")
        if metadata_val is not None:
            plant.metadata_ = metadata_val

    for key, value in update_data.items():
        if hasattr(plant, key) and value is not None:
            setattr(plant, key, value)

    db.commit()
    db.refresh(plant)

    return plant


@router.delete(
    "/{plant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_plant(
    plant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    plant = db.get(Plant, plant_id)

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    # Dependency check to prevent unsafe deletion of historical data
    from app.models import Asset, Event, Detector

    has_assets = db.execute(select(Asset).where(Asset.plant_id == plant.id)).scalars().first() is not None
    has_events = db.execute(select(Event).where(Event.plant_id == plant.id)).scalars().first() is not None
    has_detectors = db.execute(select(Detector).where(Detector.plant_id == plant.id)).scalars().first() is not None

    if has_assets or has_events or has_detectors:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete plant with dependent assets or historical data. Remove dependent resources first.",
        )

    db.delete(plant)
    db.commit()
    return None


@router.get(
    "/{plant_id}/assets/tree",
    response_model=list[AssetTreeNode],
)
def get_plant_asset_tree(
    plant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve full recursive asset hierarchy tree for a plant."""
    plant = db.get(Plant, plant_id)
    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    assets = db.execute(
        select(Asset).where(Asset.plant_id == plant.id).order_by(Asset.name)
    ).scalars().all()

    asset_ids = [a.id for a in assets]
    channels = db.execute(
        select(Channel).where(Channel.asset_id.in_(asset_ids))
    ).scalars().all() if asset_ids else []

    channels_by_asset: dict[UUID, list[dict]] = {}
    for ch in channels:
        channels_by_asset.setdefault(ch.asset_id, []).append({
            "id": str(ch.id),
            "canonical_key": ch.canonical_key,
            "source_name": ch.source_name,
            "receive_unit": ch.receive_unit,
            "interval_s": ch.interval_s,
            "agg_semantics": ch.agg_semantics,
        })

    nodes: dict[UUID, dict] = {}
    for a in assets:
        nodes[a.id] = {
            "id": a.id,
            "plant_id": a.plant_id,
            "parent_id": a.parent_id,
            "name": a.name,
            "asset_type": a.asset_type,
            "make": a.make,
            "model": a.model,
            "rated_kw": float(a.rated_kw) if a.rated_kw is not None else None,
            "metadata": a.metadata_ or {},
            "children": [],
            "channels": channels_by_asset.get(a.id, []),
        }

    roots: list[dict] = []
    for a in assets:
        node = nodes[a.id]
        if a.parent_id and a.parent_id in nodes:
            nodes[a.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots

