"""Comprehensive test suite for Organization Provisioning and Role-Based User Management.

Verifies the 12 core requirements:
1. Super Admin creates an organization and initial admin.
2. Organization gets a unique tenant ID.
3. Organization Admin invites an Engineer.
4. Organization Admin invites a Viewer.
5. Invitation acceptance and password setup.
6. Engineer and Viewer receive the correct organization and role.
7. Organization Admin cannot create another organization.
8. Organization Admin cannot create another Org Admin.
9. Organization Admin cannot access another tenant.
10. Engineer and Viewer cannot access admin APIs.
11. Public registration cannot grant privileged roles.
12. Failed organization creation does not leave orphaned records.
"""

from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def super_admin_auth(client):
    res = client.post(
        "/auth/login",
        json={"email": "plantiq@gmail.com", "password": "Password123!", "portal": "platform_admin"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def org_admin_auth(client):
    res = client.post(
        "/auth/login",
        json={"email": "surya@gmail.com", "password": "Password123!"},
    )
    assert res.status_code == 200, res.text
    return {
        "Authorization": f"Bearer {res.json()['access_token']}",
        "user": res.json()["user"],
    }


# Test 1 & 2: Super Admin creates organization and initial admin, gets unique tenant ID
def test_1_and_2_super_admin_creates_organization_with_unique_tenant_id(client, super_admin_auth):
    suffix = uuid4().hex[:6]
    org_name = f"Adani Solar {suffix}"
    admin_email = f"admin_{suffix}@adani.plantiq.ai"

    res = client.post(
        "/organizations",
        json={
            "name": org_name,
            "details": "50MW Solar Plant in Rajasthan",
            "admin_email": admin_email,
            "admin_password": "AdaniAdmin#2026",
            "admin_full_name": "Adani Administrator",
        },
        headers=super_admin_auth,
    )
    assert res.status_code == 201, res.text
    data = res.json()

    # Requirement 2: Organization gets unique tenant ID
    assert "id" in data
    tenant_id = data["id"]
    assert tenant_id is not None
    assert data["name"] == org_name
    assert data["status"] == "active"
    assert data["details"] == "50MW Solar Plant in Rajasthan"
    assert data["admin_user"] is not None
    assert data["admin_user"]["email"] == admin_email

    # Verify newly created Initial Admin can authenticate
    login_res = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "AdaniAdmin#2026"},
    )
    assert login_res.status_code == 200, login_res.text
    admin_data = login_res.json()
    assert admin_data["user"]["role"] == "admin"
    assert admin_data["user"]["org_id"] == tenant_id


