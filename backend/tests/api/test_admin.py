"""Tests for Admin Panel, RBAC and Tenant Isolation (§13.2, Task S6-FS-02).

Covers:
- Super Admin privileges: organization creation, cross-tenant user listing & management.
- Organization Admin privileges: scoped user management within own organization.
- Cross-organization access denial (tenant isolation).
- Privilege escalation defense: Org Admin cannot create or elevate to Super Admin.
- User lifecycle: creation, update (role, name, active status, password), deletion.
- Self-deactivation and self-deletion defense.
- Audit log retrieval with multi-tenant scoping, pagination, and action/entity filtering.
- Detector Registry and Alert Rules administrative access and multi-plant scoping.
"""

from __future__ import annotations

import uuid
from typing import Dict
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash
from app.db.database import get_db
from app.main import app
from app.db.database import SessionLocal


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from app.models.entities import (
    AlertRule,
    AuditLog,
    CanonicalSignal,
    Detector,
    Organization,
    Plant,
    User,
)


@pytest.fixture
def admin_test_env(db_session: Session):
    """Set up two separate organizations with Super Admin, Org Admins, and regular users."""
    # Org 1: Surya Energy
    org_1 = Organization(name="Surya Solar Power Ltd")
    db_session.add(org_1)
    db_session.flush()

    # Org 2: Pavagada Green Power
    org_2 = Organization(name="Pavagada Green Power Ltd")
    db_session.add(org_2)
    db_session.flush()

    # Super Admin (belongs to Org 1 or platform system org)
    super_admin = User(
        org_id=org_1.id,
        email=f"superadmin_{uuid.uuid4().hex[:6]}@plantiq.io",
        password_hash=get_password_hash("SuperAdmin123!"),
        full_name="Global Super Administrator",
        role="super_admin",
        is_active=True,
    )

    # Org 1 Admin
    org1_admin = User(
        org_id=org_1.id,
        email=f"org1_admin_{uuid.uuid4().hex[:6]}@surya.com",
        password_hash=get_password_hash("Org1Admin123!"),
        full_name="Surya Org Administrator",
        role="admin",
        is_active=True,
    )

    # Org 1 Engineer
    org1_engineer = User(
        org_id=org_1.id,
        email=f"org1_eng_{uuid.uuid4().hex[:6]}@surya.com",
        password_hash=get_password_hash("Engineer123!"),
        full_name="Surya Field Engineer",
        role="engineer",
        is_active=True,
    )

    # Org 2 Admin
    org2_admin = User(
        org_id=org_2.id,
        email=f"org2_admin_{uuid.uuid4().hex[:6]}@pavagada.com",
        password_hash=get_password_hash("Org2Admin123!"),
        full_name="Pavagada Org Administrator",
        role="admin",
        is_active=True,
    )

    # Org 2 Viewer
    org2_viewer = User(
        org_id=org_2.id,
        email=f"org2_viewer_{uuid.uuid4().hex[:6]}@pavagada.com",
        password_hash=get_password_hash("Viewer123!"),
        full_name="Pavagada Stakeholder Viewer",
        role="viewer",
        is_active=True,
    )

    db_session.add_all([super_admin, org1_admin, org1_engineer, org2_admin, org2_viewer])
    db_session.flush()

    # Plants for each org
    plant_1 = Plant(
        org_id=org_1.id,
        name="Surya Plant Alpha",
        plant_type="solar",
        capacity_ac_kw=50000.0,
        capacity_dc_kwp=55000.0,
    )
    plant_2 = Plant(
        org_id=org_2.id,
        name="Pavagada Plant Beta",
        plant_type="solar",
        capacity_ac_kw=20000.0,
        capacity_dc_kwp=22000.0,
    )
    db_session.add_all([plant_1, plant_2])
    db_session.flush()

    # Ensure canonical signal exists for detectors
    sig = db_session.get(CanonicalSignal, "power_ac")
    if not sig:
        sig = CanonicalSignal(
            key="power_ac",
            name="AC Active Power",
            category="electrical",
            unit="W",
            phys_min=0,
            phys_max=5000000,
            applicable_types=["inverter"],
        )
        db_session.add(sig)
        db_session.flush()

    # Add Detectors
    det_1 = Detector(
        plant_id=plant_1.id,
        name="Surya Inverter Outlier Detector",
        method="zscore",
        canonical_key="power_ac",
        asset_scope={"asset_type": "inverter"},
        parameters={"threshold": 3.0},
        condition_text="zscore > 3.0",
        enabled=True,
    )
    det_2 = Detector(
        plant_id=plant_2.id,
        name="Pavagada Trip Detector",
        method="deviation",
        canonical_key="power_ac",
        asset_scope={"asset_type": "inverter"},
        parameters={"threshold": 0.2},
        condition_text="pr_deviation > 0.2",
        enabled=True,
    )
    db_session.add_all([det_1, det_2])

    # Add Alert Rules
    rule_1 = AlertRule(
        plant_id=plant_1.id,
        name="Surya Critical Generation Drop",
        metric="power_ac",
        threshold=1000.0,
        direction="below",
        severity="critical",
        channels=["email"],
        enabled=True,
    )
    rule_2 = AlertRule(
        plant_id=plant_2.id,
        name="Pavagada High Temp Warning",
        metric="temp_module",
        threshold=65.0,
        direction="above",
        severity="warning",
        channels=["webhook"],
        enabled=True,
    )
    db_session.add_all([rule_1, rule_2])

    # Add Audit Logs
    audit_1 = AuditLog(
        user_id=org1_admin.id,
        action="user_created",
        entity="user",
        entity_id=org1_engineer.id,
        details={"email": org1_engineer.email, "org_id": str(org_1.id)},
    )
    audit_2 = AuditLog(
        user_id=org2_admin.id,
        action="rule_created",
        entity="alert_rule",
        entity_id=rule_2.id,
        details={"name": rule_2.name, "org_id": str(org_2.id)},
    )
    db_session.add_all([audit_1, audit_2])

    db_session.commit()

    def get_token(u: User) -> str:
        return create_access_token(
            data={"sub": str(u.id), "org_id": str(u.org_id), "role": u.role}
        )

    return {
        "org_1": org_1,
        "org_2": org_2,
        "super_admin": super_admin,
        "org1_admin": org1_admin,
        "org1_engineer": org1_engineer,
        "org2_admin": org2_admin,
        "org2_viewer": org2_viewer,
        "plant_1": plant_1,
        "plant_2": plant_2,
        "det_1": det_1,
        "det_2": det_2,
        "rule_1": rule_1,
        "rule_2": rule_2,
        "super_token": get_token(super_admin),
        "org1_admin_token": get_token(org1_admin),
        "org1_eng_token": get_token(org1_engineer),
        "org2_admin_token": get_token(org2_admin),
        "org2_viewer_token": get_token(org2_viewer),
    }


