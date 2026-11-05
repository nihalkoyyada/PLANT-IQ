"""Add super_admin to users role check constraint.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03 12:30:00.000000

Task: S6-FS-02
Description:
- Updates ck_users_role to allow ('super_admin', 'admin', 'engineer', 'viewer').
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing check constraint and replace with updated allowed roles
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('super_admin', 'admin', 'engineer', 'viewer')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('admin', 'engineer', 'viewer')",
    )

