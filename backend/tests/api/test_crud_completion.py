from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, Plant, Asset, Channel, CanonicalSignal, Detector, User
from app.core.security import create_access_token


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def crud_setup():
    """Setup test organization, users (admin, viewer), second org user, plant, asset, channel."""
    db = SessionLocal()
    suffix = uuid4().hex[:6]
    try:
        # Org 1
        org1 = Organization(name=f"CRUD Test Org 1_{suffix}")
        db.add(org1)
        db.commit()
        db.refresh(org1)

        # Admin User Org 1
        admin_user = User(
            org_id=org1.id,
            email=f"crud_admin_{suffix}@test.com",
            password_hash="hashed_pw",
            full_name="CRUD Admin",
            role="admin",
            is_active=True,
        )
        db.add(admin_user)

        # Viewer User Org 1
        viewer_user = User(
            org_id=org1.id,
            email=f"crud_viewer_{suffix}@test.com",
            password_hash="hashed_pw",
            full_name="CRUD Viewer",
            role="viewer",
            is_active=True,
        )
        db.add(viewer_user)

        # Org 2 & User
        org2 = Organization(name=f"CRUD Test Org 2_{suffix}")
        db.add(org2)
        db.commit()
        db.refresh(org2)

        org2_user = User(
            org_id=org2.id,
            email=f"crud_org2_{suffix}@test.com",
            password_hash="hashed_pw",
            full_name="Org2 User",
            role="admin",
            is_active=True,
        )
        db.add(org2_user)

        db.commit()
        db.refresh(admin_user)
        db.refresh(viewer_user)
        db.refresh(org2_user)

        admin_token = create_access_token({"sub": str(admin_user.id), "org_id": str(org1.id), "role": "admin"})
        viewer_token = create_access_token({"sub": str(viewer_user.id), "org_id": str(org1.id), "role": "viewer"})
        org2_token = create_access_token({"sub": str(org2_user.id), "org_id": str(org2.id), "role": "admin"})

        # Seed test plant
        plant = Plant(
            org_id=org1.id,
            name=f"CRUD Test Plant_{suffix}",
            plant_type="solar",
            capacity_ac_kw=10000.0,
            capacity_dc_kwp=12000.0,
        )
        db.add(plant)
        db.commit()
        db.refresh(plant)

        # Seed canonical signal if not present
        cs = db.query(CanonicalSignal).filter(CanonicalSignal.key == "power_ac").first()
        if not cs:
            cs = CanonicalSignal(
                key="power_ac",
                name="AC Power",
                category="electrical",
                unit="kW",
                applicable_types=["inverter"],
            )
            db.add(cs)
            db.commit()

        return {
            "org1": org1,
            "org2": org2,
            "admin": admin_user,
            "viewer": viewer_user,
            "org2_user": org2_user,
            "admin_headers": {"Authorization": f"Bearer {admin_token}"},
            "viewer_headers": {"Authorization": f"Bearer {viewer_token}"},
            "org2_headers": {"Authorization": f"Bearer {org2_token}"},
            "plant": plant,
            "suffix": suffix,
        }
    finally:
        db.close()


# ----------------------------------------------------
# PLANTS CRUD TESTS
# ----------------------------------------------------

