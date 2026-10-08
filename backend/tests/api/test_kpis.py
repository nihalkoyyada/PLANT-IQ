from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, Plant, User, Asset
from app.core.security import create_access_token


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
    assert "total_expected_mwh" in data
    assert "total_actual_mwh" in data
    assert "total_loss_mwh" in data
    assert "losers" in data
    assert data["plant_id"] == plant_id
    assert "plant_pr" in data


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
        # When no telemetry exists for the plant:
        assert data["has_data"] is False
        assert data["plant_pr"] is None
    finally:
        db.close()


def test_get_top_losers_with_telemetry_calculates_pr(client, kpi_test_setup):
    from datetime import datetime, timezone
    from app.models import Channel, Reading

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
        db.refresh(ac_chan)
        db.refresh(dc_chan)

        # Add readings: 10,000 kW AC, 12,000 kW DC -> PR = 10000 / (12000 * 0.98) ~ 85.0%
        r_ac = Reading(channel_id=ac_chan.id, ts=datetime.now(timezone.utc), value=10000.0, quality=100)
        r_dc = Reading(channel_id=dc_chan.id, ts=datetime.now(timezone.utc), value=12000.0, quality=100)
        db.add_all([r_ac, r_dc])
        db.commit()

        headers = kpi_test_setup["headers"]
        response = client.get(f"/plants/{plant.id}/kpis/top-losers?range=24h", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_data"] is True
        assert data["plant_pr"] is not None
        assert isinstance(data["plant_pr"], float)
        # Ensure target PR (e.g. 78.0%) is not returned as actual PR
        assert data["plant_pr"] != plant.expected_pr
    finally:
        db.close()


def test_kpis_organization_isolation(client, kpi_test_setup):
    db = SessionLocal()
    try:
        # Create Org B and User B if not exists
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
        # Accessing Org A's plant from Org B user should be forbidden (403)
        response = client.get(f"/plants/{plant_id}/kpis/top-losers", headers=headers_b)
        assert response.status_code == 403
    finally:
        db.close()


def test_pr_heatmap_zero_vs_missing_telemetry(client, kpi_test_setup):
    from datetime import datetime, timezone
    from app.models import Channel, Reading

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

        # Active Inverter Channels & Readings
        c_ac1 = db.query(Channel).filter(Channel.asset_id == inv_active.id, Channel.canonical_key == "power_ac").first()
        if not c_ac1:
            c_ac1 = Channel(asset_id=inv_active.id, canonical_key="power_ac", source_name="ac1", interval_s=900, agg_semantics="avg")
            db.add(c_ac1)

        c_dc1 = db.query(Channel).filter(Channel.asset_id == inv_active.id, Channel.canonical_key == "power_dc").first()
        if not c_dc1:
            c_dc1 = Channel(asset_id=inv_active.id, canonical_key="power_dc", source_name="dc1", interval_s=900, agg_semantics="avg")
            db.add(c_dc1)

        db.commit()
        db.refresh(c_ac1)
        db.refresh(c_dc1)

        db.add_all([
            Reading(channel_id=c_ac1.id, ts=now_ts, value=80.0, quality=100),
            Reading(channel_id=c_dc1.id, ts=now_ts, value=100.0, quality=100),
        ])

        # Zero Inverter Channels & Readings
        c_ac2 = db.query(Channel).filter(Channel.asset_id == inv_zero.id, Channel.canonical_key == "power_ac").first()
        if not c_ac2:
            c_ac2 = Channel(asset_id=inv_zero.id, canonical_key="power_ac", source_name="ac2", interval_s=900, agg_semantics="avg")
            db.add(c_ac2)

        db.commit()
        db.refresh(c_ac2)
        db.add(Reading(channel_id=c_ac2.id, ts=now_ts, value=0.0, quality=100))

        db.commit()

        headers = kpi_test_setup["headers"]
        response = client.get(f"/plants/{test_plant.id}/kpis/heatmap?range=24h", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["inverters"]) == 3

        inv_map = {row["asset_name"]: row["cells"] for row in data["inverters"]}

        # Check Active Inverter: has valid PR
        active_cell = inv_map["Inv Active"][-1]
        assert active_cell["has_data"] is True
        assert active_cell["pr"] is not None
        assert active_cell["pr"] > 0.0

        # Check Zero Inverter: has valid 0.0 PR
        zero_cell = inv_map["Inv Zero"][-1]
        assert zero_cell["has_data"] is True
        assert zero_cell["pr"] == 0.0
        assert zero_cell["ac_kw"] == 0.0

        # Check Missing Inverter: has N/A / None
        missing_cell = inv_map["Inv Missing"][-1]
        assert missing_cell["has_data"] is False
        assert missing_cell["pr"] is None
        assert missing_cell["pr_pct"] == "N/A"
        assert missing_cell["status"] == "missing_data"
    finally:
        db.close()


