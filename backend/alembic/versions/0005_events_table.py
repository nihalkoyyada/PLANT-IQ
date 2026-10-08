"""Create events table for S3-FS-03 event management and CSV import.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06 15:45:00.000000

Task: S3-FS-03
Description:
- Creates `events` table for persisting plant and asset events (alarms, faults, grid outages, maintenance, etc.)
- Supports severity, source, event_type, start/end timestamps, code, message, and metadata JSON.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create events table or add missing columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("events"):
        op.create_table(
            "events",
            sa.Column(
                "id",
                sa.UUID(),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
                primary_key=True,
            ),
            sa.Column(
                "plant_id",
                sa.UUID(),
                sa.ForeignKey("plants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "asset_id",
                sa.UUID(),
                sa.ForeignKey("assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "source",
                sa.String(length=64),
                nullable=False,
                server_default="scada",
            ),
            sa.Column(
                "event_type",
                sa.String(length=64),
                nullable=False,
                server_default="fault",
            ),
            sa.Column(
                "severity",
                sa.String(length=32),
                nullable=False,
                server_default="info",
            ),
            sa.Column(
                "start_time",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "end_time",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "code",
                sa.String(length=64),
                nullable=True,
            ),
            sa.Column(
                "message",
                sa.Text(),
                nullable=False,
            ),
            sa.Column(
                "metadata",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_events_plant_id", "events", ["plant_id"])
        op.create_index("ix_events_asset_id", "events", ["asset_id"])
        op.create_index("ix_events_start_time", "events", ["start_time"])
        op.create_index("ix_events_severity", "events", ["severity"])
        op.create_index("ix_events_event_type", "events", ["event_type"])
        op.create_index("ix_events_source", "events", ["source"])
    else:
        columns = [c["name"] for c in inspector.get_columns("events")]
        if "created_at" not in columns:
            op.add_column("events", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

    # Ensure flexible check constraints for source and severity
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS ck_events_source;")
    op.create_check_constraint(
        "ck_events_source",
        "events",
        "source IN ('scada', 'manual', 'system', 'inverter', 'grid', 'weather', 'detector')",
    )

    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS ck_events_severity;")
    op.create_check_constraint(
        "ck_events_severity",
        "events",
        "severity IN ('info', 'warning', 'critical', 'error')",
    )


def downgrade() -> None:
    """Drop events table."""
    op.drop_index("ix_events_source", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_severity", table_name="events")
    op.drop_index("ix_events_start_time", table_name="events")
    op.drop_index("ix_events_asset_id", table_name="events")
    op.drop_index("ix_events_plant_id", table_name="events")
    op.drop_table("events")