def test_plant_update_success(client, crud_setup):
    headers = crud_setup["admin_headers"]
    plant_id = crud_setup["plant"].id

    res = client.patch(
        f"/plants/{plant_id}",
        json={"name": f"Updated Plant_{crud_setup['suffix']}", "capacity_ac_kw": 15000.0},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == f"Updated Plant_{crud_setup['suffix']}"
    assert data["capacity_ac_kw"] == 15000.0


def test_plant_update_rbac_forbidden(client, crud_setup):
    headers = crud_setup["viewer_headers"]
    plant_id = crud_setup["plant"].id

    res = client.patch(
        f"/plants/{plant_id}",
        json={"name": "Hacked Plant Name"},
        headers=headers,
    )
    assert res.status_code == 403


def test_plant_update_org_isolation(client, crud_setup):
    headers = crud_setup["org2_headers"]
    plant_id = crud_setup["plant"].id

    res = client.patch(
        f"/plants/{plant_id}",
        json={"name": "Cross Org Plant"},
        headers=headers,
    )
    assert res.status_code == 403


def test_plant_delete_conflict_with_assets(client, crud_setup):
    headers = crud_setup["admin_headers"]
    db = SessionLocal()
    plant_id = crud_setup["plant"].id
    asset = Asset(plant_id=plant_id, name=f"Inverter Block_{crud_setup['suffix']}", asset_type="inverter")
    db.add(asset)
    db.commit()
    db.close()

    res = client.delete(f"/plants/{plant_id}", headers=headers)
    assert res.status_code == 409
    assert "Cannot delete plant with dependent assets" in res.json()["detail"]


# ----------------------------------------------------
# ASSETS CRUD TESTS
# ----------------------------------------------------

def test_asset_update_and_delete(client, crud_setup):
    headers = crud_setup["admin_headers"]
    plant_id = crud_setup["plant"].id
    suffix = crud_setup["suffix"]

    # Create unreferenced asset
    create_res = client.post(
        "/assets",
        json={"plant_id": str(plant_id), "name": f"Isolated Inverter_{suffix}", "asset_type": "inverter"},
        headers=headers,
    )
    assert create_res.status_code == 201
    asset_id = create_res.json()["id"]

    # Update asset
    patch_res = client.patch(
        f"/assets/{asset_id}",
        json={"name": f"Renamed Inverter_{suffix}", "make": "SMA"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == f"Renamed Inverter_{suffix}"
    assert patch_res.json()["make"] == "SMA"

    # Delete asset
    del_res = client.delete(f"/assets/{asset_id}", headers=headers)
    assert del_res.status_code == 204

    # Verify 404 after deletion
    get_res = client.get(f"/assets/{asset_id}", headers=headers)
    assert get_res.status_code == 404


def test_asset_delete_conflict_with_channels(client, crud_setup):
    headers = crud_setup["admin_headers"]
    plant_id = crud_setup["plant"].id
    suffix = crud_setup["suffix"]

    # Create asset
    asset_res = client.post(
        "/assets",
        json={"plant_id": str(plant_id), "name": f"Asset With Channel_{suffix}", "asset_type": "inverter"},
        headers=headers,
    )
    asset_id = asset_res.json()["id"]

    # Create channel under asset
    client.post(
        "/channels",
        json={
            "asset_id": asset_id,
            "canonical_key": "power_ac",
            "source_name": f"inv_power_{suffix}",
            "interval_s": 60,
        },
        headers=headers,
    )

    # Attempt to delete asset -> should trigger 409 Conflict
    del_res = client.delete(f"/assets/{asset_id}", headers=headers)
    assert del_res.status_code == 409


# ----------------------------------------------------
# CHANNELS CRUD TESTS
# ----------------------------------------------------

def test_channel_update_and_delete(client, crud_setup):
    headers = crud_setup["admin_headers"]
    plant_id = crud_setup["plant"].id
    suffix = crud_setup["suffix"]

    # Create asset & channel
    asset_res = client.post(
        "/assets",
        json={"plant_id": str(plant_id), "name": f"Asset For Channel Test_{suffix}", "asset_type": "inverter"},
        headers=headers,
    )
    asset_id = asset_res.json()["id"]

    ch_res = client.post(
        "/channels",
        json={
            "asset_id": asset_id,
            "canonical_key": "power_ac",
            "source_name": f"temp_channel_source_{suffix}",
            "interval_s": 60,
        },
        headers=headers,
    )
    assert ch_res.status_code == 201
    ch_id = ch_res.json()["id"]

    # Update channel
    up_res = client.patch(
        f"/channels/{ch_id}",
        json={"interval_s": 300, "agg_semantics": "sum"},
        headers=headers,
    )
    assert up_res.status_code == 200
    assert up_res.json()["interval_s"] == 300
    assert up_res.json()["agg_semantics"] == "sum"

    # Delete channel (no readings recorded)
    del_res = client.delete(f"/channels/{ch_id}", headers=headers)
    assert del_res.status_code == 204


# ----------------------------------------------------
# CANONICAL SIGNALS CRUD TESTS
# ----------------------------------------------------

def test_canonical_signals_full_crud(client, crud_setup):
    headers = crud_setup["admin_headers"]
    test_key = f"test_signal_{uuid4().hex[:6]}"

    # Create
    create_res = client.post(
        "/canonical-signals",
        json={
            "key": test_key,
            "name": "Test Custom Signal",
            "category": "environmental",
            "unit": "W/m2",
        },
        headers=headers,
    )
    assert create_res.status_code == 201
    assert create_res.json()["key"] == test_key

    # Get single
    get_res = client.get(f"/canonical-signals/{test_key}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Test Custom Signal"

    # Update
    up_res = client.patch(
        f"/canonical-signals/{test_key}",
        json={"unit": "kW/m2", "description": "Updated description"},
        headers=headers,
    )
    assert up_res.status_code == 200
    assert up_res.json()["unit"] == "kW/m2"

    # Delete
    del_res = client.delete(f"/canonical-signals/{test_key}", headers=headers)
    assert del_res.status_code == 204


def test_canonical_signal_duplicate_conflict(client, crud_setup):
    headers = crud_setup["admin_headers"]
    res = client.post(
        "/canonical-signals",
        json={
            "key": "power_ac",
            "name": "Duplicate Power AC",
            "category": "electrical",
            "unit": "kW",
        },
        headers=headers,
    )
    assert res.status_code == 409


# ----------------------------------------------------
# DETECTORS CRUD TESTS
# ----------------------------------------------------

def test_detectors_full_crud(client, crud_setup):
    headers = crud_setup["admin_headers"]
    plant_id = crud_setup["plant"].id
    suffix = crud_setup["suffix"]

    # Create detector
    create_res = client.post(
        "/detectors",
        json={
            "plant_id": str(plant_id),
            "name": f"Inverter Underperformance ZScore_{suffix}",
            "method": "zscore",
            "canonical_key": "power_ac",
            "parameters": {"threshold": 3.0},
            "enabled": True,
        },
        headers=headers,
    )
    assert create_res.status_code == 201
    detector_id = create_res.json()["id"]

    # List detectors
    list_res = client.get(f"/detectors?plant_id={plant_id}", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # Get single detector
    get_res = client.get(f"/detectors/{detector_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == f"Inverter Underperformance ZScore_{suffix}"

    # Update detector
    up_res = client.patch(
        f"/detectors/{detector_id}",
        json={"enabled": False, "parameters": {"threshold": 2.5}},
        headers=headers,
    )
    assert up_res.status_code == 200
    assert up_res.json()["enabled"] is False

    # Delete detector
    del_res = client.delete(f"/detectors/{detector_id}", headers=headers)
    assert del_res.status_code == 204