# Test 3: Organization Admin invites an Engineer
def test_3_org_admin_invites_engineer(client, org_admin_auth):
    headers = org_admin_auth["Authorization"]
    admin_org_id = org_admin_auth["user"]["org_id"]

    suffix = uuid4().hex[:6]
    invite_email = f"eng_{suffix}@surya.plantiq.ai"

    res = client.post(
        "/admin/invitations",
        json={
            "email": invite_email,
            "full_name": f"Surya Engineer {suffix}",
            "role": "engineer",
        },
        headers={"Authorization": headers},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["email"] == invite_email
    assert data["role"] == "engineer"
    assert data["org_id"] == admin_org_id
    assert data["status"] == "pending"
    assert "token" in data
    assert "invitation_link" in data


# Test 4: Organization Admin invites a Viewer
def test_4_org_admin_invites_viewer(client, org_admin_auth):
    headers = org_admin_auth["Authorization"]
    admin_org_id = org_admin_auth["user"]["org_id"]

    suffix = uuid4().hex[:6]
    invite_email = f"viewer_{suffix}@surya.plantiq.ai"

    res = client.post(
        "/admin/invitations",
        json={
            "email": invite_email,
            "full_name": f"Surya Viewer {suffix}",
            "role": "viewer",
        },
        headers={"Authorization": headers},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["email"] == invite_email
    assert data["role"] == "viewer"
    assert data["org_id"] == admin_org_id
    assert data["status"] == "pending"
    assert "token" in data


# Test 5 & 6: Invitation acceptance, password setup, role & organization binding
def test_5_and_6_invitation_acceptance_and_role_organization_binding(client, org_admin_auth):
    headers = org_admin_auth["Authorization"]
    admin_org_id = org_admin_auth["user"]["org_id"]

    suffix = uuid4().hex[:6]
    invite_email = f"eng_accept_{suffix}@surya.plantiq.ai"

    # Step 1: Org Admin invites Engineer
    invite_res = client.post(
        "/admin/invitations",
        json={
            "email": invite_email,
            "full_name": "Acceptance Test Engineer",
            "role": "engineer",
        },
        headers={"Authorization": headers},
    )
    assert invite_res.status_code == 201
    token = invite_res.json()["token"]

    # Step 2: Invitee verifies token
    verify_res = client.get(f"/auth/invitations/{token}")
    assert verify_res.status_code == 200, verify_res.text
    assert verify_res.json()["valid"] is True
    assert verify_res.json()["email"] == invite_email
    assert verify_res.json()["role"] == "engineer"
    assert verify_res.json()["org_id"] == admin_org_id

    # Step 3: Invitee accepts invitation and sets password
    accept_res = client.post(
        "/auth/invitations/accept",
        json={"token": token, "password": "NewEngineerSecure#2026"},
    )
    assert accept_res.status_code == 200, accept_res.text
    accept_data = accept_res.json()
    assert accept_data["user"]["role"] == "engineer"
    assert accept_data["user"]["org_id"] == admin_org_id
    assert accept_data["user"]["email"] == invite_email

    # Step 4: Login with newly accepted credentials
    login_res = client.post(
        "/auth/login",
        json={"email": invite_email, "password": "NewEngineerSecure#2026"},
    )
    assert login_res.status_code == 200
    token_str = login_res.json()["access_token"]

    # Step 5: Check /auth/me for verified identity
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token_str}"})
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "engineer"
    assert me_res.json()["org_id"] == admin_org_id


# Test 7: Organization Admin cannot create another organization
def test_7_org_admin_cannot_create_organization(client, org_admin_auth):
    headers = {"Authorization": org_admin_auth["Authorization"]}

    # Attempt via /organizations
    res1 = client.post(
        "/organizations",
        json={"name": "Rogue Org By Admin"},
        headers=headers,
    )
    assert res1.status_code == 403

    # Attempt via /platform/organizations
    res2 = client.post(
        "/platform/organizations",
        json={"name": "Rogue Org By Admin 2"},
        headers=headers,
    )
    assert res2.status_code == 403


# Test 8: Organization Admin cannot create another Org Admin
def test_8_org_admin_cannot_create_another_org_admin(client, org_admin_auth):
    headers = {"Authorization": org_admin_auth["Authorization"]}

    # Direct creation attempt
    res1 = client.post(
        "/admin/users",
        json={
            "email": f"rogue_admin_{uuid4().hex[:6]}@surya.plantiq.ai",
            "full_name": "Rogue Admin",
            "password": "Password#123",
            "role": "admin",
        },
        headers=headers,
    )
    assert res1.status_code == 403
    assert "Super Admin" in res1.json()["detail"]

    # Invitation attempt
    res2 = client.post(
        "/admin/invitations",
        json={
            "email": f"rogue_invite_{uuid4().hex[:6]}@surya.plantiq.ai",
            "full_name": "Rogue Admin Inv",
            "role": "admin",
        },
        headers=headers,
    )
    assert res2.status_code == 403


# Test 9: Organization Admin cannot access another tenant
def test_9_org_admin_cannot_access_another_tenant(client, org_admin_auth, super_admin_auth):
    headers = {"Authorization": org_admin_auth["Authorization"]}

    # Create another tenant using Super Admin
    other_org_name = f"Tata Power {uuid4().hex[:6]}"
    other_res = client.post(
        "/organizations",
        json={"name": other_org_name, "details": "Other Tenant"},
        headers=super_admin_auth,
    )
    assert other_res.status_code == 201
    other_org_id = other_res.json()["id"]

    # Org Admin attempts to access other organization details
    get_res = client.get(f"/organizations/{other_org_id}", headers=headers)
    assert get_res.status_code == 403

    # Org Admin attempts to query users belonging to another org
    users_res = client.get(f"/admin/users?org_id={other_org_id}", headers=headers)
    assert users_res.status_code == 200
    # Should only return users in Surya Power Corp (enforce_org_access or auto-scoped)
    for u in users_res.json()["items"]:
        assert str(u["org_id"]) == str(org_admin_auth["user"]["org_id"])


# Test 10: Engineer and Viewer cannot access admin APIs
def test_10_engineer_and_viewer_cannot_access_admin_apis(client):
    # Engineer login
    eng_res = client.post(
        "/auth/login",
        json={"email": "satish@gmail.com", "password": "Password123!"},
    )
    assert eng_res.status_code == 200
    eng_headers = {"Authorization": f"Bearer {eng_res.json()['access_token']}"}

    # Viewer login
    view_res = client.post(
        "/auth/login",
        json={"email": "suresh@gmail.com", "password": "Password123!"},
    )
    assert view_res.status_code == 200
    view_headers = {"Authorization": f"Bearer {view_res.json()['access_token']}"}

    for h in [eng_headers, view_headers]:
        assert client.get("/admin/users", headers=h).status_code == 403
        assert client.post("/admin/users", json={}, headers=h).status_code == 403
        assert client.post("/admin/invitations", json={}, headers=h).status_code == 403
        assert client.get("/admin/audit-logs", headers=h).status_code == 403
        assert client.get("/platform/overview", headers=h).status_code == 403


# Test 11: Public registration cannot grant privileged roles
def test_11_public_registration_cannot_grant_privileged_roles(client):
    suffix = uuid4().hex[:6]

    # Attempt to self-register as Super Admin
    r1 = client.post(
        "/auth/register",
        json={
            "email": f"hacker_super_{suffix}@example.com",
            "password": "Password#2026",
            "full_name": "Hacker Super",
            "role": "super_admin",
        },
    )
    assert r1.status_code == 403

    # Attempt to self-register as Org Admin
    r2 = client.post(
        "/auth/register",
        json={
            "email": f"hacker_admin_{suffix}@example.com",
            "password": "Password#2026",
            "full_name": "Hacker Admin",
            "role": "admin",
        },
    )
    assert r2.status_code == 403

    # Attempt to self-register as Engineer without invitation
    r3 = client.post(
        "/auth/register",
        json={
            "email": f"hacker_eng_{suffix}@example.com",
            "password": "Password#2026",
            "full_name": "Hacker Eng",
            "role": "engineer",
        },
    )
    assert r3.status_code == 403


# Test 12: Failed organization creation does not leave orphaned records
def test_12_failed_organization_creation_does_not_leave_orphaned_records(client, super_admin_auth):
    suffix = uuid4().hex[:6]
    rogue_org_name = f"Atomic Rollback Org {suffix}"

    # Use existing email from super_admin or admin to guarantee collision on initial admin creation
    colliding_email = "plantiq@gmail.com"

    # Attempt creation with colliding initial admin email
    res = client.post(
        "/organizations",
        json={
            "name": rogue_org_name,
            "details": "This should be atomically rolled back",
            "admin_email": colliding_email,
            "admin_password": "ValidPassword#2026",
            "admin_full_name": "Colliding Admin",
        },
        headers=super_admin_auth,
    )
    # Must fail with 409 Conflict
    assert res.status_code == 409

    # Verify that the organization was NOT created (no orphaned record in DB)
    list_res = client.get("/organizations", headers=super_admin_auth)
    assert list_res.status_code == 200
    existing_names = [o["name"] for o in list_res.json()]
    assert rogue_org_name not in existing_names
