"""Comprehensive Unit & Integration Tests for Task S4-AI-03 (D3 Irradiance-Residual Detector).

Tests:
1. Clear-Sky Solar Irradiance Model:
   - Solar position calculation (zenith, elevation, declination, hour angle).
   - Theoretical GHI clear-sky irradiance (Haurwitz model).
   - Theoretical clear-sky AC power generation.
2. D3 Irradiance-Residual Anomaly Detector:
   - Healthy clear-sky generation (zero false alarms).
   - Natural cloud cover attenuation filtering (transient dips suppressed).
   - Severe dust accumulation / soiling and module degradation detection.
   - Sudden midday inverter trip under clear skies.
   - Pyranometer sensor obstruction detection (soiled sensor vs active inverter).
   - Direct execution on irradiance channels.
3. Policy & System Integration:
   - Plugin registry discovery and aliases ('d3_irradiance_residual', 'irradiance_residual', 'd3').
   - SeverityPolicy and FinancialLossPolicy evaluation.
   - Anomaly deduplication and event window merging.
   - Automated Celery Beat background execution via execute_plant_anomaly_scan.
"""

from datetime import datetime, timedelta, timezone
import math
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
    D3IrradianceResidualDetector,
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
    calculate_clear_sky_expected_power,
    calculate_clear_sky_irradiance,
    calculate_solar_position,
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
    """Seed test plant with coordinates, inverter, canonical signal, and channel."""
    org = Organization(name="S4 D3 Test Org", slug="s4-d3-test-org")
    db_session.add(org)
    db_session.flush()

    # Pavagada Solar Park coordinates (~14.1° N, 77.3° E)
    plant = Plant(
        org_id=org.id,
        name="Pavagada Solar Complex D3",
        plant_type="solar",
        latitude=14.10,
        longitude=77.30,
        capacity_ac_kw=2000.0,
        capacity_dc_kwp=2400.0,
        expected_pr=0.82,
        tariff_inr_per_kwh=3.50,
    )
    db_session.add(plant)
    db_session.flush()

    inverter = Asset(
        plant_id=plant.id,
        name="INV-D3-01",
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
        source_name="INV-D3-01 Active Power",
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
# 1. Clear-Sky Solar Model Unit Tests
# =====================================================================
def test_solar_position_day_vs_night():
    """Verify solar position calculation at solar noon vs midnight."""
    lat = 14.10
    lon = 77.30

    # Solar noon at Pavagada (77.3° E longitude -> ~06:50 UTC is ~12:00 LST)
    noon_dt = datetime(2026, 3, 21, 6, 50, tzinfo=timezone.utc)  # Spring equinox
    cos_zenith, zenith_deg, elevation_deg = calculate_solar_position(noon_dt, lat, lon)

    assert cos_zenith > 0.85
    assert zenith_deg < 30.0
    assert elevation_deg > 60.0

    # Midnight (18:50 UTC is ~00:00 LST)
    midnight_dt = datetime(2026, 3, 21, 18, 50, tzinfo=timezone.utc)
    cos_m, zenith_m, elev_m = calculate_solar_position(midnight_dt, lat, lon)

    assert cos_m == 0.0
    assert zenith_m == 90.0
    assert elev_m == 0.0


def test_clear_sky_irradiance_diurnal_curve():
    """Verify Haurwitz clear-sky horizontal irradiance envelope."""
    lat = 14.10
    lon = 77.30

    # Nighttime -> exactly 0 W/m²
    night_dt = datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc)
    assert calculate_clear_sky_irradiance(night_dt, lat, lon) == 0.0

    # Solar noon on summer solstice -> high GHI ~950-1050 W/m²
    noon_dt = datetime(2026, 6, 21, 6, 50, tzinfo=timezone.utc)
    ghi_noon = calculate_clear_sky_irradiance(noon_dt, lat, lon)
    assert 900.0 <= ghi_noon <= 1080.0

    # Expected power for 1000 kW rated with 0.80 PR
    exp_power = calculate_clear_sky_expected_power(noon_dt, lat, lon, rated_kw=1000.0, expected_pr=0.80)
    assert 720.0 <= exp_power <= 864.0


