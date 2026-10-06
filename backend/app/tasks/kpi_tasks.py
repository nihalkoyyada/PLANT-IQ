"""Celery Background Tasks for Daily Solar KPI Rollups (§11).

Task: S3-AI-01
Implements:
- Daily KPI rollup calculation per plant and per inverter.
- Local timezone day windowing (00:00 to 23:59:59 plant-local).
- Telemetry alignment and input coverage computation.
- Idempotent upsert into TimescaleDB `kpi_values` table.
- Celery background tasks:
    * `tasks.compute_daily_kpis`: Compute rollups for a specific plant and date.
    * `tasks.run_all_plants_daily_kpis`: Compute rollups across all plants (scheduled via Beat).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID
import zoneinfo

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.kpi_engine import (
    FLAG_APPROX_GHI,
    FLAG_INSUFFICIENT_DATA,
    FLAG_LOW_CONFIDENCE,
    KPIKey,
    KPIResult,
    compute_inverter_solar_kpis,
    compute_plant_solar_kpis,
    integrate_irradiation_kwh_m2,
)
from app.core.celery_app import celery_app
from app.db.session import create_db_engine, get_session_factory
from app.models.entities import Asset, Channel, KPIValue, Plant, Reading


def get_plant_timezone(plant: Plant) -> zoneinfo.ZoneInfo:
    """Resolve ZoneInfo for plant, defaulting to Asia/Kolkata."""
    tz_str = plant.timezone if plant.timezone else "Asia/Kolkata"
    try:
        return zoneinfo.ZoneInfo(tz_str)
    except Exception:
        return zoneinfo.ZoneInfo("Asia/Kolkata")


def align_readings_to_grid(
    readings: Sequence[Reading],
    day_start_local: datetime,
    cadence_minutes: int = 15,
    expected_intervals: int = 96,
) -> List[Optional[float]]:
    """Bucket time-series readings onto a 96-interval uniform daily grid.

    Args:
        readings: List of Reading entities sorted by timestamp.
        day_start_local: Start of the day in plant-local timezone.
        cadence_minutes: Sampling interval in minutes (default 15m).
        expected_intervals: Expected total intervals (96 for 24 hours at 15m).

    Returns:
        List of float values of length expected_intervals, with None for missing intervals.
    """
    grid: List[Optional[float]] = [None] * expected_intervals
    cadence_seconds = cadence_minutes * 60

    for r in readings:
        ts = r.ts
        if ts.tzinfo is None:
            # Treat naive timestamp as plant-local
            ts = ts.replace(tzinfo=day_start_local.tzinfo)
        else:
            # Convert to local timezone
            ts = ts.astimezone(day_start_local.tzinfo)

        offset_s = (ts - day_start_local).total_seconds()
        idx = int(round(offset_s / float(cadence_seconds)))
        if 0 <= idx < expected_intervals:
            val = float(r.value) if r.value is not None else None
            grid[idx] = val

    return grid


def compute_daily_kpis_for_plant(
    session: Session,
    plant: Plant,
    target_date: date,
    expected_intervals: int = 96,
) -> Dict[str, Any]:
    """Execute complete daily KPI rollup for a plant and its inverters.

    Args:
        session: Active SQLAlchemy session.
        plant: Plant entity.
        target_date: Calendar date to rollup.
        expected_intervals: Number of intervals expected (default 96 for 15-min).

    Returns:
        Summary dict containing counts and calculated KPI metrics.
    """
    tz = get_plant_timezone(plant)
    day_start_local = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tz
    )
    day_end_local = day_start_local + timedelta(days=1)

    # 1. Locate weather channel (irradiance_poa or irradiance_ghi)
    plant_assets = session.scalars(
        select(Asset).where(Asset.plant_id == plant.id)
    ).all()
    asset_by_id = {a.id: a for a in plant_assets}

    # Weather channels across plant
    weather_channels = session.scalars(
        select(Channel)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(
            Asset.plant_id == plant.id,
            Channel.canonical_key.in_(["irradiance_poa", "irradiance_ghi"]),
        )
    ).all()

    poa_channel: Optional[Channel] = None
    is_ghi = False
    for ch in weather_channels:
        if ch.canonical_key == "irradiance_poa":
            poa_channel = ch
            is_ghi = False
            break
        elif ch.canonical_key == "irradiance_ghi" and poa_channel is None:
            poa_channel = ch
            is_ghi = True

    poa_grid: List[Optional[float]] = [None] * expected_intervals
    if poa_channel:
        poa_readings = session.scalars(
            select(Reading)
            .where(
                Reading.channel_id == poa_channel.id,
                Reading.ts >= day_start_local,
                Reading.ts < day_end_local,
            )
            .order_by(Reading.ts.asc())
        ).all()
        poa_grid = align_readings_to_grid(
            poa_readings, day_start_local, expected_intervals=expected_intervals
        )

    # Integrate daily POA irradiation (kWh/m²)
    poa_kwh_m2, valid_poa_count = integrate_irradiation_kwh_m2(poa_grid, interval_hours=0.25)
    daily_poa: Optional[float] = poa_kwh_m2 if poa_kwh_m2 > 0 else None

    # 2. Process each inverter
    inverter_assets = [a for a in plant_assets if a.asset_type.lower() == "inverter"]
    num_inverters = len(inverter_assets)

    # Plant-level capacity defaults if not set on assets
    default_inv_dc = (
        float(plant.capacity_dc_kwp) / num_inverters
        if plant.capacity_dc_kwp and num_inverters > 0
        else 1250.0
    )
    default_inv_ac = (
        float(plant.capacity_ac_kw) / num_inverters
        if plant.capacity_ac_kw and num_inverters > 0
        else 1250.0
    )

    inverter_kpis_map: Dict[str, Dict[str, KPIResult]] = {}
    persisted_records_count = 0

    for inv in inverter_assets:
        inv_meta = inv.metadata_ or {}
        inv_dc = float(inv_meta.get("rated_dc_kwp", inv.rated_kw or default_inv_dc))
        inv_ac = float(inv_meta.get("rated_ac_kw", inv.rated_kw or default_inv_ac))

        # Query inverter channels
        inv_channels = session.scalars(
            select(Channel).where(Channel.asset_id == inv.id)
        ).all()
        ch_by_key = {c.canonical_key: c for c in inv_channels}

        # Power AC
        p_ac_grid: List[Optional[float]] = [None] * expected_intervals
        if "power_ac" in ch_by_key:
            readings = session.scalars(
                select(Reading)
                .where(
                    Reading.channel_id == ch_by_key["power_ac"].id,
                    Reading.ts >= day_start_local,
                    Reading.ts < day_end_local,
                )
                .order_by(Reading.ts.asc())
            ).all()
            p_ac_grid = align_readings_to_grid(
                readings, day_start_local, expected_intervals=expected_intervals
            )

        # Power DC
        p_dc_grid: Optional[List[Optional[float]]] = None
        if "power_dc" in ch_by_key:
            dc_readings = session.scalars(
                select(Reading)
                .where(
                    Reading.channel_id == ch_by_key["power_dc"].id,
                    Reading.ts >= day_start_local,
                    Reading.ts < day_end_local,
                )
                .order_by(Reading.ts.asc())
            ).all()
            p_dc_grid = align_readings_to_grid(
                dc_readings, day_start_local, expected_intervals=expected_intervals
            )

        # Compute inverter KPIs
        expected_pr = float(plant.expected_pr) if plant.expected_pr else 0.78
        inv_results = compute_inverter_solar_kpis(
            power_ac_w=p_ac_grid,
            power_dc_w=p_dc_grid,
            irradiance_poa_wm2=poa_grid,
            capacity_dc_kwp=inv_dc,
            capacity_ac_kw=inv_ac,
            expected_pr=expected_pr,
            interval_hours=0.25,
            is_ghi=is_ghi,
            expected_count=expected_intervals,
        )
        inverter_kpis_map[inv.name] = inv_results

        # Persist inverter KPIs to kpi_values
        for k_key, res in inv_results.items():
            upsert_kpi_value(
                session=session,
                time_val=day_start_local,
                plant_id=plant.id,
                asset_id=inv.id,
                kpi_key=k_key,
                period="day",
                value=res.value,
                coverage=res.coverage,
                flags=res.flags,
            )
            persisted_records_count += 1

    # 3. Compute Plant-level rollup KPIs
    plant_dc = float(plant.capacity_dc_kwp) if plant.capacity_dc_kwp else default_inv_dc * num_inverters
    plant_ac = float(plant.capacity_ac_kw) if plant.capacity_ac_kw else default_inv_ac * num_inverters
    plant_pr_target = float(plant.expected_pr) if plant.expected_pr else 0.78

    plant_results = compute_plant_solar_kpis(
        inverter_kpis=inverter_kpis_map,
        plant_capacity_dc_kwp=plant_dc,
        plant_capacity_ac_kw=plant_ac,
        plant_expected_pr=plant_pr_target,
        irradiation_poa_kwh_m2=daily_poa,
        is_ghi=is_ghi,
    )

    # Persist plant-level KPIs (asset_id = None)
    for k_key, res in plant_results.items():
        upsert_kpi_value(
            session=session,
            time_val=day_start_local,
            plant_id=plant.id,
            asset_id=None,
            kpi_key=k_key,
            period="day",
            value=res.value,
            coverage=res.coverage,
            flags=res.flags,
        )
        persisted_records_count += 1

    session.commit()

    return {
        "plant_id": str(plant.id),
        "plant_name": plant.name,
        "date": target_date.isoformat(),
        "inverters_count": len(inverter_assets),
        "persisted_records": persisted_records_count,
        "plant_kpis": {k: res.as_dict() for k, res in plant_results.items()},
    }


def upsert_kpi_value(
    session: Session,
    time_val: datetime,
    plant_id: UUID,
    asset_id: Optional[UUID],
    kpi_key: str,
    period: str,
    value: Optional[float],
    coverage: float,
    flags: List[str],
) -> Optional[KPIValue]:
    """Idempotently insert or update a KPIValue record in the database."""
    stmt = select(KPIValue).where(
        KPIValue.time == time_val,
        KPIValue.plant_id == plant_id,
        KPIValue.kpi_key == kpi_key,
        KPIValue.period == period,
    )
    if asset_id is None:
        stmt = stmt.where(KPIValue.asset_id.is_(None))
    else:
        stmt = stmt.where(KPIValue.asset_id == asset_id)

    existing = session.scalars(stmt).first()
    if existing:
        up_stmt = update(KPIValue).where(
            KPIValue.time == time_val,
            KPIValue.plant_id == plant_id,
            KPIValue.kpi_key == kpi_key,
            KPIValue.period == period,
        )
        if asset_id is None:
            up_stmt = up_stmt.where(KPIValue.asset_id.is_(None))
        else:
            up_stmt = up_stmt.where(KPIValue.asset_id == asset_id)
        session.execute(
            up_stmt.values(value=value, coverage=coverage, flags=list(flags))
        )
        return existing
    else:
        new_row = KPIValue(
            time=time_val,
            plant_id=plant_id,
            asset_id=asset_id,
            kpi_key=kpi_key,
            period=period,
            value=value,
            coverage=coverage,
            flags=list(flags),
        )
        session.add(new_row)
        return new_row


# ---------------------------------------------------------------------------
# Celery Tasks (§11, S3-AI-01)
# ---------------------------------------------------------------------------


@celery_app.task(name="tasks.compute_daily_kpis", bind=True)
def compute_daily_kpis(
    self: Task,
    plant_id: str,
    target_date_str: str,
    db_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Celery task computing daily KPI rollups for a specific plant and date.

    Args:
        plant_id: UUID string of the plant.
        target_date_str: Date string in 'YYYY-MM-DD' format.
        db_url: Optional database connection URL override.

    Returns:
        Summary dictionary with execution results.
    """
    engine = create_db_engine(db_url)
    session_factory = get_session_factory(engine)
    target_date = date.fromisoformat(target_date_str)
    p_uuid = UUID(plant_id)

    with session_factory() as session:
        plant = session.get(Plant, p_uuid)
        if not plant:
            raise ValueError(f"Plant with id {plant_id} not found.")

        result = compute_daily_kpis_for_plant(
            session=session,
            plant=plant,
            target_date=target_date,
        )
        return result


