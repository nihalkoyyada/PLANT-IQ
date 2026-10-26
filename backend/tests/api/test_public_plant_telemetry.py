import pytest
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import get_db, SessionLocal
from app.models import Plant, Asset, Channel, Reading, Organization, User
from app.api.plants import clear_public_summary_cache, _normalize_public_ac_kw, _normalize_public_dc_kw
from app.core.security import create_access_token
from sqlalchemy import select, func


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_summary_cache():
    """Ensure in-memory cache is reset before each test."""
    clear_public_summary_cache()
    yield
    clear_public_summary_cache()


def test_public_plant_summary_no_auth_required():
    """Ensure /plants/public-summary is public-safe and does not require Authorization header."""
    response = client.get("/plants/public-summary")
    assert response.status_code == 200
    data = response.json()
    assert "plant_id" in data
    assert "plant_name" in data
    assert "ac_power_mw" in data
    assert "dc_power_mw" in data
    assert "data_freshness" in data
    assert "status_label" in data
    assert "trend" in data
    assert isinstance(data["trend"], list)


def test_public_plant_summary_real_database_readings():
    """Verify live values against known database records for the configured demo plant."""
    response = client.get("/plants/public-summary")
    assert response.status_code == 200
    data = response.json()

    assert data["plant_name"] == "Surya Solar Farm - 50MW"
    assert data["capacity_ac_mw"] > 0
    assert data["capacity_dc_mw"] > 0
    assert data["inverter_count"] == 22  # 22 active inverters with SCADA channels
    assert data["channel_count"] == 44

    # Latest reading in Kaggle dataset is at 2020-06-17 23:45:00 UTC
    assert data["latest_timestamp"] == "2020-06-17T23:45:00+00:00"
    assert data["ac_power_mw"] == 0.0
    assert data["dc_power_mw"] == 0.0
    assert data["data_freshness"] == "STALE"
    assert "STALE" in data["status_label"]
    assert data["stale_days"] is not None and data["stale_days"] >= 2300

    # Trend points should cover the preceding 24h chronologically
    assert len(data["trend"]) > 0
    first_pt = data["trend"][0]
    last_pt = data["trend"][-1]
    assert first_pt["timestamp"] < last_pt["timestamp"]
    assert data["peak_ac_power_mw"] > 20.0  # Midday peak generation was ~29 MW


def test_public_plant_summary_inverter_asset_count_explanation():
    """
    Verify explanation of 22 active inverters vs 23 total inverter rows in database.
    Surya Solar Farm has 23 total inverter assets, but exactly 1 dormant asset
    ('Inverter HmiyD2TTLFNqkNe') has 0 channels and 0 readings.
    """
    db = SessionLocal()
    try:
        plant_id = "d253760d-d8ad-4a18-b655-fc22a5222d59"
        total_inverters = db.execute(
            select(Asset).where(Asset.plant_id == plant_id, Asset.asset_type == "inverter")
        ).scalars().all()
        assert len(total_inverters) == 23

        # Check channels on each inverter
        inverters_with_channels = []
        dormant_inverters = []
        for inv in total_inverters:
            chan_count = db.scalar(
                select(func.count(Channel.id)).where(Channel.asset_id == inv.id)
            )
            if chan_count > 0:
                inverters_with_channels.append(inv)
            else:
                dormant_inverters.append(inv)

        assert len(inverters_with_channels) == 22
        assert len(dormant_inverters) == 1
        assert dormant_inverters[0].name == "Inverter HmiyD2TTLFNqkNe"

        # Verify that endpoint correctly reports 22 active inverters
        res = client.get("/plants/public-summary")
        assert res.status_code == 200
        assert res.json()["inverter_count"] == 22
    finally:
        db.close()