# =====================================================================
# 2. D3 Irradiance-Residual Anomaly Detector Unit Tests
# =====================================================================
def test_d3_detector_healthy_plant_no_false_alarms():
    """Healthy plant matching clear-sky baseline within normal noise emits no anomalies."""
    detector = D3IrradianceResidualDetector()
    lat, lon = 14.10, 77.30
    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
    )

    # Generate 1 full day of 15-minute readings (05:00 UTC to 14:00 UTC daylight)
    base_date = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    for i in range(36):  # 9 hours of daylight
        ts = base_date + timedelta(minutes=15 * i)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=1000.0, expected_pr=0.80)
        # Healthy plant generates ~96% - 100% of clear sky
        p_act = p_clear * 0.97
        observations.append((ts, p_act))

    anomalies = detector.detect(observations, {}, ctx)
    assert len(anomalies) == 0


def test_d3_natural_cloud_cover_attenuation_filtered():
    """Natural transient cloud dips must be filtered out and not flagged as site defects."""
    detector = D3IrradianceResidualDetector()
    lat, lon = 14.10, 77.30

    base_date = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    weather_irr = {}

    for i in range(36):
        ts = base_date + timedelta(minutes=15 * i)
        ghi_clear = calculate_clear_sky_irradiance(ts, lat, lon)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=1000.0, expected_pr=0.80)

        # Passing clouds at intervals 14 and 15 (noon cloud cover)
        if i in (14, 15):
            # Cloud cuts measured sunlight to 30%
            weather_irr[ts] = ghi_clear * 0.30
            p_act = p_clear * 0.30
        else:
            weather_irr[ts] = ghi_clear * 0.98
            p_act = p_clear * 0.98

        observations.append((ts, p_act))

    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=1000.0,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
        irradiance_reference=weather_irr,
    )

    anomalies = detector.detect(observations, {}, ctx)
    # The cloud drop was synchronous with measured weather pyranometer -> no false site alarm!
    assert len(anomalies) == 0


def test_d3_severe_dust_and_soiling_deficit_detected():
    """Severe dust accumulation on panels under clear skies must be detected with robust residual."""
    detector = D3IrradianceResidualDetector()
    lat, lon = 14.10, 77.30
    rated_kw = 1000.0

    base_date = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    weather_irr = {}

    # Under cloudless sky, soiled panels deliver only 65% of clear-sky capacity (35% deficit)
    for i in range(36):
        ts = base_date + timedelta(minutes=15 * i)
        ghi_clear = calculate_clear_sky_irradiance(ts, lat, lon)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=rated_kw, expected_pr=0.80)

        weather_irr[ts] = ghi_clear * 0.99  # Pyranometer shows clear bright skies!
        p_act = p_clear * 0.65  # Inverter severely depressed due to thick dust crust

        observations.append((ts, p_act))

    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=rated_kw,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
        irradiance_reference=weather_irr,
    )

    anomalies = detector.detect(observations, {"threshold_pct": 0.18}, ctx)
    assert len(anomalies) >= 1

    a = anomalies[0]
    assert a.anomaly_type == "d3_irradiance_residual"
    assert a.score >= 0.30
    assert a.loss_kw > 100.0
    assert a.loss_kwh > 200.0
    assert a.details["root_cause_indicator"] == "severe_dust_accumulation_or_module_degradation"
    assert a.details["robust_slope_beta"] == pytest.approx(0.65, abs=0.05)
    assert a.details["deficit_pct"] >= 30.0


