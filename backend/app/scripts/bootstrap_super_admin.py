"""Bootstrap Super Administrator provisioning CLI for PlantIQ.

Provides a secure, transactional bootstrap mechanism to initialize or recover
the Platform Super Administrator account with zero tenant binding (org_id=NULL).

Usage:
    # Interactive mode:
    python -m app.scripts.bootstrap_super_admin

    # Automated / CLI mode:
    python -m app.scripts.bootstrap_super_admin --full-name "Platform Admin" --email admin@plantiq.io --password "SecurePass123!"

    # Recovery mode (explicit promotion or password reset):
    python -m app.scripts.bootstrap_super_admin --email admin@plantiq.io --password "NewPass123!" --recover
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

# Ensure backend root is in sys.path
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parent.parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.security import get_password_hash, verify_password
from app.db.database import SessionLocal
from app.models.entities import User

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
MIN_PASSWORD_LENGTH = 8


def validate_email(email: str) -> str:
    """Validate and normalize email address."""
    if not email:
        raise ValueError("Email address cannot be empty.")
    email_clean = email.strip().lower()
    if not EMAIL_REGEX.match(email_clean):
        raise ValueError(f"Invalid email address format: '{email}'")
    return email_clean


def validate_password(password: str, confirm_password: Optional[str] = None) -> None:
    """Validate password strength and confirmation match."""
    if not password:
        raise ValueError("Password cannot be empty.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if confirm_password is not None and password != confirm_password:
        raise ValueError("Passwords do not match.")


def validate_full_name(full_name: str) -> str:
    """Validate administrator full name."""
    if not full_name or not full_name.strip():
        raise ValueError("Administrator full name cannot be empty.")
    name_clean = full_name.strip()
    if len(name_clean) < 2:
        raise ValueError("Administrator full name must be at least 2 characters.")
    return name_clean


def bootstrap_super_admin(
    email: str,
    password: str,
    full_name: str,
    confirm_password: Optional[str] = None,
    recover: bool = False,
    db: Optional[Session] = None,
) -> Tuple[User, bool]:
    """Provision or recover a Super Admin account transactionally.

    Args:
        email: Administrator email address.
        password: Plain text administrator password.
        full_name: Administrator full name.
        confirm_password: Optional confirmation password to verify match.
        recover: Whether to allow recovering/promoting existing non-super_admin accounts.
        db: Optional database session (creates a new SessionLocal if omitted).

    Returns:
        Tuple[User, bool]: (User instance, True if newly created/updated, False if already existed)

    Raises:
        ValueError: If validation fails or unauthorized promotion is attempted.
    """
    clean_email = validate_email(email)
    validate_password(password, confirm_password)
    clean_name = validate_full_name(full_name)

    session_created = False
    if db is None:
        db = SessionLocal(expire_on_commit=False)
        session_created = True
    else:
        db.expire_on_commit = False

    try:
        existing_user = (
            db.query(User).filter(func.lower(User.email) == clean_email).first()
        )

        if existing_user:
            # Case 1: Account already exists as super_admin
            if existing_user.role == "super_admin":
                if recover:
                    # Update credentials in recovery mode
                    existing_user.full_name = clean_name
                    existing_user.password_hash = get_password_hash(password)
                    existing_user.org_id = None
                    existing_user.is_active = True
                    db.commit()
                    db.refresh(existing_user)
                    log_audit_event(
                        db,
                        action="SUPER_ADMIN_PASSWORD_RESET",
                        entity="user",
                        user_id=existing_user.id,
                        entity_id=existing_user.id,
                        details={
                            "email": clean_email,
                            "role": "super_admin",
                            "action_type": "bootstrap_recover",
                        },
                    )
                    if session_created:
                        db.expunge(existing_user)
                    return existing_user, True
                else:
                    # Idempotent: report already exists, do not duplicate
                    if session_created:
                        db.expunge(existing_user)
                    return existing_user, False

            # Case 2: Account exists with another role (admin, engineer, viewer)
            if not recover:
                raise ValueError(
                    f"Account exists with role '{existing_user.role}'. "
                    f"Silent promotion is prohibited. Use --recover to explicitly promote."
                )

            # Explicit recovery promotion
            old_role = existing_user.role
            existing_user.role = "super_admin"
            existing_user.org_id = None
            existing_user.full_name = clean_name
            existing_user.password_hash = get_password_hash(password)
            existing_user.is_active = True
            db.commit()
            db.refresh(existing_user)

            log_audit_event(
                db,
                action="SUPER_ADMIN_PROMOTED",
                entity="user",
                user_id=existing_user.id,
                entity_id=existing_user.id,
                details={
                    "email": clean_email,
                    "previous_role": old_role,
                    "new_role": "super_admin",
                    "org_id": None,
                },
            )
            if session_created:
                db.expunge(existing_user)
            return existing_user, True

        # Case 3: Create initial Super Admin account
        new_user = User(
            id=uuid4(),
            email=clean_email,
            full_name=clean_name,
            role="super_admin",
            org_id=None,
            password_hash=get_password_hash(password),
            is_active=True,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        log_audit_event(
            db,
            action="BOOTSTRAP_SUPER_ADMIN_CREATED",
            entity="user",
            user_id=new_user.id,
            entity_id=new_user.id,
            details={
                "email": clean_email,
                "role": "super_admin",
                "org_id": None,
            },
        )
        if session_created:
            db.expunge(new_user)
        return new_user, True

    except Exception:
        db.rollback()
        raise
    finally:
        if session_created:
            db.close()


def main() -> None:
    """CLI Entrypoint for Super Admin bootstrap."""
    parser = argparse.ArgumentParser(
        description="PlantIQ Super Administrator Provisioning CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--full-name",
        type=str,
        default=None,
        help="Administrator full name",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Administrator email address",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="Administrator password (hidden input if omitted)",
    )
    parser.add_argument(
        "--confirm-password",
        type=str,
        default=None,
        help="Administrator password confirmation",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        default=False,
        help="Explicitly recover or promote an existing account",
    )

    args = parser.parse_args()

    # Prompt interactively if arguments are omitted
    full_name = args.full_name
    if not full_name:
        try:
            full_name = input("Enter Super Administrator Full Name: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(1)

    email = args.email
    if not email:
        try:
            email = input("Enter Super Administrator Email: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(1)

    password = args.password
    confirm_password = args.confirm_password

    if not password:
        try:
            password = getpass.getpass("Enter Super Administrator Password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(1)
        try:
            confirm_password = getpass.getpass("Confirm Super Administrator Password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(1)

    try:
        user, changed = bootstrap_super_admin(
            email=email,
            password=password,
            full_name=full_name,
            confirm_password=confirm_password,
            recover=args.recover,
        )

        if changed:
            print(
                f"[SUCCESS] Super Administrator '{user.email}' provisioned successfully "
                f"(role: super_admin, org_id: NULL)."
            )
        else:
            print(
                f"[INFO] Super Admin account already exists for {user.email}."
            )
        sys.exit(0)

    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to provision Super Admin: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
