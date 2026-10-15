"""Regression tests for Anomaly Detection Scan assets_scanned tracking and idempotency.

Verifies:
1. assets_scanned reflects the actual number of assets genuinely evaluated (with telemetry),
   not merely loaded from the database or non-inverter assets.
2. An empty plant or non-existent plant returns assets_scanned: 0.
3. Repeated scans create zero duplicate anomalies and preserve existing statuses
   (e.g., acknowledged, resolved) and technician notes.
4. Scan response counts (detected, created, merged) are mathematically consistent
   with actual processing results.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.entities import Anomaly, Asset, Base, Channel, Event, Organization, Plant, Reading
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
def regression_setup(db_session: Session) -> Dict[str, Any]:
    """Create test organization and plant."""
    uid = uuid4().hex[:8]
    org = Organization(name=f"Regression Org {uid}")
    db_session.add(org)
    db_session.flush()

    plant = Plant(
        org_id=org.id,
        name=f"Regression Plant {uid}",
        plant_type="solar",
        capacity_dc_kwp=3000.0,
        capacity_ac_kw=2500.0,
        tariff_inr_per_kwh=3.50,
        expected_pr=0.82,
    )
    db_session.add(plant)
    db_session.commit()

    return {"org": org, "plant": plant}


def test_assets_scanned_reflects_actual_evaluated_inverters(
    db_session: Session, regression_setup: Dict[str, Any]
):
    """Verify assets_scanned counts only inverters genuinely evaluated with sufficient telemetry.

    Setup:
    - Inverter 1: Has active_power channel and 10 readings -> genuinely processed.
    - Inverter 2: Has active_power channel and 10 readings -> genuinely processed.
    - Inverter 3: Has active_power channel but only 2 readings (< 4 threshold) -> skipped.
    - Inverter 4: Has NO channels at all -> skipped.
    - Transformer 1 (non-inverter): Has 10 readings -> not processed by default inverter detectors.

    Expected: assets_scanned == 2 (NOT 4, NOT 5, NOT 22).
    """
    plant = regression_setup["plant"]
    now = datetime.now(timezone.utc)

    # Inverter 1 (valid readings)
    inv1 = Asset(plant_id=plant.id, name="INV-01", asset_type="inverter", metadata_json={"rated_ac_kw": 1000.0})
    db_session.add(inv1)
    db_session.flush()
    ch1 = Channel(asset_id=inv1.id, canonical_signal_key="power_ac", source_name="AC_PWR", interval_s=900)
    db_session.add(ch1)
    db_session.flush()
    for i in range(10):
        ts = now - timedelta(hours=2) + timedelta(minutes=15 * i)
        val = 0.0 if i >= 6 else 750.0  # midday trip fault
        db_session.add(Reading(channel_id=ch1.id, ts=ts, value=val, quality=0))

    # Inverter 2 (valid readings)
    inv2 = Asset(plant_id=plant.id, name="INV-02", asset_type="inverter", metadata_json={"rated_ac_kw": 1000.0})
    db_session.add(inv2)
    db_session.flush()
    ch2 = Channel(asset_id=inv2.id, canonical_signal_key="power_ac", source_name="AC_PWR", interval_s=900)
    db_session.add(ch2)
    db_session.flush()
    for i in range(10):
        ts = now - timedelta(hours=2) + timedelta(minutes=15 * i)
        val = 800.0
        db_session.add(Reading(channel_id=ch2.id, ts=ts, value=val, quality=0))

    # Inverter 3 (only 2 readings, below minimum threshold of 4)
    inv3 = Asset(plant_id=plant.id, name="INV-03-INSUFFICIENT", asset_type="inverter")
    db_session.add(inv3)
    db_session.flush()
    ch3 = Channel(asset_id=inv3.id, canonical_signal_key="power_ac", source_name="AC_PWR", interval_s=900)
    db_session.add(ch3)
    db_session.flush()
    for i in range(2):
        ts = now - timedelta(hours=2) + timedelta(minutes=15 * i)
        db_session.add(Reading(channel_id=ch3.id, ts=ts, value=500.0, quality=0))

    # Inverter 4 (no channels)
    inv4 = Asset(plant_id=plant.id, name="INV-04-NO-CHANNELS", asset_type="inverter")
    db_session.add(inv4)

    # Transformer 1 (non-inverter asset)
    tx1 = Asset(plant_id=plant.id, name="TX-01", asset_type="transformer")
    db_session.add(tx1)
    db_session.flush()
    ch_tx = Channel(asset_id=tx1.id, canonical_signal_key="power_ac", source_name="TX_PWR", interval_s=900)
    db_session.add(ch_tx)
    db_session.flush()
    for i in range(10):
        ts = now - timedelta(hours=2) + timedelta(minutes=15 * i)
        db_session.add(Reading(channel_id=ch_tx.id, ts=ts, value=1500.0, quality=0))

    db_session.commit()

    # Execute scan
    summary = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert summary["status"] == "success"
    # Assets scanned MUST be exactly 2 (INV-01 and INV-02)
    assert summary["assets_scanned"] == 2
    assert summary["assets_scanned"] != 22
    assert summary["detectors_evaluated"] >= 1


def test_empty_plant_returns_assets_scanned_zero(
    db_session: Session, regression_setup: Dict[str, Any]
):
    """Verify that an empty plant with zero assets returns assets_scanned: 0."""
    plant = regression_setup["plant"]

    summary = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert summary["status"] == "success"
    assert summary["assets_scanned"] == 0
    assert summary["anomalies_detected"] == 0
    assert summary["anomalies_created"] == 0
    assert summary["anomalies_merged"] == 0


def test_nonexistent_plant_returns_assets_scanned_zero(db_session: Session):
    """Verify that a non-existent plant ID safely returns status plant_not_found and assets_scanned: 0."""
    random_id = uuid4()
    summary = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=random_id,
        window_hours=24,
    )

    assert summary["status"] == "plant_not_found"
    assert summary["assets_scanned"] == 0


def test_repeated_scans_create_no_duplicates_and_preserve_status_and_notes(
    db_session: Session, regression_setup: Dict[str, Any]
):
    """Verify repeated scans create zero duplicate anomalies and preserve operator triage status and notes."""
    plant = regression_setup["plant"]
    now = datetime.now(timezone.utc)

    # Setup inverter with a clear trip condition
    inv = Asset(plant_id=plant.id, name="INV-TRIP-TEST", asset_type="inverter", metadata_json={"rated_ac_kw": 1000.0})
    db_session.add(inv)
    db_session.flush()

    ch = Channel(asset_id=inv.id, canonical_signal_key="power_ac", source_name="AC_PWR", interval_s=900)
    db_session.add(ch)
    db_session.flush()

    # Telemetry: sudden midday drop to 0.0
    for i in range(12):
        ts = now - timedelta(hours=3) + timedelta(minutes=15 * i)
        val = 0.0 if i in (6, 7, 8) else 850.0
        db_session.add(Reading(channel_id=ch.id, ts=ts, value=val, quality=0))
    db_session.commit()

    # Pass 1: Initial scan
    scan1 = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert scan1["status"] == "success"
    assert scan1["assets_scanned"] == 1
    assert scan1["anomalies_created"] >= 1
    initial_created = scan1["anomalies_created"]

    # Verify initial anomaly in database
    anomalies_pass1 = db_session.execute(
        select(Anomaly).where(Anomaly.plant_id == plant.id)
    ).scalars().all()
    assert len(anomalies_pass1) == initial_created

    # Simulate field technician triage
    target_anomaly = anomalies_pass1[0]
    target_id = target_anomaly.id
    target_anomaly.status = "acknowledged"
    target_anomaly.status_note = "Technician dispatched to replace inverter IGBT module."
    db_session.commit()

    # Pass 2: Re-run scan over exact same telemetry window
    scan2 = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert scan2["status"] == "success"
    assert scan2["assets_scanned"] == 1
    assert scan2["anomalies_created"] == 0  # ZERO new anomalies created
    assert scan2["anomalies_merged"] >= 1  # Reconciled with existing anomalies

    # Verify database state after re-scan
    anomalies_pass2 = db_session.execute(
        select(Anomaly).where(Anomaly.plant_id == plant.id)
    ).scalars().all()

    # 1. NO DUPLICATE RECORDS
    assert len(anomalies_pass2) == len(anomalies_pass1)

    # 2. STATUS PRESERVED
    updated_anomaly = db_session.get(Anomaly, target_id)
    assert updated_anomaly is not None
    assert updated_anomaly.status == "acknowledged"

    # 3. TECHNICIAN NOTE PRESERVED
    assert updated_anomaly.status_note == "Technician dispatched to replace inverter IGBT module."


def test_scan_response_counts_consistency_with_processing_results(
    db_session: Session, regression_setup: Dict[str, Any]
):
    """Verify that scan response metrics are mathematically consistent with processing output."""
    plant = regression_setup["plant"]
    now = datetime.now(timezone.utc)

    # Seed 2 inverters with anomalies
    for idx in range(1, 3):
        inv = Asset(plant_id=plant.id, name=f"INV-CONSISTENCY-{idx}", asset_type="inverter", metadata_json={"rated_ac_kw": 1000.0})
        db_session.add(inv)
        db_session.flush()

        ch = Channel(asset_id=inv.id, canonical_signal_key="power_ac", source_name=f"AC_PWR_{idx}", interval_s=900)
        db_session.add(ch)
        db_session.flush()

        for i in range(10):
            ts = now - timedelta(hours=2) + timedelta(minutes=15 * i)
            val = 0.0 if i >= 5 else 700.0
            db_session.add(Reading(channel_id=ch.id, ts=ts, value=val, quality=0))

    db_session.commit()

    # Run scan
    res = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert res["status"] == "success"
    assert res["assets_scanned"] == 2
    # Consistency check: detected candidate events = created + merged
    assert res["anomalies_detected"] == res["anomalies_created"] + res["anomalies_merged"]

    # Re-run scan immediately: all candidate events must now be merged, 0 created
    res2 = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )
    assert res2["assets_scanned"] == 2
    assert res2["anomalies_created"] == 0
    assert res2["anomalies_merged"] == res2["anomalies_detected"]