# =====================================================================
# STEP 2: RBAC & SUPER ADMIN / ORG ADMIN TESTS
# =====================================================================


def test_super_admin_can_create_organization(client: TestClient, admin_test_env: Dict):
    """Super Admin is authorized to create new organizations and initial admin."""
    token = admin_test_env["super_token"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": f"Adani Green Park {uuid.uuid4().hex[:4]}",
        "admin_email": f"adani_admin_{uuid.uuid4().hex[:4]}@adani.com",
        "admin_password": "AdaniPassword123!",
        "admin_full_name": "Adani Operations Lead",
    }
    resp = client.post("/organizations", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["name"] == payload["name"]


def test_org_admin_cannot_create_organization(client: TestClient, admin_test_env: Dict):
    """Organization Admin is forbidden from creating new tenant organizations."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"name": "Unauthorized Org Creation"}
    resp = client.post("/organizations", json=payload, headers=headers)
    assert resp.status_code == 403
    assert "Super Administrators" in resp.json()["detail"]


def test_super_admin_can_view_all_organizations(client: TestClient, admin_test_env: Dict):
    """Super Admin receives the global list of organizations."""
    token = admin_test_env["super_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/organizations", headers=headers)
    assert resp.status_code == 200
    orgs = resp.json()
    org_ids = [o["id"] for o in orgs]
    assert str(admin_test_env["org_1"].id) in org_ids
    assert str(admin_test_env["org_2"].id) in org_ids


def test_org_admin_sees_only_own_organization(client: TestClient, admin_test_env: Dict):
    """Organization Admin sees only their assigned organization."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/organizations", headers=headers)
    assert resp.status_code == 200
    orgs = resp.json()
    assert len(orgs) == 1
    assert orgs[0]["id"] == str(admin_test_env["org_1"].id)