def test_public_plant_summary_ac_dc_unit_conversions_and_no_double_counting():
    """
    Verify unit conversion correctness:
    - AC readings in kW normalized correctly (1,244.78 kW -> 1.24 MW)
    - Kaggle deci-kW DC readings (raw ~12,764 deci-kW / 10.0 -> 1,276.4 kW -> 1.28 MW)
    - Inverter DC-to-AC conversion efficiency is in realistic ~97.5% range
    - Checks that no duplicate plant-level virtual channels double-count with inverters.
    """
    db = SessionLocal()
    try:
        plant_id = "d253760d-d8ad-4a18-b655-fc22a5222d59"

        # Unit normalizer functions test
        ac_norm = _normalize_public_ac_kw(1244.7875, "kW")
        assert round(ac_norm, 2) == 1244.79

        dc_norm = _normalize_public_dc_kw(12764.125, "kW", None)
        assert round(dc_norm, 2) == 1276.41

        # Midday peak timestamp
        ts_peak = datetime(2020, 6, 17, 12, 15, tzinfo=timezone.utc)
        ac_readings = db.execute(
            select(Reading.value)
            .join(Channel, Reading.channel_id == Channel.id)
            .join(Asset, Channel.asset_id == Asset.id)
            .where(
                Asset.plant_id == plant_id,
                Channel.canonical_key == "power_ac",
                Reading.ts == ts_peak,
            )
        ).scalars().all()

        dc_readings = db.execute(
            select(Reading.value)
            .join(Channel, Reading.channel_id == Channel.id)
            .join(Asset, Channel.asset_id == Asset.id)
            .where(
                Asset.plant_id == plant_id,
                Channel.canonical_key == "power_dc",
                Reading.ts == ts_peak,
            )
        ).scalars().all()

        # Exactly 22 inverters reported readings at peak
        assert len(ac_readings) == 22
        assert len(dc_readings) == 22

        sum_ac_kw = sum(_normalize_public_ac_kw(float(v), "kW") for v in ac_readings)
        sum_dc_kw = sum(_normalize_public_dc_kw(float(v), "kW", None) for v in dc_readings)

        ac_mw = round(sum_ac_kw / 1000.0, 2)
        dc_mw = round(sum_dc_kw / 1000.0, 2)

        assert ac_mw == 29.05
        assert dc_mw == 29.79

        # Physical efficiency between 95% and 99%
        efficiency = ac_mw / dc_mw
        assert 0.95 <= efficiency <= 0.99
    finally:
        db.close()


def test_public_plant_summary_zero_power_and_historical_metrics_distinction():
    """
    Verify night readings return 0.0 MW, and historical metrics (peak, last_active)
    are strictly separated and never substituted for current power.
    """
    response = client.get("/plants/public-summary")
    assert response.status_code == 200
    data = response.json()

    # Current output at 23:45 UTC is 0.0 MW
    assert data["ac_power_mw"] == 0.0
    assert data["dc_power_mw"] == 0.0

    # Historical metrics are populated and distinct
    assert data["peak_ac_power_mw"] is not None
    assert data["peak_ac_power_mw"] > 0.0
    assert data["peak_ac_power_mw"] != data["ac_power_mw"]

    assert data["last_active_ac_mw"] is not None
    assert data["last_active_ac_mw"] > 0.0
    assert data["last_active_timestamp"] is not None
    assert data["last_active_timestamp"] != data["latest_timestamp"]


def test_public_plant_summary_cache_control_and_caching():
    """Verify HTTP Cache-Control header is present and in-memory cache responds quickly."""
    res1 = client.get("/plants/public-summary")
    assert res1.status_code == 200
    assert "public" in res1.headers.get("cache-control", "")
    assert "max-age=15" in res1.headers.get("cache-control", "")

    # Fast subsequent call hits cache
    res2 = client.get("/plants/public-summary")
    assert res2.status_code == 200
    assert res2.json()["plant_id"] == res1.json()["plant_id"]


def test_public_plant_summary_caching_per_plant_isolation():
    """Verify caching is isolated per resolved plant and does not leak data between plants."""
    db = SessionLocal()
    org = db.query(Organization).first()
    other_plant = Plant(
        org_id=org.id,
        name="Showcase Plant B",
        plant_type="solar",
        capacity_ac_kw=15000.0,
        capacity_dc_kwp=18000.0,
        metadata_={"is_public": True},
    )
    db.add(other_plant)
    db.commit()
    db.refresh(other_plant)
    other_plant_id = str(other_plant.id)
    db.close()

    try:
        # Cache demo plant
        res_demo = client.get("/plants/public-summary")
        assert res_demo.status_code == 200
        assert res_demo.json()["plant_name"] == "Surya Solar Farm - 50MW"

        # Query other public plant
        res_other = client.get(f"/plants/public-summary?plant_id={other_plant_id}")
        assert res_other.status_code == 200
        assert res_other.json()["plant_name"] == "Showcase Plant B"
        assert res_other.json()["plant_id"] == other_plant_id

        # Verify demo plant cached response was not overwritten or corrupted
        res_demo2 = client.get("/plants/public-summary")
        assert res_demo2.status_code == 200
        assert res_demo2.json()["plant_name"] == "Surya Solar Farm - 50MW"
    finally:
        clean_db = SessionLocal()
        p = clean_db.get(Plant, UUID(other_plant_id))
        if p:
            clean_db.delete(p)
            clean_db.commit()
        clean_db.close()


