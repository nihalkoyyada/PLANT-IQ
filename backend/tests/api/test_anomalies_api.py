"""API Integration Tests for Anomaly Detection, Triage, and Summary Endpoints (§12, Task S4-AI-01)."""

from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.main import app
from app.models import Anomaly, Organization, Plant, User


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def api_setup():
    """Setup test organization, admin user, plant, and sample anomaly."""
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == "Test Org Anomalies").first()
        if not org:
            org = Organization(name="Test Org Anomalies")
            db.add(org)
            db.commit()
            db.refresh(org)

        admin = db.query(User).filter(User.email == "anomaly_admin@test.com").first()
        if not admin:
            admin = User(
                org_id=org.id,
                email="anomaly_admin@test.com",
                password_hash="hashed_pw",
                full_name="Anomaly Admin",
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)

        plant = db.query(Plant).filter(Plant.name == "Anomaly Test Plant", Plant.org_id == org.id).first()
        if not plant:
            plant = Plant(
                org_id=org.id,
                name="Anomaly Test Plant",
                plant_type="solar",
                capacity_ac_kw=5000.0,
                capacity_dc_kwp=5500.0,
                tariff_inr_per_kwh=4.00,
            )
            db.add(plant)
            db.commit()
            db.refresh(plant)

        # Seed an anomaly
        anomaly = Anomaly(
            plant_id=plant.id,
            start_time=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
            source="detector",
            score=0.92,
            severity="critical",
            status="open",
            estimated_loss_kw=250.0,
            summary="Midday inverter trip test",
            details={
                "total_energy_loss_kwh": 250.0,
                "total_financial_loss_inr": 1000.0,
                "merged_events_count": 1,
            },
        )
        db.add(anomaly)
        db.commit()
        db.refresh(anomaly)

        plant_id = plant.id
        anomaly_id = anomaly.id

        admin_token = create_access_token(
            data={"sub": str(admin.id), "org_id": str(org.id), "role": admin.role}
        )

        return {
            "org_id": org.id,
            "admin_id": admin.id,
            "admin_token": admin_token,
            "plant_id": plant_id,
            "anomaly_id": anomaly_id,
        }
    finally:
        db.close()


def test_get_anomalies_list(client: TestClient, api_setup: dict):
    """Verify listing anomalies with filters and org scoping."""
    headers = {"Authorization": f"Bearer {api_setup['admin_token']}"}
    response = client.get(
        f"/anomalies?plant_id={api_setup['plant_id']}",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["severity"] == "critical"
    assert data[0]["status"] == "open"


def test_get_anomalies_summary(client: TestClient, api_setup: dict):
    """Verify aggregated summary metrics calculation."""
    headers = {"Authorization": f"Bearer {api_setup['admin_token']}"}
    response = client.get(
        f"/anomalies/summary?plant_id={api_setup['plant_id']}",
        headers=headers,
    )
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_anomalies"] >= 1
    assert summary["critical_count"] >= 1
    assert summary["total_estimated_loss_kwh"] >= 250.0
    assert summary["total_estimated_financial_loss_inr"] >= 1000.0


def test_get_single_anomaly(client: TestClient, api_setup: dict):
    """Verify retrieving a single anomaly by ID."""
    headers = {"Authorization": f"Bearer {api_setup['admin_token']}"}
    anom_id = str(api_setup["anomaly_id"])
    response = client.get(f"/anomalies/{anom_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == anom_id
    assert data["summary"] == "Midday inverter trip test"


def test_triage_anomaly(client: TestClient, api_setup: dict):
    """Verify triaging an anomaly (acknowledge, status note, RCA)."""
    headers = {"Authorization": f"Bearer {api_setup['admin_token']}"}
    anom_id = str(api_setup["anomaly_id"])

    payload = {
        "status": "acknowledged",
        "status_note": "Investigating inverter DC disconnect switch.",
        "rca_narrative": {"root_cause": "Grid transient trip", "action": "Remote reset initiated"},
    }

    response = client.patch(f"/anomalies/{anom_id}", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "acknowledged"
    assert data["status_note"] == "Investigating inverter DC disconnect switch."
    assert data["rca_narrative"]["root_cause"] == "Grid transient trip"
