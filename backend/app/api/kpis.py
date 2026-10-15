import math
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from typing import Optional, List, Tuple, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Plant, Asset, Channel, Reading, User, KPIValue
from app.schemas.kpi import (
    PRHeatmapCell,
    PRHeatmapRow,
    PRHeatmapResponse,
    TopLosersItem,
    LossAnalysisResponse,
)
from app.api.deps import get_current_user, enforce_org_access
from app.ai.kpi_engine import G_STC_KW_M2


router = APIRouter(
    prefix="/plants",
    tags=["KPIs & Loss Analysis"],
)


def normalize_power_kw(
    val: Optional[float],
    unit: Optional[str] = None,
    conversion: Optional[str] = None,
    capacity_ac_kw: float = 1000.0,
    is_dc: bool = False,
    is_dc_10x: Optional[bool] = None,
) -> Optional[float]:
    """Normalize raw telemetry power reading to kW using channel unit metadata and fallback heuristics."""
    if val is None or math.isnan(val):
        return None

    u = (unit or "").strip().lower()
    c = (conversion or "").strip().lower()

    if u in ("w", "watt", "watts"):
        return val / 1000.0
    if u in ("mw", "megawatt", "megawatts"):
        return val * 1000.0
    if u in ("deci-kw", "deci_kw") or "val / 10" in c or "val * 0.1" in c:
        return val / 10.0

    if is_dc:
        if is_dc_10x is True:
            return val / 10.0
        elif is_dc_10x is False:
            return val
        if u in ("kw", "kilowatt", "kilowatts"):
            if val > max(250.0, capacity_ac_kw * 1.2):
                return val / 10.0
            return val
        if val > 50000.0:
            return val / 1000.0
        if val > 250.0:
            return val / 10.0
        if val > capacity_ac_kw * 2.0:
            return val / 10.0
        return val

    if u in ("kw", "kilowatt", "kilowatts"):
        return val

    # Heuristic fallback for Kaggle / raw telemetry with missing unit metadata
    if val > 50000.0:
        return val / 1000.0
    if val > capacity_ac_kw * 2.0:
        return val / 10.0
    return val


def normalize_irradiance_wm2(
    val: Optional[float],
    unit: Optional[str] = None,
) -> Optional[float]:
    """Normalize raw solar irradiance reading to W/m²."""
    if val is None or math.isnan(val) or val < 0:
        return None

    u = (unit or "").strip().lower()
    if u in ("kw/m2", "kw/m²"):
        return val * 1000.0
    if u in ("w/m2", "w/m²"):
        return val

    # Heuristic: irradiance <= 2.5 is given in kW/m²
    if 0 < val <= 2.5:
        return val * 1000.0
    return val


def get_reporting_window(
    max_ts: datetime,
    range_period: str,
) -> tuple[datetime, datetime]:
    """Calculate exact UTC start and end boundaries for KPI reporting windows.

    Interval Semantics:
    - Half-open interval: [start_time, window_end)
    - Anchoring: Aligned to the top of the hour following max_ts.
      For the historical Surya dataset (max_ts = 2020-06-17 23:45:00 UTC), window_end is
      strictly 2020-06-18 00:00:00 UTC.
    - Durations:
      - '24h': exactly 24.0 hours (24h) -> 2020-06-17 00:00:00 to 2020-06-18 00:00:00
      - '7d':  exactly 168.0 hours (7 days) -> 2020-06-11 00:00:00 to 2020-06-18 00:00:00
      - '30d': exactly 720.0 hours (30 days) -> 2020-05-19 00:00:00 to 2020-06-18 00:00:00
    - Interval rule: Readings are matched on start_time <= Reading.ts < window_end.
      No reporting window includes future periods beyond available telemetry.
    """
    if max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    window_end = max_ts.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    period = range_period.lower()
    if period == "7d":
        start_time = window_end - timedelta(days=7)
    elif period == "30d":
        start_time = window_end - timedelta(days=30)
    else:
        # Default 24h
        start_time = window_end - timedelta(hours=24)

    return start_time, window_end


