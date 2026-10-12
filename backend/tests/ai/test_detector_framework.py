"""Unit & Integration Tests for Anomaly Detector Framework & Dedup Engine (§12, Task S4-AI-01).

Validates:
1. Detector Registry plugin pattern (discovery, registration, error handling).
2. Built-in algorithms (zscore, iqr, deviation, isolation_forest, trip, flatline).
3. Severity and Financial Loss Policy evaluation.
4. Merge and Deduplication logic (preventing duplicate alerts for ongoing anomalies).
5. Background plant anomaly scan execution and database persistence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.anomaly_dedup import find_matching_open_anomaly, merge_or_create_anomaly, persist_and_deduplicate_anomalies
from app.ai.anomaly_policy import FinancialLossPolicy, SeverityPolicy
from app.ai.detector_registry import (
    BaseDetector,
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
    register_detector,
)
from app.db.base import Base
from app.models.entities import (
    Anomaly,
    Asset,
    CanonicalSignal,
    Channel,
    Detector,
    Event,
    Organization,
    Plant,
    Reading,
    User,
)
from app.tasks.detector_tasks import execute_plant_anomaly_scan


# =====================================================================
# Fixtures
# =====================================================================
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
def sample_plant(db_session: Session) -> Dict[str, Any]:
    """Seed test plant, inverter asset, canonical signal, channel, and detector."""
    org = Organization(name="Solar Corp", slug="solar-corp")
    db_session.add(org)
    db_session.flush()

    plant = Plant(
        org_id=org.id,
        name="SunPark Alpha",
        plant_type="solar",
        capacity_ac_kw=10000.0,
        capacity_dc_kwp=11000.0,
        expected_pr=0.82,
        tariff_inr_per_kwh=4.20,
    )
    db_session.add(plant)
    db_session.flush()

    inverter = Asset(
        plant_id=plant.id,
        name="INV-01",
        asset_type="inverter",
        rated_kw=1000.0,
    )
    db_session.add(inverter)
    db_session.flush()

    sig = CanonicalSignal(
        key="active_power",
        name="Active Power",
        category="electrical",
        unit="kW",
    )
    db_session.add(sig)
    db_session.flush()

    channel = Channel(
        asset_id=inverter.id,
        canonical_key="active_power",
        source_name="W_INV01",
        interval_s=900,
    )
    db_session.add(channel)
    db_session.flush()

    det = Detector(
        plant_id=plant.id,
        name="Inverter Deviation Detector",
        method="deviation",
        canonical_key="active_power",
        asset_scope={"asset_type": "inverter"},
        parameters={"threshold_pct": 0.20},
        enabled=True,
    )
    db_session.add(det)
    db_session.commit()

    return {
        "org": org,
        "plant": plant,
        "inverter": inverter,
        "channel": channel,
        "detector": det,
    }


# =====================================================================
# 1. Detector Registry Tests
# =====================================================================
def test_detector_registry_discovery():
    """Verify built-in detectors are registered and discoverable."""
    detectors = DetectorRegistry.list_detectors()
    assert "zscore" in detectors
    assert "iqr" in detectors
    assert "deviation" in detectors
    assert "isolation_forest" in detectors
    assert "trip" in detectors
    assert "flatline" in detectors


def test_detector_registry_instantiation():
    """Verify registry instantiates detectors correctly."""
    zscore_det = DetectorRegistry.get("zscore")
    assert isinstance(zscore_det, BaseDetector)
    assert zscore_det.name == "zscore"

    with pytest.raises(KeyError):
        DetectorRegistry.get("non_existent_detector")


def test_custom_detector_registration():
    """Verify @register_detector registers custom algorithms."""
    @register_detector("custom_threshold", description="Custom Threshold Detector")
    class CustomThresholdDetector(BaseDetector):
        name = "custom_threshold"

        def detect(self, observations, parameters, context):
            return []

    assert DetectorRegistry.has_detector("custom_threshold")
    meta = DetectorRegistry.get_metadata("custom_threshold")
    assert meta["name"] == "custom_threshold"
    assert "Custom Threshold" in meta["description"]


# =====================================================================
# 2. Algorithm Tests
# =====================================================================
def test_zscore_detector_flags_outlier():
    """Test Z-Score algorithm flags statistical outliers and forms an anomaly candidate."""
    det = DetectorRegistry.get("zscore")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    # 20 normal points around 500 kW, plus 2 severe drops to 50 kW
    observations = [(base_time + timedelta(minutes=15 * i), 500.0) for i in range(20)]
    observations[10] = (base_time + timedelta(minutes=15 * 10), 50.0)
    observations[11] = (base_time + timedelta(minutes=15 * 11), 50.0)

    anomalies = det.detect(observations, parameters={"threshold": 2.5}, context=ctx)
    assert len(anomalies) >= 1
    anom = anomalies[0]
    assert anom.anomaly_type == "zscore"
    assert anom.score >= 0.5
    assert anom.loss_kw is not None and anom.loss_kw > 0


def test_iqr_detector_flags_boundary_violation():
    """Test IQR detector on quartile bound violations."""
    det = DetectorRegistry.get("iqr")
    ctx = DetectorContext(plant_id=uuid4(), canonical_key="active_power", cadence_seconds=900)

    base_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    # Series of 30 points mostly 800 kW, one outlier at 100 kW
    observations = [(base_time + timedelta(minutes=15 * i), 800.0 + (i % 3)) for i in range(30)]
    observations[15] = (base_time + timedelta(minutes=15 * 15), 100.0)

    anomalies = det.detect(observations, parameters={"k": 1.5}, context=ctx)
    assert len(anomalies) >= 1
    assert anomalies[0].anomaly_type == "iqr"
    assert anomalies[0].actual_value < 200.0


def test_deviation_detector_flags_underperformance():
    """Test generation deviation detector when solar inverter underperforms diurnal curve."""
    det = DetectorRegistry.get("deviation")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.85,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    # Expected midday power is ~700 kW, but inverter produces only 200 kW
    observations = [(base_time + timedelta(minutes=15 * i), 200.0) for i in range(6)]

    anomalies = det.detect(observations, parameters={"threshold_pct": 0.25}, context=ctx)
    assert len(anomalies) >= 1
    anom = anomalies[0]
    assert anom.anomaly_type == "deviation"
    assert anom.loss_kw > 200.0
    assert anom.loss_kwh > 0.0


def test_trip_detector_flags_midday_outage():
    """Test trip detector on abrupt 0 kW drop during sunny daylight hours."""
    det = DetectorRegistry.get("trip")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    # Midday zero generation across 4 intervals
    observations = [(base_time + timedelta(minutes=15 * i), 0.0) for i in range(4)]

    anomalies = det.detect(observations, parameters={}, context=ctx)
    assert len(anomalies) == 1
    anom = anomalies[0]
    assert anom.anomaly_type == "trip"
    assert anom.severity == "critical"
    assert anom.score >= 0.95


def test_flatline_detector_flags_frozen_sensor():
    """Test flatline detector on repeating non-zero sensor reading."""
    det = DetectorRegistry.get("flatline")
    ctx = DetectorContext(plant_id=uuid4(), canonical_key="active_power", cadence_seconds=900)

    base_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    # 6 consecutive intervals repeating 452.17 kW
    observations = [(base_time + timedelta(minutes=15 * i), 452.17) for i in range(6)]

    anomalies = det.detect(observations, parameters={"min_consecutive": 4}, context=ctx)
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "flatline"
    assert anomalies[0].details["frozen_value"] == 452.17


def test_isolation_forest_detector_identifies_outlier():
    """Test pure-NumPy Isolation Forest detector isolates anomalous values."""
    det = DetectorRegistry.get("isolation_forest")
    ctx = DetectorContext(plant_id=uuid4(), canonical_key="active_power", cadence_seconds=900)

    base_time = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    # 40 normal points around 600 kW, plus 2 distant points at 50 kW
    observations = [(base_time + timedelta(minutes=15 * i), 600.0 + (i % 5)) for i in range(40)]
    observations[20] = (base_time + timedelta(minutes=15 * 20), 50.0)
    observations[21] = (base_time + timedelta(minutes=15 * 21), 50.0)

    anomalies = det.detect(observations, parameters={"contamination": 0.08}, context=ctx)
    assert len(anomalies) >= 1
    assert anomalies[0].anomaly_type == "isolation_forest"


# =====================================================================
# 3. Severity & Financial Loss Policy Tests
# =====================================================================
def test_severity_policy_classification():
    """Verify SeverityPolicy classifies into standard tiers ('low', 'medium', 'high', 'critical')."""
    # 1. Critical
    assert SeverityPolicy.evaluate(anomaly_type="trip") == "critical"
    assert SeverityPolicy.evaluate(loss_kw=150.0) == "critical"
    assert SeverityPolicy.evaluate(loss_kw=30.0, score=0.92) == "critical"

    # 2. High
    assert SeverityPolicy.evaluate(loss_kw=40.0) == "high"
    assert SeverityPolicy.evaluate(deficit_pct=0.40, duration_minutes=60) == "high"

    # 3. Medium
    assert SeverityPolicy.evaluate(loss_kw=12.0) == "medium"
    assert SeverityPolicy.evaluate(anomaly_type="flatline") == "medium"

    # 4. Low
    assert SeverityPolicy.evaluate(loss_kw=2.0, deficit_pct=0.05, score=0.30) == "low"


def test_financial_loss_policy_calculation():
    """Verify accurate kWh loss integration and INR tariff quantification."""
    assessment = FinancialLossPolicy.calculate(
        loss_kwh=100.0,
        power_deficit_kw=20.0,
        duration_minutes=300,
        tariff_inr_per_kwh=4.50,
    )
    assert assessment.energy_loss_kwh == 100.0
    assert assessment.financial_loss_inr == 450.0
    assert assessment.effective_tariff_inr == 4.50
    assert "₹450.00" in assessment.to_dict()["formatted_loss"]


# =====================================================================
# 4. Merge & Deduplication Engine Tests
# =====================================================================
def test_merge_contiguous_anomalies_dedup(db_session: Session, sample_plant: Dict[str, Any]):
    """Verify that contiguous anomaly detections are merged to prevent duplicate alert fatigue."""
    plant = sample_plant["plant"]
    inverter = sample_plant["inverter"]
    channel = sample_plant["channel"]
    det = sample_plant["detector"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        tariff_inr_per_kwh=plant.tariff_inr_per_kwh,
    )

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)
    t2 = t1 + timedelta(minutes=30)

    # 1. First detection window: 10:00 - 10:30
    cand1 = DetectedAnomaly(
        start_time=t0,
        end_time=t1,
        score=0.70,
        anomaly_type="deviation",
        summary="Initial deviation detected",
        loss_kw=50.0,
        loss_kwh=25.0,
    )

    anom1, action1 = merge_or_create_anomaly(
        db=db_session,
        candidate=cand1,
        context=ctx,
        detector_id=det.id,
    )
    assert action1 == "created"
    assert anom1.status == "open"
    assert anom1.details["merged_events_count"] == 1

    # Verify Event record created in sync
    event = db_session.execute(select(Event).where(Event.plant_id == plant.id)).scalars().first()
    assert event is not None
    assert event.source == "detector"

    # 2. Second detection window (immediately adjoining): 10:30 - 11:00
    cand2 = DetectedAnomaly(
        start_time=t1,
        end_time=t2,
        score=0.85,
        anomaly_type="deviation",
        summary="Continued deviation detected",
        loss_kw=60.0,
        loss_kwh=30.0,
    )

    anom2, action2 = merge_or_create_anomaly(
        db=db_session,
        candidate=cand2,
        context=ctx,
        detector_id=det.id,
    )
    assert action2 == "merged"
    assert anom2.id == anom1.id  # SAME record, not duplicate!
    assert anom2.end_time == t2  # Extended time window
    assert anom2.score == 0.85   # Updated to higher score
    assert anom2.details["merged_events_count"] == 2
    assert anom2.details["total_energy_loss_kwh"] == 55.0  # 25 + 30
    assert anom2.details["total_financial_loss_inr"] == round(55.0 * 4.20, 2)

    # Database should only contain 1 anomaly record
    all_anoms = db_session.execute(select(Anomaly)).scalars().all()
    assert len(all_anoms) == 1


def test_separate_anomaly_after_gap(db_session: Session, sample_plant: Dict[str, Any]):
    """Verify that an anomaly occurring long after an earlier one creates a distinct record."""
    plant = sample_plant["plant"]
    inverter = sample_plant["inverter"]
    channel = sample_plant["channel"]
    det = sample_plant["detector"]

    ctx = DetectorContext(plant_id=plant.id, asset_id=inverter.id, channel_id=channel.id)

    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=30)
    # 5-hour gap
    t2 = t1 + timedelta(hours=5)
    t3 = t2 + timedelta(minutes=30)

    cand1 = DetectedAnomaly(start_time=t0, end_time=t1, score=0.6, anomaly_type="zscore", summary="Morning drop")
    cand2 = DetectedAnomaly(start_time=t2, end_time=t3, score=0.6, anomaly_type="zscore", summary="Afternoon drop")

    anom1, act1 = merge_or_create_anomaly(db_session, cand1, ctx, detector_id=det.id)
    anom2, act2 = merge_or_create_anomaly(db_session, cand2, ctx, detector_id=det.id)

    assert act1 == "created"
    assert act2 == "created"
    assert anom1.id != anom2.id

    all_anoms = db_session.execute(select(Anomaly)).scalars().all()
    assert len(all_anoms) == 2


# =====================================================================
# 5. Background Scan Task Execution Tests
# =====================================================================
def test_execute_plant_anomaly_scan(db_session: Session, sample_plant: Dict[str, Any]):
    """Test execute_plant_anomaly_scan end-to-end against seeded readings."""
    plant = sample_plant["plant"]
    inverter = sample_plant["inverter"]
    channel = sample_plant["channel"]

    now = datetime.now(timezone.utc)
    # Seed 10 readings with midday drop to 0
    readings = []
    for i in range(10):
        ts = now - timedelta(hours=2) + timedelta(minutes=15 * i)
        val = 0.0 if i >= 6 else 800.0
        r = Reading(channel_id=channel.id, ts=ts, value=val, quality=0)
        readings.append(r)
    db_session.add_all(readings)
    db_session.commit()

    summary = execute_plant_anomaly_scan(
        db=db_session,
        plant_id=plant.id,
        window_hours=24,
    )

    assert summary["status"] == "success"
    assert summary["detectors_evaluated"] >= 1
    assert summary["anomalies_detected"] >= 1
    assert summary["anomalies_created"] >= 1

    # Verify anomalies in database
    db_anomalies = db_session.execute(select(Anomaly).where(Anomaly.plant_id == plant.id)).scalars().all()
    assert len(db_anomalies) >= 1
    assert db_anomalies[0].status == "open"
