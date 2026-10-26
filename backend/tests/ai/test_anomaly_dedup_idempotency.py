"""Regression test suite for idempotent anomaly persistence and deduplication.

Verifies:
1. Re-running the exact same detection does not create duplicate anomalies or events.
2. Anomaly acknowledgement status, notes, and RCA information are preserved on re-scan.
3. Anomaly resolution status is preserved without resurrecting historical records.
4. Linked operational events in the events table are updated in-place without duplicates.
5. Genuinely separate time intervals remain distinct records.
6. Different detector instances evaluating the same physical incident do not produce duplicates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.anomaly_dedup import find_matching_anomaly, merge_or_create_anomaly, persist_and_deduplicate_anomalies
from app.ai.detector_registry import DetectedAnomaly, DetectorContext
from app.models.entities import Anomaly, Asset, Base, Channel, Event, Organization, Plant


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
def dedup_test_setup(db_session: Session) -> Dict[str, Any]:
    """Create a minimal org, plant, inverter, and channel hierarchy."""
    uid = uuid4().hex[:8]
    org = Organization(name=f"Dedup Test Org {uid}")
    db_session.add(org)
    db_session.flush()

    plant = Plant(
        org_id=org.id,
        name=f"Dedup Test Plant {uid}",
        plant_type="solar",
        capacity_dc_kwp=1500.0,
        capacity_ac_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )
    db_session.add(plant)
    db_session.flush()

    inverter = Asset(
        plant_id=plant.id,
        name=f"Inverter-Dedup-{uid}",
        asset_type="inverter",
        metadata_json={"rated_ac_kw": 1250.0},
    )
    db_session.add(inverter)
    db_session.flush()

    channel = Channel(
        asset_id=inverter.id,
        canonical_signal_key="power_ac",
        source_name="AC_POWER",
        source_unit="kW",
        interval_s=900,
    )
    db_session.add(channel)
    db_session.commit()

    return {
        "org": org,
        "plant": plant,
        "inverter": inverter,
        "channel": channel,
    }


def test_rerunning_same_detection_creates_zero_duplicates(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that scanning the exact same candidate interval twice creates exactly 1 anomaly and 1 event."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)
    cand = DetectedAnomaly(
        start_time=t0,
        end_time=t1,
        score=0.85,
        anomaly_type="d2_pr_deviation",
        summary="Midday generation deficit",
        loss_kw=200.0,
        loss_kwh=100.0,
    )

    # First execution: creates new anomaly
    anom1, act1 = merge_or_create_anomaly(db_session, cand, ctx)
    assert act1 == "created"
    assert anom1.status == "open"
    anom1_id = anom1.id

    # Verify 1 anomaly and 1 event
    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    all_events = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 1
    assert len(all_events) == 1
    assert (all_events[0].metadata_json or {}).get("anomaly_id") == str(anom1_id)

    # Second execution: re-run exact same candidate
    anom2, act2 = merge_or_create_anomaly(db_session, cand, ctx)
    assert act2 == "merged"
    assert anom2.id == anom1_id

    # Verify STILL exactly 1 anomaly and 1 event
    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    all_events = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 1
    assert len(all_events) == 1


def test_acknowledged_anomaly_status_and_rca_preserved_on_rescan(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that re-scanning an acknowledged anomaly preserves status, notes, and RCA, and creates no duplicates."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=45)
    cand = DetectedAnomaly(
        start_time=t0,
        end_time=t1,
        score=0.90,
        anomaly_type="d2_pr_deviation",
        summary="Severe string loss",
        loss_kw=250.0,
        loss_kwh=180.0,
    )

    anom, act = merge_or_create_anomaly(db_session, cand, ctx)
    assert act == "created"
    anom_id = anom.id

    # Operator acknowledges anomaly and enters dispatch note + RCA
    anom.status = "acknowledged"
    anom.status_note = "Field technician dispatched to inspect string combiner boxes."
    anom.rca_narrative = {"root_cause": "blown_dc_fuse", "recommended_action": "replace_fuse_box"}
    db_session.commit()

    # Re-run detection on exact same interval
    anom_after, act_after = merge_or_create_anomaly(db_session, cand, ctx)
    assert act_after == "merged"
    assert anom_after.id == anom_id

    # Verify status, note, and RCA are completely preserved
    assert anom_after.status == "acknowledged"
    assert anom_after.status_note == "Field technician dispatched to inspect string combiner boxes."
    assert anom_after.rca_narrative == {"root_cause": "blown_dc_fuse", "recommended_action": "replace_fuse_box"}

    # Verify no duplicate anomaly or event created
    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    all_events = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 1
    assert len(all_events) == 1


def test_acknowledged_anomaly_window_extension_preserves_status(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that contiguous window extension of an acknowledged anomaly keeps status='acknowledged'."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)
    cand1 = DetectedAnomaly(
        start_time=t0,
        end_time=t1,
        score=0.85,
        anomaly_type="d2_pr_deviation",
        summary="PR deficit window 1",
        loss_kw=200.0,
        loss_kwh=100.0,
    )

    anom1, _ = merge_or_create_anomaly(db_session, cand1, ctx)
    anom1.status = "acknowledged"
    anom1.status_note = "Acknowledged by Operations Control."
    db_session.commit()

    # Adjoining interval arrives: 10:30 - 11:00
    t2 = t1 + timedelta(minutes=30)
    cand2 = DetectedAnomaly(
        start_time=t1,
        end_time=t2,
        score=0.88,
        anomaly_type="d2_pr_deviation",
        summary="PR deficit window 2",
        loss_kw=220.0,
        loss_kwh=110.0,
    )

    anom2, act2 = merge_or_create_anomaly(db_session, cand2, ctx)
    assert act2 == "merged"
    assert anom2.id == anom1.id
    assert anom2.end_time == t2
    assert anom2.status == "acknowledged"
    assert anom2.status_note == "Acknowledged by Operations Control."

    # Verify linked event end_time was updated
    all_events = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(all_events) == 1
    ev = all_events[0]
    ev_end = ev.end_time.replace(tzinfo=timezone.utc) if ev.end_time.tzinfo is None else ev.end_time
    assert ev_end == t2


def test_resolved_historical_anomaly_not_resurrected(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that re-scanning a historical interval that was already resolved does not create an open duplicate."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t0 = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)
    cand = DetectedAnomaly(
        start_time=t0,
        end_time=t1,
        score=0.80,
        anomaly_type="d2_pr_deviation",
        summary="Morning tracking issue",
        loss_kw=150.0,
        loss_kwh=200.0,
    )

    anom, _ = merge_or_create_anomaly(db_session, cand, ctx)
    anom_id = anom.id
    anom.status = "resolved"
    anom.status_note = "Tracker realigned by maintenance."
    db_session.commit()

    # Re-run detection on the same historical interval
    anom_rescan, act_rescan = merge_or_create_anomaly(db_session, cand, ctx)
    assert anom_rescan.id == anom_id
    assert anom_rescan.status == "resolved"
    assert anom_rescan.status_note == "Tracker realigned by maintenance."

    # Ensure no second anomaly was created
    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 1


def test_separate_time_intervals_remain_distinct(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that genuinely separate incidents (gap > tolerance) create distinct anomaly records."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    # Event 1: Morning drop (08:00 - 08:30)
    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    cand1 = DetectedAnomaly(
        start_time=t0,
        end_time=t0 + timedelta(minutes=30),
        score=0.85,
        anomaly_type="d2_pr_deviation",
        summary="Morning drop",
        loss_kw=200.0,
        loss_kwh=100.0,
    )

    # Event 2: Afternoon drop 6 hours later (14:30 - 15:00)
    t2 = t0 + timedelta(hours=6, minutes=30)
    cand2 = DetectedAnomaly(
        start_time=t2,
        end_time=t2 + timedelta(minutes=30),
        score=0.85,
        anomaly_type="d2_pr_deviation",
        summary="Afternoon drop",
        loss_kw=200.0,
        loss_kwh=100.0,
    )

    anom1, act1 = merge_or_create_anomaly(db_session, cand1, ctx, continuation_tolerance_minutes=120)
    anom2, act2 = merge_or_create_anomaly(db_session, cand2, ctx, continuation_tolerance_minutes=120)

    assert act1 == "created"
    assert act2 == "created"
    assert anom1.id != anom2.id

    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    all_events = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 2
    assert len(all_events) == 2


def test_batch_idempotency_second_run_zero_created(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify persist_and_deduplicate_anomalies handles repeated batches idempotently."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    candidates = [
        DetectedAnomaly(
            start_time=t0,
            end_time=t0 + timedelta(minutes=30),
            score=0.80,
            anomaly_type="d2_pr_deviation",
            summary="Interval 1",
            loss_kw=100.0,
            loss_kwh=50.0,
        ),
        DetectedAnomaly(
            start_time=t0 + timedelta(minutes=30),
            end_time=t0 + timedelta(minutes=60),
            score=0.85,
            anomaly_type="d2_pr_deviation",
            summary="Interval 2",
            loss_kw=120.0,
            loss_kwh=60.0,
        ),
    ]

    # Pass 1
    persisted1, created1, merged1 = persist_and_deduplicate_anomalies(db_session, candidates, ctx)
    assert created1 == 1
    assert merged1 == 1

    # Pass 2: Exact same batch re-scanned
    persisted2, created2, merged2 = persist_and_deduplicate_anomalies(db_session, candidates, ctx)
    assert created2 == 0
    assert merged2 == 2

    # Overall DB count is still exactly 1 merged anomaly record
    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 1


def test_reproduction_of_three_record_duplicate_scenario(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Exact reproduction test for the reported 3-record duplicate scenario on plant d253760d:

    1. Scan 1 (07:21 UTC): detects interval 06:45 to 07:15 UTC -> creates Record 1 and Event 1 (end 07:15).
    2. Operator acknowledges Record 1 and enters technician dispatch note.
    3. Scan 2 (09:54 UTC): detects extended full-day interval 06:45 to 18:15 UTC ->
       In bug, created Record 2 and Event 2 (end 18:15) because Record 1 was acknowledged.
       With fix, MUST merge into Record 1, extend end_time to 18:15, preserve acknowledged status & note,
       update Event 1 end_time to 18:15, and create 0 new anomalies and 0 new events.
    4. Scan 3 (10:30 UTC): repeats full-day scan 06:45 to 18:15 UTC ->
       In bug, created Record 3 and Event 3.
       With fix, MUST merge into Record 1, create 0 new anomalies, and create 0 new events.
    """
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t_start = datetime(2020, 6, 17, 6, 45, tzinfo=timezone.utc)
    t_end_scan1 = datetime(2020, 6, 17, 7, 15, tzinfo=timezone.utc)
    t_end_scan2 = datetime(2020, 6, 17, 18, 15, tzinfo=timezone.utc)

    # 1. SCAN 1: 06:45 to 07:15 UTC
    cand_scan1 = DetectedAnomaly(
        start_time=t_start,
        end_time=t_end_scan1,
        score=1.0,
        severity="critical",
        anomaly_type="d2_pr_deviation",
        summary="PR deviation detected on inverter",
        loss_kw=193.79,
        loss_kwh=96.90,
    )
    persisted1, created1, merged1 = persist_and_deduplicate_anomalies(
        db_session, [cand_scan1], ctx, detector_id=None
    )
    assert created1 == 1
    assert merged1 == 0
    rec1 = persisted1[0]
    rec1_id = rec1.id
    assert rec1.start_time.replace(tzinfo=timezone.utc) == t_start
    assert rec1.end_time.replace(tzinfo=timezone.utc) == t_end_scan1
    assert rec1.status == "open"

    # Verify Event 1 was created ending at 07:15
    events1 = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(events1) == 1
    ev1 = events1[0]
    assert ev1.end_time.replace(tzinfo=timezone.utc) == t_end_scan1

    # 2. OPERATOR ACKNOWLEDGES RECORD 1
    rec1.status = "acknowledged"
    rec1.status_note = "Field technician dispatched to inspect string combiner boxes."
    db_session.commit()

    # 3. SCAN 2: 06:45 to 18:15 UTC (Full-day telemetry arrives)
    cand_scan2 = DetectedAnomaly(
        start_time=t_start,
        end_time=t_end_scan2,
        score=1.0,
        severity="critical",
        anomaly_type="d2_pr_deviation",
        summary="PR deviation detected on inverter",
        loss_kw=193.79,
        loss_kwh=457.92,
    )
    persisted2, created2, merged2 = persist_and_deduplicate_anomalies(
        db_session, [cand_scan2], ctx, detector_id=None
    )
    # MUST NOT CREATE DUPLICATE!
    assert created2 == 0
    assert merged2 == 1
    assert persisted2[0].id == rec1_id
    assert persisted2[0].start_time.replace(tzinfo=timezone.utc) == t_start
    assert persisted2[0].end_time.replace(tzinfo=timezone.utc) == t_end_scan2
    assert persisted2[0].status == "acknowledged"
    assert persisted2[0].status_note == "Field technician dispatched to inspect string combiner boxes."

    # Verify Event 1 end_time updated to 18:15 and NO Event 2 was created!
    events2 = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(events2) == 1
    assert events2[0].id == ev1.id
    assert events2[0].end_time.replace(tzinfo=timezone.utc) == t_end_scan2

    # 4. SCAN 3: 06:45 to 18:15 UTC (Repeated scan)
    persisted3, created3, merged3 = persist_and_deduplicate_anomalies(
        db_session, [cand_scan2], ctx, detector_id=None
    )
    # MUST NOT CREATE RECORD 3!
    assert created3 == 0
    assert merged3 == 1
    assert persisted3[0].id == rec1_id

    # Overall DB count is STILL exactly 1 anomaly and 1 event
    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    all_events = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 1
    assert len(all_events) == 1