@router.get(
    "/kpis/heatmap",
    response_model=PRHeatmapResponse,
)
@router.get(
    "/{plant_id}/kpis/heatmap",
    response_model=PRHeatmapResponse,
)
def get_pr_heatmap(
    plant_id: Optional[UUID] = None,
    range_period: str = Query(default="24h", alias="range", description="Time range: 24h, 7d, 30d"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve Performance Ratio (PR) Heatmap across all plant inverters according to IEC 61724-1 standard."""
    # 1. Resolve Plant
    plant = None
    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
        enforce_org_access(current_user, plant.org_id)
    else:
        plant = db.execute(
            select(Plant).where(Plant.org_id == current_user.org_id).order_by(Plant.created_at.desc())
        ).scalars().first()
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No plant found for user organization")

    # 2. Resolve Inverter Assets
    inverters = db.execute(
        select(Asset).where(
            Asset.plant_id == plant.id,
            (Asset.asset_type == "inverter") | (Asset.name.ilike("%inverter%")),
        ).order_by(Asset.name)
    ).scalars().all()

    if not inverters:
        inverters = db.execute(
            select(Asset)
            .join(Plant, Asset.plant_id == Plant.id)
            .where(
                Plant.org_id == current_user.org_id,
                (Asset.asset_type == "inverter") | (Asset.name.ilike("%inverter%")),
            )
            .order_by(Asset.name)
        ).scalars().all()

    # 3. Query max telemetry timestamp across plant inverter channels
    max_ts = db.execute(
        select(func.max(Reading.ts))
        .join(Channel, Reading.channel_id == Channel.id)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(Asset.plant_id == plant.id)
    ).scalar()

    if not max_ts:
        max_ts = datetime.now(timezone.utc)

    if max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    # 4. Determine time window and buckets ending at latest telemetry timestamp
    is_hourly = range_period.lower() not in ("7d", "30d")
    start_time, window_end = get_reporting_window(max_ts, range_period)

    bucket_dts: List[datetime] = []
    time_buckets: List[str] = []

    if range_period.lower() == "7d":
        for i in range(7):
            dt = start_time + timedelta(days=i)
            bucket_dts.append(dt)
            time_buckets.append(dt.strftime("%b %d"))
    elif range_period.lower() == "30d":
        for i in range(10):
            dt = start_time + timedelta(days=i * 3)
            bucket_dts.append(dt)
            time_buckets.append(dt.strftime("%b %d"))
    else:
        # 24h: 24 hourly buckets
        for i in range(24):
            dt = start_time + timedelta(hours=i)
            bucket_dts.append(dt)
            time_buckets.append(dt.strftime("%H:00"))

    if not inverters:
        return PRHeatmapResponse(
            plant_id=plant.id,
            range=range_period,
            time_buckets=time_buckets,
            inverters=[],
            has_poa=False,
        )

    inverter_ids = [inv.id for inv in inverters]

    # 5. Fetch AC, DC, and Weather POA Irradiance channels
    ac_channels = db.execute(
        select(Channel).where(Channel.asset_id.in_(inverter_ids), Channel.canonical_key == "power_ac")
    ).scalars().all()
    dc_channels = db.execute(
        select(Channel).where(Channel.asset_id.in_(inverter_ids), Channel.canonical_key == "power_dc")
    ).scalars().all()
    poa_channels = db.execute(
        select(Channel)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(
            Asset.plant_id == plant.id,
            Channel.canonical_key.in_(["irradiance_poa", "irradiance_ghi", "irradiance"]),
        )
    ).scalars().all()

    ac_chan_map = {c.asset_id: c for c in ac_channels}
    dc_chan_map = {c.asset_id: c for c in dc_channels}
    poa_channel = poa_channels[0] if poa_channels else None

    all_chan_ids = list(set([c.id for c in ac_channels] + [c.id for c in dc_channels] + ([poa_channel.id] if poa_channel else [])))

    readings = []
    if all_chan_ids:
        readings = db.execute(
            select(Reading).where(
                Reading.channel_id.in_(all_chan_ids),
                Reading.ts >= start_time,
                Reading.ts < window_end,
            )
        ).scalars().all()

    channel_meta_map = {c.id: c for c in ac_channels + dc_channels + poa_channels}
    reading_buckets: Dict[UUID, Dict[int, List[float]]] = {
        c_id: {idx: [] for idx in range(len(bucket_dts))} for c_id in all_chan_ids
    }

    for r in readings:
        r_ts = r.ts
        if r_ts.tzinfo is None:
            r_ts = r_ts.replace(tzinfo=timezone.utc)

        for idx, b_dt in enumerate(bucket_dts):
            if is_hourly:
                b_end = b_dt + timedelta(hours=1)
            elif range_period.lower() == "7d":
                b_end = b_dt + timedelta(days=1)
            else:
                b_end = b_dt + timedelta(days=3)

            if b_dt <= r_ts < b_end:
                reading_buckets[r.channel_id][idx].append(float(r.value))
                break

    # 6. Build heatmap rows per inverter
    heatmap_rows: List[PRHeatmapRow] = []
    has_poa_data = False

    for inv in inverters:
        ac_c = ac_chan_map.get(inv.id)
        dc_c = dc_chan_map.get(inv.id)

        ac_c_id = ac_c.id if ac_c else None
        dc_c_id = dc_c.id if dc_c else None

        inv_capacity_ac = float(inv.rated_kw) if inv.rated_kw and float(inv.rated_kw) > 0 else (
            (float(plant.capacity_ac_kw) / len(inverters)) if (plant.capacity_ac_kw and float(plant.capacity_ac_kw) > 0 and len(inverters) > 0) else 1000.0
        )
        inv_meta = inv.metadata_json or {}
        if "rated_dc_kwp" in inv_meta and float(inv_meta["rated_dc_kwp"]) > 0:
            inv_capacity_dc = float(inv_meta["rated_dc_kwp"])
        elif plant.capacity_dc_kwp and float(plant.capacity_dc_kwp) > 0 and len(inverters) > 0:
            inv_capacity_dc = float(plant.capacity_dc_kwp) / len(inverters)
        else:
            inv_capacity_dc = inv_capacity_ac * 1.2

        # Check if inverter DC channel readings are 10x scaled (deci-kW)
        is_dc_10x: Optional[bool] = None
        if dc_c:
            dc_u = (dc_c.receive_unit or "").strip().lower()
            dc_c_conv = (dc_c.conversion or "").strip().lower()
            if dc_u in ("deci-kw", "deci_kw") or "val / 10" in dc_c_conv or "val * 0.1" in dc_c_conv:
                is_dc_10x = True
            elif dc_c_id in reading_buckets:
                all_dc_raw = [v for bucket in reading_buckets[dc_c_id].values() for v in bucket if v is not None]
                if all_dc_raw and max(all_dc_raw) > max(250.0, inv_capacity_ac * 1.2):
                    is_dc_10x = True
                elif all_dc_raw:
                    is_dc_10x = False

        cells: List[PRHeatmapCell] = []

        for idx in range(len(bucket_dts)):
            ac_raw_vals = reading_buckets[ac_c_id][idx] if ac_c_id and ac_c_id in reading_buckets else []
            dc_raw_vals = reading_buckets[dc_c_id][idx] if dc_c_id and dc_c_id in reading_buckets else []
            poa_raw_vals = reading_buckets[poa_channel.id][idx] if (poa_channel and poa_channel.id in reading_buckets) else []

            # Average and normalize AC power (kW)
            ac_kw_val: Optional[float] = None
            if ac_raw_vals:
                avg_raw = sum(ac_raw_vals) / len(ac_raw_vals)
                ac_kw_val = normalize_power_kw(avg_raw, ac_c.receive_unit if ac_c else None, ac_c.conversion if ac_c else None, inv_capacity_ac)

            # Average and normalize DC power (kW)
            dc_kw_val: Optional[float] = None
            if dc_raw_vals:
                avg_raw = sum(dc_raw_vals) / len(dc_raw_vals)
                dc_kw_val = normalize_power_kw(avg_raw, dc_c.receive_unit if dc_c else None, dc_c.conversion if dc_c else None, inv_capacity_ac, is_dc=True, is_dc_10x=is_dc_10x)

            # Average and normalize POA Irradiance (W/m²)
            poa_wm2_val: Optional[float] = None
            if poa_raw_vals:
                avg_raw = sum(poa_raw_vals) / len(poa_raw_vals)
                poa_wm2_val = normalize_irradiance_wm2(avg_raw, poa_channel.receive_unit if poa_channel else None)

            # Compute Inverter Conversion Efficiency
            efficiency: Optional[float] = None
            if ac_kw_val is not None and dc_kw_val is not None and dc_kw_val > 0:
                efficiency = round(min(100.0, max(0.0, (ac_kw_val / dc_kw_val * 100.0))), 1)

            if ac_kw_val is None:
                cells.append(PRHeatmapCell(
                    timestamp=time_buckets[idx],
                    label=time_buckets[idx],
                    pr=None,
                    pr_pct="N/A",
                    status="missing_data",
                    has_data=False,
                    ac_kw=None,
                    dc_kw=round(dc_kw_val, 2) if dc_kw_val is not None else None,
                    efficiency=efficiency,
                ))
            else:
                pr_val: Optional[float] = None
                pr_pct = "N/A"
                status_str = "missing_data"
                has_data_cell = True

                # Calculate IEC 61724-1 PR strictly when POA irradiance is available
                if poa_wm2_val is not None and poa_wm2_val > 50.0 and inv_capacity_dc > 0:
                    has_poa_data = True
                    expected_ac_kw = inv_capacity_dc * (poa_wm2_val / 1000.0)
                    if expected_ac_kw > 0:
                        raw_pr = (ac_kw_val / expected_ac_kw) * 100.0
                        pr_val = round(max(0.0, raw_pr), 1)
                        pr_pct = f"{pr_val}%"
                        status_str = "healthy" if pr_val >= 78.0 else ("moderate" if pr_val >= 65.0 else "degraded")
                elif ac_kw_val is not None:
                    # Telemetry present but no POA irradiance baseline available
                    pr_val = None
                    pr_pct = "N/A"
                    status_str = "missing_irradiance" if poa_channel is None else "healthy"

                cells.append(PRHeatmapCell(
                    timestamp=time_buckets[idx],
                    label=time_buckets[idx],
                    pr=pr_val,
                    pr_pct=pr_pct,
                    status=status_str,
                    has_data=has_data_cell,
                    ac_kw=round(ac_kw_val, 2),
                    dc_kw=round(dc_kw_val, 2) if dc_kw_val is not None else None,
                    efficiency=efficiency,
                ))

        heatmap_rows.append(PRHeatmapRow(
            asset_id=inv.id,
            asset_name=inv.name,
            cells=cells,
        ))

    return PRHeatmapResponse(
        plant_id=plant.id,
        range=range_period,
        time_buckets=time_buckets,
        inverters=heatmap_rows,
        has_poa=has_poa_data,
    )


@router.get(
    "/kpis/top-losers",
    response_model=LossAnalysisResponse,
)
@router.get(
    "/{plant_id}/kpis/top-losers",
    response_model=LossAnalysisResponse,
)
def get_top_losers(
    plant_id: Optional[UUID] = None,
    range_period: str = Query(default="24h", alias="range", description="Time range: 24h, 7d, 30d"),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve Loss Analysis and Top Loser inverters according to IEC standard solar PR & POA baseline."""
    # 1. Resolve Plant
    plant = None
    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
        enforce_org_access(current_user, plant.org_id)
    else:
        plant = db.execute(
            select(Plant).where(Plant.org_id == current_user.org_id).order_by(Plant.created_at.desc())
        ).scalars().first()
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No plant found for user organization")

    # 2. Resolve Inverter Assets
    inverters = db.execute(
        select(Asset).where(
            Asset.plant_id == plant.id,
            (Asset.asset_type == "inverter") | (Asset.name.ilike("%inverter%")),
        ).order_by(Asset.name)
    ).scalars().all()

    if not inverters:
        inverters = db.execute(
            select(Asset)
            .join(Plant, Asset.plant_id == Plant.id)
            .where(
                Plant.org_id == current_user.org_id,
                (Asset.asset_type == "inverter") | (Asset.name.ilike("%inverter%")),
            )
            .order_by(Asset.name)
        ).scalars().all()

    if not inverters:
        return LossAnalysisResponse(
            plant_id=plant.id,
            range=range_period,
            total_expected_mwh=None,
            total_actual_mwh=0.0,
            net_shortfall_mwh=None,
            aggregate_inverter_deficit_mwh=None,
            total_loss_mwh=None,
            total_loss_pct=None,
            net_shortfall_pct=None,
            has_data=False,
            has_poa=False,
            plant_pr=None,
            ranking_mode="none",
            losers=[],
        )

    # 3. Query max telemetry timestamp across plant inverter channels
    max_ts = db.execute(
        select(func.max(Reading.ts))
        .join(Channel, Reading.channel_id == Channel.id)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(Asset.plant_id == plant.id)
    ).scalar()

    if not max_ts:
        max_ts = datetime.now(timezone.utc)

    if max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    start_time, window_end = get_reporting_window(max_ts, range_period)

    inverter_ids = [inv.id for inv in inverters]

    # 4. Fetch AC, DC, and Weather POA Irradiance channels
    ac_channels = db.execute(
        select(Channel).where(Channel.asset_id.in_(inverter_ids), Channel.canonical_key == "power_ac")
    ).scalars().all()
    dc_channels = db.execute(
        select(Channel).where(Channel.asset_id.in_(inverter_ids), Channel.canonical_key == "power_dc")
    ).scalars().all()
    poa_channels = db.execute(
        select(Channel)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(
            Asset.plant_id == plant.id,
            Channel.canonical_key.in_(["irradiance_poa", "irradiance_ghi", "irradiance"]),
        )
    ).scalars().all()

    ac_chan_map = {c.asset_id: c for c in ac_channels}
    dc_chan_map = {c.asset_id: c for c in dc_channels}
    poa_channel = poa_channels[0] if poa_channels else None

    all_chan_ids = list(set([c.id for c in ac_channels] + [c.id for c in dc_channels] + ([poa_channel.id] if poa_channel else [])))

    readings_by_channel: Dict[UUID, List[Reading]] = {c_id: [] for c_id in all_chan_ids}

    if all_chan_ids:
        readings = db.execute(
            select(Reading).where(
                Reading.channel_id.in_(all_chan_ids),
                Reading.ts >= start_time,
                Reading.ts < window_end,
            ).order_by(Reading.ts)
        ).scalars().all()

        for r in readings:
            readings_by_channel[r.channel_id].append(r)

    # 5. Integrate POA Solar Irradiation over the reporting period
    poa_readings = readings_by_channel.get(poa_channel.id, []) if poa_channel else []
    total_poa_kwh_m2 = 0.0
    has_poa = False

    if poa_readings:
        poa_interval_h = (poa_channel.interval_s / 3600.0) if (poa_channel and poa_channel.interval_s and poa_channel.interval_s > 0) else 0.25
        if len(poa_readings) >= 2:
            p_ts = sorted([r.ts.replace(tzinfo=timezone.utc) if r.ts.tzinfo is None else r.ts for r in poa_readings])
            p_deltas = [(p_ts[i] - p_ts[i - 1]).total_seconds() for i in range(1, len(p_ts))]
            p_op = [d for d in p_deltas if 0 < d <= 7200]
            if p_op:
                p_op.sort()
                mid = len(p_op) // 2
                median_s = p_op[mid] if len(p_op) % 2 != 0 else (p_op[mid - 1] + p_op[mid]) / 2.0
                poa_interval_h = median_s / 3600.0
        valid_poa = [normalize_irradiance_wm2(float(r.value), poa_channel.receive_unit) for r in poa_readings]
        valid_poa_clean = [g for g in valid_poa if g is not None and g > 50.0]
        if valid_poa_clean:
            has_poa = True
            total_poa_kwh_m2 = sum(g / 1000.0 * poa_interval_h for g in valid_poa_clean)

    total_expected_mwh = 0.0
    total_actual_mwh = 0.0
    total_loss_mwh = 0.0
    has_any_data = False
    inverter_losses: List[dict] = []

    for inv in inverters:
        ac_chan = ac_chan_map.get(inv.id)
        dc_chan = dc_chan_map.get(inv.id)

        ac_readings = readings_by_channel.get(ac_chan.id, []) if ac_chan else []
        dc_readings = readings_by_channel.get(dc_chan.id, []) if dc_chan else []

        if not ac_readings and not dc_readings:
            inverter_losses.append({
                "asset_id": inv.id,
                "asset_name": inv.name,
                "expected_mwh": None,
                "actual_mwh": 0.0,
                "loss_mwh": None,
                "loss_pct": None,
                "pr": None,
                "efficiency": None,
                "has_data": False,
            })
            continue

        has_any_data = True

        inv_capacity_ac = float(inv.rated_kw) if inv.rated_kw and float(inv.rated_kw) > 0 else (
            (float(plant.capacity_ac_kw) / len(inverters)) if (plant.capacity_ac_kw and float(plant.capacity_ac_kw) > 0 and len(inverters) > 0) else 1000.0
        )
        inv_meta = inv.metadata_json or {}
        if "rated_dc_kwp" in inv_meta and float(inv_meta["rated_dc_kwp"]) > 0:
            inv_capacity_dc = float(inv_meta["rated_dc_kwp"])
        elif plant.capacity_dc_kwp and float(plant.capacity_dc_kwp) > 0 and len(inverters) > 0:
            inv_capacity_dc = float(plant.capacity_dc_kwp) / len(inverters)
        else:
            inv_capacity_dc = inv_capacity_ac * 1.2

        ac_interval_h = (ac_chan.interval_s / 3600.0) if (ac_chan and ac_chan.interval_s and ac_chan.interval_s > 0) else 0.25

        ac_map: Dict[datetime, float] = {}
        for r in ac_readings:
            r_ts = r.ts.replace(tzinfo=timezone.utc) if r.ts.tzinfo is None else r.ts
            ac_map[r_ts] = float(r.value)

        dc_map: Dict[datetime, float] = {}
        for r in dc_readings:
            r_ts = r.ts.replace(tzinfo=timezone.utc) if r.ts.tzinfo is None else r.ts
            dc_map[r_ts] = float(r.value)

        all_timestamps = sorted(list(set(list(ac_map.keys()) + list(dc_map.keys()))))

        # Dynamically determine AC telemetry sampling cadence from actual timestamp deltas
        if len(all_timestamps) >= 2:
            deltas = [(all_timestamps[i] - all_timestamps[i - 1]).total_seconds() for i in range(1, len(all_timestamps))]
            operational_deltas = [d for d in deltas if 0 < d <= 7200]
            if operational_deltas:
                operational_deltas.sort()
                mid = len(operational_deltas) // 2
                median_delta_s = operational_deltas[mid] if len(operational_deltas) % 2 != 0 else (operational_deltas[mid - 1] + operational_deltas[mid]) / 2.0
                ac_interval_h = median_delta_s / 3600.0

        is_dc_10x: Optional[bool] = None
        if dc_chan:
            dc_u = (dc_chan.receive_unit or "").strip().lower()
            dc_c_conv = (dc_chan.conversion or "").strip().lower()
            if dc_u in ("deci-kw", "deci_kw") or "val / 10" in dc_c_conv or "val * 0.1" in dc_c_conv:
                is_dc_10x = True
            elif dc_readings:
                max_raw_dc = max((float(r.value) for r in dc_readings if r.value is not None), default=0.0)
                if max_raw_dc > max(250.0, inv_capacity_ac * 1.2):
                    is_dc_10x = True
                else:
                    is_dc_10x = False

        actual_kwh = 0.0
        dc_kwh = 0.0

        for r_ts in all_timestamps:
            v_ac = ac_map.get(r_ts)
            v_dc = dc_map.get(r_ts)

            if v_ac is None and (v_dc is None or v_dc <= 0):
                continue

            ac_kw = normalize_power_kw(v_ac, ac_chan.receive_unit if ac_chan else None, ac_chan.conversion if ac_chan else None, inv_capacity_ac) if v_ac is not None else 0.0
            dc_kw = normalize_power_kw(v_dc, dc_chan.receive_unit if dc_chan else None, dc_chan.conversion if dc_chan else None, inv_capacity_ac, is_dc=True, is_dc_10x=is_dc_10x) if v_dc is not None else None

            if ac_kw is not None:
                actual_kwh += max(0.0, ac_kw) * ac_interval_h
            if dc_kw is not None:
                dc_kwh += max(0.0, dc_kw) * ac_interval_h

        actual_mwh = round(actual_kwh / 1000.0, 2)
        dc_mwh = round(dc_kwh / 1000.0, 2)

        # Inverter AC/DC Conversion Efficiency
        efficiency: Optional[float] = None
        if dc_mwh > 0 and actual_mwh > 0:
            efficiency = round(min(100.0, max(0.0, (actual_mwh / dc_mwh * 100.0))), 1)

        expected_mwh: Optional[float] = None
        loss_mwh: Optional[float] = None
        loss_pct: Optional[float] = None
        pr_val: Optional[float] = None

        # Calculate PR and Loss Analysis when POA irradiation baseline is present
        if has_poa and total_poa_kwh_m2 > 0 and inv_capacity_dc > 0:
            expected_kwh = inv_capacity_dc * (total_poa_kwh_m2 / G_STC_KW_M2)
            expected_mwh = round(expected_kwh / 1000.0, 2)

            loss_mwh = max(0.0, round(expected_mwh - actual_mwh, 2))
            loss_pct = round((loss_mwh / expected_mwh * 100.0), 2) if expected_mwh > 0 else 0.0
            pr_val = round(max(0.0, (actual_mwh / expected_mwh * 100.0)), 1) if expected_mwh > 0 else None

            total_expected_mwh += expected_mwh
            total_loss_mwh += loss_mwh

        total_actual_mwh += actual_mwh

        inverter_losses.append({
            "asset_id": inv.id,
            "asset_name": inv.name,
            "expected_mwh": expected_mwh,
            "actual_mwh": actual_mwh,
            "loss_mwh": loss_mwh,
            "loss_pct": loss_pct,
            "pr": pr_val,
            "efficiency": efficiency,
            "has_data": True,
        })

    inverters_with_data = [item for item in inverter_losses if item["has_data"]]
    losers: List[TopLosersItem] = []

    # Distinct mathematical definitions:
    # 1. Net plant shortfall = max(sum(expected) - sum(actual), 0)
    # 2. Per-inverter deficit = max(expected_i - actual_i, 0)
    # 3. Aggregate inverter deficit = sum(per-inverter deficits)
    rounded_expected = round(total_expected_mwh, 2) if has_poa else None
    rounded_actual = round(total_actual_mwh, 2)
    aggregate_inverter_deficit = round(total_loss_mwh, 2) if has_poa else None
    net_plant_shortfall = max(0.0, round(total_expected_mwh - total_actual_mwh, 2)) if (has_poa and total_expected_mwh is not None) else None

    net_shortfall_pct = (
        round((net_plant_shortfall / total_expected_mwh * 100.0), 2)
        if (has_poa and total_expected_mwh > 0 and net_plant_shortfall is not None)
        else (0.0 if has_poa else None)
    )
    total_loss_pct = (
        round((aggregate_inverter_deficit / total_expected_mwh * 100.0), 2)
        if (has_poa and total_expected_mwh > 0 and aggregate_inverter_deficit is not None)
        else None
    )

    if has_poa:
        # Strictly filter to inverters with a positive energy deficit (> 0)
        underperforming = [item for item in inverters_with_data if (item["loss_mwh"] or 0.0) > 0.0]
        if underperforming:
            ranking_mode = "deficit"
            underperforming.sort(key=lambda x: x["loss_mwh"], reverse=True)
            for idx, item in enumerate(underperforming[:limit], start=1):
                losers.append(TopLosersItem(
                    rank=idx,
                    asset_id=item["asset_id"],
                    asset_name=item["asset_name"],
                    expected_mwh=item["expected_mwh"],
                    actual_mwh=item["actual_mwh"],
                    loss_mwh=item["loss_mwh"],
                    loss_pct=item["loss_pct"],
                    pr=item["pr"],
                    efficiency=item["efficiency"],
                    has_data=True,
                ))
        else:
            # All inverters met or exceeded expected energy: no arbitrary ranking or fake losers
            ranking_mode = "none"
    else:
        # Telemetry present but no POA irradiance baseline: rank by lowest measured AC generation
        ranking_mode = "generation"
        inverters_with_data.sort(key=lambda x: x["actual_mwh"], reverse=False)
        for idx, item in enumerate(inverters_with_data[:limit], start=1):
            losers.append(TopLosersItem(
                rank=idx,
                asset_id=item["asset_id"],
                asset_name=item["asset_name"],
                expected_mwh=item["expected_mwh"],
                actual_mwh=item["actual_mwh"],
                loss_mwh=item["loss_mwh"],
                loss_pct=item["loss_pct"],
                pr=item["pr"],
                efficiency=item["efficiency"],
                has_data=True,
            ))

    plant_pr = round(max(0.0, (total_actual_mwh / total_expected_mwh * 100.0)), 1) if (has_poa and total_expected_mwh > 0) else None

    return LossAnalysisResponse(
        plant_id=plant.id,
        range=range_period,
        total_expected_mwh=rounded_expected,
        total_actual_mwh=rounded_actual,
        net_shortfall_mwh=net_plant_shortfall,
        aggregate_inverter_deficit_mwh=aggregate_inverter_deficit,
        total_loss_mwh=aggregate_inverter_deficit,
        total_loss_pct=total_loss_pct,
        net_shortfall_pct=net_shortfall_pct,
        has_data=has_any_data,
        has_poa=has_poa,
        plant_pr=plant_pr,
        ranking_mode=ranking_mode,
        losers=losers,
    )


@router.get(
    "/{plant_id}/kpis/daily",
    tags=["KPIs & Loss Analysis"],
)
@router.get(
    "/{plant_id}/kpis",
    tags=["KPIs & Loss Analysis"],
)
def get_daily_kpis(
    plant_id: UUID,
    target_date: Optional[date] = Query(default=None, alias="date"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve daily KPI rollups for a plant from TimescaleDB kpi_values."""
    plant = db.get(Plant, plant_id)
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
    enforce_org_access(current_user, plant.org_id)

    query = select(KPIValue).where(
        KPIValue.plant_id == plant.id,
        KPIValue.period == "day",
    )
    if target_date is not None:
        query = query.where(func.date(KPIValue.time) == target_date)
    else:
        if start_date is not None:
            query = query.where(func.date(KPIValue.time) >= start_date)
        if end_date is not None:
            query = query.where(func.date(KPIValue.time) <= end_date)

    query = query.order_by(KPIValue.time.desc())
    records = db.execute(query).scalars().all()

    return [
        {
            "time": r.time.isoformat(),
            "plant_id": str(r.plant_id),
            "asset_id": str(r.asset_id) if r.asset_id else None,
            "kpi_key": r.kpi_key,
            "period": r.period,
            "value": r.value,
            "coverage": float(r.coverage),
            "flags": r.flags or [],
        }
        for r in records
    ]

