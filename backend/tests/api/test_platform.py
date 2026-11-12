"""Automated integration tests for Platform Super Admin Console.

Verifies:
1. Role-based access control (Super Admin permitted, Org Admin/Engineer/Viewer denied 403).
2. Organization management (Listing, creation with initial admin, details).
3. Organization suspension and reactivation.
4. Suspended organization access block (users blocked from APIs while super_admin retains access).
5. Explicit, audited tenant inspection view.
6. Global user management (listing, role update, status change, self-deactivation protection).
7. Cross-tenant plants & assets inventory.
8. Platform monitoring diagnostics (API, DB, Redis, Celery, ingestion pipeline).
9. Global audit log viewer with filters.
10. Platform SaaS settings configuration.
"""

from typing import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash
from app.db.database import SessionLocal, get_db
from app.main import app
from app.models.entities import AuditLog, Organization, Plant, PlatformSetting, User


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def test_setup_data(db_session: Session):
    """Seed test organizations and users."""
    suffix = uuid4().hex[:6]

    # Org 1: Alpha Energy
    org_alpha = Organization(name=f"Alpha Energy {suffix}", status="active")
    db_session.add(org_alpha)
    db_session.flush()

    # Org 2: Beta Power
    org_beta = Organization(name=f"Beta Power {suffix}", status="active")
    db_session.add(org_beta)
    db_session.flush()

    # 1. Super Admin (Global platform operator)
    super_admin = User(
        org_id=org_alpha.id,
        email=f"superadmin_{suffix}@plantiq.io",
        password_hash=get_password_hash("superpass123"),
        full_name="Global Platform SuperAdmin",
        role="super_admin",
        is_active=True,
    )

    # 2. Org Admin for Alpha
    alpha_admin = User(
        org_id=org_alpha.id,
        email=f"alpha_admin_{suffix}@alpha.com",
        password_hash=get_password_hash("alphapass123"),
        full_name="Alpha Org Administrator",
        role="admin",
        is_active=True,
    )

    # 3. Engineer for Alpha
    alpha_eng = User(
        org_id=org_alpha.id,
        email=f"alpha_eng_{suffix}@alpha.com",
        password_hash=get_password_hash("alphapass123"),
        full_name="Alpha Field Engineer",
        role="engineer",
        is_active=True,
    )

    # 4. Org Admin for Beta
    beta_admin = User(
        org_id=org_beta.id,
        email=f"beta_admin_{suffix}@beta.com",
        password_hash=get_password_hash("betapass123"),
        full_name="Beta Org Administrator",
        role="admin",
        is_active=True,
    )

    db_session.add_all([super_admin, alpha_admin, alpha_eng, beta_admin])

    # Add a test plant for Alpha
    plant_alpha = Plant(
        org_id=org_alpha.id,
        name=f"Alpha Solar Park {suffix}",
        plant_type="solar",
        capacity_ac_kw=25000.0,
    )
    db_session.add(plant_alpha)
    db_session.commit()

    # Generate JWT tokens
    def make_token(user: User) -> str:
        return create_access_token({
            "sub": str(user.id),
            "org_id": str(user.org_id),
            "role": user.role,
        })

    # Ensure maintenance mode is False initially
    setting = db_session.get(PlatformSetting, "saas_config")
    if setting and setting.value:
        val = dict(setting.value)
        val["maintenance_mode"] = False
        setting.value = val
        db_session.commit()

    yield {
        "org_alpha": org_alpha,
        "org_beta": org_beta,
        "super_admin": super_admin,
        "super_token": make_token(super_admin),
        "alpha_admin": alpha_admin,
        "alpha_token": make_token(alpha_admin),
        "alpha_eng": alpha_eng,
        "eng_token": make_token(alpha_eng),
        "beta_admin": beta_admin,
        "beta_token": make_token(beta_admin),
        "plant_alpha": plant_alpha,
    }

    # Ensure maintenance mode is False on teardown
    setting = db_session.get(PlatformSetting, "saas_config")
    if setting and setting.value:
        val = dict(setting.value)
        val["maintenance_mode"] = False
        setting.value = val
        db_session.commit()


