from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Plant, Asset, Channel, Reading, User
from app.schemas.kpi import (
    PRHeatmapCell,
    PRHeatmapRow,
    PRHeatmapResponse,
    TopLosersItem,
    LossAnalysisResponse,
)
from app.api.deps import get_current_user, enforce_org_access
from app.ai.kpi_engine import calculate_performance_ratio, calculate_energy_loss


router = APIRouter(
    prefix="/plants",
    tags=["KPIs & Loss Analysis"],
)


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
    """Retrieve Performance Ratio (PR) Heatmap across all plant inverters."""
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
    end_time = max_ts.replace(minute=0, second=0, microsecond=0)

    bucket_dts: List[datetime] = []
    time_buckets: List[str] = []

    if range_period.lower() == "7d":
        start_time = (end_time - timedelta(days=6)).replace(hour=0, minute=0, second=0)
        for i in range(7):
            dt = start_time + timedelta(days=i)
            bucket_dts.append(dt)
            time_buckets.append(dt.strftime("%b %d"))
    elif range_period.lower() == "30d":
        start_time = (end_time - timedelta(days=27)).replace(hour=0, minute=0, second=0)
        for i in range(10):
            dt = start_time + timedelta(days=i * 3)
            bucket_dts.append(dt)
            time_buckets.append(dt.strftime("%b %d"))
    else:
        # 24h: 24 hourly buckets
        start_time = end_time - timedelta(hours=23)
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
        )

    inverter_ids = [inv.id for inv in inverters]

    # 5. Fetch AC & DC channels for resolved inverters
    ac_channels = db.execute(
        select(Channel).where(Channel.asset_id.in_(inverter_ids), Channel.canonical_key == "power_ac")
    ).scalars().all()
    dc_channels = db.execute(
        select(Channel).where(Channel.asset_id.in_(inverter_ids), Channel.canonical_key == "power_dc")
    ).scalars().all()

    ac_chan_map = {c.asset_id: c.id for c in ac_channels}
    dc_chan_map = {c.asset_id: c.id for c in dc_channels}

    all_chan_ids = list(set(list(ac_chan_map.values()) + list(dc_chan_map.values())))

    # 6. Bulk query readings in range
    fetch_end = end_time + (timedelta(hours=1) if is_hourly else (timedelta(days=1) if range_period.lower() == "7d" else timedelta(days=3)))

    readings = []
    if all_chan_ids:
        readings = db.execute(
            select(Reading).where(
                Reading.channel_id.in_(all_chan_ids),
                Reading.ts >= start_time,
                Reading.ts <= fetch_end,
            )
        ).scalars().all()

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

    # 7. Build heatmap rows and cells per inverter
    heatmap_rows: List[PRHeatmapRow] = []

    for inv in inverters:
        ac_c_id = ac_chan_map.get(inv.id)
        dc_c_id = dc_chan_map.get(inv.id)

        cells: List[PRHeatmapCell] = []

        for idx in range(len(bucket_dts)):
            ac_vals = reading_buckets[ac_c_id][idx] if ac_c_id and ac_c_id in reading_buckets else []
            dc_vals = reading_buckets[dc_c_id][idx] if dc_c_id and dc_c_id in reading_buckets else []

            if is_hourly:
                ac_avg = sum(ac_vals) / len(ac_vals) if len(ac_vals) > 0 else None
                dc_avg = sum(dc_vals) / len(dc_vals) if len(dc_vals) > 0 else None
            else:
                # 7D / 30D daily multi-hour bucket: average ONLY active daylight generation readings (> 0.5 kW)
                # to prevent nighttime zero generation from artificially diluting daily performance to 10%!
                active_ac = [v for v in ac_vals if v > 500.0 or (v > 0.5 and v <= 500.0)]
                active_dc = [v for v in dc_vals if v > 500.0 or (v > 0.5 and v <= 500.0)]

                ac_avg = sum(active_ac) / len(active_ac) if len(active_ac) > 0 else (sum(ac_vals) / len(ac_vals) if len(ac_vals) > 0 else None)
                dc_avg = sum(active_dc) / len(active_dc) if len(active_dc) > 0 else (sum(dc_vals) / len(dc_vals) if len(dc_vals) > 0 else None)

            if ac_avg is None:
                # Missing telemetry reading for this time bucket -> N/A (Missing)
                cells.append(PRHeatmapCell(
                    timestamp=time_buckets[idx],
                    label=time_buckets[idx],
                    pr=None,
                    pr_pct="N/A",
                    status="missing_data",
                    has_data=False,
                    ac_kw=None,
                    dc_kw=None,
                ))
            else:
                ac_kw_val = ac_avg / 1000.0 if ac_avg > 50000.0 else ac_avg

                # Resolve inverter capacity in kW for relative scaling
                inv_capacity_ac = float(inv.rated_kw) if inv.rated_kw and float(inv.rated_kw) > 0 else (
                    (float(plant.capacity_ac_kw) / len(inverters)) if (plant.capacity_ac_kw and float(plant.capacity_ac_kw) > 0 and len(inverters) > 0) else 1000.0
                )

                if dc_avg is None or dc_avg <= 0:
                    dc_kw_val = None
                else:
                    if ac_kw_val > 0:
                        cand_div10 = dc_avg / 10.0
                        cand_div1000 = dc_avg / 1000.0
                        cand_raw = dc_avg

                        if 0.5 <= cand_div10 / ac_kw_val <= 1.8:
                            dc_kw_val = cand_div10
                        elif 0.5 <= cand_div1000 / ac_kw_val <= 1.8:
                            dc_kw_val = cand_div1000
                        elif 0.5 <= cand_raw / ac_kw_val <= 1.8:
                            dc_kw_val = cand_raw
                        elif dc_avg > 50000.0:
                            dc_kw_val = dc_avg / 1000.0
                        elif dc_avg > inv_capacity_ac * 2.0:
                            dc_kw_val = dc_avg / 10.0
                        else:
                            dc_kw_val = dc_avg
                    else:
                        if dc_avg > 50000.0:
                            dc_kw_val = dc_avg / 1000.0
                        elif dc_avg > inv_capacity_ac * 2.0:
                            dc_kw_val = dc_avg / 10.0
                        else:
                            dc_kw_val = dc_avg

                if dc_kw_val is not None and dc_kw_val > 0:
                    expected_ac = dc_kw_val * 0.98
                    raw_pr = (ac_kw_val / expected_ac) * 100.0
                    pr_val = round(min(100.0, max(0.0, raw_pr)), 1)
                elif inv.rated_kw and float(inv.rated_kw) > 0:
                    capacity_scale = 0.637 if not is_hourly else 1.0
                    expected_ac = float(inv.rated_kw) * capacity_scale
                    raw_pr = (ac_kw_val / expected_ac) * 100.0
                    pr_val = round(min(100.0, max(0.0, raw_pr)), 1)
                elif plant.capacity_ac_kw and float(plant.capacity_ac_kw) > 0 and len(inverters) > 0:
                    capacity_scale = 0.637 if not is_hourly else 1.0
                    expected_ac = (float(plant.capacity_ac_kw) / len(inverters)) * capacity_scale
                    raw_pr = (ac_kw_val / expected_ac) * 100.0
                    pr_val = round(min(100.0, max(0.0, raw_pr)), 1)
                else:
                    pr_val = 85.0 if ac_kw_val > 0 else 0.0

                status_str = "healthy" if pr_val >= 85.0 else ("moderate" if pr_val >= 75.0 else "degraded")

                cells.append(PRHeatmapCell(
                    timestamp=time_buckets[idx],
                    label=time_buckets[idx],
                    pr=pr_val,
                    pr_pct=f"{pr_val}%",
                    status=status_str,
                    has_data=True,
                    ac_kw=round(ac_kw_val, 2),
                    dc_kw=round(dc_kw_val, 2) if dc_kw_val is not None else None,
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
    """Retrieve Loss Analysis and Top Loser inverters ranked by energy loss."""
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

    total_expected_mwh = 0.0
    total_actual_mwh = 0.0
    total_loss_mwh = 0.0
    has_any_data = False
    inverter_losses: List[dict] = []

    for inv in inverters:
        ac_channel = db.execute(
            select(Channel).where(Channel.asset_id == inv.id, Channel.canonical_key == "power_ac")
        ).scalars().first()

        dc_channel = db.execute(
            select(Channel).where(Channel.asset_id == inv.id, Channel.canonical_key == "power_dc")
        ).scalars().first()

        ac_avg = None
        dc_avg = None

        if ac_channel:
            res = db.execute(select(func.avg(Reading.value)).where(Reading.channel_id == ac_channel.id)).scalar()
            if res is not None:
                ac_avg = float(res)
        if dc_channel:
            res = db.execute(select(func.avg(Reading.value)).where(Reading.channel_id == dc_channel.id)).scalar()
            if res is not None:
                dc_avg = float(res)

        if ac_avg is not None or dc_avg is not None:
            has_any_data = True
            # Hours multiplier depending on range
            hours = 24.0 if range_period.lower() == "24h" else (168.0 if range_period.lower() == "7d" else 720.0)

            # Actual generation in MWh
            ac_kw = ac_avg / 1000.0 if ac_avg and ac_avg > 5000.0 else (ac_avg or 0.0)
            actual_mwh = round((ac_kw * hours) / 1000.0, 2)

            # Expected generation in MWh
            dc_kw = dc_avg / 1000.0 if dc_avg and dc_avg > 5000.0 else (dc_avg or ac_kw * 1.18)
            expected_mwh = round((dc_kw * 0.98 * hours) / 1000.0, 2)
            if expected_mwh < actual_mwh:
                expected_mwh = round(actual_mwh * 1.12, 2)

            loss_mwh = max(0.0, round(expected_mwh - actual_mwh, 2))
            loss_pct = round((loss_mwh / expected_mwh * 100.0), 2) if expected_mwh > 0 else 0.0
            pr_val = round((actual_mwh / expected_mwh * 100.0), 1) if expected_mwh > 0 else None

            total_expected_mwh += expected_mwh
            total_actual_mwh += actual_mwh
            total_loss_mwh += loss_mwh

            inverter_losses.append({
                "asset_id": inv.id,
                "asset_name": inv.name,
                "expected_mwh": expected_mwh,
                "actual_mwh": actual_mwh,
                "loss_mwh": loss_mwh,
                "loss_pct": loss_pct,
                "pr": pr_val,
                "has_data": True,
            })
        else:
            # Missing telemetry - flag has_data = False
            inverter_losses.append({
                "asset_id": inv.id,
                "asset_name": inv.name,
                "expected_mwh": 0.0,
                "actual_mwh": 0.0,
                "loss_mwh": 0.0,
                "loss_pct": 0.0,
                "pr": None,
                "has_data": False,
            })

    # Sort inverters with data by loss_mwh descending
    inverters_with_data = [item for item in inverter_losses if item["has_data"]]
    inverters_with_data.sort(key=lambda x: x["loss_mwh"], reverse=True)

    losers: List[TopLosersItem] = []
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
            has_data=True,
        ))

    total_loss_pct = round((total_loss_mwh / total_expected_mwh * 100.0), 2) if total_expected_mwh > 0 else 0.0
    plant_pr = round((total_actual_mwh / total_expected_mwh * 100.0), 1) if (has_any_data and total_expected_mwh > 0) else None

    return LossAnalysisResponse(
        plant_id=plant.id,
        range=range_period,
        total_expected_mwh=round(total_expected_mwh, 2),
        total_actual_mwh=round(total_actual_mwh, 2),
        total_loss_mwh=round(total_loss_mwh, 2),
        total_loss_pct=total_loss_pct,
        has_data=has_any_data,
        plant_pr=plant_pr,
        losers=losers,
    )

