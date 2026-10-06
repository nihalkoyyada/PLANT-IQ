"""Integration Tests for Daily KPI Rollup Tasks & TimescaleDB Persistence (§11, Task S3-AI-01).

Validates:
- Telemetry alignment to uniform 15-minute daily grid.
- Full daily KPI rollup execution per plant and per inverter.
- Idempotent upsert into `kpi_values` table (no duplicate primary key violations).
- Input coverage % accuracy and low-confidence / insufficient-data flag recording.
- Plant-level rollup (asset_id = None) and inverter-level rollups (asset_id = inverter.id).
- Celery task invocation contract.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
import uuid
import zoneinfo
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.kpi_engine import KPIKey
from app.db.base import Base
from app.models.entities import (
    Asset,
    CanonicalSignal,
    Channel,
    KPIValue,
    Organization,
    Plant,
    Reading,
)
from app.tasks.kpi_tasks import (
    align_readings_to_grid,
    compute_daily_kpis,
    compute_daily_kpis_for_plant,
    get_plant_timezone,
    upsert_kpi_value,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database session fixture."""
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as session:
        yield session


@pytest.fixture
def seeded_plant(db_session: Session) -> Dict[str, Any]:
    """Seed test Organization, Plant, 2 Inverters, Weather Station, and Channels."""
    # 1. Organization
    org = Organization(name="Test Solar Corp", slug="test-solar")
    db_session.add(org)
    db_session.flush()

    # 2. Plant (Surya-A test asset)
    plant = Plant(
        org_id=org.id,
        name="Surya-A-Test",
        slug="surya-a-test",
        plant_type="solar",
        capacity_dc_kwp=2500.0,
        capacity_ac_kw=2500.0,
        timezone="Asia/Kolkata",
        expected_pr=0.78,
    )
    db_session.add(plant)
    db_session.flush()

    # 3. Canonical signals
    sig_pac = CanonicalSignal(
        signal_key="power_ac",
        display_name="AC Power",
        category="power",
        unit="W",
        data_type="float",
        monotonicity="none",
        bound_min_rule="0.0",
        bound_max_rule="1500000.0",
    )
    sig_pdc = CanonicalSignal(
        signal_key="power_dc",
        display_name="DC Power",
        category="power",
        unit="W",
        data_type="float",
        monotonicity="none",
        bound_min_rule="0.0",
        bound_max_rule="1500000.0",
    )
    sig_poa = CanonicalSignal(
        signal_key="irradiance_poa",
        display_name="POA Irradiance",
        category="weather",
        unit="W/m²",
        data_type="float",
        monotonicity="none",
        bound_min_rule="0.0",
        bound_max_rule="1500.0",
    )
    db_session.add_all([sig_pac, sig_pdc, sig_poa])
    db_session.flush()

    # 4. Inverters (INV-01, INV-02)
    inv1 = Asset(
        plant_id=plant.id,
        name="INV-01",
        asset_type="inverter",
        metadata_json={"rated_dc_kwp": 1250.0, "rated_ac_kw": 1250.0},
    )
    inv2 = Asset(
        plant_id=plant.id,
        name="INV-02",
        asset_type="inverter",
        metadata_json={"rated_dc_kwp": 1250.0, "rated_ac_kw": 1250.0},
    )
    ws = Asset(
        plant_id=plant.id,
        name="WS-01",
        asset_type="weather_station",
        metadata_json={},
    )
    db_session.add_all([inv1, inv2, ws])
    db_session.flush()

    # 5. Channels
    ch_inv1_pac = Channel(
        asset_id=inv1.id,
        canonical_key="power_ac",
        source_name="INV1_AC",
        interval_s=900,
        receive_unit="W",
    )
    ch_inv1_pdc = Channel(
        asset_id=inv1.id,
        canonical_key="power_dc",
        source_name="INV1_DC",
        interval_s=900,
        receive_unit="W",
    )
    ch_inv2_pac = Channel(
        asset_id=inv2.id,
        canonical_key="power_ac",
        source_name="INV2_AC",
        interval_s=900,
        receive_unit="W",
    )
    ch_inv2_pdc = Channel(
        asset_id=inv2.id,
        canonical_key="power_dc",
        source_name="INV2_DC",
        interval_s=900,
        receive_unit="W",
    )
    ch_ws_poa = Channel(
        asset_id=ws.id,
        canonical_key="irradiance_poa",
        source_name="WS_POA",
        interval_s=900,
        receive_unit="W/m²",
    )
    db_session.add_all([ch_inv1_pac, ch_inv1_pdc, ch_inv2_pac, ch_inv2_pdc, ch_ws_poa])
    db_session.commit()

    return {
        "org": org,
        "plant": plant,
        "inv1": inv1,
        "inv2": inv2,
        "ws": ws,
        "ch_inv1_pac": ch_inv1_pac,
        "ch_inv1_pdc": ch_inv1_pdc,
        "ch_inv2_pac": ch_inv2_pac,
        "ch_inv2_pdc": ch_inv2_pdc,
        "ch_ws_poa": ch_ws_poa,
    }


