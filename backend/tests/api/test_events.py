import io
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, Plant, User, Event
from app.core.security import create_access_token


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_setup():
    """Setup test organization, users (admin, engineer, viewer), and plant."""
    db = SessionLocal()
    try:
        # Fetch or create test org
        org = db.query(Organization).filter(Organization.name == "Test Org Events").first()
        if not org:
            org = Organization(name="Test Org Events")
            db.add(org)
            db.commit()
            db.refresh(org)

        # Create admin user
        admin_user = db.query(User).filter(User.email == "events_admin@test.com").first()
        if not admin_user:
            admin_user = User(
                org_id=org.id,
                email="events_admin@test.com",
                password_hash="hashed_pw",
                full_name="Events Admin",
                role="admin",
                is_active=True,
            )
            db.add(admin_user)

        # Create viewer user
        viewer_user = db.query(User).filter(User.email == "events_viewer@test.com").first()
        if not viewer_user:
            viewer_user = User(
                org_id=org.id,
                email="events_viewer@test.com",
                password_hash="hashed_pw",
                full_name="Events Viewer",
                role="viewer",
                is_active=True,
            )
            db.add(viewer_user)

        # Create plant
        plant = db.query(Plant).filter(Plant.name == "Events Test Plant", Plant.org_id == org.id).first()
        if not plant:
            plant = Plant(
                org_id=org.id,
                name="Events Test Plant",
                plant_type="solar",
                capacity_ac_kw=5000.0,
                capacity_dc_kwp=6000.0,
            )
            db.add(plant)

        db.commit()
        db.refresh(admin_user)
        db.refresh(viewer_user)
        db.refresh(plant)

        admin_token = create_access_token({"sub": str(admin_user.id), "org_id": str(org.id), "role": "admin"})
        viewer_token = create_access_token({"sub": str(viewer_user.id), "org_id": str(org.id), "role": "viewer"})

        yield {
            "org": org,
            "admin_user": admin_user,
            "viewer_user": viewer_user,
            "plant": plant,
            "admin_headers": {"Authorization": f"Bearer {admin_token}"},
            "viewer_headers": {"Authorization": f"Bearer {viewer_token}"},
        }
    finally:
        db.close()


def test_get_events_unauthenticated(client):
    response = client.get("/events")
    assert response.status_code == 401


def test_create_event_success(client, test_setup):
    headers = test_setup["admin_headers"]
    plant_id = str(test_setup["plant"].id)

    payload = {
        "plant_id": plant_id,
        "source": "inverter",
        "event_type": "grid_fault",
        "severity": "critical",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "code": "E001",
        "message": "Inverter DC Overvoltage Fault",
        "metadata": {"inverter_id": "INV-01"},
    }

    response = client.post("/events", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["plant_id"] == plant_id
    assert data["source"] == "inverter"
    assert data["severity"] == "critical"
    assert data["message"] == "Inverter DC Overvoltage Fault"
    assert "id" in data


def test_create_event_viewer_forbidden(client, test_setup):
    headers = test_setup["viewer_headers"]
    plant_id = str(test_setup["plant"].id)

    payload = {
        "plant_id": plant_id,
        "source": "scada",
        "event_type": "warning",
        "severity": "warning",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "message": "Viewer create attempt",
    }

    response = client.post("/events", json=payload, headers=headers)
    assert response.status_code == 403


def test_get_events_filtering(client, test_setup):
    headers = test_setup["admin_headers"]
    plant_id = str(test_setup["plant"].id)

    # Post two events with distinct severities
    client.post("/events", json={
        "plant_id": plant_id,
        "source": "grid",
        "event_type": "outage",
        "severity": "critical",
        "start_time": "2026-10-01T10:00:00Z",
        "message": "Grid frequency drop",
    }, headers=headers)

    client.post("/events", json={
        "plant_id": plant_id,
        "source": "weather",
        "event_type": "soiling",
        "severity": "info",
        "start_time": "2026-10-02T12:00:00Z",
        "message": "High Dust Alert",
    }, headers=headers)

    # Filter by severity=critical
    res1 = client.get(f"/events?plant_id={plant_id}&severity=critical", headers=headers)
    assert res1.status_code == 200
    events1 = res1.json()
    assert all(e["severity"] == "critical" for e in events1)
    assert any(e["message"] == "Grid frequency drop" for e in events1)

    # Filter by source=weather
    res2 = client.get(f"/events?plant_id={plant_id}&source=weather", headers=headers)
    assert res2.status_code == 200
    events2 = res2.json()
    assert all(e["source"] == "weather" for e in events2)


def test_import_events_csv_success(client, test_setup):
    headers = test_setup["admin_headers"]
    plant_id = str(test_setup["plant"].id)

    csv_content = f"""plant_id,source,event_type,severity,start_time,code,message
{plant_id},scada,fault,warning,2026-10-03T08:00:00Z,W101,Transformer Temperature Warning
{plant_id},inverter,shutdown,critical,2026-10-03T09:30:00Z,C202,Emergency Stop Button Activated
"""
    files = {"file": ("events.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/events/import-csv", files=files, headers=headers)
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_rows"] == 2
    assert summary["imported_rows"] == 2
    assert summary["failed_rows"] == 0
    assert len(summary["validation_errors"]) == 0


def test_import_events_csv_invalid_rows(client, test_setup):
    headers = test_setup["admin_headers"]
    plant_id = str(test_setup["plant"].id)

    csv_content = f"""plant_id,source,severity,start_time,message
{plant_id},scada,warning,INVALID_DATE_FORMAT,Valid message with bad timestamp
{plant_id},scada,warning,2026-10-04T10:00:00Z,
invalid_uuid,scada,info,2026-10-04T11:00:00Z,Message with bad plant UUID
"""
    files = {"file": ("bad_events.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/events/import-csv", files=files, headers=headers)
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_rows"] == 3
    assert summary["failed_rows"] == 3
    assert summary["imported_rows"] == 0
    assert len(summary["validation_errors"]) == 3