def test_public_plant_summary_freshness_boundary_tests(monkeypatch):
    """
    Boundary tests for freshness threshold evaluation:
    Rule: age_hours <= threshold_hours -> LIVE, else STALE.
    Tests precisely:
    1. age < threshold (just below boundary) -> LIVE
    2. age == threshold (exact boundary point) -> LIVE (since <= is true)
    3. age > threshold (just above boundary) -> STALE
    """
    # 1. Fetch demo plant actual timestamp and compute exact age
    res_base = client.get("/plants/public-summary")
    assert res_base.status_code == 200
    base_data = res_base.json()
    target_ts = datetime.fromisoformat(base_data["latest_timestamp"])

    # Fix current time deterministically with monkeypatch to prevent clock drift during test
    fixed_now = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.api.plants.get_current_utc_time", lambda: fixed_now)

    exact_age_hours = (fixed_now - target_ts).total_seconds() / 3600.0

    # Boundary 1: threshold is slightly larger than age (just below threshold) -> LIVE
    clear_public_summary_cache()
    thresh_live = exact_age_hours + 0.05  # 3 minutes above age
    res_below = client.get(f"/plants/public-summary?stale_hours={thresh_live}")
    assert res_below.status_code == 200
    assert res_below.json()["data_freshness"] == "LIVE"
    assert res_below.json()["status_label"] == "SCADA TELEMETRY ACTIVE"

    # Boundary 2: threshold is exactly equal to age (exact boundary) -> LIVE (age <= threshold)
    clear_public_summary_cache()
    res_exact = client.get(f"/plants/public-summary?stale_hours={exact_age_hours}")
    assert res_exact.status_code == 200
    assert res_exact.json()["data_freshness"] == "LIVE"
    assert res_exact.json()["status_label"] == "SCADA TELEMETRY ACTIVE"

    # Boundary 3: threshold is slightly smaller than age (just above threshold) -> STALE
    clear_public_summary_cache()
    thresh_stale = exact_age_hours - 0.05  # 3 minutes below age
    res_above = client.get(f"/plants/public-summary?stale_hours={thresh_stale}")
    assert res_above.status_code == 200
    assert res_above.json()["data_freshness"] == "STALE"
    assert "STALE" in res_above.json()["status_label"]


