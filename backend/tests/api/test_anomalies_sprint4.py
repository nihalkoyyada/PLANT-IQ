"""Integration Tests for Sprint 4 Anomaly APIs, Evidence & Bulk Triage (Tasks S4-FS-01, S4-FS-02)."""

from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.main import app
from app.models import Anomaly, Asset, AuditLog, Organization, Plant, User


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def s4_setup():
    """Setup multi-tenant test organizations, plants, assets, and anomalies."""
    db = SessionLocal()
    try:
        # Org 1
        org1 = db.query(Organization).filter(Organization.name == "Sprint4 Org Alpha").first()
        if not org1:
            org1 = Organization(name="Sprint4 Org Alpha")
            db.add(org1)
            db.commit()
            db.refresh(org1)

        user1 = db.query(User).filter(User.email == "eng_alpha@plantiq.io").first()
        if not user1:
            user1 = User(
                org_id=org1.id,
                email="eng_alpha@plantiq.io",
                password_hash="hashed_pw",
                full_name="Alpha Engineer",
                role="engineer",
                is_active=True,
            )
            db.add(user1)
            db.commit()
            db.refresh(user1)

        plant1 = db.query(Plant).filter(Plant.name == "Alpha Solar Plant").first()
        if not plant1:
            plant1 = Plant(
                org_id=org1.id,
                name="Alpha Solar Plant",
                plant_type="solar",
                capacity_ac_kw=2000.0,
                capacity_dc_kwp=2200.0,
                tariff_inr_per_kwh=3.75,
            )
            db.add(plant1)
            db.commit()
            db.refresh(plant1)

        asset1 = db.query(Asset).filter(Asset.name == "Inverter-Alpha-01").first()
        if not asset1:
            asset1 = Asset(
                plant_id=plant1.id,
                name="Inverter-Alpha-01",
                asset_type="inverter",
                rated_kw=1000.0,
            )
            db.add(asset1)
            db.commit()
            db.refresh(asset1)

        # Seed two anomalies for plant 1
        anom1 = Anomaly(
            plant_id=plant1.id,
            asset_id=asset1.id,
            start_time=datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 7, 10, 13, 0, tzinfo=timezone.utc),
            source="detector",
            score=0.95,
            severity="critical",
            status="open",
            estimated_loss_kw=450.0,
            summary="Midday inverter trip detected on Inverter-Alpha-01",
            details={
                "total_energy_loss_kwh": 900.0,
                "total_financial_loss_inr": 3375.0,
                "anomaly_type": "trip",
            },
        )
        anom2 = Anomaly(
            plant_id=plant1.id,
            asset_id=asset1.id,
            start_time=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
            source="detector",
            score=0.72,
            severity="high",
            status="open",
            estimated_loss_kw=180.0,
            summary="PR deviation detected on Inverter-Alpha-01",
            details={
                "total_energy_loss_kwh": 180.0,
                "total_financial_loss_inr": 675.0,
                "anomaly_type": "deviation",
            },
        )
        db.add_all([anom1, anom2])
        db.commit()
        db.refresh(anom1)
        db.refresh(anom2)

        # Org 2 (for tenant isolation test)
        org2 = db.query(Organization).filter(Organization.name == "Sprint4 Org Beta").first()
        if not org2:
            org2 = Organization(name="Sprint4 Org Beta")
            db.add(org2)
            db.commit()
            db.refresh(org2)

        user2 = db.query(User).filter(User.email == "eng_beta@plantiq.io").first()
        if not user2:
            user2 = User(
                org_id=org2.id,
                email="eng_beta@plantiq.io",
                password_hash="hashed_pw",
                full_name="Beta Engineer",
                role="engineer",
                is_active=True,
            )
            db.add(user2)
            db.commit()
            db.refresh(user2)

        token1 = create_access_token(data={"sub": str(user1.id), "org_id": str(org1.id), "role": user1.role})
        token2 = create_access_token(data={"sub": str(user2.id), "org_id": str(org2.id), "role": user2.role})

        return {
            "token1": token1,
            "token2": token2,
            "org1_id": org1.id,
            "plant1_id": plant1.id,
            "anom1_id": anom1.id,
            "anom2_id": anom2.id,
        }
    finally:
        db.close()


