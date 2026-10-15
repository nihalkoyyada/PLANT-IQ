"""Integration & Unit Tests for Alert Rules Engine & Delivery (§12, Task S4-FS-03)."""

from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.alerts.engine import evaluate_anomaly_alerts, evaluate_kpi_alerts
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.main import app
from app.models import AlertDelivery, AlertRule, Anomaly, Organization, Plant, User


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def alert_setup():
    """Setup test organization, plants, and users."""
    db = SessionLocal()
    try:
        org_a = db.query(Organization).filter(Organization.name == "Alert Test Org Alpha").first()
        if not org_a:
            org_a = Organization(name="Alert Test Org Alpha")
            db.add(org_a)
            db.commit()
            db.refresh(org_a)

        admin_a = db.query(User).filter(User.email == "alert_admin@plantiq.io").first()
        if not admin_a:
            admin_a = User(
                org_id=org_a.id,
                email="alert_admin@plantiq.io",
                password_hash="hashed_pw",
                full_name="Alert Admin",
                role="admin",
                is_active=True,
            )
            db.add(admin_a)
            db.commit()
            db.refresh(admin_a)

        plant_a = db.query(Plant).filter(Plant.name == "Alert Test Solar Plant").first()
        if not plant_a:
            plant_a = Plant(
                org_id=org_a.id,
                name="Alert Test Solar Plant",
                plant_type="solar",
                capacity_ac_kw=1000.0,
                capacity_dc_kwp=1100.0,
            )
            db.add(plant_a)
            db.commit()
            db.refresh(plant_a)

        # Org B (for cross-org rejection)
        org_b = db.query(Organization).filter(Organization.name == "Alert Test Org Beta").first()
        if not org_b:
            org_b = Organization(name="Alert Test Org Beta")
            db.add(org_b)
            db.commit()
            db.refresh(org_b)

        user_b = db.query(User).filter(User.email == "other_user@plantiq.io").first()
        if not user_b:
            user_b = User(
                org_id=org_b.id,
                email="other_user@plantiq.io",
                password_hash="hashed_pw",
                full_name="Other User",
                role="engineer",
                is_active=True,
            )
            db.add(user_b)
            db.commit()
            db.refresh(user_b)

        token_a = create_access_token(data={"sub": str(admin_a.id), "org_id": str(org_a.id), "role": admin_a.role})
        token_b = create_access_token(data={"sub": str(user_b.id), "org_id": str(org_b.id), "role": user_b.role})

        return {
            "token_a": token_a,
            "token_b": token_b,
            "org_a_id": org_a.id,
            "plant_a_id": plant_a.id,
            "admin_a_id": admin_a.id,
        }
    finally:
        db.close()


def test_alert_rule_crud_lifecycle(client: TestClient, alert_setup: dict):
    """Verify creating, reading, updating, and deleting alert rules with credential masking."""
    headers = {"Authorization": f"Bearer {alert_setup['token_a']}"}

    # 1. Create Alert Rule with sensitive config
    rule_payload = {
        "plant_id": str(alert_setup["plant_a_id"]),
        "name": "High Loss Critical Notification",
        "metric": "severity",
        "threshold": 1.0,
        "direction": "above",
        "severity": "critical",
        "channels": ["email", "webhook"],
        "enabled": True,
        "config": {
            "recipients": ["ops@plantiq.io", "tech@plantiq.io"],
            "webhook_url": "https://hooks.plantiq.io/alerts",
            "webhook_secret": "super_secret_auth_token_xyz123",
        },
    }

    res = client.post("/alert-rules", json=rule_payload, headers=headers)
    assert res.status_code == 201, res.text
    created = res.json()
    rule_id = created["id"]
    assert created["name"] == "High Loss Critical Notification"
    assert created["severity"] == "critical"
    # Verify credential masking
    assert created["config"]["webhook_secret"] == "***"

    # 2. Get Rules List
    res_list = client.get(f"/alert-rules?plant_id={alert_setup['plant_a_id']}", headers=headers)
    assert res_list.status_code == 200
    rules = res_list.json()
    assert any(r["id"] == rule_id for r in rules)

    # 3. Update Rule
    update_payload = {"threshold": 2.0, "name": "Updated Critical Rule"}
    res_update = client.patch(f"/alert-rules/{rule_id}", json=update_payload, headers=headers)
    assert res_update.status_code == 200
    assert res_update.json()["name"] == "Updated Critical Rule"
    assert res_update.json()["threshold"] == 2.0

    # 4. Test Notification Dispatch Endpoint
    test_res = client.post(
        f"/alert-rules/{rule_id}/test",
        json={"test_message": "Verifying delivery hook"},
        headers=headers,
    )
    assert test_res.status_code == 200
    test_data = test_res.json()
    assert test_data["rule_id"] == rule_id

    # 5. Delete Rule
    res_del = client.delete(f"/alert-rules/{rule_id}", headers=headers)
    assert res_del.status_code == 204


