"""Update user foreign key constraints to ON DELETE SET NULL and CASCADE.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-04 15:35:00.000000

Task: Safe User Deletion & Cascade Constraints
Description:
- Changes audit_log.user_id FK constraint to ON DELETE SET NULL.
- Changes files.created_by FK constraint to ON DELETE SET NULL.
- Changes anomalies.rca_by FK constraint to ON DELETE SET NULL.
- Changes conversations.user_id FK constraint to ON DELETE CASCADE.
"""

from typing import Sequence, Union
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. audit_log.user_id -> users.id (ON DELETE SET NULL)
    op.drop_constraint("audit_log_user_id_fkey", "audit_log", type_="foreignkey")
    op.create_foreign_key(
        "audit_log_user_id_fkey",
        "audit_log",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. files.created_by -> users.id (ON DELETE SET NULL)
    op.drop_constraint("files_created_by_fkey", "files", type_="foreignkey")
    op.create_foreign_key(
        "files_created_by_fkey",
        "files",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. anomalies.rca_by -> users.id (ON DELETE SET NULL)
    op.drop_constraint("anomalies_rca_by_fkey", "anomalies", type_="foreignkey")
    op.create_foreign_key(
        "anomalies_rca_by_fkey",
        "anomalies",
        "users",
        ["rca_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4. conversations.user_id -> users.id (ON DELETE CASCADE)
    op.drop_constraint("conversations_user_id_fkey", "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_user_id_fkey",
        "conversations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("conversations_user_id_fkey", "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_user_id_fkey",
        "conversations",
        "users",
        ["user_id"],
        ["id"],
    )

    op.drop_constraint("anomalies_rca_by_fkey", "anomalies", type_="foreignkey")
    op.create_foreign_key(
        "anomalies_rca_by_fkey",
        "anomalies",
        "users",
        ["rca_by"],
        ["id"],
    )

    op.drop_constraint("files_created_by_fkey", "files", type_="foreignkey")
    op.create_foreign_key(
        "files_created_by_fkey",
        "files",
        "users",
        ["created_by"],
        ["id"],
    )

    op.drop_constraint("audit_log_user_id_fkey", "audit_log", type_="foreignkey")
    op.create_foreign_key(
        "audit_log_user_id_fkey",
        "audit_log",
        "users",
        ["user_id"],
        ["id"],
    )