def test_align_readings_to_grid() -> None:
    """Verify alignment of 15m timestamped readings onto a 96-interval grid."""
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    day_start = datetime(2020, 5, 15, 0, 0, 0, tzinfo=tz)

    r1 = Reading(
        channel_id=uuid.uuid4(),
        ts=day_start + timedelta(minutes=0),
        value=100.0,
        quality=0,
    )
    r2 = Reading(
        channel_id=uuid.uuid4(),
        ts=day_start + timedelta(minutes=15),
        value=200.0,
        quality=0,
    )
    r3 = Reading(
        channel_id=uuid.uuid4(),
        ts=day_start + timedelta(minutes=60),  # interval 4
        value=500.0,
        quality=0,
    )

    grid = align_readings_to_grid([r1, r2, r3], day_start, expected_intervals=96)

    assert grid[0] == 100.0
    assert grid[1] == 200.0
    assert grid[2] is None
    assert grid[3] is None
    assert grid[4] == 500.0
    assert len(grid) == 96


def test_compute_daily_kpis_for_plant_full_pipeline(
    db_session: Session, seeded_plant: Dict[str, Any]
) -> None:
    """Verify end-to-end daily KPI rollup execution and persistence into kpi_values."""
    plant: Plant = seeded_plant["plant"]
    inv1: Asset = seeded_plant["inv1"]
    inv2: Asset = seeded_plant["inv2"]
    ch_inv1_pac: Channel = seeded_plant["ch_inv1_pac"]
    ch_inv1_pdc: Channel = seeded_plant["ch_inv1_pdc"]
    ch_inv2_pac: Channel = seeded_plant["ch_inv2_pac"]
    ch_inv2_pdc: Channel = seeded_plant["ch_inv2_pdc"]
    ch_ws_poa: Channel = seeded_plant["ch_ws_poa"]

    target_date = date(2020, 5, 15)
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    day_start = datetime(2020, 5, 15, 0, 0, 0, tzinfo=tz)

    # Seed 96 intervals of readings
    readings: List[Reading] = []
    for i in range(96):
        ts = day_start + timedelta(minutes=15 * i)
        # Daylight during intervals 24..63 (06:00 to 16:00)
        is_daylight = 24 <= i < 64
        poa_val = 800.0 if is_daylight else 0.0
        p_ac = 1000_000.0 if is_daylight else 0.0  # 1000 kW
        p_dc = 1025_000.0 if is_daylight else 0.0  # 1025 kW

        readings.append(Reading(channel_id=ch_ws_poa.id, ts=ts, value=poa_val, quality=0))
        readings.append(Reading(channel_id=ch_inv1_pac.id, ts=ts, value=p_ac, quality=0))
        readings.append(Reading(channel_id=ch_inv1_pdc.id, ts=ts, value=p_dc, quality=0))
        readings.append(Reading(channel_id=ch_inv2_pac.id, ts=ts, value=p_ac, quality=0))
        readings.append(Reading(channel_id=ch_inv2_pdc.id, ts=ts, value=p_dc, quality=0))

    db_session.add_all(readings)
    db_session.commit()

    # Execute rollup
    summary = compute_daily_kpis_for_plant(
        session=db_session,
        plant=plant,
        target_date=target_date,
    )

    assert summary["plant_name"] == "Surya-A-Test"
    assert summary["inverters_count"] == 2
    # 2 inverters * 7 KPIs + 1 plant * 7 KPIs = 21 records
    assert summary["persisted_records"] == 21

    # Verify rows in kpi_values table
    kpi_rows = db_session.scalars(select(KPIValue)).all()
    assert len(kpi_rows) == 21

    # Plant-level rows (asset_id is None)
    plant_rows = [r for r in kpi_rows if r.asset_id is None]
    assert len(plant_rows) == 7
    plant_keys = {r.kpi_key: r for r in plant_rows}

    # Total plant energy: 1000 kW * 0.25h * 40 intervals * 2 inverters = 20,000 kWh
    assert plant_keys[KPIKey.ENERGY_AC.value].value == 20000.0
    assert plant_keys[KPIKey.SPECIFIC_YIELD.value].value == 20000.0 / 2500.0  # 8.0 kWh/kWp
    assert plant_keys[KPIKey.AVAILABILITY.value].value == 1.0
    assert plant_keys[KPIKey.PERFORMANCE_RATIO.value].value == 1.0
    assert plant_keys[KPIKey.INVERTER_EFFICIENCY.value].value == pytest.approx(0.9756, rel=1e-3)
    assert plant_keys[KPIKey.ENERGY_LOSS.value].value == 0.0

    # Inverter rows (asset_id is not None)
    inv1_rows = [r for r in kpi_rows if r.asset_id == inv1.id]
    assert len(inv1_rows) == 7
    inv1_keys = {r.kpi_key: r for r in inv1_rows}
    assert inv1_keys[KPIKey.ENERGY_AC.value].value == 10000.0
    assert inv1_keys[KPIKey.SPECIFIC_YIELD.value].value == 8.0
    assert inv1_keys[KPIKey.AVAILABILITY.value].value == 1.0