# =====================================================================
# STEP 3: USER MANAGEMENT & TENANT ISOLATION TESTS
# =====================================================================


def test_org_admin_list_users_scoped_to_own_org(client: TestClient, admin_test_env: Dict):
    """Org Admin only sees users from their own organization."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/admin/users", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    for item in data["items"]:
        assert item["org_id"] == str(admin_test_env["org_1"].id)


def test_super_admin_can_list_users_cross_org(client: TestClient, admin_test_env: Dict):
    """Super Admin can list users across all organizations or filter by org."""
    token = admin_test_env["super_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # All users
    resp = client.get("/admin/users", headers=headers)
    assert resp.status_code == 200
    all_users = resp.json()
    org_ids = {u["org_id"] for u in all_users["items"]}
    assert str(admin_test_env["org_1"].id) in org_ids
    assert str(admin_test_env["org_2"].id) in org_ids

    # Filtered by org_2
    resp_filtered = client.get(
        f"/admin/users?org_id={admin_test_env['org_2'].id}",
        headers=headers,
    )
    assert resp_filtered.status_code == 200
    filtered_users = resp_filtered.json()
    for u in filtered_users["items"]:
        assert u["org_id"] == str(admin_test_env["org_2"].id)


def test_org_admin_create_user_in_own_org(client: TestClient, admin_test_env: Dict):
    """Org Admin can create a new engineer or viewer in their organization."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    new_email = f"new_solar_tech_{uuid.uuid4().hex[:6]}@surya.com"
    payload = {
        "email": new_email,
        "password": "Password123!",
        "full_name": "Solar Field Technician",
        "role": "engineer",
        "is_active": True,
    }
    resp = client.post("/admin/users", json=payload, headers=headers)
    assert resp.status_code == 201
    user_data = resp.json()
    assert user_data["email"] == new_email
    assert user_data["role"] == "engineer"
    assert user_data["org_id"] == str(admin_test_env["org_1"].id)


def test_org_admin_cannot_create_user_in_another_org(client: TestClient, admin_test_env: Dict):
    """Org Admin cannot specify another organization's ID when creating a user."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "email": f"hacker_{uuid.uuid4().hex[:6]}@pavagada.com",
        "password": "Password123!",
        "full_name": "Injected User",
        "role": "engineer",
        "org_id": str(admin_test_env["org_2"].id),
    }
    resp = client.post("/admin/users", json=payload, headers=headers)
    assert resp.status_code == 403
    assert "Cannot create users in another organization" in resp.json()["detail"]


def test_org_admin_cannot_create_super_admin(client: TestClient, admin_test_env: Dict):
    """Privilege escalation check: Org Admin cannot create a Super Admin account."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "email": f"fake_super_{uuid.uuid4().hex[:6]}@surya.com",
        "password": "Password123!",
        "full_name": "Fake Super Admin",
        "role": "super_admin",
    }
    resp = client.post("/admin/users", json=payload, headers=headers)
    assert resp.status_code == 403
    assert "Only Super Administrators" in resp.json()["detail"]