def test_public_plant_summary_configured_24h_threshold_fresh_vs_stale_readings(monkeypatch):
    """
    Test the configured 24.0h threshold against recent vs older readings:
    - Reading at 23.9h ago (within 24h threshold) -> LIVE
    - Reading at 24.0h ago (exact 24h threshold) -> LIVE
    - Reading at 24.1h ago (beyond 24h threshold) -> STALE
    """
    fixed_now = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.api.plants.get_current_utc_time", lambda: fixed_now)

    db = SessionLocal()
    org = db.query(Organization).first()

    test_plant = Plant(
        org_id=org.id,
        name=f"24h Boundary Test Plant {uuid4()}",
        plant_type="solar",
        capacity_ac_kw=5000.0,
        capacity_dc_kwp=6000.0,
        metadata_={"is_public": True},
    )
    db.add(test_plant)
    db.commit()
    db.refresh(test_plant)

    asset = Asset(
        plant_id=test_plant.id,
        name="Test Inverter 01",
        asset_type="inverter",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    ac_chan = Channel(
        asset_id=asset.id,
        canonical_key="power_ac",
        source_name="INVERTER_AC",
        receive_unit="kW",
    )
    db.add(ac_chan)
    db.commit()
    db.refresh(ac_chan)

    plant_id_str = str(test_plant.id)
    chan_id = ac_chan.id
    asset_id = asset.id
    db.close()

    try:
        # Case A: Reading at 23.9h ago -> LIVE
        db = SessionLocal()
        ts_23_9h = fixed_now - timedelta(hours=23, minutes=54)
        db.add(Reading(channel_id=chan_id, ts=ts_23_9h, value=500.0))
        db.commit()
        db.close()

        clear_public_summary_cache()
        res_fresh = client.get(f"/plants/public-summary?plant_id={plant_id_str}")
        assert res_fresh.status_code == 200
        assert res_fresh.json()["data_freshness"] == "LIVE"
        assert res_fresh.json()["status_label"] == "SCADA TELEMETRY ACTIVE"

        # Case B: Reading at 24.0h ago (exact 24.0h boundary) -> LIVE (age <= threshold)
        db = SessionLocal()
        db.query(Reading).filter(Reading.channel_id == chan_id).delete()
        ts_24_0h = fixed_now - timedelta(hours=24)
        db.add(Reading(channel_id=chan_id, ts=ts_24_0h, value=500.0))
        db.commit()
        db.close()

        clear_public_summary_cache()
        res_exact = client.get(f"/plants/public-summary?plant_id={plant_id_str}")
        assert res_exact.status_code == 200
        assert res_exact.json()["data_freshness"] == "LIVE"
        assert res_exact.json()["status_label"] == "SCADA TELEMETRY ACTIVE"

        # Case C: Reading at 24.1h ago (beyond 24h threshold) -> STALE
        db = SessionLocal()
        db.query(Reading).filter(Reading.channel_id == chan_id).delete()
        ts_24_1h = fixed_now - timedelta(hours=24, minutes=6)
        db.add(Reading(channel_id=chan_id, ts=ts_24_1h, value=500.0))
        db.commit()
        db.close()

        clear_public_summary_cache()
        res_stale = client.get(f"/plants/public-summary?plant_id={plant_id_str}")
        assert res_stale.status_code == 200
        assert res_stale.json()["data_freshness"] == "STALE"
        assert "STALE" in res_stale.json()["status_label"]
    finally:
        clean_db = SessionLocal()
        clean_db.query(Reading).filter(Reading.channel_id == chan_id).delete()
        clean_db.query(Channel).filter(Channel.id == chan_id).delete()
        clean_db.query(Asset).filter(Asset.id == asset_id).delete()
        p = clean_db.get(Plant, UUID(plant_id_str))
        if p:
            clean_db.delete(p)
        clean_db.commit()
        clean_db.close()


def test_public_plant_summary_tenant_isolation_arbitrary_plant_forbidden():
    """
    Verify tenant data isolation:
    Arbitrary unauthenticated requests to a private plant ID must return 403 Forbidden.
    No tenant-specific telemetry can be scraped through arbitrary plant_id parameters.
    """
    db = SessionLocal()
    org = db.query(Organization).first()
    user = db.query(User).filter(User.org_id == org.id).first()

    # Create a private plant belonging to this organization (without is_public)
    private_plant = Plant(
        org_id=org.id,
        name="Private Confidential Solar Plant",
        plant_type="solar",
        capacity_ac_kw=20000.0,
        capacity_dc_kwp=24000.0,
        metadata_={"confidential": True},  # NOT public
    )
    db.add(private_plant)
    db.commit()
    db.refresh(private_plant)
    private_plant_id = str(private_plant.id)
    user_id = str(user.id) if user else None
    db.close()

    try:
        # 1. Unauthenticated request must return 403 Forbidden
        res_unauth = client.get(f"/plants/public-summary?plant_id={private_plant_id}")
        assert res_unauth.status_code == 403
        assert "Access denied" in res_unauth.json()["detail"]
        assert "restricted to the configured showcase demo plant" in res_unauth.json()["detail"]

        # 2. Authenticated request by the owner org member must succeed
        if user_id:
            token = create_access_token(user_id)
            headers = {"Authorization": f"Bearer {token}"}
            res_auth = client.get(f"/plants/public-summary?plant_id={private_plant_id}", headers=headers)
            assert res_auth.status_code == 200
            assert res_auth.json()["plant_name"] == "Private Confidential Solar Plant"
    finally:
        clean_db = SessionLocal()
        p = clean_db.get(Plant, UUID(private_plant_id))
        if p:
            clean_db.delete(p)
            clean_db.commit()
        clean_db.close()


def test_public_plant_summary_non_zero_parameter():
    """Verify non_zero=True prioritizes the latest active daytime generation."""
    response = client.get("/plants/public-summary?non_zero=true")
    assert response.status_code == 200
    data = response.json()

    # At 2020-06-17 18:30:00, generation was active before sunset
    assert data["latest_timestamp"] == "2020-06-17T18:30:00+00:00"
    assert data["ac_power_mw"] > 0.0
    assert data["dc_power_mw"] > 0.0


def test_public_plant_summary_nonexistent_plant_returns_404():
    """Verify providing an unknown plant_id returns 404."""
    unknown_id = uuid4()
    response = client.get(f"/plants/public-summary?plant_id={unknown_id}")
    assert response.status_code == 404


def test_public_plant_summary_offline_plant_without_telemetry():
    """Verify a public plant with zero telemetry reports OFFLINE / UNAVAILABLE gracefully."""
    db = SessionLocal()
    org = db.query(Organization).first()
    empty_plant = Plant(
        org_id=org.id,
        name="Empty Test Solar Plant",
        plant_type="solar",
        capacity_ac_kw=10000.0,
        capacity_dc_kwp=12000.0,
        metadata_={"is_public": True},  # Explicitly public showcase
    )
    db.add(empty_plant)
    db.commit()
    db.refresh(empty_plant)
    empty_plant_id = str(empty_plant.id)
    db.close()

    try:
        response = client.get(f"/plants/public-summary?plant_id={empty_plant_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["plant_name"] == "Empty Test Solar Plant"
        assert data["ac_power_mw"] == 0.0
        assert data["dc_power_mw"] == 0.0
        assert data["latest_timestamp"] is None
        assert data["data_freshness"] == "OFFLINE"
        assert data["status_label"] == "TELEMETRY UNAVAILABLE"
        assert len(data["trend"]) == 0
    finally:
        clean_db = SessionLocal()
        p = clean_db.get(Plant, UUID(empty_plant_id))
        if p:
            clean_db.delete(p)
            clean_db.commit()
        clean_db.close()
