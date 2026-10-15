"""Tests for Anomaly Severity Boundaries, Telemetry Distribution, and Audit Invariants (§12, Sprint 4).

Validates:
1. Severity boundaries: Critical, High, Medium, Low, and Nominal.
2. Normal nighttime zero output does not trigger false anomalies or deficits.
3. Daylight dropouts (inverter trips to 0 kW during peak sun) are flagged as Critical.
4. Moderate deficits (e.g. 10-25% string underperformance) classify into Medium/High.
5. Missing irradiance falls back cleanly to peer-median or diurnal envelope without error.
6. Inverter capacity resolution never substitutes plant-level DC/AC capacity for individual assets.
"""

from datetime import datetime, timedelta, timezone
import math
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.anomaly_policy import FinancialLossPolicy, SeverityPolicy
from app.ai.anomaly_service import AnomalyCalculationService
from app.ai.detector_registry import (
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
    integrate_power_deficit,
)
from app.models.entities import Asset, Base, Organization, Plant


@pytest.fixture
def memory_db():
    """In-memory SQLite session for isolated database-backed unit tests."""
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
        session.close()


# =========================================================================
# 1. Severity Boundaries & Tier Classification
# =========================================================================

def test_severity_boundary_critical_trip():
    """Verify that a daylight inverter trip is always classified as CRITICAL."""
    sev = SeverityPolicy.evaluate(
        loss_kw=850.0,
        loss_kwh=425.0,
        score=1.0,
        duration_minutes=30,
        deficit_pct=1.0,
        anomaly_type="trip",
        rated_kw=1000.0,
    )
    assert sev == "critical"


def test_severity_boundary_critical_massive_loss():
    """Verify that massive power or energy loss is classified as CRITICAL."""
    # Loss >= 100 kW on a 1000 kW asset with significant duration
    sev = SeverityPolicy.evaluate(
        loss_kw=180.0,
        loss_kwh=450.0,
        score=0.95,
        duration_minutes=690,
        deficit_pct=0.20,
        anomaly_type="shading_or_soiling",
        rated_kw=1250.0,
    )
    assert sev == "critical"


def test_severity_boundary_high_substantial_loss():
    """Verify that substantial generation loss with moderate deficit is classified as HIGH."""
    sev = SeverityPolicy.evaluate(
        loss_kw=40.0,
        loss_kwh=60.0,
        score=0.80,
        duration_minutes=180,
        deficit_pct=0.35,
        anomaly_type="shading_or_soiling",
        rated_kw=1250.0,
    )
    assert sev == "high"


def test_severity_boundary_medium_moderate_deficit():
    """Verify that moderate deficit without massive energy loss classifies as MEDIUM."""
    sev = SeverityPolicy.evaluate(
        loss_kw=15.0,
        loss_kwh=15.0,
        score=0.60,
        duration_minutes=60,
        deficit_pct=0.15,
        anomaly_type="soiling",
        rated_kw=1250.0,
    )
    assert sev == "medium"


def test_severity_boundary_low_minor_deficit():
    """Verify that minor sub-5 kW power delta or statistical blip classifies as LOW."""
    sev = SeverityPolicy.evaluate(
        loss_kw=4.0,
        loss_kwh=2.0,
        score=0.45,
        duration_minutes=30,
        deficit_pct=0.04,
        anomaly_type="outlier",
        rated_kw=1250.0,
    )
    assert sev == "low"


# =========================================================================
# 2. Normal Nighttime Zero Output
# =========================================================================

def test_normal_nighttime_zero_output_produces_zero_deficit():
    """Verify that zero power during nighttime (expected = 0) produces zero loss."""
    t_midnight = datetime(2026, 6, 17, 2, 0, tzinfo=timezone.utc)
    ts_list = [t_midnight + timedelta(minutes=15 * i) for i in range(8)]
    actual_vals = [0.0] * 8
    expected_vals = [0.0] * 8  # Nighttime expected is 0

    peak_kw, avg_kw, loss_kwh = integrate_power_deficit(
        timestamps=ts_list,
        actual_vals=actual_vals,
        expected_vals=expected_vals,
        cadence_seconds=900,
        rated_kw=1250.0,
    )
    assert peak_kw == 0.0
    assert avg_kw == 0.0
    assert loss_kwh == 0.0


# =========================================================================
# 3. Daylight Dropouts (Trips during peak sun)
# =========================================================================

def test_daylight_dropout_detects_severe_deficit():
    """Verify that an inverter dropping to 0 kW while expected is 800 kW detects severe loss."""
    t_noon = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    ts_list = [t_noon + timedelta(minutes=15 * i) for i in range(4)]  # 1 hour
    actual_vals = [0.0] * 4  # Trip to 0
    expected_vals = [800.0] * 4  # Expected midday generation

    peak_kw, avg_kw, loss_kwh = integrate_power_deficit(
        timestamps=ts_list,
        actual_vals=actual_vals,
        expected_vals=expected_vals,
        cadence_seconds=900,
        rated_kw=1250.0,
    )
    assert peak_kw == 800.0
    assert avg_kw == 800.0
    assert loss_kwh == 800.0  # 800 kW * 1 hr = 800 kWh