def test_d3_inverter_trip_under_clearsky():
    """Midday abrupt drop to zero power while clear-sky is at peak is flagged as inverter trip."""
    detector = D3IrradianceResidualDetector()
    lat, lon = 14.10, 77.30
    rated_kw = 1000.0

    base_date = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []

    for i in range(36):
        ts = base_date + timedelta(minutes=15 * i)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=rated_kw, expected_pr=0.80)

        # Midday trip between 11:30 and 13:00 (intervals 14 to 20)
        if 14 <= i <= 20:
            p_act = 0.0
        else:
            p_act = p_clear * 0.97

        observations.append((ts, p_act))

    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=rated_kw,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
    )

    anomalies = detector.detect(observations, {}, ctx)
    assert len(anomalies) >= 1
    trip_anom = anomalies[0]
    assert trip_anom.details["root_cause_indicator"] == "inverter_trip_under_clearsky"
    assert trip_anom.actual_value == 0.0
    assert trip_anom.expected_value > 500.0


def test_d3_pyranometer_sensor_obstruction_detection():
    """Pyranometer reading low while inverter is generating high indicates sensor obstruction."""
    detector = D3IrradianceResidualDetector()
    lat, lon = 14.10, 77.30
    rated_kw = 1000.0

    base_date = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []
    weather_irr = {}

    for i in range(36):
        ts = base_date + timedelta(minutes=15 * i)
        ghi_clear = calculate_clear_sky_irradiance(ts, lat, lon)
        p_clear = calculate_clear_sky_expected_power(ts, lat, lon, rated_kw=rated_kw, expected_pr=0.80)

        # Pyranometer is blocked/soiled (reads 200 W/m² instead of 950 W/m²)
        weather_irr[ts] = ghi_clear * 0.25
        # But inverter generates near expected power
        p_act = p_clear * 0.95

        observations.append((ts, p_act))

    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="active_power",
        rated_kw=rated_kw,
        expected_pr=0.80,
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
        irradiance_reference=weather_irr,
    )

    anomalies = detector.detect(observations, {}, ctx)
    assert len(anomalies) >= 1
    assert any(a.details["root_cause_indicator"] == "sensor_obstruction_or_soiled_pyranometer" for a in anomalies)


def test_d3_irradiance_channel_direct_evaluation():
    """Running D3 detector directly on an irradiance channel flags blocked pyranometers."""
    detector = D3IrradianceResidualDetector()
    lat, lon = 14.10, 77.30

    base_date = datetime(2026, 3, 21, 5, 0, tzinfo=timezone.utc)
    observations = []

    # Direct pyranometer readings: sensor obscured by bird droppings / mud
    for i in range(36):
        ts = base_date + timedelta(minutes=15 * i)
        ghi_clear = calculate_clear_sky_irradiance(ts, lat, lon)
        # Blocked pyranometer reads only 40% of theoretical clear-sky irradiance
        ghi_act = ghi_clear * 0.40
        observations.append((ts, ghi_act))

    ctx = DetectorContext(
        plant_id=uuid4(),
        canonical_key="poa_irradiance",
        latitude=lat,
        longitude=lon,
        cadence_seconds=900,
    )

    anomalies = detector.detect(observations, {"threshold_pct": 0.20}, ctx)
    assert len(anomalies) >= 1
    a = anomalies[0]
    assert a.metric_name == "poa_irradiance"
    assert "W/m²" in a.summary
    assert a.details["root_cause_indicator"] == "sensor_obstruction_or_pyranometer_soiling"


# =====================================================================
# 3. Registry & Policy Integration Tests
# =====================================================================
def test_d3_detector_registry_discovery():
    """Verify D3 detector is discoverable in DetectorRegistry by primary key and aliases."""
    assert DetectorRegistry.has_detector("d3_irradiance_residual")
    assert DetectorRegistry.has_detector("irradiance_residual")
    assert DetectorRegistry.has_detector("d3")

    det1 = DetectorRegistry.get("d3_irradiance_residual")
    det2 = DetectorRegistry.get("irradiance_residual")
    det3 = DetectorRegistry.get("d3")

    assert isinstance(det1, D3IrradianceResidualDetector)
    assert isinstance(det2, D3IrradianceResidualDetector)
    assert isinstance(det3, D3IrradianceResidualDetector)


