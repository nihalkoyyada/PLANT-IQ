"""Utility script to remove all duplicate or test Super Admin accounts.

Clears all users with role 'super_admin' from the database while safely
nullifying foreign key references in audit logs, conversations, files, etc.

Usage:
    python -m app.scripts.reset_super_admins
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend root is on sys.path
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parent.parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from sqlalchemy import text
from app.db.database import SessionLocal
from app.models.entities import User


def purge_all_super_admins() -> int:
    """Safely purge all super_admin accounts from the database."""
    with SessionLocal() as db:
        # Nullify foreign key references to prevent constraint violations
        db.execute(
            text(
                "UPDATE audit_log SET user_id = NULL WHERE user_id IN (SELECT id FROM users WHERE role = 'super_admin')"
            )
        )
        db.execute(
            text(
                "UPDATE conversations SET user_id = NULL WHERE user_id IN (SELECT id FROM users WHERE role = 'super_admin')"
            )
        )
        db.execute(
            text(
                "UPDATE files SET created_by = NULL WHERE created_by IN (SELECT id FROM users WHERE role = 'super_admin')"
            )
        )
        db.execute(
            text(
                "UPDATE anomalies SET rca_by = NULL WHERE rca_by IN (SELECT id FROM users WHERE role = 'super_admin')"
            )
        )
        db.execute(
            text(
                "UPDATE user_invitations SET invited_by_user_id = NULL WHERE invited_by_user_id IN (SELECT id FROM users WHERE role = 'super_admin')"
            )
        )

        deleted = (
            db.query(User)
            .filter(User.role == "super_admin")
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted


def main() -> None:
    deleted_count = purge_all_super_admins()
    print(
        f"[SUCCESS] Purged {deleted_count} Super Admin account(s). "
        f"The database now has 0 super_admin accounts.\n"
        f"You can now create a fresh Super Admin account using:\n"
        f"    python -m app.scripts.bootstrap_super_admin"
    )


if __name__ == "__main__":
    main()

