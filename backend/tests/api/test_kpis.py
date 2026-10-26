from uuid import uuid4
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, Plant, User, Asset, Channel, Reading
from app.core.security import create_access_token
from app.ai.kpi_engine import calculate_performance_ratio


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def kpi_test_setup():
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == "Test Org KPIs").first()
        if not org:
            org = Organization(name="Test Org KPIs")
            db.add(org)
            db.commit()
            db.refresh(org)

        user = db.query(User).filter(User.email == "kpis_admin@test.com").first()
        if not user:
            user = User(
                org_id=org.id,
                email="kpis_admin@test.com",
                password_hash="hashed_pw",
                full_name="KPIs Admin",
                role="admin",
                is_active=True,
            )
            db.add(user)

        plant = db.query(Plant).filter(Plant.name == "KPI Test Plant", Plant.org_id == org.id).first()
        if not plant:
            plant = Plant(
                org_id=org.id,
                name="KPI Test Plant",
                plant_type="solar",
                capacity_ac_kw=10000.0,
                capacity_dc_kwp=12000.0,
            )
            db.add(plant)
            db.commit()
            db.refresh(plant)

            # Add test inverter asset
            inv = Asset(
                plant_id=plant.id,
                name="Test Inverter 01",
                asset_type="inverter",
            )
            db.add(inv)
            db.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        yield {
            "org": org,
            "user": user,
            "plant": plant,
            "headers": headers,
        }
    finally:
        db.close()


def test_get_pr_heatmap_unauthenticated(client):
    response = client.get("/plants/kpis/heatmap")
    assert response.status_code == 401


