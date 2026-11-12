"""Automated test suite for PlantIQ Super Admin bootstrap provisioning.

Verifies:
1. First Super Admin creation via bootstrap.
2. Password hashing verified via verify_password (bcrypt).
3. Duplicate email prevention (reports already exists, doesn't duplicate).
4. Existing Org Admin cannot be silently promoted without --recover.
5. Super Admin login succeeds at /auth/login with portal="platform_admin".
6. Org Admin cannot access Platform Admin (rejected with 403).
7. Super Admin has org_id=None (no tenant binding).
8. Bootstrap command rejects invalid email and short password.
9. Repeated bootstrap operations are idempotent and do not create duplicate accounts.
10. Direct CLI execution via python -m app.scripts.bootstrap_super_admin.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent.parent
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.entities import User, Organization
from app.core.security import get_password_hash, verify_password, decode_access_token
from app.scripts.bootstrap_super_admin import bootstrap_super_admin


@pytest.fixture
def client():
    return TestClient(app)


def test_01_first_super_admin_creation():
    """Test 1: First Super Admin creation via bootstrap."""
    db = SessionLocal()
    try:
        email = f"bootstrap_super_{uuid4().hex[:8]}@plantiq.io"
        full_name = "Chief Platform Administrator"
        password = "PlatformMaster#2026"

        user, created = bootstrap_super_admin(
            email=email,
            password=password,
            full_name=full_name,
            confirm_password=password,
            db=db,
        )

        assert created is True
        assert user is not None
        assert user.email == email
        assert user.full_name == full_name
        assert user.role == "super_admin"
        assert user.is_active is True
        assert user.org_id is None

        # Verify persisted in database
        db_user = db.query(User).filter(User.email == email).first()
        assert db_user is not None
        assert db_user.role == "super_admin"
        assert db_user.org_id is None
    finally:
        db.close()


def test_02_password_hashing_verified():
    """Test 2: Password hashing verified via verify_password."""
    db = SessionLocal()
    try:
        email = f"bootstrap_pwd_{uuid4().hex[:8]}@plantiq.io"
        password = "SecureBcryptPass#2026"

        user, _ = bootstrap_super_admin(
            email=email,
            password=password,
            full_name="Security Admin",
            db=db,
        )

        # Password must be hashed and not stored in plain text
        assert user.password_hash != password
        assert user.password_hash.startswith(("$2b$", "$2a$", "$2y$"))

        # Password verification must succeed with correct password
        assert verify_password(password, user.password_hash) is True

        # Verification must fail with incorrect password
        assert verify_password("WrongPassword#9999", user.password_hash) is False
        assert verify_password("", user.password_hash) is False
    finally:
        db.close()


def test_03_duplicate_email_prevention():
    """Test 3: Duplicate email prevention (reports already exists, doesn't duplicate)."""
    db = SessionLocal()
    try:
        email = f"duplicate_test_{uuid4().hex[:8]}@plantiq.io"
        password = "PrimaryPassword#2026"

        # Initial bootstrap
        user1, created1 = bootstrap_super_admin(
            email=email,
            password=password,
            full_name="Primary Super Admin",
            db=db,
        )
        assert created1 is True

        # Second bootstrap without --recover
        user2, created2 = bootstrap_super_admin(
            email=email,
            password="DifferentPassword#2026",
            full_name="Duplicate Attempt",
            recover=False,
            db=db,
        )
        assert created2 is False
        assert user1.id == user2.id

        # Total user count in database for this email must remain exactly 1
        count = db.query(User).filter(User.email == email).count()
        assert count == 1
    finally:
        db.close()


def test_04_existing_org_admin_cannot_be_silently_promoted():
    """Test 4: Existing Org Admin cannot be silently promoted without --recover."""
    db = SessionLocal()
    try:
        # Create an organization and an Org Admin
        org = Organization(name=f"Tenant Org {uuid4().hex[:6]}")
        db.add(org)
        db.commit()
        db.refresh(org)

        email = f"org_admin_{uuid4().hex[:8]}@tenant.com"
        admin_user = User(
            org_id=org.id,
            email=email,
            full_name="Tenant Org Admin",
            role="admin",
            password_hash=get_password_hash("TenantAdmin#2026"),
            is_active=True,
        )
        db.add(admin_user)
        db.commit()

        # Attempt bootstrap without recover - MUST raise ValueError
        with pytest.raises(ValueError) as excinfo:
            bootstrap_super_admin(
                email=email,
                password="NewSuperPass#2026",
                full_name="Attempted Promotion",
                recover=False,
                db=db,
            )
        assert "Silent promotion is prohibited" in str(excinfo.value)

        # Verify user role is still 'admin' and org_id unchanged
        db.refresh(admin_user)
        assert admin_user.role == "admin"
        assert admin_user.org_id == org.id

        # Now attempt bootstrap WITH recover=True - MUST succeed
        promoted_user, changed = bootstrap_super_admin(
            email=email,
            password="NewSuperPass#2026",
            full_name="Recovered Platform Admin",
            recover=True,
            db=db,
        )
        assert changed is True
        assert promoted_user.role == "super_admin"
        assert promoted_user.org_id is None
        assert verify_password("NewSuperPass#2026", promoted_user.password_hash) is True
    finally:
        db.close()


def test_05_super_admin_login_portal_success(client):
    """Test 5: Super Admin login succeeds at /auth/login with portal='platform_admin'."""
    db = SessionLocal()
    try:
        email = f"super_login_{uuid4().hex[:8]}@plantiq.io"
        password = "PlatformLoginPass#2026"

        user, _ = bootstrap_super_admin(
            email=email,
            password=password,
            full_name="Portal Admin",
            db=db,
        )

        # Login with platform_admin portal parameter
        response = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": password,
                "portal": "platform_admin",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["user"]["role"] == "super_admin"
        assert data["user"]["org_id"] is None
        assert "access_token" in data

        # Decode JWT token to verify claims
        claims = decode_access_token(data["access_token"])
        assert claims["role"] == "super_admin"
        assert claims["org_id"] is None
        assert claims["sub"] == str(user.id)
    finally:
        db.close()


def test_06_org_admin_cannot_access_platform_admin(client):
    """Test 6: Org Admin cannot access Platform Admin."""
    db = SessionLocal()
    try:
        org = Organization(name=f"Restricted Org {uuid4().hex[:6]}")
        db.add(org)
        db.commit()
        db.refresh(org)

        email = f"restricted_admin_{uuid4().hex[:8]}@restricted.com"
        password = "OrgPassword#2026"
        org_admin = User(
            org_id=org.id,
            email=email,
            full_name="Restricted Admin",
            role="admin",
            password_hash=get_password_hash(password),
            is_active=True,
        )
        db.add(org_admin)
        db.commit()

        # 1. Org Admin attempting login at platform_admin portal is rejected with 403
        response = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": password,
                "portal": "platform_admin",
            },
        )
        assert response.status_code == 403
        assert "Platform Admin Portal is strictly restricted" in response.json()["detail"]

        # 2. Org Admin token cannot access Platform Admin API endpoints
        scada_login = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": password,
                "portal": "scada",
            },
        )
        assert scada_login.status_code == 200
        org_token = scada_login.json()["access_token"]

        platform_res = client.get(
            "/platform/overview",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert platform_res.status_code == 403
    finally:
        db.close()


def test_07_super_admin_has_null_org_id():
    """Test 7: Super Admin has org_id=None (no tenant binding)."""
    db = SessionLocal()
    try:
        email = f"null_tenant_{uuid4().hex[:8]}@plantiq.io"
        user, _ = bootstrap_super_admin(
            email=email,
            password="NullOrgPassword#2026",
            full_name="Decoupled Super Admin",
            db=db,
        )

        assert user.org_id is None
        assert user.organization is None

        # Verify directly in raw SQL to ensure column value in PostgreSQL is NULL
        from sqlalchemy import text

        row = db.execute(
            text("SELECT org_id FROM users WHERE id = :user_id"),
            {"user_id": user.id},
        ).fetchone()
        assert row is not None
        assert row[0] is None
    finally:
        db.close()


def test_08_bootstrap_validation_rejects_invalid_inputs():
    """Test 8: Bootstrap command rejects invalid email and short password."""
    # Invalid email formats
    invalid_emails = ["notanemail", "test@", "@domain.com", "user space@site.com"]
    for inv_email in invalid_emails:
        with pytest.raises(ValueError) as exc:
            bootstrap_super_admin(
                email=inv_email,
                password="ValidPassword#2026",
                full_name="Valid Name",
            )
        assert "Invalid email address format" in str(exc.value)

    # Password too short (< 8 chars)
    short_passwords = ["short", "12345", "abc"]
    for short_pw in short_passwords:
        with pytest.raises(ValueError) as exc:
            bootstrap_super_admin(
                email=f"valid_{uuid4().hex[:6]}@plantiq.io",
                password=short_pw,
                full_name="Valid Name",
            )
        assert "at least 8 characters" in str(exc.value)

    # Password mismatch
    with pytest.raises(ValueError) as exc:
        bootstrap_super_admin(
            email=f"valid_{uuid4().hex[:6]}@plantiq.io",
            password="ValidPassword#2026",
            confirm_password="MismatchPassword#2026",
            full_name="Valid Name",
        )
    assert "Passwords do not match" in str(exc.value)


def test_09_repeated_bootstrap_operations_are_idempotent():
    """Test 9: Repeated bootstrap operations are idempotent and do not create duplicate accounts."""
    db = SessionLocal()
    try:
        email = f"idempotent_{uuid4().hex[:8]}@plantiq.io"
        password = "IdempotentPass#2026"

        # Call 1: Creation
        user1, created1 = bootstrap_super_admin(
            email=email,
            password=password,
            full_name="Idempotent Super Admin",
            db=db,
        )
        assert created1 is True

        # Call 2: Repeat with same email
        user2, created2 = bootstrap_super_admin(
            email=email,
            password=password,
            full_name="Idempotent Super Admin",
            db=db,
        )
        assert created2 is False
        assert user1.id == user2.id

        # Call 3: Repeat again
        user3, created3 = bootstrap_super_admin(
            email=email,
            password=password,
            full_name="Idempotent Super Admin",
            db=db,
        )
        assert created3 is False
        assert user1.id == user3.id

        # Exactly 1 account in database
        users_count = db.query(User).filter(User.email == email).count()
        assert users_count == 1
    finally:
        db.close()


def test_10_cli_module_execution():
    """Test 10: Verify execution via python -m app.scripts.bootstrap_super_admin CLI."""
    email = f"cli_super_{uuid4().hex[:8]}@plantiq.io"
    password = "CLIPassword#2026"
    full_name = "CLI Provisioned Admin"

    cmd = [
        sys.executable,
        "-m",
        "app.scripts.bootstrap_super_admin",
        "--email",
        email,
        "--password",
        password,
        "--confirm-password",
        password,
        "--full-name",
        full_name,
    ]

    result = subprocess.run(
        cmd,
        cwd=str(_backend_dir),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "provisioned successfully" in result.stdout
    assert "super_admin" in result.stdout

    # Verify user exists in database
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        assert user.role == "super_admin"
        assert user.org_id is None
        assert verify_password(password, user.password_hash) is True
    finally:
        db.close()
