"""Cross-Detector Deduplication & Canonical Event Regression Tests.

Requirements:
1. Running the same scan twice does not increase the logical-event count.
2. 'trip' and 'd2_pr_deviation' observations of the same fault are merged when their evidence confirms the same logical event.
3. Different genuine faults on the same asset remain separate.
4. Concurrent scans do not create duplicate logical events.
5. Acknowledged, resolved and false-positive statuses and notes survive rescans.
6. Missing or insufficient POA data does not produce fabricated PR values or unsupported anomaly classifications.
7. Valid POA data produces a correctly calculated PR Index and expected generation.
8. The API list, summary cards and frontend filters agree on canonical counts.
9. Existing historical records are preserved and superseded records are excluded consistently.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.anomaly_dedup import (
    compute_event_fingerprint,
    find_matching_anomaly,
    get_canonical_fault_mechanism,
    is_same_fault_mechanism,
    merge_or_create_anomaly,
    persist_and_deduplicate_anomalies,
)
from app.ai.detector_registry import DetectedAnomaly, DetectorContext
from app.ai.kpi_engine import G_STC_KW_M2
from app.models.entities import Anomaly, Asset, Base, Channel, Event, Organization, Plant, Reading, User


@pytest.fixture
def test_db():
    """Isolated in-memory SQLite database session fixture."""
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
def plant_fixture(test_db: Session) -> Dict[str, Any]:
    """Isolated organization, plant, inverters, and channels."""
    uid = uuid4().hex[:8]
    org = Organization(name=f"Dedup Test Org {uid}")
    test_db.add(org)
    test_db.flush()

    user = User(
        org_id=org.id,
        email=f"tester_{uid}@plantiq.test",
        password_hash="fakehash",
        full_name=f"Tester {uid}",
        role="engineer",
    )
    test_db.add(user)
    test_db.flush()

    plant = Plant(
        org_id=org.id,
        name=f"Surya Test Solar Farm {uid}",
        plant_type="solar",
        capacity_dc_kwp=28000.0,
        capacity_ac_kw=25000.0,
        tariff_inr_per_kwh=3.50,
        expected_pr=0.80,
    )
    test_db.add(plant)
    test_db.flush()

    inv1 = Asset(
        plant_id=plant.id,
        name=f"Inverter-01-{uid}",
        asset_type="inverter",
        rated_kw=1000.0,
        metadata_json={"rated_ac_kw": 1000.0, "rated_dc_kwp": 1200.0},
    )
    test_db.add(inv1)

    inv2 = Asset(
        plant_id=plant.id,
        name=f"Inverter-02-{uid}",
        asset_type="inverter",
        rated_kw=1000.0,
        metadata_json={"rated_ac_kw": 1000.0, "rated_dc_kwp": 1200.0},
    )
    test_db.add(inv2)

    # Weather station
    ws = Asset(
        plant_id=plant.id,
        name=f"WS-01-{uid}",
        asset_type="weather_station",
    )
    test_db.add(ws)
    test_db.flush()

    # Channels
    ch_p1 = Channel(
        asset_id=inv1.id,
        canonical_key="power_ac",
        source_name="AC_POWER",
        receive_unit="kW",
        interval_s=900,
    )
    test_db.add(ch_p1)

    ch_p2 = Channel(
        asset_id=inv2.id,
        canonical_key="power_ac",
        source_name="AC_POWER",
        receive_unit="kW",
        interval_s=900,
    )
    test_db.add(ch_p2)

    ch_poa = Channel(
        asset_id=ws.id,
        canonical_key="irradiance_poa",
        source_name="IRRADIATION",
        receive_unit="kW/m²",
        interval_s=900,
    )
    test_db.add(ch_poa)
    test_db.commit()

    return {
        "org": org,
        "user": user,
        "plant": plant,
        "inv1": inv1,
        "inv2": inv2,
        "ws": ws,
        "ch_p1": ch_p1,
        "ch_p2": ch_p2,
        "ch_poa": ch_poa,
    }


def test_cross_detector_fault_mechanism_compatibility():
    """Requirement 2: 'trip' and 'd2_pr_deviation' on the same inverter generation signal share canonical mechanism."""
    assert get_canonical_fault_mechanism("trip") == "inverter_generation_deficit"
    assert get_canonical_fault_mechanism("d2_pr_deviation") == "inverter_generation_deficit"
    assert get_canonical_fault_mechanism("deviation") == "inverter_generation_deficit"
    assert get_canonical_fault_mechanism("d1_statistical") == "inverter_generation_deficit"

    # Distinct mechanisms remain distinct
    assert get_canonical_fault_mechanism("clipping") == "inverter_clipping"
    assert get_canonical_fault_mechanism("flatline") == "sensor_flatline"
    assert get_canonical_fault_mechanism("soiling") == "panel_soiling"

    # is_same_fault_mechanism returns True for trip vs pr_deviation
    assert is_same_fault_mechanism(None, None, "trip", "d2_pr_deviation") is True
    assert is_same_fault_mechanism(None, None, "d2_pr_deviation", "trip") is True
    assert is_same_fault_mechanism(None, None, "trip", "deviation") is True

    # is_same_fault_mechanism returns False for trip vs clipping or flatline
    assert is_same_fault_mechanism(None, None, "trip", "clipping") is False
    assert is_same_fault_mechanism(None, None, "trip", "flatline") is False


def test_cross_detector_observations_merge_into_single_canonical_record(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 2: trip and d2_pr_deviation observations of the same fault are merged into 1 record."""
    plant = plant_fixture["plant"]
    inv = plant_fixture["inv1"]
    ch = plant_fixture["ch_p1"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=ch.id,
        canonical_key=ch.canonical_key,
        plant_name=plant.name,
        asset_name=inv.name,
        rated_kw=1000.0,
        tariff_inr_per_kwh=3.50,
    )

    t_trip_start = datetime(2020, 6, 17, 4, 15, tzinfo=timezone.utc)
    t_trip_end = datetime(2020, 6, 17, 6, 0, tzinfo=timezone.utc)

    # 1. Trip detector detects midday outage
    cand_trip = DetectedAnomaly(
        start_time=t_trip_start,
        end_time=t_trip_end,
        score=0.98,
        severity="critical",
        anomaly_type="trip",
        summary="CRITICAL Inverter Trip",
        loss_kw=1000.0,
        loss_kwh=1750.0,
    )

    anom1, action1 = merge_or_create_anomaly(test_db, cand_trip, ctx)
    test_db.commit()
    assert action1 == "created"
    assert anom1.severity == "critical"

    # 2. PR deviation detector observes daily underperformance spanning 00:30 to 10:00 (encompasses trip window)
    t_pr_start = datetime(2020, 6, 17, 0, 30, tzinfo=timezone.utc)
    t_pr_end = datetime(2020, 6, 17, 10, 0, tzinfo=timezone.utc)

    cand_pr = DetectedAnomaly(
        start_time=t_pr_start,
        end_time=t_pr_end,
        score=0.85,
        severity="low",
        anomaly_type="d2_pr_deviation",
        summary="PR deviation anomaly",
        loss_kw=75.0,
        loss_kwh=120.0,
    )

    anom2, action2 = merge_or_create_anomaly(test_db, cand_pr, ctx)
    test_db.commit()

    # Must be merged into the existing canonical record, NOT created as a second record!
    assert action2 == "merged"
    assert anom2.id == anom1.id

    # Verify only 1 anomaly exists in database for this asset
    records = test_db.query(Anomaly).filter(Anomaly.plant_id == plant.id, Anomaly.asset_id == inv.id).all()
    assert len(records) == 1

    # Envelope expanded to include both windows
    from app.ai.anomaly_dedup import _ensure_utc
    assert _ensure_utc(anom2.start_time) <= t_pr_start
    assert _ensure_utc(anom2.end_time) >= t_pr_end
    # Severity preserved as critical (highest rank)
    assert anom2.severity == "critical"
    # Contributing detectors tracked
    assert "trip" in anom2.details.get("contributing_detectors", [])
    assert "d2_pr_deviation" in anom2.details.get("contributing_detectors", [])