def test_cross_org_alert_rule_access_rejected(client: TestClient, alert_setup: dict):
    """Verify that users from another organization cannot view or modify alert rules."""
    headers_a = {"Authorization": f"Bearer {alert_setup['token_a']}"}
    headers_b = {"Authorization": f"Bearer {alert_setup['token_b']}"}

    # Create rule in Org A
    rule_payload = {
        "plant_id": str(alert_setup["plant_a_id"]),
        "name": "Org A Confidential Alert Rule",
        "metric": "severity",
        "threshold": 1.0,
        "direction": "above",
        "severity": "warning",
        "channels": ["email"],
        "enabled": True,
        "config": {"recipients": ["eng@plantiq.io"]},
    }
    res_create = client.post("/alert-rules", json=rule_payload, headers=headers_a)
    assert res_create.status_code == 201
    rule_id = res_create.json()["id"]

    # Org B user attempts to read rule
    res_get = client.get(f"/alert-rules/{rule_id}", headers=headers_b)
    assert res_get.status_code in (403, 404)

    # Org B user attempts to update rule
    res_patch = client.patch(f"/alert-rules/{rule_id}", json={"name": "Hacked"}, headers=headers_b)
    assert res_patch.status_code in (403, 404)


def test_alert_engine_evaluation_and_deduplication(alert_setup: dict):
    """Verify alert rules evaluation dispatches notifications and suppresses duplicates."""
    db = SessionLocal()
    try:
        # Clean up any leftover rules from previous tests on this plant
        db.query(AlertRule).filter(AlertRule.plant_id == alert_setup["plant_a_id"]).delete()
        db.commit()

        # Create rule
        rule = AlertRule(
            plant_id=alert_setup["plant_a_id"],
            name="Midday Inverter Trip Rule",
            metric="severity",
            threshold=1.0,
            direction="above",
            severity="critical",
            channels=["email"],
            enabled=True,
            config={"recipients": ["critical_ops@plantiq.io"], "smtp_host": "mock"},
        )
        db.add(rule)

        # Create critical anomaly
        anomaly = Anomaly(
            plant_id=alert_setup["plant_a_id"],
            start_time=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 1, 13, 0, tzinfo=timezone.utc),
            source="detector",
            score=0.98,
            severity="critical",
            status="open",
            estimated_loss_kw=500.0,
            summary="Midday trip evaluation test",
            details={"total_energy_loss_kwh": 500.0},
        )
        db.add(anomaly)
        db.commit()
        db.refresh(rule)
        db.refresh(anomaly)

        # First evaluation: Should dispatch 1 delivery
        deliveries_1 = evaluate_anomaly_alerts(db=db, anomaly=anomaly, cooldown_minutes=60)
        assert len(deliveries_1) == 1
        assert deliveries_1[0].status in ("delivered", "failed")

        # Second immediate evaluation (e.g. detector job retry): Should be suppressed by deduplication!
        deliveries_2 = evaluate_anomaly_alerts(db=db, anomaly=anomaly, cooldown_minutes=60)
        assert len(deliveries_2) == 0, "Duplicate alert was not suppressed by deduplication engine"
    finally:
        db.close()
