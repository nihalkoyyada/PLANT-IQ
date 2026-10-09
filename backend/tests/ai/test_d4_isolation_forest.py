"""Comprehensive Unit & Integration Tests for Task S4-AI-04 (D4 Isolation Forest Detector).

Tests:
1. Multi-Variable Feature Engineering:
   - Rolling time window aggregation (raw value, rolling mean, rolling std, ramp delta, loading, diurnal factor, expected ratio).
2. Per-Asset Model Fit:
   - Isolated machine learning model trained custom per asset using scikit-learn IsolationForest.
   - Clean baseline operation produces zero false alarms.
3. Persistence Verification:
   - Transient single/double-interval telemetry glitches are filtered out.
   - Genuine persistent behavioral shifts (>= min_persistence intervals) are confirmed and flagged.
4. Failure Mode Identification:
   - Erratic high-volatility sensor noise / inverter hunting.
   - Persistent multi-variable derating and behavioral shifts.
5. Framework Integration:
   - Discovery via DetectorRegistry under 'd4_isolation_forest', 'isolation_forest', 'd4'.
   - SeverityPolicy and FinancialLossPolicy evaluation.
   - Anomaly deduplication and window merging.
   - Automated Celery Beat background execution via execute_plant_anomaly_scan.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.anomaly_dedup import persist_and_deduplicate_anomalies
from app.ai.anomaly_policy import FinancialLossPolicy, SeverityPolicy
from app.ai.detector_registry import (
    BaseDetector,
    D4IsolationForestDetector,
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
    calculate_clear_sky_expected_power,
    extract_per_asset_telemetry_features,
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
    """Seed test plant, inverter asset, and channel."""
    org = Organization(name="S4 D4 Test Org", slug="s4-d4-test-org")
    db_session.add(org)
    db_session.flush()

    plant = Plant(
        org_id=org.id,
        name="Pavagada Solar Complex D4",
        plant_type="solar",
        latitude=14.10,
        longitude=77.30,
        capacity_ac_kw=2000.0,
        capacity_dc_kwp=2400.0,
        expected_pr=0.82,
        tariff_inr_per_kwh=3.60,
    )
    db_session.add(plant)
    db_session.flush()

    inverter = Asset(
        plant_id=plant.id,
        name="INV-D4-01",
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
        source_name="INV-D4-01 Active Power",
        interval_s=900,
    )
    db_session.add(channel)
    db_session.commit()

    return {
        "org": org,
        "plant": plant,
        "inverter": inverter,
        "channel": channel,
        "signal": sig,
    }


# =====================================================================
# 1. Multi-Variable Feature Engineering Tests
# =====================================================================
def test_extract_per_asset_telemetry_features():
    """Verify multi-variable features are extracted across rolling time windows."""
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.80,
        latitude=14.10,
        longitude=77.30,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
    observations = []
    for i in range(24):
        ts = base_time + timedelta(minutes=15 * i)
        val = 400.0 + (i * 20.0)
        observations.append((ts, val))

    X, valid_mask, expected_baselines, feature_names = extract_per_asset_telemetry_features(
        observations=observations,
        context=ctx,
        window_size=4,
    )

    assert X.shape[0] == 24
    assert X.shape[1] == 7
    assert len(feature_names) == 7
    assert "rolling_mean" in feature_names
    assert "rolling_std" in feature_names
    assert "ramp_delta" in feature_names

    # Check rolling mean and std
    assert np.all(X[:, 0] > 0)
    assert np.all(valid_mask)
    # Ramp delta for constant step is positive
    assert X[1, 3] == 20.0


# =====================================================================
# 2. Per-Asset Model Fit & Healthy Operation
# =====================================================================
def test_d4_clean_operational_baseline_no_false_alarms():
    """Consistent, healthy operational telemetry emits zero false alarms."""
    detector = D4IsolationForestDetector()
    lat, lon = 14.10, 77.30
    ctx = DetectorContext(
        plant_id=uuid4(),
        asset_name="INV-D4-01",
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
    )

    # 36 intervals (9 daylight hours) matching site coordinates
    base_time = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    for i in range(36):
        ts = base_time + timedelta(minutes=15 * i)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=1000.0, expected_pr=0.80)
        p_noise = p_clear * 0.97 + float(np.random.RandomState(i).normal(0.0, 3.0))
        observations.append((ts, max(0.0, p_noise)))

    anomalies = detector.detect(observations, {"contamination": 0.05, "min_persistence": 3}, ctx)
    assert len(anomalies) == 0


# =====================================================================
# 3. Persistence Verification: Telemetry Glitch Filtering
# =====================================================================
def test_d4_transient_glitch_filtered_by_persistence_check():
    """Brief 1-2 interval telemetry glitches must be suppressed by the persistence checker."""
    detector = D4IsolationForestDetector()
    lat, lon = 14.10, 77.30
    ctx = DetectorContext(
        plant_id=uuid4(),
        asset_name="INV-D4-01",
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    for i in range(36):
        ts = base_time + timedelta(minutes=15 * i)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=1000.0, expected_pr=0.80)
        p = p_clear * 0.97

        # Inject a single 15-minute glitch at index 18 (sensor bounce)
        if i == 18:
            p = 50.0

        observations.append((ts, p))

    anomalies = detector.detect(
        observations,
        {"contamination": 0.05, "min_persistence": 3},
        ctx,
    )

    # The single-interval glitch must NOT trigger an anomaly event
    assert len(anomalies) == 0


def test_d4_persistent_behavioral_derating_confirmed():
    """A behavioral deviation persisting across >= min_persistence intervals is confirmed and flagged."""
    detector = D4IsolationForestDetector()
    lat, lon = 14.10, 77.30
    ctx = DetectorContext(
        plant_id=uuid4(),
        asset_name="INV-D4-01",
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    for i in range(36):
        ts = base_time + timedelta(minutes=15 * i)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=1000.0, expected_pr=0.80)
        p = p_clear * 0.97

        # Persistent derating across 5 intervals (1.25 hours) from index 16 to 21
        if 16 <= i <= 21:
            p = p_clear * 0.40  # Severe multi-variable behavioral shift

        observations.append((ts, p))

    anomalies = detector.detect(
        observations,
        {"contamination": 0.08, "min_persistence": 3},
        ctx,
    )

    assert len(anomalies) >= 1
    a = anomalies[0]
    assert a.anomaly_type == "d4_isolation_forest"
    assert a.score >= 0.40
    assert a.loss_kw > 100.0
    assert a.loss_kwh > 50.0
    assert a.details["persistence_verified"] is True
    assert a.details["point_count"] >= 3
    assert a.details["per_asset_custom_fit"] is True
    assert "derating" in a.details["root_cause_indicator"] or "outlier" in a.details["root_cause_indicator"]


# =====================================================================
# 4. Erratic Noise / Inverter Hunting Failure Mode
# =====================================================================
def test_d4_erratic_noise_and_hunting_detected():
    """High-frequency volatility and oscillatory hunting is detected as erratic noise."""
    detector = D4IsolationForestDetector()
    lat, lon = 14.10, 77.30
    ctx = DetectorContext(
        plant_id=uuid4(),
        asset_name="INV-D4-01",
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
    )

    base_time = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    for i in range(36):
        ts = base_time + timedelta(minutes=15 * i)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=1000.0, expected_pr=0.80)
        p = p_clear * 0.97

        # Severe wild oscillations across intervals 16 to 22
        if 16 <= i <= 22:
            oscillation = 280.0 if (i % 2 == 0) else -280.0
            p = max(50.0, p + oscillation)

        observations.append((ts, p))

    anomalies = detector.detect(
        observations,
        {"contamination": 0.08, "min_persistence": 3},
        ctx,
    )

    assert len(anomalies) >= 1
    found_hunting = any(
        "hunting" in a.details.get("root_cause_indicator", "") or a.score >= 0.40
        for a in anomalies
    )
    assert found_hunting


# =====================================================================
# 5. Registry & Aliases Tests
# =====================================================================
def test_d4_detector_registry_discovery():
    """Verify D4 detector is discoverable in DetectorRegistry by primary key and aliases."""
    assert DetectorRegistry.has_detector("d4_isolation_forest")
    assert DetectorRegistry.has_detector("isolation_forest")
    assert DetectorRegistry.has_detector("d4")

    det1 = DetectorRegistry.get("d4_isolation_forest")
    det2 = DetectorRegistry.get("isolation_forest")
    det3 = DetectorRegistry.get("d4")

    assert isinstance(det1, D4IsolationForestDetector)
    assert isinstance(det2, D4IsolationForestDetector)
    assert isinstance(det3, D4IsolationForestDetector)


def test_d4_severity_and_financial_loss_policy():
    """Verify severity tiering and financial loss assessment for D4 anomalies."""
    fin = FinancialLossPolicy.calculate(
        loss_kwh=400.0,
        power_deficit_kw=200.0,
        duration_minutes=120,
        tariff_inr_per_kwh=3.60,
    )
    assert fin.energy_loss_kwh == 400.0
    assert fin.financial_loss_inr == 1440.0
    assert fin.to_dict()["formatted_loss"] == "₹1,440.00"

    sev = SeverityPolicy.evaluate(
        loss_kw=200.0,
        loss_kwh=400.0,
        score=0.90,
        duration_minutes=120,
        deficit_pct=0.50,
        anomaly_type="d4_isolation_forest",
        rated_kw=1000.0,
    )
    assert sev == "critical"


# =====================================================================
# 6. Deduplication & Celery Background Scan Execution
# =====================================================================
def test_d4_deduplication_engine_merge(db_session: Session, test_setup: Dict[str, Any]):
    """Test deduplication engine merges contiguous D4 anomaly spans."""
    plant = test_setup["plant"]
    inverter = test_setup["inverter"]
    channel = test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        canonical_key="active_power",
        rated_kw=1000.0,
        tariff_inr_per_kwh=3.60,
        cadence_seconds=900,
    )

    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    cand1 = DetectedAnomaly(
        start_time=t0,
        end_time=t0 + timedelta(minutes=45),
        score=0.82,
        anomaly_type="d4_isolation_forest",
        summary="Isolation Forest derating window 1",
        loss_kw=150.0,
        loss_kwh=112.5,
        actual_value=350.0,
        expected_value=500.0,
    )

    persisted1, created1, merged1 = persist_and_deduplicate_anomalies(db_session, [cand1], ctx)
    assert created1 == 1
    assert merged1 == 0
    assert persisted1[0].status == "open"

    # Second candidate immediately adjoining window 1
    cand2 = DetectedAnomaly(
        start_time=t0 + timedelta(minutes=45),
        end_time=t0 + timedelta(minutes=90),
        score=0.85,
        anomaly_type="d4_isolation_forest",
        summary="Isolation Forest derating window 2",
        loss_kw=160.0,
        loss_kwh=120.0,
        actual_value=340.0,
        expected_value=500.0,
    )

    persisted2, created2, merged2 = persist_and_deduplicate_anomalies(db_session, [cand2], ctx)
    assert created2 == 0
    assert merged2 == 1
    assert persisted2[0].id == persisted1[0].id
    assert persisted2[0].details["total_energy_loss_kwh"] == pytest.approx(232.5, abs=0.1)


def test_execute_plant_scan_with_d4(db_session: Session, test_setup: Dict[str, Any]):
    """Test execute_plant_anomaly_scan automatically runs D4 detector and persists anomalies."""
    plant = test_setup["plant"]
    inverter = test_setup["inverter"]
    channel = test_setup["channel"]

    # Seed 32 readings with an extended derating period
    base_time = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
    readings = []
    for i in range(32):
        ts = base_time + timedelta(minutes=15 * i)
        # Normal midday power ~700 kW, derating down to 100 kW across 6 intervals
        val = 100.0 if 14 <= i <= 20 else 700.0
        readings.append(Reading(channel_id=channel.id, ts=ts, value=val, quality=0))

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
