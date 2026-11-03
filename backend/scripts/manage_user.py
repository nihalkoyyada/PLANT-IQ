"""User management CLI for PlantIQ administrators and developers.

Provides safe operations to create, update, list, and reset user passwords
using application-standard bcrypt hashing without exposing credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Ensure backend root is on sys.path
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import typer
from sqlalchemy import select
from app.db.database import SessionLocal
from app.models.entities import User, Organization
from app.core.security import get_password_hash
from app.core.audit import log_audit_event

app = typer.Typer(help="PlantIQ User Management CLI")


@app.command("list")
def list_users(limit: int = typer.Option(20, help="Max users to display")):
    """List registered users with non-sensitive metadata."""
    with SessionLocal() as db:
        users = (
            db.execute(select(User).order_by(User.created_at.desc()).limit(limit))
            .scalars()
            .all()
        )
        if not users:
            typer.echo("No users found.")
            return

        typer.echo(f"\n{'EMAIL':<35} {'FULL NAME':<25} {'ROLE':<10} {'ACTIVE':<8} {'ORG ID':<36}")
        typer.echo("-" * 120)
        for u in users:
            typer.echo(
                f"{u.email:<35} {(u.full_name or 'N/A'):<25} {u.role:<10} {str(u.is_active):<8} {str(u.org_id):<36}"
            )
        typer.echo(f"\nShowing {len(users)} users.\n")


@app.command("create")
def create_user(
    email: str = typer.Option(..., prompt=True, help="User email address"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="User password (min 6 characters)"),
    full_name: str = typer.Option(..., prompt=True, help="User full name"),
    role: str = typer.Option("engineer", help="Role: admin, engineer, viewer"),
    org_id: Optional[str] = typer.Option(None, help="Organization UUID (optional)"),
):
    """Create a new user with secure bcrypt password hashing."""
    email_clean = email.strip().lower()
    if not email_clean or "@" not in email_clean:
        typer.secho("Error: Invalid email format.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if len(password) < 6:
        typer.secho("Error: Password must be at least 6 characters.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    role_clean = role.strip().lower()
    if role_clean not in ("admin", "engineer", "viewer"):
        typer.secho("Error: Role must be admin, engineer, or viewer.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    with SessionLocal() as db:
        existing = db.execute(select(User).where(User.email == email_clean)).scalars().first()
        if existing:
            typer.secho(f"Error: User '{email_clean}' already exists.", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        # Resolve organization
        org = None
        if org_id:
            org = db.get(Organization, org_id)
            if not org:
                typer.secho(f"Error: Organization '{org_id}' not found.", fg=typer.colors.RED)
                raise typer.Exit(code=1)
        else:
            org = db.execute(select(Organization).order_by(Organization.created_at.asc())).scalars().first()
            if not org:
                org = Organization(name="Default Surya Organization")
                db.add(org)
                db.flush()

        hashed_pw = get_password_hash(password)
        new_user = User(
            org_id=org.id,
            email=email_clean,
            password_hash=hashed_pw,
            full_name=full_name.strip(),
            role=role_clean,
            is_active=True,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        log_audit_event(
            db,
            action="cli_user_created",
            entity="user",
            user_id=new_user.id,
            entity_id=new_user.id,
            details={"email": new_user.email, "role": new_user.role, "org_id": str(new_user.org_id)},
        )

        typer.secho(f"Successfully created user '{email_clean}' with role '{role_clean}'.", fg=typer.colors.GREEN)


@app.command("set-password")
def set_password(
    email: str = typer.Option(..., prompt=True, help="User email address"),
    new_password: str = typer.Option(..., prompt=True, hide_input=True, help="New password (min 6 characters)"),
):
    """Safely update an existing user's password using bcrypt hashing."""
    email_clean = email.strip().lower()
    if len(new_password) < 6:
        typer.secho("Error: Password must be at least 6 characters.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email_clean)).scalars().first()
        if not user:
            typer.secho(f"Error: User '{email_clean}' not found.", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        user.password_hash = get_password_hash(new_password)
        db.commit()

        log_audit_event(
            db,
            action="cli_password_reset",
            entity="user",
            user_id=user.id,
            entity_id=user.id,
            details={"email": email_clean},
        )

        typer.secho(f"Successfully updated password for '{email_clean}'.", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()

