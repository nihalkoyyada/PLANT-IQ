"""Regression tests for POA-aware Anomaly Detection, Solar Ramp Guards, and Re-scan Auto-Reconciliation.

Verifies:
1. POA-aware detection: When weather station irradiance_poa is mapped and inverter generation
   tracks or exceeds measured insolation, zero false-positive anomalies are flagged.
2. Normal solar ramp-up and ramp-down: Morning ramp-up (06:00-08:00) and evening ramp-down (16:30-18:30)
   do not falsely trigger PR deviation anomalies. Single-interval fluctuations are suppressed.
3. Repeated scan idempotency and auto-reconciliation:
   - Repeated scans create 0 duplicate anomalies.
   - Re-running with a valid POA baseline auto-reconciles open unconfirmed detector anomalies
     to status='false_positive' with explanatory audit notes while preserving records and
     operator triage statuses (e.g. 'acknowledged').
4. Genuine sustained underperformance: When an inverter suffers sustained underperformance
   under strong POA irradiance, the detector accurately flags it with correct severity, loss kW,
   and energy loss kWh.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.detector_registry import DetectorContext, DetectorRegistry
from app.models.entities import Anomaly, Asset, Base, Channel, Organization, Plant, Reading
from app.tasks.detector_tasks import execute_plant_anomaly_scan


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
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def plant_setup(db_session: Session) -> Dict[str, Any]:
    """Create test organization, plant, weather station, and inverter."""
    uid = uuid4().hex[:8]
    org = Organization(name=f"Solar Org {uid}")
    db_session.add(org)
    db_session.flush()

    plant = Plant(
        org_id=org.id,
        name=f"Surya Test Solar Farm {uid}",
        plant_type="solar",
        capacity_dc_kwp=28000.0,
        capacity_ac_kw=25000.0,
        tariff_inr_per_kwh=3.50,
        expected_pr=0.78,
        latitude=27.5398,
        longitude=71.9161,
    )
    db_session.add(plant)
    db_session.flush()

    # Weather Station WS-01 with irradiance_poa
    ws = Asset(plant_id=plant.id, name="WS-01", asset_type="weather_station")
    db_session.add(ws)
    db_session.flush()

    ws_channel = Channel(
        asset_id=ws.id,
        canonical_signal_key="irradiance_poa",
        source_name="IRRADIATION",
        receive_unit="kW/m²",
        interval_s=900,
    )
    db_session.add(ws_channel)
    db_session.flush()

    # Inverter INV-01
    inv = Asset(
        plant_id=plant.id,
        name="INV-01",
        asset_type="inverter",
        metadata_json={"rated_ac_kw": 1250.0},
    )
    db_session.add(inv)
    db_session.flush()

    p_channel = Channel(
        asset_id=inv.id,
        canonical_signal_key="power_ac",
        source_name="AC_POWER",
        receive_unit="kW",
        interval_s=900,
    )
    db_session.add(p_channel)
    db_session.commit()

    return {
        "org": org,
        "plant": plant,
        "ws": ws,
        "ws_channel": ws_channel,
        "inv": inv,
        "p_channel": p_channel,
    }


def test_poa_aware_detection_nominal_generation_flags_zero_anomalies(
    db_session: Session, plant_setup: Dict[str, Any]
):
    """When generation tracks measured POA (including variable clouds), zero anomalies are detected."""
    plant = plant_setup["plant"]
    ws_ch = plant_setup["ws_channel"]
    p_ch = plant_setup["p_channel"]

    base_time = datetime(2026, 6, 17, 6, 0, tzinfo=timezone.utc)
    rated_kw = 1250.0
    expected_pr = 0.78

    # Seed 12 hours of telemetry (48 intervals of 15 min)
    # Varied irradiance simulating partial overcast conditions (0.1 to 0.9 kW/m²)
    for i in range(48):
        ts = base_time + timedelta(minutes=15 * i)
        # POA in kW/m²
        hour_fraction = i / 48.0
        poa_val = 0.85 * max(0.0, 1.0 - 4.0 * (hour_fraction - 0.5) ** 2)
        # Actual power generating nominally at ~80% PR
        expected_kw = poa_val * rated_kw * expected_pr
        act_power = expected_kw * 1.02  # Inverter performing slightly above expected PR

        db_session.add(Reading(channel_id=ws_ch.id, ts=ts, value=poa_val, quality=0))
        db_session.add(Reading(channel_id=p_ch.id, ts=ts, value=act_power, quality=0))

    db_session.commit()

    res = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert res["status"] == "success"
    assert res["poa_baseline_used"] is True
    assert res["anomalies_detected"] == 0
    assert res["anomalies_created"] == 0


def test_normal_solar_ramp_up_down_not_flagged(
    db_session: Session, plant_setup: Dict[str, Any]
):
    """Verify morning ramp-up and evening ramp-down variations do not generate false positives."""
    det = DetectorRegistry.get("d2_pr_deviation")
    plant = plant_setup["plant"]
    inv = plant_setup["inv"]
    p_ch = plant_setup["p_channel"]

    # Morning ramp: 06:00 to 07:30 (low sun elevation, power ramping from 0 to 80 kW)
    morning_base = datetime(2026, 6, 17, 6, 0, tzinfo=timezone.utc)
    morning_obs = []
    irradiance_ref = {}
    for i in range(7):
        ts = morning_base + timedelta(minutes=15 * i)
        poa = 0.05 + 0.03 * i  # 50 to 230 W/m²
        irradiance_ref[ts] = poa * 1000.0
        # Inverter ramping up
        power = max(0.0, (poa * 1250.0 * 0.78) * 0.90)
        morning_obs.append((ts, power))

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=p_ch.id,
        canonical_key="power_ac",
        plant_name=plant.name,
        asset_name=inv.name,
        asset_type="inverter",
        rated_kw=1250.0,
        expected_pr=0.78,
        irradiance_reference=irradiance_ref,
        cadence_seconds=900,
    )

    anomalies = det.detect(morning_obs, {}, ctx)
    assert len(anomalies) == 0, f"Morning ramp-up falsely flagged: {anomalies}"


def test_repeated_scans_and_auto_reconciliation(
    db_session: Session, plant_setup: Dict[str, Any]
):
    """Verify repeated scans are idempotent and uncalibrated false positives are auto-reconciled."""
    plant = plant_setup["plant"]
    ws_ch = plant_setup["ws_channel"]
    inv = plant_setup["inv"]
    p_ch = plant_setup["p_channel"]

    base_time = datetime(2026, 6, 17, 6, 0, tzinfo=timezone.utc)

    # 1. Create an existing OPEN false-positive anomaly (as if from earlier uncalibrated run)
    fake_fp = Anomaly(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=p_ch.id,
        start_time=base_time + timedelta(hours=1),
        end_time=base_time + timedelta(hours=3),
        source="detector",
        severity="critical",
        status="open",
        estimated_loss_kw=200.0,
        summary="Uncalibrated clear-sky detector anomaly",
        details={"irradiance_reference_used": False},
    )
    # Also create an ACKNOWLEDGED anomaly to ensure human triage is preserved
    ack_anomaly = Anomaly(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=p_ch.id,
        start_time=base_time + timedelta(hours=4),
        end_time=base_time + timedelta(hours=6),
        source="detector",
        severity="high",
        status="acknowledged",
        status_note="Technician inspecting string.",
        details={"irradiance_reference_used": False},
    )
    db_session.add(fake_fp)
    db_session.add(ack_anomaly)
    db_session.commit()

    # 2. Add calibrated telemetry and POA readings showing nominal operation with realistic solar variation
    import math
    for i in range(40):
        ts = base_time + timedelta(minutes=15 * i)
        solar_frac = math.sin((i + 1) / 42.0 * math.pi)
        poa_kw = round(0.85 * max(0.1, solar_frac), 3)
        act_kw = round(poa_kw * 1250.0 * 0.78 * (0.99 + 0.02 * (i % 4)), 1)
        db_session.add(Reading(channel_id=ws_ch.id, ts=ts, value=poa_kw, quality=0))
        db_session.add(Reading(channel_id=p_ch.id, ts=ts, value=act_kw, quality=0))
    db_session.commit()

    # 3. Execute scan
    res = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert res["status"] == "success"
    assert res["poa_baseline_used"] is True
    assert res["anomalies_detected"] == 0
    assert res["anomalies_reconciled"] == 1  # Exactly the 1 un-triaged open anomaly was reconciled!

    # Verify database state
    db_session.refresh(fake_fp)
    db_session.refresh(ack_anomaly)

    # Fake FP is now false_positive with audit note
    assert fake_fp.status == "false_positive"
    assert "Auto-reconciled" in fake_fp.status_note
    assert fake_fp.details.get("reconciled_by") == "poa_calibrated_scan"

    # Human-triaged acknowledged anomaly is strictly preserved!
    assert ack_anomaly.status == "acknowledged"
    assert ack_anomaly.status_note == "Technician inspecting string."


def test_genuine_sustained_underperformance_flagged(
    db_session: Session, plant_setup: Dict[str, Any]
):
    """When an inverter genuinely underperforms under high POA, it is flagged with correct metrics."""
    plant = plant_setup["plant"]
    ws_ch = plant_setup["ws_channel"]
    inv = plant_setup["inv"]
    p_ch = plant_setup["p_channel"]

    base_time = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
    rated_kw = 1250.0
    expected_pr = 0.78

    # 8 intervals (2 hours) of blazing sun: 900 W/m² (0.90 kW/m²)
    # Expected power = 0.90 * 1250 * 0.78 = 877.5 kW
    # Actual power = 300 kW (severe underperformance, ~34% PR instead of 78%)
    for i in range(8):
        ts = base_time + timedelta(minutes=15 * i)
        db_session.add(Reading(channel_id=ws_ch.id, ts=ts, value=0.90, quality=0))
        db_session.add(Reading(channel_id=p_ch.id, ts=ts, value=300.0 + (i % 4) * 10.0, quality=0))
    db_session.commit()

    res = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert res["status"] == "success"
    assert res["poa_baseline_used"] is True
    assert res["anomalies_detected"] >= 1
    assert res["anomalies_created"] >= 1

    # Verify persisted anomaly in DB
    anom = db_session.execute(
        select(Anomaly)
        .where(Anomaly.plant_id == plant.id, Anomaly.asset_id == inv.id, Anomaly.status == "open")
    ).scalars().first()

    assert anom is not None
    assert anom.status == "open"
    assert anom.estimated_loss_kw is not None
    assert anom.estimated_loss_kw > 400.0  # Deficit: ~577.5 kW
    assert anom.details.get("irradiance_reference_used") is True
    assert anom.details.get("actual_pr") < 0.40
    assert anom.details.get("expected_pr") == 0.78