# =========================================================================
# 4. Moderate Deficits (String failures, partial soiling)
# =========================================================================

def test_moderate_deficit_partial_string_loss():
    """Verify that a 15% string loss is calculated accurately without exceeding rated bounds."""
    t_morning = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
    ts_list = [t_morning + timedelta(minutes=15 * i) for i in range(8)]  # 2 hours
    expected_vals = [600.0] * 8
    actual_vals = [510.0] * 8  # 90 kW deficit (15%)

    peak_kw, avg_kw, loss_kwh = integrate_power_deficit(
        timestamps=ts_list,
        actual_vals=actual_vals,
        expected_vals=expected_vals,
        cadence_seconds=900,
        rated_kw=1250.0,
    )
    assert round(peak_kw, 1) == 90.0
    assert round(avg_kw, 1) == 90.0
    # 90 kW * 2 hr = 180 kWh
    assert round(loss_kwh, 1) == 180.0


# =========================================================================
# 5. Missing Irradiance Fallback Behavior
# =========================================================================

def test_missing_irradiance_diurnal_envelope_fallback():
    """Verify that D2 PR detector falls back gracefully to diurnal envelope when weather POA is None."""
    det = DetectorRegistry.get("d2_pr_deviation")
    ctx = DetectorContext(
        plant_id=uuid4(),
        asset_id=uuid4(),
        asset_name="INV-01",
        asset_type="inverter",
        rated_kw=1000.0,
        expected_pr=0.80,
        cadence_seconds=900,
        irradiance_reference=None,  # Missing irradiance!
    )

    # 10:00 to 14:00 UTC (sun is high)
    t_start = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
    observations = []
    for i in range(16):
        ts = t_start + timedelta(minutes=15 * i)
        # Inverter produces normal power
        hour = ts.hour + (ts.minute / 60.0)
        solar_factor = math.sin((hour - 6.0) / 12.5 * math.pi)
        val = 1000.0 * 0.85 * solar_factor * 0.80
        observations.append((ts, val))

    # Should NOT crash and should find 0 anomalies on nominal data
    candidates = det.detect(observations, parameters={"threshold_pct": 0.15}, context=ctx)
    assert len(candidates) == 0


# =========================================================================
# 6. Asset-Level Capacity Resolution vs Plant-Level Normalization
# =========================================================================

def test_asset_capacity_resolution_never_uses_plant_dc_capacity(memory_db):
    """Verify that individual inverter rated capacity NEVER inherits the 28 MW plant DC capacity."""
    org = Organization(name="Test Org")
    memory_db.add(org)
    memory_db.flush()

    # Create plant with 28.28 MW DC capacity and 22 inverters
    plant = Plant(
        org_id=org.id,
        name="Surya Solar Farm - 50MW",
        plant_type="solar",
        capacity_dc_kwp=28280.55,
        capacity_ac_kw=25000.0,
        expected_pr=0.78,
        tariff_inr_per_kwh=3.5,
    )
    memory_db.add(plant)
    memory_db.flush()

    # Create 22 inverters without explicit asset-level rated_kw
    inverters = []
    for i in range(22):
        inv = Asset(
            plant_id=plant.id,
            name=f"Inverter-{i+1}",
            asset_type="inverter",
        )
        memory_db.add(inv)
        inverters.append(inv)
    memory_db.flush()

    # Check capacity resolution for one inverter
    first_inv = inverters[0]
    resolved_kw = AnomalyCalculationService.resolve_asset_rated_kw(memory_db, asset=first_inv, plant=plant)

    # Must resolve to plant.capacity_ac_kw / 22 = 25000 / 22 ~ 1136.36 kW (NOT 28280 kW!)
    assert resolved_kw < 2000.0, f"Resolved capacity {resolved_kw} must be ~1136 kW, not plant DC 28280 kW!"
    assert round(resolved_kw, 1) == 1136.4


def test_power_deficit_bounded_by_inverter_rating():
    """Verify that integrate_power_deficit clamps peak deficit to individual inverter capacity."""
    t_start = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    ts_list = [t_start + timedelta(minutes=15 * i) for i in range(4)]
    actual_vals = [0.0] * 4
    # Expected power corrupted by erroneous plant-scale number (e.g. 15,000 kW)
    expected_vals = [15000.0] * 4

    peak_kw, avg_kw, loss_kwh = integrate_power_deficit(
        timestamps=ts_list,
        actual_vals=actual_vals,
        expected_vals=expected_vals,
        cadence_seconds=900,
        rated_kw=1250.0,  # Clamped to inverter capacity
    )
    assert peak_kw == 1250.0, f"Peak deficit must be clamped to rated capacity 1250 kW, got {peak_kw}"
    assert loss_kwh <= 1250.0 * 1.0, f"Energy loss must not exceed 1250 kWh over 1 hour, got {loss_kwh}"