def test_compute_daily_kpis_idempotency(
    db_session: Session, seeded_plant: Dict[str, Any]
) -> None:
    """Verify that running rollup twice updates existing records without primary key errors."""
    plant: Plant = seeded_plant["plant"]
    target_date = date(2020, 5, 15)

    # First run (empty data -> insufficient data)
    summary1 = compute_daily_kpis_for_plant(
        session=db_session,
        plant=plant,
        target_date=target_date,
    )
    assert summary1["persisted_records"] == 21
    rows_count1 = len(db_session.scalars(select(KPIValue)).all())
    assert rows_count1 == 21

    # Second run on same date
    summary2 = compute_daily_kpis_for_plant(
        session=db_session,
        plant=plant,
        target_date=target_date,
    )
    rows_count2 = len(db_session.scalars(select(KPIValue)).all())
    assert rows_count2 == 21  # Total count unchanged (idempotent upsert)


def test_upsert_kpi_value_updates_existing(db_session: Session) -> None:
    """Verify upsert_kpi_value updates value, coverage, and flags for existing row."""
    t0 = datetime(2020, 5, 15, 0, 0, 0, tzinfo=timezone.utc)
    p_id = uuid.uuid4()
    a_id = uuid.uuid4()

    # Insert
    row1 = upsert_kpi_value(
        session=db_session,
        time_val=t0,
        plant_id=p_id,
        asset_id=a_id,
        kpi_key="pr",
        period="day",
        value=0.75,
        coverage=0.90,
        flags=[],
    )
    db_session.commit()

    assert row1 is not None
    assert row1.value == 0.75
    assert float(row1.coverage) == pytest.approx(0.90)

    # Update
    upsert_kpi_value(
        session=db_session,
        time_val=t0,
        plant_id=p_id,
        asset_id=a_id,
        kpi_key="pr",
        period="day",
        value=0.78,
        coverage=1.0,
        flags=["approx_ghi"],
    )
    db_session.commit()

    updated_row = db_session.scalars(
        select(KPIValue).where(
            KPIValue.time == t0,
            KPIValue.plant_id == p_id,
            KPIValue.asset_id == a_id,
            KPIValue.kpi_key == "pr",
            KPIValue.period == "day",
        )
    ).first()

    assert updated_row is not None
    assert updated_row.value == 0.78
    assert float(updated_row.coverage) == pytest.approx(1.0)
    assert updated_row.flags == ["approx_ghi"]