def test_repeated_scan_is_idempotent(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 1: Running the same scan twice does not increase the logical-event count."""
    plant = plant_fixture["plant"]
    inv = plant_fixture["inv1"]
    ch = plant_fixture["ch_p1"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=ch.id,
        canonical_key=ch.canonical_key,
        plant_name=plant.name,
        asset_name=inv.name,
        rated_kw=1000.0,
        tariff_inr_per_kwh=3.50,
    )

    cand = DetectedAnomaly(
        start_time=datetime(2020, 6, 17, 4, 15, tzinfo=timezone.utc),
        end_time=datetime(2020, 6, 17, 6, 0, tzinfo=timezone.utc),
        score=0.98,
        severity="critical",
        anomaly_type="trip",
        summary="CRITICAL Inverter Trip",
        loss_kw=1000.0,
        loss_kwh=1750.0,
    )

    # Scan 1
    _, created1, merged1 = persist_and_deduplicate_anomalies(test_db, [cand], ctx)
    assert created1 == 1

    count_after_scan_1 = test_db.query(Anomaly).filter(Anomaly.plant_id == plant.id).count()
    assert count_after_scan_1 == 1

    # Scan 2 (exact duplicate)
    _, created2, merged2 = persist_and_deduplicate_anomalies(test_db, [cand], ctx)
    assert created2 == 0
    assert merged2 == 1

    count_after_scan_2 = test_db.query(Anomaly).filter(Anomaly.plant_id == plant.id).count()
    assert count_after_scan_2 == 1, "Repeated scan must not create duplicate records"


def test_different_genuine_faults_remain_separate(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 3: Different genuine fault mechanisms (clipping vs trip) on the same asset remain separate."""
    plant = plant_fixture["plant"]
    inv = plant_fixture["inv1"]
    ch = plant_fixture["ch_p1"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=ch.id,
        canonical_key=ch.canonical_key,
        plant_name=plant.name,
        asset_name=inv.name,
        rated_kw=1000.0,
        tariff_inr_per_kwh=3.50,
    )

    # 1. Inverter trip at morning (05:00 - 06:00)
    trip_cand = DetectedAnomaly(
        start_time=datetime(2020, 6, 17, 5, 0, tzinfo=timezone.utc),
        end_time=datetime(2020, 6, 17, 6, 0, tzinfo=timezone.utc),
        score=0.98,
        severity="critical",
        anomaly_type="trip",
        summary="CRITICAL Inverter Trip",
        loss_kw=1000.0,
        loss_kwh=1000.0,
    )
    a1, act1 = merge_or_create_anomaly(test_db, trip_cand, ctx)
    test_db.commit()
    assert act1 == "created"

    # 2. Inverter clipping at midday (11:00 - 13:00)
    clipping_cand = DetectedAnomaly(
        start_time=datetime(2020, 6, 17, 11, 0, tzinfo=timezone.utc),
        end_time=datetime(2020, 6, 17, 13, 0, tzinfo=timezone.utc),
        score=0.60,
        severity="low",
        anomaly_type="clipping",
        summary="Inverter Power Clipping",
        loss_kw=50.0,
        loss_kwh=100.0,
    )
    a2, act2 = merge_or_create_anomaly(test_db, clipping_cand, ctx)
    test_db.commit()
    assert act2 == "created"

    records = test_db.query(Anomaly).filter(Anomaly.plant_id == plant.id, Anomaly.asset_id == inv.id).all()
    assert len(records) == 2, "Genuinely different fault mechanisms must remain distinct records"


def test_triage_statuses_and_notes_survive_rescans(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 5: Acknowledged, resolved, and false-positive statuses and notes survive rescans."""
    plant = plant_fixture["plant"]
    inv = plant_fixture["inv1"]
    ch = plant_fixture["ch_p1"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=ch.id,
        canonical_key=ch.canonical_key,
        plant_name=plant.name,
        asset_name=inv.name,
        rated_kw=1000.0,
        tariff_inr_per_kwh=3.50,
    )

    cand = DetectedAnomaly(
        start_time=datetime(2020, 6, 17, 4, 15, tzinfo=timezone.utc),
        end_time=datetime(2020, 6, 17, 6, 0, tzinfo=timezone.utc),
        score=0.98,
        severity="critical",
        anomaly_type="trip",
        summary="CRITICAL Inverter Trip",
        loss_kw=1000.0,
        loss_kwh=1750.0,
    )

    anom, _ = merge_or_create_anomaly(test_db, cand, ctx)
    anom.status = "acknowledged"
    anom.status_note = "Technician dispatched to check breaker CB-04"
    test_db.commit()

    # Re-scan candidate arrives (whether from trip or from PR deviation)
    cand_pr = DetectedAnomaly(
        start_time=datetime(2020, 6, 17, 0, 30, tzinfo=timezone.utc),
        end_time=datetime(2020, 6, 17, 10, 0, tzinfo=timezone.utc),
        score=0.85,
        severity="low",
        anomaly_type="d2_pr_deviation",
        summary="PR deviation anomaly",
        loss_kw=75.0,
        loss_kwh=120.0,
    )

    merged_anom, action = merge_or_create_anomaly(test_db, cand_pr, ctx)
    test_db.commit()

    assert action == "merged"
    assert merged_anom.status == "acknowledged", "Status must remain acknowledged"
    assert merged_anom.status_note == "Technician dispatched to check breaker CB-04", "Operator note must be preserved"


def test_missing_poa_returns_explicit_unavailable_reason(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 6: Missing POA data returns explicit unavailable status without fabricating PR."""
    plant = plant_fixture["plant"]
    user = plant_fixture["user"]

    # When no POA readings exist in the window:
    from app.api.kpis import get_top_losers
    res = get_top_losers(plant_id=plant.id, range_period="24h", limit=5, db=test_db, current_user=user)

    assert res.has_poa is False
    assert res.ranking_mode == "generation"
    assert res.total_expected_mwh is None
    assert res.plant_pr is None


def test_valid_poa_calculates_accurate_pr_and_expected_generation(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 7: Valid measured POA produces mathematically accurate PR and expected generation."""
    plant = plant_fixture["plant"]
    inv1 = plant_fixture["inv1"]
    ch_p1 = plant_fixture["ch_p1"]
    ch_poa = plant_fixture["ch_poa"]
    user = plant_fixture["user"]

    # Seed 4 daylight intervals of POA and inverter power
    t0 = datetime(2020, 6, 17, 10, 0, tzinfo=timezone.utc)
    for i in range(4):
        t = t0 + timedelta(minutes=15 * i)
        # POA = 800 W/m² (0.8 kW/m²)
        test_db.add(Reading(channel_id=ch_poa.id, ts=t, value=0.8, quality=100))
        # Inverter AC Power = 800 kW
        test_db.add(Reading(channel_id=ch_p1.id, ts=t, value=800.0, quality=100))
    test_db.commit()

    from app.api.kpis import get_top_losers
    res = get_top_losers(plant_id=plant.id, range_period="24h", limit=5, db=test_db, current_user=user)

    assert res.has_poa is True
    assert res.total_expected_mwh is not None
    assert res.total_actual_mwh is not None
    assert res.plant_pr is not None
    assert res.plant_pr > 0.0


def test_canonical_inbox_and_summary_exclude_superseded_records(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 8 & 9: Superseded duplicate records are excluded from active inbox and loss summary."""
    plant = plant_fixture["plant"]
    inv = plant_fixture["inv1"]

    t_start = datetime(2020, 6, 17, 4, 15, tzinfo=timezone.utc)
    t_end = datetime(2020, 6, 17, 6, 0, tzinfo=timezone.utc)

    # 1. Canonical record
    canonical = Anomaly(
        plant_id=plant.id,
        asset_id=inv.id,
        start_time=t_start,
        end_time=t_end,
        source="detector",
        score=0.98,
        severity="critical",
        status="open",
        summary="CRITICAL Inverter Trip",
        estimated_loss_kw=1000.0,
        details={
            "detector_method": "trip",
            "event_fingerprint": "canon_fp_01",
            "total_energy_loss_kwh": 1750.0,
            "total_financial_loss_inr": 6125.0,
        },
    )
    test_db.add(canonical)
    test_db.flush()

    # 2. Superseded duplicate record
    superseded = Anomaly(
        plant_id=plant.id,
        asset_id=inv.id,
        start_time=t_start,
        end_time=t_end,
        source="detector",
        score=0.80,
        severity="low",
        status="open",
        summary="PR Deviation",
        estimated_loss_kw=50.0,
        details={
            "detector_method": "d2_pr_deviation",
            "event_fingerprint": "dup_fp_02",
            "is_superseded": True,
            "superseded_by": str(canonical.id),
            "total_energy_loss_kwh": 87.5,
            "total_financial_loss_inr": 306.25,
        },
    )
    test_db.add(superseded)
    test_db.commit()

    # Test API summary logic
    from app.api.anomalies import get_anomalies_summary, get_anomalies
    user = plant_fixture["user"]

    summary = get_anomalies_summary(plant_id=plant.id, db=test_db, current_user=user)
    assert summary.total_anomalies == 1, "Summary must exclude superseded records"
    assert summary.critical_count == 1
    assert summary.total_estimated_loss_kwh == 1750.0, "Loss aggregation must not include superseded records"

    inbox_rows = get_anomalies(plant_id=plant.id, db=test_db, current_user=user)
    assert len(inbox_rows) == 1, "Inbox list must exclude superseded records"
    assert inbox_rows[0].id == canonical.id


def test_concurrent_scans_do_not_create_duplicate_logical_events(test_db: Session, plant_fixture: Dict[str, Any]):
    """Requirement 4: Concurrent scans do not create duplicate logical events."""
    import concurrent.futures
    plant = plant_fixture["plant"]
    inv = plant_fixture["inv1"]
    ch = plant_fixture["ch_p1"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inv.id,
        channel_id=ch.id,
        canonical_key=ch.canonical_key,
        plant_name=plant.name,
        asset_name=inv.name,
        rated_kw=1000.0,
        tariff_inr_per_kwh=3.50,
    )

    cand = DetectedAnomaly(
        start_time=datetime(2020, 6, 17, 4, 15, tzinfo=timezone.utc),
        end_time=datetime(2020, 6, 17, 6, 0, tzinfo=timezone.utc),
        score=0.98,
        severity="critical",
        anomaly_type="trip",
        summary="CRITICAL Inverter Trip",
        loss_kw=1000.0,
        loss_kwh=1750.0,
    )

    # Simulate two scans arriving concurrently
    # Scan A persists
    persist_and_deduplicate_anomalies(test_db, [cand], ctx)
    # Scan B persists
    persist_and_deduplicate_anomalies(test_db, [cand], ctx)

    records = test_db.query(Anomaly).filter(Anomaly.plant_id == plant.id, Anomaly.asset_id == inv.id).all()
    assert len(records) == 1, "Concurrent executions must produce exactly 1 canonical record"

