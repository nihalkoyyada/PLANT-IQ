from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, User, File, MappingTemplate, IngestionJob
from app.core.security import get_password_hash, create_access_token


@pytest.fixture
def client():
    return TestClient(app)


def test_admin_login(client):
    response = client.post("/auth/login", json={"email": "admin@surya.plantiq.ai", "password": "SuryaAdmin#2026"})
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["role"] == "admin"
    assert "access_token" in data


def test_engineer_login(client):
    response = client.post("/auth/login", json={"email": "engineer@surya.plantiq.ai", "password": "SuryaEngineer#2026"})
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["role"] == "engineer"
    assert "access_token" in data


def test_viewer_login(client):
    response = client.post("/auth/login", json={"email": "viewer@surya.plantiq.ai", "password": "SuryaViewer#2026"})
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["role"] == "viewer"
    assert "access_token" in data


def test_login_invalid_password(client):
    response = client.post("/auth/login", json={"email": "admin@surya.plantiq.ai", "password": "WrongPassword"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_unknown_user(client):
    response = client.post("/auth/login", json={"email": "nonexistent@example.com", "password": "any"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_get_me_for_all_roles(client):
    db_session = SessionLocal()
    try:
        for role_name in ["admin", "engineer", "viewer"]:
            user = db_session.query(User).filter(User.role == role_name).first()
            assert user is not None
            token = create_access_token({"sub": str(user.id), "org_id": str(user.org_id), "role": role_name})
            headers = {"Authorization": f"Bearer {token}"}
            response = client.get("/auth/me", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["role"] == role_name
    finally:
        db_session.close()


def test_get_me_expired_jwt(client):
    db_session = SessionLocal()
    try:
        user = db_session.query(User).first()
        token = create_access_token(
            {"sub": str(user.id), "org_id": str(user.org_id), "role": user.role},
            expires_delta=timedelta(seconds=-10),
        )

        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/auth/me", headers=headers)
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()
    finally:
        db_session.close()


def test_get_me_invalid_jwt(client):
    headers = {"Authorization": "Bearer invalid.jwt.token"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_get_me_numeric_sub_returns_401(client):
    token = create_access_token({"sub": 12345, "role": "admin"})
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_get_me_missing_header(client):
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


def test_rbac_upload_and_ingestion_permissions(client):
    db_session = SessionLocal()
    try:
        admin_user = db_session.query(User).filter(User.role == "admin").first()
        engineer_user = db_session.query(User).filter(User.role == "engineer").first()
        viewer_user = db_session.query(User).filter(User.role == "viewer").first()

        admin_headers = {"Authorization": f"Bearer {create_access_token({'sub': str(admin_user.id), 'org_id': str(admin_user.org_id), 'role': 'admin'})}"}
        engineer_headers = {"Authorization": f"Bearer {create_access_token({'sub': str(engineer_user.id), 'org_id': str(engineer_user.org_id), 'role': 'engineer'})}"}
        viewer_headers = {"Authorization": f"Bearer {create_access_token({'sub': str(viewer_user.id), 'org_id': str(viewer_user.org_id), 'role': 'viewer'})}"}

        csv_content = b"DATE_TIME,PLANT_ID,SOURCE_KEY,DC_POWER,AC_POWER\n2020-05-15 00:00:00,1,INV-1,10.5,10.0\n"

        # 1. Admin can upload
        res_admin = client.post("/files/upload", files={"file": ("admin.csv", csv_content, "text/csv")}, headers=admin_headers)
        assert res_admin.status_code == 201

        # 2. Engineer can upload
        res_engineer = client.post("/files/upload", files={"file": ("engineer.csv", csv_content, "text/csv")}, headers=engineer_headers)
        assert res_engineer.status_code == 201

        # 3. Viewer CANNOT upload (403 Forbidden)
        res_viewer = client.post("/files/upload", files={"file": ("viewer.csv", csv_content, "text/csv")}, headers=viewer_headers)
        assert res_viewer.status_code == 403
        assert "not authorized" in res_viewer.json()["detail"].lower()

        # 4. Viewer CANNOT run AI profile (403 Forbidden)
        res_ai_viewer = client.post("/ai/profile", json={}, headers=viewer_headers)
        assert res_ai_viewer.status_code == 403

        # 5. Viewer CAN read files (200 OK)
        res_files_viewer = client.get("/files", headers=viewer_headers)
        assert res_files_viewer.status_code == 200

    finally:
        db_session.close()


def test_organization_isolation_across_users(client):
    db_session = SessionLocal()
    try:
        # Org A & User A
        org_a = Organization(name=f"Org A {uuid4()}")
        db_session.add(org_a)
        db_session.commit()
        db_session.refresh(org_a)

        user_a = User(
            org_id=org_a.id,
            email=f"usera_{uuid4()}@example.com",
            password_hash=get_password_hash("Pass123!"),
            full_name="User A",
            role="engineer",
        )
        db_session.add(user_a)

        # Org B & User B & File B
        org_b = Organization(name=f"Org B {uuid4()}")
        db_session.add(org_b)
        db_session.commit()
        db_session.refresh(org_b)

        user_b = User(
            org_id=org_b.id,
            email=f"userb_{uuid4()}@example.com",
            password_hash=get_password_hash("Pass123!"),
            full_name="User B",
            role="engineer",
        )
        db_session.add(user_b)
        db_session.commit()
        db_session.refresh(user_a)
        db_session.refresh(user_b)

        file_b = File(
            org_id=org_b.id,
            kind="raw_upload",
            path="uploads/org_b_data.csv",
            original_name="org_b_data.csv",
            size_bytes=100,
            created_by=user_b.id,
        )
        db_session.add(file_b)
        db_session.commit()
        db_session.refresh(file_b)

        # Create JWT for User A
        token_a = create_access_token({"sub": str(user_a.id), "org_id": str(org_a.id), "role": "engineer"})
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # User A tries to access File B (which belongs to Org B)
        response = client.get(f"/files/{file_b.id}", headers=headers_a)
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]
    finally:
        db_session.close()


# ----------------------------------------------------
# REGISTRATION & REFRESH TOKEN & AUDIT LOG TESTS
# ----------------------------------------------------

def test_register_admin_role(client):
    unique_email = f"reg_admin_{uuid4().hex[:6]}@example.com"
    pw = "AdminPass#2026"
    response = client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": pw,
            "full_name": "Registered Admin User",
            "organization_name": "Admin Test Org",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == unique_email
    assert data["user"]["role"] == "admin"
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]

    # Verify DB state
    db = SessionLocal()
    try:
        user_db = db.query(User).filter(User.email == unique_email).first()
        assert user_db is not None
        assert user_db.role == "admin"
    finally:
        db.close()

    # Login with registered Admin
    login_res = client.post("/auth/login", json={"email": unique_email, "password": pw})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    assert login_res.json()["user"]["role"] == "admin"

    # Verify /auth/me returns admin role
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "admin"


def test_register_engineer_role(client):
    unique_email = f"reg_eng_{uuid4().hex[:6]}@example.com"
    pw = "EngineerPass#2026"
    response = client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": pw,
            "full_name": "Registered Engineer User",
            "organization_name": "Engineer Test Org",
            "role": "engineer",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["role"] == "engineer"

    # Login with registered Engineer
    login_res = client.post("/auth/login", json={"email": unique_email, "password": pw})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    assert login_res.json()["user"]["role"] == "engineer"

    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "engineer"


def test_register_viewer_role(client):
    unique_email = f"reg_viewer_{uuid4().hex[:6]}@example.com"
    pw = "ViewerPass#2026"
    response = client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": pw,
            "full_name": "Registered Viewer User",
            "organization_name": "Viewer Test Org",
            "role": "viewer",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["role"] == "viewer"

    # Login with registered Viewer
    login_res = client.post("/auth/login", json={"email": unique_email, "password": pw})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    assert login_res.json()["user"]["role"] == "viewer"

    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "viewer"


def test_register_invalid_role(client):
    response = client.post(
        "/auth/register",
        json={
            "email": f"badrole_{uuid4().hex[:6]}@example.com",
            "password": "Password#2026",
            "full_name": "Invalid Role User",
            "role": "superadmin",
        },
    )
    assert response.status_code == 422
    assert "Role must be one of" in response.json()["detail"]


def test_register_duplicate_email(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "admin@surya.plantiq.ai",
            "password": "SuryaAdmin#2026",
            "full_name": "Duplicate Admin",
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_register_short_password(client):
    response = client.post(
        "/auth/register",
        json={
            "email": f"short_{uuid4().hex[:6]}@example.com",
            "password": "123",
            "full_name": "Short Password User",
        },
    )
    assert response.status_code == 422



def test_refresh_token_success(client):
    # First login to get refresh token
    login_res = client.post("/auth/login", json={"email": "admin@surya.plantiq.ai", "password": "SuryaAdmin#2026"})
    assert login_res.status_code == 200
    refresh_tok = login_res.json()["refresh_token"]

    # Call refresh endpoint
    ref_res = client.post("/auth/refresh", json={"refresh_token": refresh_tok})
    assert ref_res.status_code == 200
    data = ref_res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "admin@surya.plantiq.ai"


def test_refresh_token_using_access_token_fails(client):
    # Get access token
    login_res = client.post("/auth/login", json={"email": "admin@surya.plantiq.ai", "password": "SuryaAdmin#2026"})
    access_tok = login_res.json()["access_token"]

    # Try passing access token as refresh token -> must fail 401
    ref_res = client.post("/auth/refresh", json={"refresh_token": access_tok})
    assert ref_res.status_code == 401
    assert "access tokens cannot be used as refresh tokens" in ref_res.json()["detail"].lower()


def test_audit_log_safety(client):
    db_session = SessionLocal()
    try:
        from app.models import AuditLog
        audit_entries = db_session.query(AuditLog).all()
        assert len(audit_entries) > 0

        # Verify no entry leaks passwords or raw tokens in details JSON
        for entry in audit_entries:
            details_str = str(entry.details).lower()
            assert "password" not in details_str
            assert "access_token" not in details_str
            assert "refresh_token" not in details_str
    finally:
        db_session.close()