def test_d3_severity_and_financial_loss_policy():
    """Test policy integration accurately calculates financial loss and severity tiers."""
    # Deficit of 150 kW over 2 hours = 300 kWh lost
    fin = FinancialLossPolicy.calculate(
        loss_kwh=300.0,
        power_deficit_kw=150.0,
        duration_minutes=120,
        tariff_inr_per_kwh=3.50,
    )
    assert fin.energy_loss_kwh == 300.0
    assert fin.financial_loss_inr == 1050.0
    assert fin.to_dict()["formatted_loss"] == "₹1,050.00"

    # Critical severity classification for > 200 kWh lost or > 100 kW
    sev = SeverityPolicy.evaluate(
        loss_kw=150.0,
        loss_kwh=300.0,
        score=0.85,
        duration_minutes=120,
        deficit_pct=0.40,
        anomaly_type="d3_irradiance_residual",
        rated_kw=1000.0,
    )
    assert sev == "critical"

    # Moderate deficit -> Medium severity
    sev_med = SeverityPolicy.evaluate(
        loss_kw=15.0,
        loss_kwh=15.0,
        score=0.50,
        duration_minutes=60,
        deficit_pct=0.18,
        anomaly_type="d3_irradiance_residual",
        rated_kw=1000.0,
    )
    assert sev_med == "medium"


# =====================================================================
# 4. Deduplication & Celery Background Scan Execution Tests
# =====================================================================
def test_d3_deduplication_engine_merge(db_session: Session, test_setup: Dict[str, Any]):
    """Test deduplication engine merges adjoining D3 anomaly time windows."""
    plant = test_setup["plant"]
    inverter = test_setup["inverter"]
    channel = test_setup["channel"]

    ctx = DetectorContext(
        plant_id=plant.id,
        asset_id=inverter.id,
        channel_id=channel.id,
        canonical_key="active_power",
        rated_kw=1000.0,
        tariff_inr_per_kwh=3.50,
        cadence_seconds=900,
    )

    t0 = datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc)
    cand1 = DetectedAnomaly(
        start_time=t0,
        end_time=t0 + timedelta(minutes=45),
        score=0.80,
        anomaly_type="d3_irradiance_residual",
        summary="Clear-sky deficit window 1",
        loss_kw=250.0,
        loss_kwh=187.5,
        actual_value=400.0,
        expected_value=650.0,
    )

    persisted1, created1, merged1 = persist_and_deduplicate_anomalies(db_session, [cand1], ctx)
    assert created1 == 1
    assert merged1 == 0
    assert persisted1[0].status == "open"

    # Second candidate immediately adjoining window 1
    cand2 = DetectedAnomaly(
        start_time=t0 + timedelta(minutes=45),
        end_time=t0 + timedelta(minutes=90),
        score=0.82,
        anomaly_type="d3_irradiance_residual",
        summary="Clear-sky deficit window 2",
        loss_kw=260.0,
        loss_kwh=195.0,
        actual_value=390.0,
        expected_value=650.0,
    )

    persisted2, created2, merged2 = persist_and_deduplicate_anomalies(db_session, [cand2], ctx)
    assert created2 == 0
    assert merged2 == 1
    assert persisted2[0].id == persisted1[0].id
    assert persisted2[0].details["total_energy_loss_kwh"] == pytest.approx(382.5, abs=0.1)


def test_execute_plant_scan_with_d3(db_session: Session, test_setup: Dict[str, Any]):
    """Test execute_plant_anomaly_scan automatically executes D3 detector with plant coordinates."""
    plant = test_setup["plant"]
    inverter = test_setup["inverter"]
    channel = test_setup["channel"]

    # Seed daylight readings with a persistent soiling deficit
    base_time = datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc)
    readings = []
    for i in range(16):
        ts = base_time + timedelta(minutes=15 * i)
        p_clear = calculate_clear_sky_expected_power(
            ts, plant.latitude, plant.longitude, rated_kw=1000.0, expected_pr=0.80
        )
        # Soiling deficit: generate only 50% of clear sky
        val = p_clear * 0.50
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
