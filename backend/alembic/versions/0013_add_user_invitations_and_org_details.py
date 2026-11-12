"""Add details column to organizations and create user_invitations table.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04 13:00:00.000000

Task: Organization Provisioning and Role-Based User Management
Description:
- Adds details column to organizations table.
- Creates user_invitations table for secure, auditable user onboarding.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add details column to organizations
    op.add_column(
        "organizations",
        sa.Column("details", sa.Text(), nullable=True),
    )

    # 2. Create user_invitations table
    op.create_table(
        "user_invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_user_invitations_token",
        "user_invitations",
        ["token"],
        unique=True,
    )
    op.create_index(
        "ix_user_invitations_email",
        "user_invitations",
        ["email"],
    )
    op.create_index(
        "ix_user_invitations_org_id",
        "user_invitations",
        ["org_id"],
    )
    op.create_check_constraint(
        "ck_invitation_status",
        "user_invitations",
        "status IN ('pending', 'accepted', 'expired', 'revoked')",
    )
    op.create_check_constraint(
        "ck_invitation_role",
        "user_invitations",
        "role IN ('super_admin', 'admin', 'engineer', 'viewer')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invitation_role", "user_invitations", type_="check")
    op.drop_constraint("ck_invitation_status", "user_invitations", type_="check")
    op.drop_index("ix_user_invitations_org_id", table_name="user_invitations")
    op.drop_index("ix_user_invitations_email", table_name="user_invitations")
    op.drop_index("ix_user_invitations_token", table_name="user_invitations")
    op.drop_table("user_invitations")
    op.drop_column("organizations", "details")

