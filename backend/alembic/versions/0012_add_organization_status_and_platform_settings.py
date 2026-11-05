"""Add status to organizations and create platform_settings table.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03 16:30:00.000000

Task: Platform Super Admin Architecture & UI
Description:
- Adds status column to organizations ('active', 'suspended') with server_default='active'.
- Creates platform_settings table for Super Admin platform configuration.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add status column to organizations
    op.add_column(
        "organizations",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_check_constraint(
        "ck_organizations_status",
        "organizations",
        "status IN ('active', 'suspended')",
    )

    # 2. Create platform_settings table
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.drop_constraint("ck_organizations_status", "organizations", type_="check")
    op.drop_column("organizations", "status")