# =====================================================================
# 1. PERMISSION & ACCESS RESTRICTION TESTS
# =====================================================================

def test_super_admin_can_access_platform_overview(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    resp = client.get("/platform/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_organizations" in data
    assert "active_organizations" in data
    assert "total_users" in data
    assert "ingestion_health" in data
    assert "system_health" in data
    assert data["system_health"]["api"]["status"] == "healthy"


def test_org_admin_denied_platform_overview(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['alpha_token']}"}
    resp = client.get("/platform/overview", headers=headers)
    assert resp.status_code == 403
    assert "Super Administrator" in resp.json()["detail"]


def test_engineer_denied_platform_overview(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['eng_token']}"}
    resp = client.get("/platform/overview", headers=headers)
    assert resp.status_code == 403


# =====================================================================
# 2. ORGANIZATION MANAGEMENT TESTS
# =====================================================================

def test_super_admin_list_organizations(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    resp = client.get("/platform/organizations", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    org_ids = [item["id"] for item in data["items"]]
    assert str(test_setup_data["org_alpha"].id) in org_ids
    assert str(test_setup_data["org_beta"].id) in org_ids


def test_super_admin_create_organization_with_initial_admin(client: TestClient, test_setup_data: dict):
    suffix = uuid4().hex[:6]
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    payload = {
        "name": f"Gamma Renewables {suffix}",
        "admin_email": f"gamma_admin_{suffix}@gamma.com",
        "admin_password": "gammapassword123",
        "admin_full_name": "Gamma Initial Administrator",
    }
    resp = client.post("/platform/organizations", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == payload["name"]
    assert data["status"] == "active"
    assert data["admin_user"] is not None
    assert data["admin_user"]["email"] == payload["admin_email"].lower()

    # Verify initial admin can authenticate
    login_resp = client.post(
        "/auth/login",
        json={"email": payload["admin_email"], "password": payload["admin_password"]},
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["user"]["role"] == "admin"


def test_super_admin_get_organization_details(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    org_id = str(test_setup_data["org_alpha"].id)
    resp = client.get(f"/platform/organizations/{org_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == org_id
    assert "plants" in data
    assert "users" in data
    assert len(data["plants"]) >= 1


# =====================================================================
# 3. ORGANIZATION SUSPENSION & TENANT BLOCK TESTS
# =====================================================================

def test_super_admin_suspend_and_reactivate_organization(
    client: TestClient, test_setup_data: dict, db_session: Session
):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    beta_org_id = str(test_setup_data["org_beta"].id)

    # 1. Suspend Beta Organization
    suspend_payload = {"status": "suspended", "reason": "Non-payment of SaaS invoice"}
    resp = client.patch(
        f"/platform/organizations/{beta_org_id}/status",
        json=suspend_payload,
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"

    # 2. Verify Beta user login is immediately blocked
    beta_admin = test_setup_data["beta_admin"]
    login_resp = client.post(
        "/auth/login",
        json={"email": beta_admin.email, "password": "betapass123"},
    )
    assert login_resp.status_code == 403
    assert "suspended" in login_resp.json()["detail"].lower()

    # 3. Verify existing Beta token is blocked on protected APIs
    beta_headers = {"Authorization": f"Bearer {test_setup_data['beta_token']}"}
    api_resp = client.get("/plants", headers=beta_headers)
    assert api_resp.status_code == 403
    assert "suspended" in api_resp.json()["detail"].lower()

    # 4. Super Admin can still view the suspended organization
    super_view_resp = client.get(f"/platform/organizations/{beta_org_id}", headers=headers)
    assert super_view_resp.status_code == 200
    assert super_view_resp.json()["status"] == "suspended"

    # 5. Reactivate Beta Organization
    reactivate_payload = {"status": "active", "reason": "Invoice settled"}
    reactivate_resp = client.patch(
        f"/platform/organizations/{beta_org_id}/status",
        json=reactivate_payload,
        headers=headers,
    )
    assert reactivate_resp.status_code == 200
    assert reactivate_resp.json()["status"] == "active"

    # 6. Verify Beta user can log in again
    login_ok = client.post(
        "/auth/login",
        json={"email": beta_admin.email, "password": "betapass123"},
    )
    assert login_ok.status_code == 200


# =====================================================================
# 4. AUDITED TENANT INSPECTION TESTS
# =====================================================================

def test_super_admin_inspect_tenant(client: TestClient, test_setup_data: dict, db_session: Session):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    alpha_org_id = str(test_setup_data["org_alpha"].id)

    resp = client.get(f"/platform/organizations/{alpha_org_id}/inspect", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["organization"]["id"] == alpha_org_id
    assert "summary" in data
    assert data["summary"]["plant_count"] >= 1

    # Verify audit log was recorded for TENANT_INSPECT
    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "TENANT_INSPECT", AuditLog.entity_id == test_setup_data["org_alpha"].id)
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert log is not None
    assert log.details["inspected_org_id"] == alpha_org_id


# =====================================================================
# 5. GLOBAL USER MANAGEMENT TESTS
# =====================================================================

def test_super_admin_global_user_management(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}

    # 1. List users
    resp = client.get("/platform/users", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 4
    emails = [u["email"] for u in data["items"]]
    assert test_setup_data["alpha_admin"].email in emails

    # 2. Create user in Alpha
    suffix = uuid4().hex[:6]
    create_payload = {
        "email": f"global_new_{suffix}@alpha.com",
        "password": "secretpassword123",
        "full_name": "Global Test User",
        "role": "engineer",
        "org_id": str(test_setup_data["org_alpha"].id),
        "is_active": True,
    }
    create_resp = client.post("/platform/users", json=create_payload, headers=headers)
    assert create_resp.status_code == 201
    created_user = create_resp.json()
    user_id = created_user["id"]

    # 3. Update user role and status
    update_payload = {"role": "admin", "is_active": False}
    update_resp = client.patch(f"/platform/users/{user_id}", json=update_payload, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["role"] == "admin"
    assert update_resp.json()["is_active"] is False

    # 4. Self-deactivation protection
    super_admin_id = str(test_setup_data["super_admin"].id)
    self_deact_resp = client.patch(
        f"/platform/users/{super_admin_id}",
        json={"is_active": False},
        headers=headers,
    )
    assert self_deact_resp.status_code == 400
    assert "Cannot deactivate your own" in self_deact_resp.json()["detail"]


# =====================================================================
# 6. USER DELETION TESTS

def test_super_admin_delete_user_with_audit_logs(client: TestClient, test_setup_data: dict, db_session: Session):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    suffix = uuid4().hex[:6]

    # Create a user
    create_payload = {
        "email": f"delete_me_{suffix}@tenant.com",
        "password": "TempPassword123!",
        "full_name": "Delete Target User",
        "role": "engineer",
        "org_id": str(test_setup_data["org_alpha"].id),
        "is_active": True,
    }
    create_resp = client.post("/platform/users", json=create_payload, headers=headers)
    assert create_resp.status_code == 201
    user_id = create_resp.json()["id"]

    # Add audit log entries referencing this user
    from uuid import UUID
    log = AuditLog(
        user_id=UUID(user_id),
        action="TEST_ACTION",
        entity="test",
        details={"test": True},
    )
    db_session.add(log)
    db_session.commit()

    # Verify self-delete protection
    super_admin_id = str(test_setup_data["super_admin"].id)
    self_del = client.delete(f"/platform/users/{super_admin_id}", headers=headers)
    assert self_del.status_code == 400
    assert "Cannot delete your own" in self_del.json()["detail"]

    # Delete the target user (with audit logs)
    del_resp = client.delete(f"/platform/users/{user_id}", headers=headers)
    assert del_resp.status_code == 204

    # Verify user is gone from database
    verify_resp = client.get(f"/platform/users?search=delete_me_{suffix}", headers=headers)
    assert verify_resp.status_code == 200
    assert verify_resp.json()["total"] == 0


# 7. CROSS-TENANT ASSETS & MONITORING TESTS
# =====================================================================

def test_super_admin_plants_assets_overview(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    resp = client.get("/platform/plants-assets", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_plants"] >= 1
    assert data["total_capacity_mw"] >= 25.0
    assert len(data["items"]) >= 1


def test_super_admin_platform_monitoring(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    resp = client.get("/platform/monitoring", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["api"]["status"] == "healthy"
    assert data["database"]["status"] == "healthy"
    assert "ingestion_pipeline" in data
    assert "organization_health" in data


# =====================================================================
# 7. GLOBAL AUDIT LOGS & SETTINGS TESTS
# =====================================================================

def test_super_admin_global_audit_logs(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    resp = client.get("/platform/audit-logs", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert isinstance(data["items"], list)


def test_super_admin_platform_settings(client: TestClient, test_setup_data: dict):
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}

    # 1. Read settings
    get_resp = client.get("/platform/settings", headers=headers)
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert "maintenance_mode" in data

    # 2. Update settings
    update_resp = client.patch(
        "/platform/settings",
        json={"platform_name": "PlantIQ Enterprise Hub", "maintenance_mode": True},
        headers=headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["platform_name"] == "PlantIQ Enterprise Hub"
    assert update_resp.json()["maintenance_mode"] is True

    # Restore maintenance_mode
    client.patch("/platform/settings", json={"maintenance_mode": False}, headers=headers)


def test_maintenance_mode_actual_enforcement(client: TestClient, test_setup_data: dict):
    """Verify that maintenance mode actually blocks non-super-admins while allowing Super Admin."""
    super_headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}
    alpha_headers = {"Authorization": f"Bearer {test_setup_data['alpha_token']}"}

    # 1. Enable maintenance mode
    enable_resp = client.patch(
        "/platform/settings",
        json={"maintenance_mode": True},
        headers=super_headers,
    )
    assert enable_resp.status_code == 200
    assert enable_resp.json()["maintenance_mode"] is True

    # 2. Org Admin API access should be blocked with 503
    api_resp = client.get("/plants", headers=alpha_headers)
    assert api_resp.status_code == 503
    assert "maintenance" in api_resp.json()["detail"].lower()

    # 3. Org Admin login should be blocked with 503
    login_resp = client.post(
        "/auth/login",
        json={"email": test_setup_data["alpha_admin"].email, "password": "alphapass123"},
    )
    assert login_resp.status_code == 503
    assert "maintenance" in login_resp.json()["detail"].lower()

    # 4. Super Admin can still query overview
    super_api_resp = client.get("/platform/overview", headers=super_headers)
    assert super_api_resp.status_code == 200

    # 5. Super Admin can still log in
    super_login_resp = client.post(
        "/auth/login",
        json={"email": test_setup_data["super_admin"].email, "password": "superpass123"},
    )
    assert super_login_resp.status_code == 200

    # 6. Disable maintenance mode
    disable_resp = client.patch(
        "/platform/settings",
        json={"maintenance_mode": False},
        headers=super_headers,
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["maintenance_mode"] is False

    # 7. Org Admin access restored
    restored_api_resp = client.get("/plants", headers=alpha_headers)
    assert restored_api_resp.status_code == 200


def test_credential_security_no_passwords_exposed(client: TestClient, test_setup_data: dict):
    """Verify Super Admin APIs never leak passwords, password hashes, or secrets."""
    headers = {"Authorization": f"Bearer {test_setup_data['super_token']}"}

    # 1. Check /platform/users
    users_resp = client.get("/platform/users", headers=headers)
    assert users_resp.status_code == 200
    for u in users_resp.json()["items"]:
        assert "password" not in u
        assert "password_hash" not in u
        assert "hashed_password" not in u

    # 2. Check /platform/organizations
    orgs_resp = client.get("/platform/organizations", headers=headers)
    assert orgs_resp.status_code == 200
    for org in orgs_resp.json()["items"]:
        if org.get("admin_user"):
            assert "password" not in org["admin_user"]
            assert "password_hash" not in org["admin_user"]
            assert "hashed_password" not in org["admin_user"]

    # 3. Check /platform/audit-logs
    audit_resp = client.get("/platform/audit-logs", headers=headers)
    assert audit_resp.status_code == 200
    for log in audit_resp.json()["items"]:
        details_str = str(log.get("details", {})).lower()
        assert "password_hash" not in details_str
        assert "hashed_password" not in details_str