@celery_app.task(name="tasks.run_all_plants_daily_kpis", bind=True)
def run_all_plants_daily_kpis(
    self: Task,
    target_date_str: Optional[str] = None,
    db_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Celery task running daily KPI rollups across all active plants.

    Scheduled by Celery Beat at 01:00 UTC daily for yesterday's data.

    Args:
        target_date_str: Optional date string 'YYYY-MM-DD'; defaults to yesterday.
        db_url: Optional database connection URL override.

    Returns:
        Summary dictionary of all processed plants.
    """
    engine = create_db_engine(db_url)
    session_factory = get_session_factory(engine)

    if target_date_str:
        target_date = date.fromisoformat(target_date_str)
    else:
        target_date = date.today() - timedelta(days=1)

    processed_plants: List[Dict[str, Any]] = []

    with session_factory() as session:
        plants = session.scalars(select(Plant)).all()
        for p in plants:
            res = compute_daily_kpis_for_plant(
                session=session,
                plant=p,
                target_date=target_date,
            )
            processed_plants.append({
                "plant_id": str(p.id),
                "plant_name": p.name,
                "status": "success",
                "inverters_count": res.get("inverters_count", 0),
            })

    return {
        "target_date": target_date.isoformat(),
        "total_plants": len(processed_plants),
        "plants": processed_plants,
    }