def test_bulk_triage_anomalies_and_audit_trail(client: TestClient, s4_setup: dict):
    """Verify bulk triage of multiple anomalies with transactional audit log creation."""
    headers = {"Authorization": f"Bearer {s4_setup['token1']}"}
    payload = {
        "anomaly_ids": [str(s4_setup["anom1_id"]), str(s4_setup["anom2_id"])],
        "status": "acknowledged",
        "status_note": "Bulk inspection dispatch assigned to field technician.",
    }

    res = client.post("/anomalies/bulk-triage", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["updated_count"] == 2
    assert data["status"] == "acknowledged"

    # Verify state persistence via single get
    res_single = client.get(f"/anomalies/{s4_setup['anom1_id']}", headers=headers)
    assert res_single.status_code == 200
    assert res_single.json()["status"] == "acknowledged"
    assert res_single.json()["status_note"] == payload["status_note"]

    # Verify AuditLog persistence in database
    db = SessionLocal()
    try:
        logs = db.query(AuditLog).filter(
            AuditLog.entity == "anomaly",
            AuditLog.action == "bulk_triage",
        ).all()
        assert len(logs) >= 2
    finally:
        db.close()


def test_anomaly_evidence_and_rca(client: TestClient, s4_setup: dict):
    """Verify anomaly evidence endpoint returns time-series chart points, baseline envelope, and RCA narrative."""
    headers = {"Authorization": f"Bearer {s4_setup['token1']}"}
    anom_id = str(s4_setup["anom1_id"])

    res = client.get(f"/anomalies/{anom_id}/evidence", headers=headers)
    assert res.status_code == 200, res.text
    evidence = res.json()

    assert evidence["anomaly_id"] == anom_id
    assert evidence["severity"] == "critical"
    assert len(evidence["data_points"]) >= 4

    # Verify baseline and threshold contours exist in data points
    dp = evidence["data_points"][0]
    assert "observed" in dp
    assert "baseline" in dp
    assert "upper_bound" in dp
    assert "lower_bound" in dp
    assert "is_anomaly" in dp

    # Verify Root Cause Analysis structure
    assert "ranked_hypotheses" in evidence
    assert len(evidence["ranked_hypotheses"]) >= 2
    top_hypo = evidence["ranked_hypotheses"][0]
    assert "hypothesis" in top_hypo
    assert "confidence" in top_hypo
    assert "category" in top_hypo

    # Verify distinct measured evidence from AI hypotheses
    assert "supporting_evidence" in evidence
    assert any(e.get("type") == "measured_telemetry" for e in evidence["supporting_evidence"])
    assert "recommended_checks" in evidence
    assert len(evidence["recommended_checks"]) >= 2


def test_cross_org_anomaly_isolation(client: TestClient, s4_setup: dict):
    """Verify that users from another organization cannot view or triage anomalies."""
    headers_other_org = {"Authorization": f"Bearer {s4_setup['token2']}"}
    anom_id = str(s4_setup["anom1_id"])

    # Attempt to fetch single anomaly across org boundary
    res = client.get(f"/anomalies/{anom_id}", headers=headers_other_org)
    assert res.status_code in (403, 404)

    # Attempt to fetch evidence across org boundary
    res_ev = client.get(f"/anomalies/{anom_id}/evidence", headers=headers_other_org)
    assert res_ev.status_code in (403, 404)

    # Attempt bulk triage across org boundary
    payload = {
        "anomaly_ids": [anom_id],
        "status": "resolved",
        "status_note": "Unauthorized cross-org attempt",
    }
    res_bulk = client.post("/anomalies/bulk-triage", json=payload, headers=headers_other_org)
    assert res_bulk.status_code in (403, 404)