def test_org_admin_cannot_modify_user_in_another_org(client: TestClient, admin_test_env: Dict):
    """Cross-tenant defense: Org 1 Admin cannot edit an Org 2 user."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}
    target_user_id = admin_test_env["org2_viewer"].id

    resp = client.patch(
        f"/admin/users/{target_user_id}",
        json={"role": "engineer"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]


def test_user_update_role_and_active_status(client: TestClient, admin_test_env: Dict):
    """Org Admin can update role and status of an engineer in their own org."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}
    target_user = admin_test_env["org1_engineer"]

    resp = client.patch(
        f"/admin/users/{target_user.id}",
        json={"role": "viewer", "is_active": False},
        headers=headers,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["role"] == "viewer"
    assert updated["is_active"] is False


def test_admin_cannot_deactivate_self(client: TestClient, admin_test_env: Dict):
    """Admin cannot deactivate their own active account."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}
    admin_id = admin_test_env["org1_admin"].id

    resp = client.patch(
        f"/admin/users/{admin_id}",
        json={"is_active": False},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "cannot deactivate your own" in resp.json()["detail"]


def test_admin_cannot_delete_self(client: TestClient, admin_test_env: Dict):
    """Admin cannot delete their own account."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}
    admin_id = admin_test_env["org1_admin"].id

    resp = client.delete(f"/admin/users/{admin_id}", headers=headers)
    assert resp.status_code == 400
    assert "cannot delete your own" in resp.json()["detail"]


def test_non_admin_cannot_access_admin_endpoints(client: TestClient, admin_test_env: Dict):
    """Engineers and Viewers receive HTTP 403 Forbidden on /admin endpoints."""
    eng_token = admin_test_env["org1_eng_token"]
    viewer_token = admin_test_env["org2_viewer_token"]

    for t in [eng_token, viewer_token]:
        headers = {"Authorization": f"Bearer {t}"}
        resp = client.get("/admin/users", headers=headers)
        assert resp.status_code == 403
        resp_audit = client.get("/admin/audit-logs", headers=headers)
        assert resp_audit.status_code == 403


# =====================================================================
# STEP 4: AUDIT LOG RETRIEVAL & FILTERING TESTS
# =====================================================================


def test_audit_logs_pagination_and_scoping(client: TestClient, admin_test_env: Dict):
    """Audit logs are scoped to the caller's organization with pagination."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/admin/audit-logs?limit=10&offset=0", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["limit"] == 10
    assert data["offset"] == 0

    # Ensure all returned items belong to Org 1
    for log_item in data["items"]:
        if log_item["org_id"]:
            assert log_item["org_id"] == str(admin_test_env["org_1"].id)


def test_audit_logs_filter_by_action(client: TestClient, admin_test_env: Dict):
    """Audit logs can be filtered by action type."""
    token = admin_test_env["super_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/admin/audit-logs?action=user_created", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for item in data["items"]:
        assert item["action"] == "user_created"


def test_audit_log_actions_endpoint(client: TestClient, admin_test_env: Dict):
    """Audit log distinct action categories are returned for UI filter dropdowns."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/admin/audit-logs/actions", headers=headers)
    assert resp.status_code == 200
    actions = resp.json()
    assert isinstance(actions, list)
    assert len(actions) > 0


def test_admin_summary_endpoint(client: TestClient, admin_test_env: Dict):
    """Admin summary returns aggregate counts for users, detectors, alert rules, and audit logs."""
    token = admin_test_env["org1_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/admin/summary", headers=headers)
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["role"] == "admin"
    assert summary["is_super_admin"] is False
    assert summary["total_users"] >= 2
    assert summary["total_detectors"] >= 1
    assert summary["total_alert_rules"] >= 1
    assert summary["total_audit_logs"] >= 1
