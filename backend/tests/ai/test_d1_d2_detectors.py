"""Comprehensive Unit & Integration Tests for Task S4-AI-02 (D1 and D2 Detectors).

Tests:
1. D1: Statistical Outlier Detector:
   - Z-Score mode (deviation from moving mean, global mean).
   - IQR mode (quartile boundary violations [Q1 - k*IQR, Q3 + k*IQR]).
   - Sudden spikes and drops (ramp rate slew violations).
   - Physical impossibility bounds (negative power, overcapacity surge, impossible irradiance).
2. D2: Performance Ratio Deviation Detector:
   - Actual PR calculation using POA weather irradiance reference.
   - Fallback to clear-sky diurnal solar envelope when irradiance is missing.
   - Significant PR deficit detection and classification (shading, soiling, degradation).
3. Integration:
   - Discovery and instantiation via DetectorRegistry.
   - Policy integration (SeverityPolicy and FinancialLossPolicy).
   - Deduplication engine merging adjoining windows.
   - Database task execution via execute_plant_anomaly_scan.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.anomaly_dedup import persist_and_deduplicate_anomalies
from app.ai.anomaly_policy import FinancialLossPolicy, SeverityPolicy
from app.ai.detector_registry import (
    BaseDetector,
    D1StatisticalDetector,
    D2PRDeviationDetector,
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
)
from app.models.entities import (
    Asset,
    Base,
    CanonicalSignal,
    Channel,
    Detector,
    Organization,
    Plant,
    Reading,
)
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
    with session_factory() as session:
        yield session


@pytest.fixture
def test_setup(db_session: Session) -> Dict[str, Any]:
    """Seed test plant, inverter asset, canonical signal, and channel."""
    org = Organization(name="S4 Test Org", slug="s4-test-org")
    db_session.add(org)
    db_session.flush()

    plant = Plant(
        org_id=org.id,
        name="Pavagada Solar Complex",
        plant_type="solar",
        capacity_ac_kw=5000.0,
        capacity_dc_kwp=5500.0,
        expected_pr=0.82,
        tariff_inr_per_kwh=3.80,
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
        source_name="P_AC_INV1",
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


# =====================================================================
# 1. Registry Discovery & Instantiation Tests
# =====================================================================
def test_d1_d2_registry_discovery():
    """Verify D1 and D2 detectors are discoverable in DetectorRegistry."""
    detectors = DetectorRegistry.list_detectors()
    assert "d1_statistical" in detectors
    assert "d2_pr_deviation" in detectors
    assert "statistical" in detectors
    assert "pr_deviation" in detectors


def test_d1_d2_registry_instantiation():
    """Verify registry instantiates D1 and D2 detectors with proper class types."""
    d1 = DetectorRegistry.get("d1_statistical")
    assert isinstance(d1, D1StatisticalDetector)
    assert d1.name == "d1_statistical"

    d2 = DetectorRegistry.get("d2_pr_deviation")
    assert isinstance(d2, D2PRDeviationDetector)
    assert d2.name == "d2_pr_deviation"


# =====================================================================
# 2. D1 Statistical Detector Tests
# =====================================================================
def test_d1_zscore_moving_mean_outlier():
    """Test D1 in Z-score mode flags deviations from moving mean."""
    det = DetectorRegistry.get("d1_statistical")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    # 24 readings: normal generation ~600 kW, with a severe dip to 80 kW at index 12 & 13
    observations = [(base_time + timedelta(minutes=15 * i), 600.0 + (i % 2) * 5) for i in range(24)]
    observations[12] = (base_time + timedelta(minutes=15 * 12), 80.0)
    observations[13] = (base_time + timedelta(minutes=15 * 13), 85.0)

    anomalies = det.detect(
        observations,
        parameters={"mode": "zscore", "threshold": 2.5, "window_size": 12},
        context=ctx,
    )

    assert len(anomalies) >= 1
    anom = anomalies[0]
    assert anom.anomaly_type == "d1_statistical"
    assert anom.score >= 0.5
    assert anom.actual_value < 100.0
    assert anom.loss_kw > 400.0
    assert anom.loss_kwh > 100.0
    assert "zscore" in anom.details["subtypes"] or "spike_or_drop" in anom.details["subtypes"]


def test_d1_iqr_mode_outlier():
    """Test D1 in IQR mode flags points beyond quartile boundaries."""
    det = DetectorRegistry.get("d1_statistical")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    # Series of 25 observations around 700 kW, one outlier drop to 150 kW
    observations = [(base_time + timedelta(minutes=15 * i), 700.0 + (i % 3)) for i in range(25)]
    observations[10] = (base_time + timedelta(minutes=15 * 10), 150.0)

    anomalies = det.detect(
        observations,
        parameters={"mode": "iqr", "k": 1.5, "window_size": 0},
        context=ctx,
    )

    assert len(anomalies) >= 1
    assert any(a.actual_value < 200.0 for a in anomalies)
    assert anomalies[0].details["mode"] == "iqr"


def test_d1_flags_physically_impossible_values():
    """Test D1 flags impossible values (negative solar power, impossible spikes)."""
    det = DetectorRegistry.get("d1_statistical")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    observations = [(base_time + timedelta(minutes=15 * i), 500.0) for i in range(10)]
    # Impossible negative value (-150 kW during day)
    observations[3] = (base_time + timedelta(minutes=15 * 3), -150.0)
    # Impossible surge exceeding 130% of rated capacity (2,500 kW on a 1,000 kW inverter)
    observations[7] = (base_time + timedelta(minutes=15 * 7), 2500.0)

    anomalies = det.detect(
        observations,
        parameters={"check_impossible": True},
        context=ctx,
    )

    assert len(anomalies) >= 2
    subtypes_found = [sub for a in anomalies for sub in a.details.get("subtypes", [])]
    assert "impossible_value" in subtypes_found


def test_d1_flags_sudden_spikes_and_drops():
    """Test D1 flags sudden ramp rate slew violations."""
    det = DetectorRegistry.get("d1_statistical")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    observations = [(base_time + timedelta(minutes=15 * i), 500.0) for i in range(8)]
    # Sudden +850 kW spike in 15 minutes (slew rate jump)
    observations[4] = (base_time + timedelta(minutes=15 * 4), 950.0)

    anomalies = det.detect(
        observations,
        parameters={"max_ramp_rate": 300.0, "check_spikes_drops": True},
        context=ctx,
    )

    assert len(anomalies) >= 1
    reasons = [r for a in anomalies for r in a.details.get("reasons", [])]
    assert any("spike" in r.lower() or "drop" in r.lower() for r in reasons)


# =====================================================================
# 3. D2 Performance Ratio (PR) Deviation Detector Tests
# =====================================================================
def test_d2_pr_deviation_with_irradiance_reference():
    """Test D2 calculates actual PR against irradiance reference and flags significant drop."""
    det = DetectorRegistry.get("d2_pr_deviation")

    base_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    # Irradiance is high (800 W/m2), rated capacity 1,000 kW, expected PR 0.85
    # Expected power = (800 / 1000) * 1000 * 0.85 = 680 kW
    # Actual power is severely depressed at 250 kW (actual PR = 0.3125 vs 0.85 expected)
    irradiance_map = {}
    observations = []
    for i in range(8):
        ts = base_time + timedelta(minutes=15 * i)
        irradiance_map[ts] = 800.0
        observations.append((ts, 250.0))

    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.85,
        cadence_seconds=900,
        irradiance_reference=irradiance_map,
    )

    anomalies = det.detect(
        observations,
        parameters={"threshold_pct": 0.20},
        context=ctx,
    )

    assert len(anomalies) == 1
    anom = anomalies[0]
    assert anom.anomaly_type == "d2_pr_deviation"
    assert anom.details["irradiance_reference_used"] is True
    assert anom.details["actual_pr"] < 0.40
    assert anom.details["expected_pr"] == 0.85
    assert anom.details["deficit_pct"] > 50.0
    assert anom.loss_kw > 400.0
    assert anom.loss_kwh > 800.0  # 2 hours * ~430 kW


def test_d2_pr_deviation_diurnal_curve_fallback():
    """Test D2 falls back to diurnal solar curve when weather station irradiance is unavailable."""
    det = DetectorRegistry.get("d2_pr_deviation")

    # Midday hours (11:00 to 13:00) where solar factor is high
    base_time = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    # Inverter produces only 100 kW instead of expected ~600 kW
    observations = [(base_time + timedelta(minutes=15 * i), 100.0) for i in range(8)]

    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.82,
        cadence_seconds=900,
        irradiance_reference=None,  # No weather station
    )

    anomalies = det.detect(
        observations,
        parameters={"threshold_pct": 0.20},
        context=ctx,
    )

    assert len(anomalies) == 1
    anom = anomalies[0]
    assert anom.details["irradiance_reference_used"] is False
    assert anom.loss_kw > 200.0
    assert anom.details["deficit_pct"] > 30.0


def test_d2_root_cause_classification_heuristics():
    """Test D2 classifies root cause (soiling/degradation vs shading/curtailment)."""
    det = DetectorRegistry.get("d2_pr_deviation")
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.85,
        cadence_seconds=900,
    )

    # Multi-day underperformance across 3 consecutive days
    observations = []
    for day in range(3):
        day_time = datetime(2026, 6, 1 + day, 11, 0, tzinfo=timezone.utc)
        for i in range(4):
            observations.append((day_time + timedelta(minutes=15 * i), 250.0))

    anomalies = det.detect(
        observations,
        parameters={"threshold_pct": 0.15},
        context=ctx,
    )

    assert len(anomalies) >= 1
    # Multi-day pattern should flag dust/soiling/degradation
    assert any("degradation" in a.details["root_cause_indicator"] or "dust" in a.details["root_cause_indicator"] for a in anomalies)


# =====================================================================
# 4. Severity & Financial Loss Policy Integration Tests
# =====================================================================
def test_d1_d2_severity_policy_classification():
    """Verify D1 and D2 anomalies classify into appropriate severity tiers."""
    # Critical tier: massive loss (loss_kw >= 100 kW or loss_kwh >= 200 kWh)
    sev_crit = SeverityPolicy.evaluate(
        loss_kw=250.0,
        loss_kwh=500.0,
        score=0.92,
        duration_minutes=120,
        deficit_pct=0.60,
        anomaly_type="d2_pr_deviation",
        rated_kw=1000.0,
    )
    assert sev_crit == "critical"

    # High tier: moderate loss (loss_kw >= 25 kW, duration >= 30 mins)
    sev_high = SeverityPolicy.evaluate(
        loss_kw=40.0,
        loss_kwh=60.0,
        score=0.75,
        duration_minutes=45,
        deficit_pct=0.35,
        anomaly_type="d1_statistical",
        rated_kw=1000.0,
    )
    assert sev_high == "high"

    # Financial loss calculation
    fin = FinancialLossPolicy.calculate(loss_kwh=500.0, tariff_inr_per_kwh=4.00)
    assert fin.energy_loss_kwh == 500.0
    assert fin.financial_loss_inr == 2000.00
    assert fin.to_dict()["formatted_loss"] == "₹2,000.00"


# =====================================================================
# 5. Deduplication & Celery Background Scan Execution Tests
# =====================================================================
def test_d1_d2_persist_and_deduplicate(db_session: Session, test_setup: Dict[str, Any]):
    """Test deduplication engine merges adjoining D1 and D2 candidates into single open events."""
    plant = test_setup["plant"]
    inverter = test_setup["inverter"]
    channel = test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        canonical_key="active_power",
        rated_kw=1000.0,
        tariff_inr_per_kwh=4.00,
        cadence_seconds=900,
    )

    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    cand1 = DetectedAnomaly(
        start_time=t0,
        end_time=t0 + timedelta(minutes=30),
        score=0.85,
        anomaly_type="d2_pr_deviation",
        summary="PR deficit window 1",
        loss_kw=200.0,
        loss_kwh=100.0,
        actual_value=300.0,
        expected_value=500.0,
    )

    # First pass: creates new anomaly
    persisted1, created1, merged1 = persist_and_deduplicate_anomalies(db_session, [cand1], ctx)
    assert created1 == 1
    assert merged1 == 0
    assert persisted1[0].status == "open"
    assert persisted1[0].severity == "critical"

    # Second pass: contiguous window (adjoining within 15 minutes)
    cand2 = DetectedAnomaly(
        start_time=t0 + timedelta(minutes=45),
        end_time=t0 + timedelta(minutes=75),
        score=0.88,
        anomaly_type="d2_pr_deviation",
        summary="PR deficit window 2",
        loss_kw=220.0,
        loss_kwh=110.0,
        actual_value=280.0,
        expected_value=500.0,
    )

    persisted2, created2, merged2 = persist_and_deduplicate_anomalies(db_session, [cand2], ctx)
    assert created2 == 0
    assert merged2 == 1
    assert persisted2[0].id == persisted1[0].id
    end_utc = persisted2[0].end_time.replace(tzinfo=timezone.utc) if persisted2[0].end_time.tzinfo is None else persisted2[0].end_time
    assert end_utc == cand2.end_time
    # Accumulated energy loss
    assert persisted2[0].details["total_energy_loss_kwh"] == 210.0


def test_execute_plant_scan_with_d1_d2(db_session: Session, test_setup: Dict[str, Any]):
    """Test execute_plant_anomaly_scan automatically evaluates D1 and D2 detectors."""
    plant = test_setup["plant"]
    inverter = test_setup["inverter"]
    channel = test_setup["channel"]

    now = datetime.now(timezone.utc)
    # Seed 12 readings with sudden severe drops
    readings = []
    for i in range(12):
        ts = now - timedelta(hours=3) + timedelta(minutes=15 * i)
        val = 50.0 if i in (6, 7) else 650.0
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
    assert summary["anomalies_detected"] >= 1
    assert summary["anomalies_created"] >= 1
