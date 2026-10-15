"""Add config to alert_rules and create alert_deliveries table.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12 11:55:00.000000

Task: S4-FS-03
Description:
- Adds config JSONB column to alert_rules for destination URLs, emails, and credentials.
- Creates alert_deliveries table for logging email/webhook notifications, deduplication, and retries.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add config column to alert_rules if it doesn't already exist
    op.add_column(
        "alert_rules",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )

    # Create alert_deliveries table
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("plant_id", sa.UUID(), nullable=False),
        sa.Column("anomaly_id", sa.UUID(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["anomaly_id"], ["anomalies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_deliveries_dedup_key", "alert_deliveries", ["dedup_key"])
    op.create_index("ix_alert_deliveries_plant_id", "alert_deliveries", ["plant_id"])
    op.create_index("ix_alert_deliveries_created_at", "alert_deliveries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_created_at", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_plant_id", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_dedup_key", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
    op.drop_column("alert_rules", "config")
