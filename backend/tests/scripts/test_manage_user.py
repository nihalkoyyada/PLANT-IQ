"""Tests for backend/scripts/manage_user.py CLI tool."""

import pytest
from typer.testing import CliRunner
from sqlalchemy import select
from app.db.database import SessionLocal
from app.models.entities import User, Organization
from app.core.security import verify_password
from scripts.manage_user import app

runner = CliRunner()


def test_manage_user_list():
    result = runner.invoke(app, ["list", "--limit", "5"])
    assert result.exit_code == 0
    assert "EMAIL" in result.stdout
    assert "ROLE" in result.stdout
    # Passwords or hashes must not be printed
    assert "password_hash" not in result.stdout


def test_manage_user_create_and_set_password():
    test_email = "test_cli_user_unique@plantiq.test"
    with SessionLocal() as db:
        old = db.execute(select(User).where(User.email == test_email)).scalars().first()
        if old:
            db.delete(old)
            db.commit()

    # Create user
    res_create = runner.invoke(app, [
        "create",
        "--email", test_email,
        "--password", "cliPassword123",
        "--full-name", "CLI Test User",
        "--role", "engineer",
    ])
    assert res_create.exit_code == 0
    assert "Successfully created user" in res_create.stdout

    # Verify user exists in database and password verifies
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == test_email)).scalars().first()
        assert user is not None
        assert user.role == "engineer"
        assert verify_password("cliPassword123", user.password_hash) is True
        assert verify_password("wrongPassword", user.password_hash) is False

    # Update password
    res_update = runner.invoke(app, [
        "set-password",
        "--email", test_email,
        "--new-password", "newCliPassword456",
    ])
    assert res_update.exit_code == 0
    assert "Successfully updated password" in res_update.stdout

    # Verify new password verifies
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == test_email)).scalars().first()
        assert verify_password("newCliPassword456", user.password_hash) is True
        assert verify_password("cliPassword123", user.password_hash) is False
        # Clean up
        from sqlalchemy import text
        db.execute(text("DELETE FROM audit_log WHERE user_id=:uid"), {"uid": user.id})
        db.delete(user)
        db.commit()
