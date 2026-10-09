"""Create TimescaleDB continuous aggregates for readings hypertable.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07 12:00:00.000000

Task: S2-FS-04
Description:
- Creates TimescaleDB continuous aggregate materialized views (5min, 15min, 1hour, 1day, 1week) if TimescaleDB extension is present.
- Uses `WITH NO DATA` to allow creation within transactional DDL.
- Creates indexes on continuous aggregate views for efficient channel/time queries.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_timescaledb(bind) -> bool:
    """Check if PostgreSQL dialect is used and timescaledb extension is active."""
    if bind.dialect.name != "postgresql":
        return False
    try:
        res = bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb';")).fetchone()
        return res is not None
    except Exception:
        return False


def upgrade() -> None:
    """Create continuous aggregate materialized views on TimescaleDB if active."""
    bind = op.get_bind()
    if not is_timescaledb(bind):
        return

    # Ensure readings table is a hypertable
    bind.execute(sa.text("SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE, migrate_data => TRUE);"))

    # 1. 5-minute continuous aggregate
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS readings_5min
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('5 minutes', ts) AS bucket,
            channel_id,
            count(value) AS reading_count,
            avg(value) AS average_value,
            min(value) AS minimum_value,
            max(value) AS maximum_value
        FROM readings
        GROUP BY bucket, channel_id
        WITH NO DATA;
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_readings_5min_channel_bucket
        ON readings_5min (channel_id, bucket DESC);
    """))

    # 2. 15-minute continuous aggregate
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS readings_15min
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('15 minutes', ts) AS bucket,
            channel_id,
            count(value) AS reading_count,
            avg(value) AS average_value,
            min(value) AS minimum_value,
            max(value) AS maximum_value
        FROM readings
        GROUP BY bucket, channel_id
        WITH NO DATA;
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_readings_15min_channel_bucket
        ON readings_15min (channel_id, bucket DESC);
    """))

    # 3. 1-hour continuous aggregate
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1hour
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', ts) AS bucket,
            channel_id,
            count(value) AS reading_count,
            avg(value) AS average_value,
            min(value) AS minimum_value,
            max(value) AS maximum_value
        FROM readings
        GROUP BY bucket, channel_id
        WITH NO DATA;
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_readings_1hour_channel_bucket
        ON readings_1hour (channel_id, bucket DESC);
    """))

    # 4. 1-day continuous aggregate
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1day
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', ts) AS bucket,
            channel_id,
            count(value) AS reading_count,
            avg(value) AS average_value,
            min(value) AS minimum_value,
            max(value) AS maximum_value
        FROM readings
        GROUP BY bucket, channel_id
        WITH NO DATA;
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_readings_1day_channel_bucket
        ON readings_1day (channel_id, bucket DESC);
    """))

    # 5. 1-week continuous aggregate
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1week
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('7 days', ts) AS bucket,
            channel_id,
            count(value) AS reading_count,
            avg(value) AS average_value,
            min(value) AS minimum_value,
            max(value) AS maximum_value
        FROM readings
        GROUP BY bucket, channel_id
        WITH NO DATA;
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_readings_1week_channel_bucket
        ON readings_1week (channel_id, bucket DESC);
    """))


def downgrade() -> None:
    """Drop continuous aggregate views if TimescaleDB is active."""
    bind = op.get_bind()
    if not is_timescaledb(bind):
        return

    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS readings_1week CASCADE;"))
    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS readings_1day CASCADE;"))
    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS readings_1hour CASCADE;"))
    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS readings_15min CASCADE;"))
    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS readings_5min CASCADE;"))