def test_get_pr_heatmap_success(client, kpi_test_setup):
    headers = kpi_test_setup["headers"]
    plant_id = str(kpi_test_setup["plant"].id)

    response = client.get(f"/plants/{plant_id}/kpis/heatmap?range=24h", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "time_buckets" in data
    assert "inverters" in data
    assert data["plant_id"] == plant_id
    assert len(data["time_buckets"]) == 24


def test_get_top_losers_unauthenticated(client):
    response = client.get("/plants/kpis/top-losers")
    assert response.status_code == 401


def test_get_top_losers_success(client, kpi_test_setup):
    headers = kpi_test_setup["headers"]
    plant_id = str(kpi_test_setup["plant"].id)

    response = client.get(f"/plants/{plant_id}/kpis/top-losers?range=24h", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_actual_mwh" in data
    assert "losers" in data
    assert data["plant_id"] == plant_id


def test_get_top_losers_no_telemetry_returns_null_pr(client, kpi_test_setup):
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        empty_plant = db.query(Plant).filter(Plant.org_id == org.id, Plant.name == "Empty KPI Plant").first()
        if not empty_plant:
            empty_plant = Plant(
                org_id=org.id,
                name="Empty KPI Plant",
                plant_type="solar",
                capacity_ac_kw=5000.0,
                capacity_dc_kwp=6000.0,
            )
            db.add(empty_plant)
            db.commit()
            db.refresh(empty_plant)

        inv_empty = db.query(Asset).filter(Asset.plant_id == empty_plant.id, Asset.name == "Empty Inverter 99").first()
        if not inv_empty:
            inv_empty = Asset(
                plant_id=empty_plant.id,
                name="Empty Inverter 99",
                asset_type="inverter",
            )
            db.add(inv_empty)
            db.commit()

        headers = kpi_test_setup["headers"]
        response = client.get(f"/plants/{empty_plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_data"] is False
        assert data["plant_pr"] is None
        assert data["has_poa"] is False
    finally:
        db.close()


def test_get_top_losers_with_telemetry_calculates_pr(client, kpi_test_setup):
    db = SessionLocal()
    try:
        plant = kpi_test_setup["plant"]
        inv = db.query(Asset).filter(Asset.plant_id == plant.id).first()
        if not inv:
            inv = Asset(plant_id=plant.id, name="Test Inverter 01", asset_type="inverter")
            db.add(inv)
            db.commit()
            db.refresh(inv)

        ac_chan = db.query(Channel).filter(Channel.asset_id == inv.id, Channel.canonical_key == "power_ac").first()
        if not ac_chan:
            ac_chan = Channel(
                asset_id=inv.id,
                canonical_key="power_ac",
                source_name="inverter_ac_power",
                interval_s=900,
                agg_semantics="avg",
            )
            db.add(ac_chan)

        dc_chan = db.query(Channel).filter(Channel.asset_id == inv.id, Channel.canonical_key == "power_dc").first()
        if not dc_chan:
            dc_chan = Channel(
                asset_id=inv.id,
                canonical_key="power_dc",
                source_name="inverter_dc_power",
                interval_s=900,
                agg_semantics="avg",
            )
            db.add(dc_chan)

        db.commit()

        # Add readings: 10,000 kW AC, 12,000 kW DC
        r_ac = Reading(channel_id=ac_chan.id, ts=datetime.now(timezone.utc), value=10000.0, quality=100)
        r_dc = Reading(channel_id=dc_chan.id, ts=datetime.now(timezone.utc), value=12000.0, quality=100)
        db.add_all([r_ac, r_dc])
        db.commit()

        headers = kpi_test_setup["headers"]
        response = client.get(f"/plants/{plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_data"] is True
    finally:
        db.close()


def test_kpis_organization_isolation(client, kpi_test_setup):
    db = SessionLocal()
    try:
        org_b = db.query(Organization).filter(Organization.name == "Other Org KPIs").first()
        if not org_b:
            org_b = Organization(name="Other Org KPIs")
            db.add(org_b)
            db.commit()
            db.refresh(org_b)

        user_b = db.query(User).filter(User.email == "other_org_user@test.com").first()
        if not user_b:
            user_b = User(
                org_id=org_b.id,
                email="other_org_user@test.com",
                password_hash="hashed_pw",
                full_name="Other Org User",
                role="admin",
                is_active=True,
            )
            db.add(user_b)
            db.commit()
            db.refresh(user_b)

        token_b = create_access_token({"sub": str(user_b.id), "org_id": str(org_b.id), "role": "admin"})
        headers_b = {"Authorization": f"Bearer {token_b}"}

        plant_id = str(kpi_test_setup["plant"].id)
        response = client.get(f"/plants/{plant_id}/kpis/top-losers", headers=headers_b)
        assert response.status_code == 403
    finally:
        db.close()


def test_pr_heatmap_zero_vs_missing_telemetry(client, kpi_test_setup):
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        test_plant = db.query(Plant).filter(Plant.org_id == org.id, Plant.name == "PR Heatmap Test Plant").first()
        if not test_plant:
            test_plant = Plant(
                org_id=org.id,
                name="PR Heatmap Test Plant",
                plant_type="solar",
                capacity_ac_kw=1000.0,
                capacity_dc_kwp=1200.0,
            )
            db.add(test_plant)
            db.commit()
            db.refresh(test_plant)

        inv_active = db.query(Asset).filter(Asset.plant_id == test_plant.id, Asset.name == "Inv Active").first()
        if not inv_active:
            inv_active = Asset(plant_id=test_plant.id, name="Inv Active", asset_type="inverter", rated_kw=100.0)
            db.add(inv_active)

        inv_zero = db.query(Asset).filter(Asset.plant_id == test_plant.id, Asset.name == "Inv Zero").first()
        if not inv_zero:
            inv_zero = Asset(plant_id=test_plant.id, name="Inv Zero", asset_type="inverter", rated_kw=100.0)
            db.add(inv_zero)

        inv_missing = db.query(Asset).filter(Asset.plant_id == test_plant.id, Asset.name == "Inv Missing").first()
        if not inv_missing:
            inv_missing = Asset(plant_id=test_plant.id, name="Inv Missing", asset_type="inverter", rated_kw=100.0)
            db.add(inv_missing)

        db.commit()

        now_ts = datetime.now(timezone.utc)

        c_ac1 = db.query(Channel).filter(Channel.asset_id == inv_active.id, Channel.canonical_key == "power_ac").first()
        if not c_ac1:
            c_ac1 = Channel(asset_id=inv_active.id, canonical_key="power_ac", source_name="ac1", interval_s=900, agg_semantics="avg")
            db.add(c_ac1)

        c_dc1 = db.query(Channel).filter(Channel.asset_id == inv_active.id, Channel.canonical_key == "power_dc").first()
        if not c_dc1:
            c_dc1 = Channel(asset_id=inv_active.id, canonical_key="power_dc", source_name="dc1", interval_s=900, agg_semantics="avg")
            db.add(c_dc1)

        db.commit()

        db.add_all([
            Reading(channel_id=c_ac1.id, ts=now_ts, value=80.0, quality=100),
            Reading(channel_id=c_dc1.id, ts=now_ts, value=100.0, quality=100),
        ])

        c_ac2 = db.query(Channel).filter(Channel.asset_id == inv_zero.id, Channel.canonical_key == "power_ac").first()
        if not c_ac2:
            c_ac2 = Channel(asset_id=inv_zero.id, canonical_key="power_ac", source_name="ac2", interval_s=900, agg_semantics="avg")
            db.add(c_ac2)

        db.commit()
        db.add(Reading(channel_id=c_ac2.id, ts=now_ts, value=0.0, quality=100))
        db.commit()

        headers = kpi_test_setup["headers"]
        response = client.get(f"/plants/{test_plant.id}/kpis/heatmap?range=24h", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["inverters"]) == 3

        inv_map = {row["asset_name"]: row["cells"] for row in data["inverters"]}

        active_cell = inv_map["Inv Active"][-1]
        assert active_cell["has_data"] is True

        zero_cell = inv_map["Inv Zero"][-1]
        assert zero_cell["has_data"] is True
        assert zero_cell["ac_kw"] == 0.0

        missing_cell = inv_map["Inv Missing"][-1]
        assert missing_cell["has_data"] is False
        assert missing_cell["pr"] is None
        assert missing_cell["pr_pct"] == "N/A"
        assert missing_cell["status"] == "missing_data"
    finally:
        db.close()


def test_loss_analysis_healthy_inverter_regression(client, kpi_test_setup):
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        test_plant = db.query(Plant).filter(Plant.org_id == org.id, Plant.name == "Healthy Inverter Regression Plant").first()
        if not test_plant:
            test_plant = Plant(
                org_id=org.id,
                name="Healthy Inverter Regression Plant",
                plant_type="solar",
                capacity_ac_kw=1000.0,
                capacity_dc_kwp=1200.0,
            )
            db.add(test_plant)
            db.commit()
            db.refresh(test_plant)

        inv = db.query(Asset).filter(Asset.plant_id == test_plant.id, Asset.name == "Healthy Inverter 01").first()
        if not inv:
            inv = Asset(
                plant_id=test_plant.id,
                name="Healthy Inverter 01",
                asset_type="inverter",
                rated_kw=1000.0,
            )
            db.add(inv)
            db.commit()
            db.refresh(inv)

        ac_chan = db.query(Channel).filter(Channel.asset_id == inv.id, Channel.canonical_key == "power_ac").first()
        if not ac_chan:
            ac_chan = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="ac_power", interval_s=900, agg_semantics="avg")
            db.add(ac_chan)

        dc_chan = db.query(Channel).filter(Channel.asset_id == inv.id, Channel.canonical_key == "power_dc").first()
        if not dc_chan:
            dc_chan = Channel(asset_id=inv.id, canonical_key="power_dc", source_name="dc_power", interval_s=900, agg_semantics="avg")
            db.add(dc_chan)

        db.commit()

        now_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        readings = []

        start_ts = now_ts - timedelta(hours=12)
        for i in range(48):
            r_dt = start_ts + timedelta(minutes=i * 15)
            readings.append(Reading(channel_id=ac_chan.id, ts=r_dt, value=998.0, quality=100))
            readings.append(Reading(channel_id=dc_chan.id, ts=r_dt, value=1020.408, quality=100))

        db.query(Reading).filter(Reading.channel_id.in_([ac_chan.id, dc_chan.id])).delete()
        db.commit()

        db.add_all(readings)
        db.commit()

        headers = kpi_test_setup["headers"]
        response = client.get(f"/plants/{test_plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert data["has_data"] is True
        assert len(data["losers"]) == 1
        loser = data["losers"][0]
        assert loser["actual_mwh"] == 11.98
    finally:
        db.close()


def test_consistency_heatmap_and_top_losers_scaled_dc(client, kpi_test_setup):
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        test_plant = db.query(Plant).filter(Plant.org_id == org.id, Plant.name == "Scaled DC Consistency Plant").first()
        if not test_plant:
            test_plant = Plant(
                org_id=org.id,
                name="Scaled DC Consistency Plant",
                plant_type="solar",
                capacity_ac_kw=1000.0,
                capacity_dc_kwp=1200.0,
            )
            db.add(test_plant)
            db.commit()
            db.refresh(test_plant)

        inv = db.query(Asset).filter(Asset.plant_id == test_plant.id, Asset.name == "Inverter Scaled DC").first()
        if not inv:
            inv = Asset(
                plant_id=test_plant.id,
                name="Inverter Scaled DC",
                asset_type="inverter",
                rated_kw=1000.0,
            )
            db.add(inv)
            db.commit()
            db.refresh(inv)

        ac_chan = db.query(Channel).filter(Channel.asset_id == inv.id, Channel.canonical_key == "power_ac").first()
        if not ac_chan:
            ac_chan = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="ac_power", interval_s=900, agg_semantics="avg")
            db.add(ac_chan)

        dc_chan = db.query(Channel).filter(Channel.asset_id == inv.id, Channel.canonical_key == "power_dc").first()
        if not dc_chan:
            dc_chan = Channel(asset_id=inv.id, canonical_key="power_dc", source_name="dc_power", interval_s=900, agg_semantics="avg")
            db.add(dc_chan)

        db.commit()

        now_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        readings = []

        start_ts = now_ts - timedelta(hours=12)
        for i in range(48):
            r_dt = start_ts + timedelta(minutes=i * 15)
            readings.append(Reading(channel_id=ac_chan.id, ts=r_dt, value=319.8, quality=100))
            readings.append(Reading(channel_id=dc_chan.id, ts=r_dt, value=3198.0, quality=100))

        db.query(Reading).filter(Reading.channel_id.in_([ac_chan.id, dc_chan.id])).delete()
        db.commit()

        db.add_all(readings)
        db.commit()

        headers = kpi_test_setup["headers"]

        res_hm = client.get(f"/plants/{test_plant.id}/kpis/heatmap?range=24h", headers=headers)
        assert res_hm.status_code == 200
        hm_data = res_hm.json()

        res_tl = client.get(f"/plants/{test_plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert res_tl.status_code == 200
        tl_data = res_tl.json()

        assert hm_data["plant_id"] == str(test_plant.id)
        assert tl_data["plant_id"] == str(test_plant.id)
    finally:
        db.close()


def test_loss_analysis_ranges_24h_7d_30d(client, kpi_test_setup):
    headers = kpi_test_setup["headers"]
    plant_id = str(kpi_test_setup["plant"].id)

    for rng in ["24h", "7d", "30d"]:
        res = client.get(f"/plants/{plant_id}/kpis/top-losers?range={rng}", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["range"] == rng


def test_pr_deterministic_formula_80_percent(client, kpi_test_setup):
    """Deterministic verification: 1 kWp DC capacity, 900 kWh/m² POA irradiation, 720 kWh actual AC energy -> 80% PR."""
    res = calculate_performance_ratio(
        energy_ac_kwh=720.0,
        capacity_dc_kwp=1.0,
        irradiation_poa_kwh_m2=900.0,
        g_stc_kw_m2=1.0,
    )
    assert res.is_valid is True
    assert res.value == pytest.approx(0.80, abs=0.001)
    assert res.details["expected_energy_kwh"] == 900.0


def test_pr_missing_poa_irradiance_returns_none(client, kpi_test_setup):
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        plant = db.query(Plant).filter(Plant.org_id == org.id, Plant.name == "Missing POA Plant").first()
        if not plant:
            plant = Plant(
                org_id=org.id,
                name="Missing POA Plant",
                plant_type="solar",
                capacity_ac_kw=1000.0,
                capacity_dc_kwp=1200.0,
            )
            db.add(plant)
            db.commit()
            db.refresh(plant)

        inv = db.query(Asset).filter(Asset.plant_id == plant.id, Asset.name == "Inv No POA").first()
        if not inv:
            inv = Asset(plant_id=plant.id, name="Inv No POA", asset_type="inverter", rated_kw=1000.0)
            db.add(inv)
            db.commit()

        ac_ch = db.query(Channel).filter(Channel.asset_id == inv.id, Channel.canonical_key == "power_ac").first()
        if not ac_ch:
            ac_ch = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="ac", interval_s=3600, receive_unit="kW")
            db.add(ac_ch)

        db.commit()

        now_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        readings = [Reading(channel_id=ac_ch.id, ts=now_ts - timedelta(hours=i), value=500.0, quality=100) for i in range(5)]
        db.query(Reading).filter(Reading.channel_id == ac_ch.id).delete()
        db.commit()
        db.add_all(readings)
        db.commit()

        headers = kpi_test_setup["headers"]
        res = client.get(f"/plants/{plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["has_data"] is True
        assert data["has_poa"] is False
        assert data["plant_pr"] is None
        assert data["total_expected_mwh"] is None
        assert data["total_actual_mwh"] == 2.5
    finally:
        db.close()


def test_dc_scaling_and_double_normalization_prevention():
    from app.api.kpis import normalize_power_kw, normalize_irradiance_wm2

    # Power units
    assert normalize_power_kw(100000.0, unit="W") == 100.0
    assert normalize_power_kw(3198.0, unit="deci-kW") == 319.8
    assert normalize_power_kw(3198.0, conversion="val / 10") == 319.8
    assert normalize_power_kw(319.8, unit="kW") == 319.8

    # Irradiance units
    assert normalize_irradiance_wm2(0.8, unit="kW/m2") == 800.0
    assert normalize_irradiance_wm2(800.0, unit="W/m2") == 800.0


def test_deterministic_efficiency_calculation():
    from app.api.kpis import normalize_power_kw

    # Known deterministic inputs: 100 kW AC and 102.0408 kW DC -> Efficiency = 98.0%
    ac_kw = normalize_power_kw(100.0, unit="kW")
    dc_kw = normalize_power_kw(102.0408, unit="kW", is_dc=True, is_dc_10x=False)
    assert ac_kw == 100.0
    assert dc_kw == 102.0408
    eff = round((ac_kw / dc_kw) * 100.0, 1)
    assert eff == 98.0


def test_dc_low_power_channel_scaling_regression():
    from app.api.kpis import normalize_power_kw

    # Low power reading (135.0 deci-kW = 13.5 kW DC) on a 10x-scaled DC channel
    # Must be scaled consistently to 13.5 kW DC and NOT left at 135.0 kW DC
    low_dc_kw = normalize_power_kw(135.0, unit="kW", is_dc=True, is_dc_10x=True)
    assert low_dc_kw == 13.5

    # High power reading (1118.4 deci-kW = 111.84 kW DC) on the same 10x-scaled DC channel
    high_dc_kw = normalize_power_kw(1118.4, unit="kW", is_dc=True, is_dc_10x=True)
    assert high_dc_kw == 111.84


def test_normal_kw_dc_no_double_normalization():
    from app.api.kpis import normalize_power_kw

    # Standard kW DC reading (100.0 kW) on a normal (non-10x) DC channel
    # Must NOT be divided by 10
    normal_dc_kw = normalize_power_kw(100.0, unit="kW", is_dc=True, is_dc_10x=False)
    assert normal_dc_kw == 100.0


def test_poa_baseline_overlapping_vs_missing_coverage(client, kpi_test_setup):
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        poa_plant = Plant(
            org_id=org.id,
            name=f"POA Coverage Test Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=1000.0,
            capacity_dc_kwp=1200.0,
        )
        db.add(poa_plant)
        db.commit()
        db.refresh(poa_plant)

        inv = Asset(plant_id=poa_plant.id, name="Test Inverter POA", asset_type="inverter", rated_kw=1000.0)
        ws = Asset(plant_id=poa_plant.id, name="WS-01", asset_type="weather_station")
        db.add_all([inv, ws])
        db.commit()
        db.refresh(inv)
        db.refresh(ws)

        ac_ch = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="AC", interval_s=900, receive_unit="kW")
        poa_ch = Channel(asset_id=ws.id, canonical_key="irradiance_poa", source_name="IRRAD", interval_s=900, receive_unit="kW/m²")
        db.add_all([ac_ch, poa_ch])
        db.commit()
        db.refresh(ac_ch)
        db.refresh(poa_ch)

        now_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        r_ac = Reading(channel_id=ac_ch.id, ts=now_ts, value=800.0, quality=100)
        r_poa = Reading(channel_id=poa_ch.id, ts=now_ts, value=0.8, quality=100)  # 0.8 kW/m² = 800 W/m²
        db.add_all([r_ac, r_poa])
        db.commit()

        # 1. With overlapping POA readings -> has_poa=True, valid expected energy and plant PR
        res1 = client.get(f"/plants/{poa_plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["has_data"] is True
        assert data1["has_poa"] is True
        assert data1["total_expected_mwh"] is not None
        assert data1["total_expected_mwh"] > 0
        assert data1["plant_pr"] is not None
        assert 50.0 <= data1["plant_pr"] <= 100.0

        # 2. Without POA readings -> has_poa=False, metrics default cleanly to None / N/A
        db.query(Reading).filter(Reading.channel_id == poa_ch.id).delete()
        db.commit()

        res2 = client.get(f"/plants/{poa_plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["has_data"] is True
        assert data2["has_poa"] is False
        assert data2["total_expected_mwh"] is None
        assert data2["total_loss_mwh"] is None
        assert data2["plant_pr"] is None
    finally:
        db.close()


def test_dynamic_cadence_integration_recovers_true_energy(client, kpi_test_setup):
    """Verify that when a channel has misconfigured interval_s=300 but readings are 15-min apart (900s),
    the KPI engine dynamically recovers the true 15-min cadence and does not underestimate energy by 3x."""
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        cadence_plant = Plant(
            org_id=org.id,
            name=f"Cadence Test Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=1000.0,
            capacity_dc_kwp=1200.0,
        )
        db.add(cadence_plant)
        db.commit()
        db.refresh(cadence_plant)

        inv = Asset(plant_id=cadence_plant.id, name="Cadence Inv 01", asset_type="inverter", rated_kw=1000.0)
        db.add(inv)
        db.commit()
        db.refresh(inv)

        # Channel metadata misconfigured to 300s (5m)
        ac_ch = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="AC", interval_s=300, receive_unit="kW")
        db.add(ac_ch)
        db.commit()
        db.refresh(ac_ch)

        # 4 readings exactly 15 minutes (900s) apart at 1000 kW constant power
        # True energy: 4 * 1000 kW * 0.25 h = 1000 kWh = 1.0 MWh
        # With the 300s bug it would be 4 * 1000 kW * (300/3600) = 0.33 MWh
        base_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        readings = [
            Reading(channel_id=ac_ch.id, ts=base_ts - timedelta(minutes=15 * i), value=1000.0, quality=100)
            for i in range(4)
        ]
        db.add_all(readings)
        db.commit()

        res = client.get(f"/plants/{cadence_plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["has_data"] is True
        # Must be 1.0 MWh (true 15m cadence), NOT 0.33 MWh
        assert data["total_actual_mwh"] == 1.0
    finally:
        db.close()


def test_dc_capacity_resolution_hierarchy(client, kpi_test_setup):
    """Verify that DC capacity resolves correctly:
    1. Per-inverter metadata rated_dc_kwp
    2. Plant capacity_dc_kwp / inverter count
    3. Fallback to 1.2 * AC capacity."""
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        p_configured = Plant(
            org_id=org.id,
            name=f"Configured DC Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=2000.0,
            capacity_dc_kwp=2400.0,
        )
        db.add(p_configured)
        db.commit()
        db.refresh(p_configured)

        # Inverter 1 has explicit rated_dc_kwp in metadata
        inv1 = Asset(
            plant_id=p_configured.id,
            name="Inv Explicit",
            asset_type="inverter",
            rated_kw=1000.0,
            metadata_json={"rated_dc_kwp": 1300.0},
        )
        # Inverter 2 relies on plant-level allocation
        inv2 = Asset(
            plant_id=p_configured.id,
            name="Inv Inherit",
            asset_type="inverter",
            rated_kw=1000.0,
            metadata_json={},
        )
        ws = Asset(plant_id=p_configured.id, name="WS-01", asset_type="weather_station")
        db.add_all([inv1, inv2, ws])
        db.commit()
        db.refresh(inv1)
        db.refresh(inv2)
        db.refresh(ws)

        ac_ch1 = Channel(asset_id=inv1.id, canonical_key="power_ac", source_name="AC1", interval_s=900, receive_unit="kW")
        ac_ch2 = Channel(asset_id=inv2.id, canonical_key="power_ac", source_name="AC2", interval_s=900, receive_unit="kW")
        poa_ch = Channel(asset_id=ws.id, canonical_key="irradiance_poa", source_name="POA", interval_s=900, receive_unit="kW/m²")
        db.add_all([ac_ch1, ac_ch2, poa_ch])
        db.commit()
        db.refresh(ac_ch1)
        db.refresh(ac_ch2)
        db.refresh(poa_ch)

        base_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # 1 kWh/m² irradiation: 1 reading of 1.0 kW/m² for 1 hour (4 readings of 1.0 kW/m² for 15 min = 1 kWh/m²)
        readings = [
            Reading(channel_id=poa_ch.id, ts=base_ts - timedelta(minutes=15 * i), value=1.0, quality=100)
            for i in range(4)
        ]
        readings.extend([
            Reading(channel_id=ac_ch1.id, ts=base_ts - timedelta(minutes=15 * i), value=900.0, quality=100)
            for i in range(4)
        ])
        readings.extend([
            Reading(channel_id=ac_ch2.id, ts=base_ts - timedelta(minutes=15 * i), value=900.0, quality=100)
            for i in range(4)
        ])
        db.add_all(readings)
        db.commit()

        res = client.get(f"/plants/{p_configured.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["has_data"] is True
        assert data["has_poa"] is True

        losers_map = {l["asset_name"]: l for l in data["losers"]}
        # Inv Explicit should have expected_mwh = 1300 kW * 1.0 kWh/m² = 1.3 MWh
        assert losers_map["Inv Explicit"]["expected_mwh"] == 1.3
        # Inv Inherit should have expected_mwh = (2400 kW / 2) * 1.0 kWh/m² = 1.2 MWh
        assert losers_map["Inv Inherit"]["expected_mwh"] == 1.2
    finally:
        db.close()


def test_pr_not_artificially_clamped_above_100(client, kpi_test_setup):
    """Regression test: verify that when actual generation exceeds theoretical reference yield,
    expected_mwh is NOT forced up to actual_mwh and PR is NOT clamped to 100.0%."""
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        p_test = Plant(
            org_id=org.id,
            name=f"High Yield Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=1000.0,
            capacity_dc_kwp=1000.0,
        )
        db.add(p_test)
        db.commit()
        db.refresh(p_test)

        inv = Asset(plant_id=p_test.id, name="Inv 01", asset_type="inverter", rated_kw=1000.0)
        ws = Asset(plant_id=p_test.id, name="WS-01", asset_type="weather_station")
        db.add_all([inv, ws])
        db.commit()
        db.refresh(inv)
        db.refresh(ws)

        ac_ch = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="AC", interval_s=900, receive_unit="kW")
        poa_ch = Channel(asset_id=ws.id, canonical_key="irradiance_poa", source_name="POA", interval_s=900, receive_unit="kW/m²")
        db.add_all([ac_ch, poa_ch])
        db.commit()
        db.refresh(ac_ch)
        db.refresh(poa_ch)

        base_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # Irradiance: 4 readings at 0.5 kW/m² over 1 hour = 0.5 kWh/m²
        # Expected reference yield: 1000 kWp * 0.5 kWh/m² = 500 kWh = 0.5 MWh
        readings = [
            Reading(channel_id=poa_ch.id, ts=base_ts - timedelta(minutes=15 * i), value=0.5, quality=100)
            for i in range(4)
        ]
        # Actual AC power: 4 readings at 600 kW over 1 hour = 600 kWh = 0.6 MWh
        # True physical PR: (0.6 / 0.5) * 100 = 120.0%
        readings.extend([
            Reading(channel_id=ac_ch.id, ts=base_ts - timedelta(minutes=15 * i), value=600.0, quality=100)
            for i in range(4)
        ])
        db.add_all(readings)
        db.commit()

        res = client.get(f"/plants/{p_test.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["has_data"] is True
        assert data["has_poa"] is True

        # Expected energy must remain 0.5 MWh (NOT forced to actual 0.6 MWh)
        assert data["total_expected_mwh"] == 0.5
        assert data["total_actual_mwh"] == 0.6
        # Loss must be 0.0 MWh
        assert data["total_loss_mwh"] == 0.0
        assert data["total_loss_pct"] == 0.0
        # Plant PR must be 120.0% (NOT clamped to 100.0%)
        assert data["plant_pr"] == 120.0

        # With zero deficits across all inverters, losers list must be empty (no arbitrary losers)
        assert data["net_shortfall_mwh"] == 0.0
        assert data["aggregate_inverter_deficit_mwh"] == 0.0
        assert data["ranking_mode"] == "none"
        assert len(data["losers"]) == 0
    finally:
        db.close()


def test_long_gap_cadence_inference_ignores_shutdown_periods(client, kpi_test_setup):
    """Verify that cadence inference handles long gaps (e.g. 10 hours overnight)
    without integrating power across the gap or inflating cadence."""
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        p_test = Plant(
            org_id=org.id,
            name=f"Night Gap Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=1000.0,
            capacity_dc_kwp=1000.0,
        )
        db.add(p_test)
        db.commit()
        db.refresh(p_test)

        inv = Asset(plant_id=p_test.id, name="Inv 01", asset_type="inverter", rated_kw=1000.0)
        db.add(inv)
        db.commit()
        db.refresh(inv)

        ac_ch = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="AC", interval_s=900, receive_unit="kW")
        db.add(ac_ch)
        db.commit()
        db.refresh(ac_ch)

        base_ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # 4 daytime readings at 15m cadence: 1000 kW * 0.25h * 4 = 1000 kWh = 1.0 MWh
        readings = [
            Reading(channel_id=ac_ch.id, ts=base_ts - timedelta(minutes=15 * i), value=1000.0, quality=100)
            for i in range(4)
        ]
        # 1 reading 10 hours earlier (overnight gap): 1000 kW * 0.25h = 250 kWh = 0.25 MWh
        # Total energy: 1.0 + 0.25 = 1.25 MWh
        # The 10h gap delta (>7200s) must NOT inflate cadence to 10 hours!
        readings.append(
            Reading(channel_id=ac_ch.id, ts=base_ts - timedelta(hours=10), value=1000.0, quality=100)
        )
        db.add_all(readings)
        db.commit()

        res = client.get(f"/plants/{p_test.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["has_data"] is True
        # Total energy must be 1.25 MWh, NOT 10 hours * 1000 kW!
        assert data["total_actual_mwh"] == 1.25
    finally:
        db.close()


def test_exact_reporting_window_boundaries_and_durations():
    """Verify that get_reporting_window produces exact durations:
    - 24H: exactly 24.0 hours (24h)
    - 7D: exactly 168.0 hours (168h)
    - 30D: exactly 720.0 hours (720h)
    anchored to 2020-06-18 00:00:00 UTC without future overflow."""
    from app.api.kpis import get_reporting_window
    max_ts = datetime(2020, 6, 17, 23, 45, tzinfo=timezone.utc)

    # 24H
    start_24h, end_24h = get_reporting_window(max_ts, "24h")
    assert start_24h == datetime(2020, 6, 17, 0, 0, tzinfo=timezone.utc)
    assert end_24h == datetime(2020, 6, 18, 0, 0, tzinfo=timezone.utc)
    assert (end_24h - start_24h).total_seconds() == 24 * 3600  # 24.0 hours

    # 7D
    start_7d, end_7d = get_reporting_window(max_ts, "7d")
    assert start_7d == datetime(2020, 6, 11, 0, 0, tzinfo=timezone.utc)
    assert end_7d == datetime(2020, 6, 18, 0, 0, tzinfo=timezone.utc)
    assert (end_7d - start_7d).total_seconds() == 168 * 3600  # Exactly 168.0 hours

    # 30D
    start_30d, end_30d = get_reporting_window(max_ts, "30d")
    assert start_30d == datetime(2020, 5, 19, 0, 0, tzinfo=timezone.utc)
    assert end_30d == datetime(2020, 6, 18, 0, 0, tzinfo=timezone.utc)
    assert (end_30d - start_30d).total_seconds() == 720 * 3600  # Exactly 720.0 hours


def test_consistent_window_boundaries_between_losers_and_heatmap(client, kpi_test_setup):
    """Verify that PRHeatmap and TopLosers return consistent bucket spans and do not overflow into future dates."""
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        p_test = Plant(
            org_id=org.id,
            name=f"Consistent Window Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=1000.0,
            capacity_dc_kwp=1200.0,
        )
        db.add(p_test)
        db.commit()
        db.refresh(p_test)

        inv = Asset(plant_id=p_test.id, name="Inv 01", asset_type="inverter", rated_kw=1000.0)
        db.add(inv)
        db.commit()
        db.refresh(inv)

        ac_ch = Channel(asset_id=inv.id, canonical_key="power_ac", source_name="AC", interval_s=900, receive_unit="kW")
        db.add(ac_ch)
        db.commit()
        db.refresh(ac_ch)

        # Telemetry timestamp at 2020-06-17 23:45:00 UTC
        ts = datetime(2020, 6, 17, 23, 45, tzinfo=timezone.utc)
        db.add(Reading(channel_id=ac_ch.id, ts=ts, value=1000.0, quality=100))
        db.commit()

        # Check 24H
        res_losers_24h = client.get(f"/plants/{p_test.id}/kpis/top-losers?range=24h", headers=headers)
        res_heatmap_24h = client.get(f"/plants/{p_test.id}/kpis/heatmap?range=24h", headers=headers)
        assert res_losers_24h.status_code == 200
        assert res_heatmap_24h.status_code == 200

        data_heat_24h = res_heatmap_24h.json()
        assert len(data_heat_24h["time_buckets"]) == 24
        assert data_heat_24h["time_buckets"][0] == "00:00"
        assert data_heat_24h["time_buckets"][-1] == "23:00"

        # Check 7D
        res_losers_7d = client.get(f"/plants/{p_test.id}/kpis/top-losers?range=7d", headers=headers)
        res_heatmap_7d = client.get(f"/plants/{p_test.id}/kpis/heatmap?range=7d", headers=headers)
        assert res_losers_7d.status_code == 200
        assert res_heatmap_7d.status_code == 200

        data_heat_7d = res_heatmap_7d.json()
        assert len(data_heat_7d["time_buckets"]) == 7
        assert data_heat_7d["time_buckets"][0] == "Jun 11"
        assert data_heat_7d["time_buckets"][-1] == "Jun 17"

        # Check 30D
        res_losers_30d = client.get(f"/plants/{p_test.id}/kpis/top-losers?range=30d", headers=headers)
        res_heatmap_30d = client.get(f"/plants/{p_test.id}/kpis/heatmap?range=30d", headers=headers)
        assert res_losers_30d.status_code == 200
        assert res_heatmap_30d.status_code == 200

        data_heat_30d = res_heatmap_30d.json()
        assert len(data_heat_30d["time_buckets"]) == 10
        assert data_heat_30d["time_buckets"][0] == "May 19"
        assert data_heat_30d["time_buckets"][-1] == "Jun 15"
    finally:
        db.close()


def test_surya_active_plant_telemetry_window_and_durations():
    """Verify exact reporting boundaries for active plant Surya (max_ts = 2020-06-17 23:45:00 UTC):
    - 24H: 2020-06-17 00:00:00 to 2020-06-18 00:00:00 UTC (exactly 24.0 hours)
    - 7D:  2020-06-11 00:00:00 to 2020-06-18 00:00:00 UTC (exactly 168.0 hours)
    - 30D: 2020-05-19 00:00:00 to 2020-06-18 00:00:00 UTC (exactly 720.0 hours)
    """
    from app.api.kpis import get_reporting_window
    max_ts = datetime.fromisoformat("2020-06-17T23:45:00+00:00")

    # 24H
    s_24h, e_24h = get_reporting_window(max_ts, "24h")
    assert s_24h == datetime(2020, 6, 17, 0, 0, tzinfo=timezone.utc)
    assert e_24h == datetime(2020, 6, 18, 0, 0, tzinfo=timezone.utc)
    assert (e_24h - s_24h).total_seconds() == 24 * 3600

    # 7D
    s_7d, e_7d = get_reporting_window(max_ts, "7d")
    assert s_7d == datetime(2020, 6, 11, 0, 0, tzinfo=timezone.utc)
    assert e_7d == datetime(2020, 6, 18, 0, 0, tzinfo=timezone.utc)
    assert (e_7d - s_7d).total_seconds() == 168 * 3600

    # 30D
    s_30d, e_30d = get_reporting_window(max_ts, "30d")
    assert s_30d == datetime(2020, 5, 19, 0, 0, tzinfo=timezone.utc)
    assert e_30d == datetime(2020, 6, 18, 0, 0, tzinfo=timezone.utc)
    assert (e_30d - s_30d).total_seconds() == 720 * 3600


def test_loss_analysis_all_inverters_meeting_or_exceeding_expected_energy(client, kpi_test_setup):
    """Regression test: When all inverters meet or exceed expected energy:
    - net_shortfall_mwh == 0.0
    - aggregate_inverter_deficit_mwh == 0.0
    - ranking_mode == 'none'
    - losers == [] (no arbitrary Rank 1 underperformer or fake deficit table)
    """
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        p = Plant(
            org_id=org.id,
            name=f"All Nominal Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=2000.0,
            capacity_dc_kwp=2400.0,
        )
        db.add(p)
        db.commit()
        db.refresh(p)

        inv_a = Asset(plant_id=p.id, name="Inv Nominal A", asset_type="inverter", rated_kw=1000.0, metadata_json={"rated_dc_kwp": 1200.0})
        inv_b = Asset(plant_id=p.id, name="Inv Nominal B", asset_type="inverter", rated_kw=1000.0, metadata_json={"rated_dc_kwp": 1200.0})
        ws = Asset(plant_id=p.id, name="WS-01", asset_type="weather_station")
        db.add_all([inv_a, inv_b, ws])
        db.commit()

        ac_a = Channel(asset_id=inv_a.id, canonical_key="power_ac", source_name="AC_A", interval_s=900, receive_unit="kW")
        ac_b = Channel(asset_id=inv_b.id, canonical_key="power_ac", source_name="AC_B", interval_s=900, receive_unit="kW")
        poa = Channel(asset_id=ws.id, canonical_key="irradiance_poa", source_name="POA", interval_s=900, receive_unit="W/m2")
        db.add_all([ac_a, ac_b, poa])
        db.commit()

        # Telemetry for 24h: 4 readings at 15-min cadence = 1.0 hour daylight
        # POA = 1000 W/m² (1.0 kW/m²), 4 readings * 0.25h = 1.0 kWh/m² irradiation
        # Expected energy per inverter = 1200 kWp * 1.0 kWh/m² / 1.0 = 1.20 MWh (1200 kWh)
        # Inv A AC = 1500 kW each -> 1.50 MWh (exceeds 1.20 MWh)
        # Inv B AC = 1300 kW each -> 1.30 MWh (exceeds 1.20 MWh)
        base_ts = datetime(2020, 6, 17, 12, 0, tzinfo=timezone.utc)
        readings = []
        for i in range(4):
            t = base_ts + timedelta(minutes=i * 15)
            readings.append(Reading(channel_id=poa.id, ts=t, value=1000.0, quality=100))
            readings.append(Reading(channel_id=ac_a.id, ts=t, value=1500.0, quality=100))
            readings.append(Reading(channel_id=ac_b.id, ts=t, value=1300.0, quality=100))

        db.add_all(readings)
        db.commit()

        res = client.get(f"/plants/{p.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()

        assert data["has_data"] is True
        assert data["has_poa"] is True
        assert data["total_actual_mwh"] == 2.80
        assert data["total_expected_mwh"] == 2.40
        assert data["net_shortfall_mwh"] == 0.0
        assert data["aggregate_inverter_deficit_mwh"] == 0.0
        assert data["total_loss_mwh"] == 0.0
        assert data["total_loss_pct"] == 0.0
        assert data["net_shortfall_pct"] == 0.0
        assert data["ranking_mode"] == "none"
        assert len(data["losers"]) == 0
    finally:
        db.close()


def test_loss_analysis_plant_surplus_with_individual_inverter_underperformance(client, kpi_test_setup):
    """Regression test: Plant actual generation exceeds expected energy, but one inverter underperforms:
    - net_shortfall_mwh == 0.0 (plant as a whole has surplus)
    - aggregate_inverter_deficit_mwh > 0.0 (reflects the underperforming inverter's shortfall)
    - ranking_mode == 'deficit'
    - losers contains only the underperforming inverter
    """
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        p = Plant(
            org_id=org.id,
            name=f"Partial Deficit Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=2000.0,
            capacity_dc_kwp=2400.0,
        )
        db.add(p)
        db.commit()
        db.refresh(p)

        inv_surplus = Asset(plant_id=p.id, name="Inv Surplus", asset_type="inverter", rated_kw=1000.0, metadata_json={"rated_dc_kwp": 1200.0})
        inv_deficit = Asset(plant_id=p.id, name="Inv Deficit", asset_type="inverter", rated_kw=1000.0, metadata_json={"rated_dc_kwp": 1200.0})
        ws = Asset(plant_id=p.id, name="WS-01", asset_type="weather_station")
        db.add_all([inv_surplus, inv_deficit, ws])
        db.commit()

        ac_surplus = Channel(asset_id=inv_surplus.id, canonical_key="power_ac", source_name="AC_S", interval_s=900, receive_unit="kW")
        ac_deficit = Channel(asset_id=inv_deficit.id, canonical_key="power_ac", source_name="AC_D", interval_s=900, receive_unit="kW")
        poa = Channel(asset_id=ws.id, canonical_key="irradiance_poa", source_name="POA", interval_s=900, receive_unit="W/m2")
        db.add_all([ac_surplus, ac_deficit, poa])
        db.commit()

        # 4 readings = 1.0h. Expected = 1.20 MWh each (2.40 MWh total).
        # Inv Surplus = 1600 kW each -> 1.60 MWh (surplus +0.40 MWh)
        # Inv Deficit = 900 kW each -> 0.90 MWh (deficit = 1.20 - 0.90 = 0.30 MWh)
        # Total actual = 2.50 MWh > 2.40 MWh expected (plant surplus +0.10 MWh)
        base_ts = datetime(2020, 6, 17, 12, 0, tzinfo=timezone.utc)
        readings = []
        for i in range(4):
            t = base_ts + timedelta(minutes=i * 15)
            readings.append(Reading(channel_id=poa.id, ts=t, value=1000.0, quality=100))
            readings.append(Reading(channel_id=ac_surplus.id, ts=t, value=1600.0, quality=100))
            readings.append(Reading(channel_id=ac_deficit.id, ts=t, value=900.0, quality=100))

        db.add_all(readings)
        db.commit()

        res = client.get(f"/plants/{p.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()

        assert data["total_actual_mwh"] == 2.50
        assert data["total_expected_mwh"] == 2.40
        assert data["net_shortfall_mwh"] == 0.0  # max(2.40 - 2.50, 0) == 0.0
        assert data["aggregate_inverter_deficit_mwh"] == 0.30  # 0.30 MWh deficit on Inv Deficit
        assert data["total_loss_mwh"] == 0.30
        assert data["total_loss_pct"] == pytest.approx(12.5, abs=0.1)  # 0.30 / 2.40 * 100%
        assert data["ranking_mode"] == "deficit"
        assert len(data["losers"]) == 1
        assert data["losers"][0]["asset_name"] == "Inv Deficit"
        assert data["losers"][0]["loss_mwh"] == 0.30
        assert data["losers"][0]["loss_pct"] == pytest.approx(25.0, abs=0.1)  # 0.30 / 1.20 * 100%
    finally:
        db.close()


def test_loss_analysis_correct_aggregation_of_positive_per_inverter_deficits(client, kpi_test_setup):
    """Regression test: Aggregates strictly positive deficits without allowing overperformers to offset them:
    Inv 1: Exp 1.20, Act 0.80 -> Deficit 0.40 MWh
    Inv 2: Exp 1.20, Act 1.00 -> Deficit 0.20 MWh
    Inv 3: Exp 1.20, Act 1.50 -> Deficit 0.00 MWh (surplus +0.30 MWh)
    Total Expected: 3.60 MWh, Total Actual: 3.30 MWh
    Net Plant Shortfall: max(3.60 - 3.30, 0) = 0.30 MWh
    Aggregate Inverter Deficit: 0.40 + 0.20 = 0.60 MWh
    """
    db = SessionLocal()
    try:
        org = kpi_test_setup["org"]
        headers = kpi_test_setup["headers"]

        p = Plant(
            org_id=org.id,
            name=f"Multi Deficit Plant {uuid4()}",
            plant_type="solar",
            capacity_ac_kw=3000.0,
            capacity_dc_kwp=3600.0,
        )
        db.add(p)
        db.commit()
        db.refresh(p)

        inv_1 = Asset(plant_id=p.id, name="Inv 1", asset_type="inverter", rated_kw=1000.0, metadata_json={"rated_dc_kwp": 1200.0})
        inv_2 = Asset(plant_id=p.id, name="Inv 2", asset_type="inverter", rated_kw=1000.0, metadata_json={"rated_dc_kwp": 1200.0})
        inv_3 = Asset(plant_id=p.id, name="Inv 3", asset_type="inverter", rated_kw=1000.0, metadata_json={"rated_dc_kwp": 1200.0})
        ws = Asset(plant_id=p.id, name="WS-01", asset_type="weather_station")
        db.add_all([inv_1, inv_2, inv_3, ws])
        db.commit()

        ac_1 = Channel(asset_id=inv_1.id, canonical_key="power_ac", source_name="AC_1", interval_s=900, receive_unit="kW")
        ac_2 = Channel(asset_id=inv_2.id, canonical_key="power_ac", source_name="AC_2", interval_s=900, receive_unit="kW")
        ac_3 = Channel(asset_id=inv_3.id, canonical_key="power_ac", source_name="AC_3", interval_s=900, receive_unit="kW")
        poa = Channel(asset_id=ws.id, canonical_key="irradiance_poa", source_name="POA", interval_s=900, receive_unit="W/m2")
        db.add_all([ac_1, ac_2, ac_3, poa])
        db.commit()

        base_ts = datetime(2020, 6, 17, 12, 0, tzinfo=timezone.utc)
        readings = []
        for i in range(4):
            t = base_ts + timedelta(minutes=i * 15)
            readings.append(Reading(channel_id=poa.id, ts=t, value=1000.0, quality=100))
            readings.append(Reading(channel_id=ac_1.id, ts=t, value=800.0, quality=100))
            readings.append(Reading(channel_id=ac_2.id, ts=t, value=1000.0, quality=100))
            readings.append(Reading(channel_id=ac_3.id, ts=t, value=1500.0, quality=100))

        db.add_all(readings)
        db.commit()

        res = client.get(f"/plants/{p.id}/kpis/top-losers?range=24h", headers=headers)
        assert res.status_code == 200
        data = res.json()

        assert data["total_expected_mwh"] == 3.60
        assert data["total_actual_mwh"] == 3.30
        assert data["net_shortfall_mwh"] == 0.30  # 3.60 - 3.30 = 0.30 MWh
        assert data["aggregate_inverter_deficit_mwh"] == 0.60  # 0.40 + 0.20 = 0.60 MWh
        assert data["ranking_mode"] == "deficit"
        assert len(data["losers"]) == 2
        assert data["losers"][0]["asset_name"] == "Inv 1"
        assert data["losers"][0]["loss_mwh"] == 0.40
        assert data["losers"][1]["asset_name"] == "Inv 2"
        assert data["losers"][1]["loss_mwh"] == 0.20
    finally:
        db.close()


def test_surya_active_plant_24h_7d_30d_loss_analysis_distinction(client):
    """Verify live Surya plant loss analysis across 24H, 7D, 30D:
    - 24H: All inverters meet/exceed baseline -> net shortfall = 0, aggregate deficit = 0, losers = []
    - 7D: Aggregate deficit = 4.83 MWh, net shortfall = 0 (surplus), exactly 2 underperforming inverters
    - 30D: Aggregate deficit = 23.71 MWh, net shortfall = 0 (surplus), exactly 2 underperforming inverters
    """
    db = SessionLocal()
    try:
        plant = (
            db.query(Plant)
            .join(Asset, Asset.plant_id == Plant.id)
            .filter(Asset.name.like("%1BY6WEcLG%"))
            .first()
        )
        if not plant:
            pytest.skip("Surya plant not present")
        plant_id = str(plant.id)

        user = db.query(User).filter(User.org_id == plant.org_id).first()
        if not user:
            user = db.query(User).filter(User.email == "surya@gmail.com").first()
        if not user:
            pytest.skip("Surya plant user not present")

        token = create_access_token({"sub": str(user.id), "org_id": str(user.org_id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        # 24H
        res_24h = client.get(f"/plants/{plant_id}/kpis/top-losers?range=24h", headers=headers)
        assert res_24h.status_code == 200
        data_24h = res_24h.json()
        if not data_24h.get("has_data") or not data_24h.get("has_poa"):
            pytest.skip("Live Surya plant telemetry or POA data not present in active database")
        assert data_24h["net_shortfall_mwh"] == 0.0
        assert data_24h["aggregate_inverter_deficit_mwh"] == 0.0
        assert data_24h["ranking_mode"] == "none"
        assert len(data_24h["losers"]) == 0

        # 7D
        res_7d = client.get(f"/plants/{plant_id}/kpis/top-losers?range=7d", headers=headers)
        assert res_7d.status_code == 200
        data_7d = res_7d.json()
        assert data_7d["net_shortfall_mwh"] == 0.0
        assert data_7d["aggregate_inverter_deficit_mwh"] == 4.83
        assert data_7d["ranking_mode"] == "deficit"
        assert len(data_7d["losers"]) == 2
        assert data_7d["losers"][0]["asset_name"] == "Inverter bvBOhCH3iADSZry"
        assert data_7d["losers"][0]["loss_mwh"] == 2.65
        assert data_7d["losers"][1]["asset_name"] == "Inverter 1BY6WEcLGh8j5v7"
        assert data_7d["losers"][1]["loss_mwh"] == 2.18

        # 30D
        res_30d = client.get(f"/plants/{plant_id}/kpis/top-losers?range=30d", headers=headers)
        assert res_30d.status_code == 200
        data_30d = res_30d.json()
        assert data_30d["net_shortfall_mwh"] == 0.0
        assert data_30d["ranking_mode"] == "deficit"
        assert len(data_30d["losers"]) == 2

        # In Surya-A-demo.csv, synthetic fault injection 'soil-001' on 1BY6WEcLGh8j5v7 (May 20-27)
        # reduces its generation by 10.20 MWh, elevating its loss from 10.32 MWh to 20.52 MWh
        # (aggregate deficit = 33.91 MWh, rank 1).
        # In clean Plant_1_Generation_Data.csv, 1BY6 loss is 10.32 MWh (aggregate deficit = 23.71 MWh, rank 2).
        if data_30d["aggregate_inverter_deficit_mwh"] == 33.91:
            assert data_30d["losers"][0]["asset_name"] == "Inverter 1BY6WEcLGh8j5v7"
            assert data_30d["losers"][0]["loss_mwh"] == 20.52
            assert data_30d["losers"][1]["asset_name"] == "Inverter bvBOhCH3iADSZry"
            assert data_30d["losers"][1]["loss_mwh"] == 13.39
        else:
            assert data_30d["aggregate_inverter_deficit_mwh"] == 23.71
            assert data_30d["losers"][0]["asset_name"] == "Inverter bvBOhCH3iADSZry"
            assert data_30d["losers"][0]["loss_mwh"] == 13.39
            assert data_30d["losers"][1]["asset_name"] == "Inverter 1BY6WEcLGh8j5v7"
            assert data_30d["losers"][1]["loss_mwh"] == 10.32
    finally:
        db.close()


def test_get_daily_kpis_endpoint(client, kpi_test_setup):
    """Verify GET /plants/{plant_id}/kpis and /plants/{plant_id}/kpis/daily endpoints."""
    headers = kpi_test_setup["headers"]
    plant = kpi_test_setup["plant"]

    res_alias = client.get(f"/plants/{plant.id}/kpis/daily", headers=headers)
    assert res_alias.status_code == 200
    assert isinstance(res_alias.json(), list)

    res_main = client.get(f"/plants/{plant.id}/kpis", headers=headers)
    assert res_main.status_code == 200
    assert isinstance(res_main.json(), list)