def test_matching_behavior_detector_id_null_vs_non_null(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that detector_id=None matches detector_id=UUID and does not create duplicates."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t0 = datetime(2020, 6, 17, 6, 45, tzinfo=timezone.utc)
    t1 = datetime(2020, 6, 17, 18, 15, tzinfo=timezone.utc)
    cand = DetectedAnomaly(
        start_time=t0,
        end_time=t1,
        score=1.0,
        severity="critical",
        anomaly_type="d2_pr_deviation",
        summary="PR deviation",
        loss_kw=193.79,
        loss_kwh=457.92,
    )

    # 1. First run: detector_id is None (plant scan)
    persisted1, created1, _ = persist_and_deduplicate_anomalies(db_session, [cand], ctx, detector_id=None)
    assert created1 == 1
    assert persisted1[0].detector_id is None
    anom_id = persisted1[0].id

    # 2. Second run: detector_id is a specific UUID (manual detector trigger)
    det_uuid = uuid4()
    persisted2, created2, merged2 = persist_and_deduplicate_anomalies(db_session, [cand], ctx, detector_id=det_uuid)
    assert created2 == 0
    assert merged2 == 1
    assert persisted2[0].id == anom_id
    # detector_id is now associated
    assert persisted2[0].detector_id == det_uuid

    # 3. Third run: detector_id is None again
    persisted3, created3, merged3 = persist_and_deduplicate_anomalies(db_session, [cand], ctx, detector_id=None)
    assert created3 == 0
    assert merged3 == 1
    assert persisted3[0].id == anom_id
    assert persisted3[0].detector_id == det_uuid  # Preserved!

    # DB counts stay 1
    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 1


def test_legacy_three_records_prevent_fourth_creation(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that if a database has 3 historical duplicate records (as currently in production),
    a subsequent scan matches one of them and creates ZERO new records (no record 4)."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    t0 = datetime(2020, 6, 17, 6, 45, tzinfo=timezone.utc)
    t1 = datetime(2020, 6, 17, 18, 15, tzinfo=timezone.utc)

    # Seed 3 duplicate records explicitly to mimic the current DB state
    for i in range(3):
        a = Anomaly(
            plant_id=plant.id,
            asset_id=inverter.id,
            channel_id=channel.id,
            detector_id=None,
            start_time=t0,
            end_time=t1,
            source="detector",
            score=1.0,
            severity="critical",
            status="acknowledged",
            estimated_loss_kw=193.79,
            status_note="Field technician dispatched to inspect string combiner boxes.",
            details={"total_energy_loss_kwh": 457.92},
        )
        db_session.add(a)
        db_session.flush()
        ev = Event(
            plant_id=plant.id,
            asset_id=inverter.id,
            source="detector",
            event_type="anomaly",
            severity="critical",
            start_time=t0,
            end_time=t1,
            code="D2_PR_DEVIATION",
            message="PR deviation on inverter",
            metadata_json={"anomaly_id": str(a.id)},
        )
        db_session.add(ev)
    db_session.commit()

    all_anoms_before = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    all_events_before = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    assert len(all_anoms_before) == 3
    assert len(all_events_before) == 3

    # Now run a scan with candidate covering 06:45 to 18:15
    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )
    cand = DetectedAnomaly(
        start_time=t0,
        end_time=t1,
        score=1.0,
        severity="critical",
        anomaly_type="d2_pr_deviation",
        summary="PR deviation detected on inverter",
        loss_kw=193.79,
        loss_kwh=457.92,
    )

    persisted, created, merged = persist_and_deduplicate_anomalies(db_session, [cand], ctx, detector_id=None)
    assert created == 0
    assert merged == 1

    all_anoms_after = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    all_events_after = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().all()
    # Count must remain exactly 3!
    assert len(all_anoms_after) == 3
    assert len(all_events_after) == 3


def test_different_fault_mechanisms_do_not_incorrectly_merge(db_session: Session, dedup_test_setup: Dict[str, Any]):
    """Verify that distinct fault mechanisms (e.g. trip vs clipping) on the same asset do NOT merge."""
    plant = dedup_test_setup["plant"]
    inverter = dedup_test_setup["inverter"]
    channel = dedup_test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        rated_kw=1250.0,
        tariff_inr_per_kwh=3.50,
    )

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)

    # 1. Trip candidate (10:00 - 10:30)
    trip_cand = DetectedAnomaly(
        start_time=t0,
        end_time=t0 + timedelta(minutes=30),
        score=1.0,
        severity="critical",
        anomaly_type="trip",
        summary="Inverter trip detected",
        loss_kw=1250.0,
        loss_kwh=625.0,
    )
    persisted1, created1, _ = persist_and_deduplicate_anomalies(db_session, [trip_cand], ctx)
    assert created1 == 1
    assert persisted1[0].details.get("detector_method") == "trip"
    assert persisted1[0].event_fingerprint is not None

    # 2. Clipping candidate (10:15 - 11:00) overlapping in time on the SAME inverter
    clip_cand = DetectedAnomaly(
        start_time=t0 + timedelta(minutes=15),
        end_time=t0 + timedelta(minutes=60),
        score=0.75,
        severity="medium",
        anomaly_type="clipping",
        summary="Abnormal clipping cap detected",
        loss_kw=200.0,
        loss_kwh=150.0,
    )
    persisted2, created2, merged2 = persist_and_deduplicate_anomalies(db_session, [clip_cand], ctx)
    # Must NOT merge into trip! Must create a distinct clipping anomaly!
    assert created2 == 1
    assert merged2 == 0
    assert persisted2[0].id != persisted1[0].id
    assert persisted2[0].details.get("detector_method") == "clipping"

    all_anoms = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    assert len(all_anoms) == 2

    # 3. Another trip candidate (10:00 - 10:45) arrives -> MUST merge into trip, NOT into clipping!
    trip_cand2 = DetectedAnomaly(
        start_time=t0,
        end_time=t0 + timedelta(minutes=45),
        score=1.0,
        severity="critical",
        anomaly_type="trip",
        summary="Extended trip",
        loss_kw=1250.0,
        loss_kwh=937.5,
    )
    persisted3, created3, merged3 = persist_and_deduplicate_anomalies(db_session, [trip_cand2], ctx)
    assert created3 == 0
    assert merged3 == 1
    assert persisted3[0].id == persisted1[0].id
    assert persisted3[0].details.get("detector_method") == "trip"

    # Overall DB count is STILL exactly 2 (one trip, one clipping)
    all_anoms_final = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    assert len(all_anoms_final) == 2

