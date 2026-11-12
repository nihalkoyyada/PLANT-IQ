"""Update reports table for S6-FS-01 Reports Module.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09 13:00:00.000000

Task: S6-FS-01 Reports Module
Description:
- Updates existing 'reports' table skeleton from initial schema.
- Renames period_type -> report_type, period_start -> start_date, period_end -> end_date.
- Adds org_id (FK to organizations.id CASCADE), title, file_path, file_size_bytes, metrics_summary, error_message, created_by_user_id, completed_at.
- Drops obsolete check constraints and sets up status tracking ('pending', 'processing', 'completed', 'failed').
- Adds indexes on org_id, plant_id, and created_at.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop old constraints if they exist
    try:
        op.drop_constraint("ck_reports_status", "reports", type_="check")
    except Exception:
        pass
    try:
        op.drop_constraint("ck_reports_period_type", "reports", type_="check")
    except Exception:
        pass

    # 2. Add org_id column
    op.add_column("reports", sa.Column("org_id", sa.Uuid(), nullable=True))
    # Populate org_id from plant if any existing rows exist
    op.execute(
        sa.text(
            "UPDATE reports r SET org_id = p.org_id FROM plants p WHERE r.plant_id = p.id AND r.org_id IS NULL"
        )
    )
    op.alter_column("reports", "org_id", nullable=False)
    op.create_foreign_key(
        "reports_org_id_fkey",
        "reports",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Add title
    op.add_column("reports", sa.Column("title", sa.String(length=255), nullable=True))
    op.execute(sa.text("UPDATE reports SET title = 'Operational Report' WHERE title IS NULL"))
    op.alter_column("reports", "title", nullable=False)

    # 4. Rename period columns to clean names
    try:
        op.alter_column("reports", "period_type", new_column_name="report_type", existing_type=sa.Text(), type_=sa.String(length=32))
    except Exception:
        pass
    try:
        op.alter_column("reports", "period_start", new_column_name="start_date", existing_type=sa.Date())
    except Exception:
        pass
    try:
        op.alter_column("reports", "period_end", new_column_name="end_date", existing_type=sa.Date())
    except Exception:
        pass

    # 5. Add execution & storage metadata columns
    op.add_column("reports", sa.Column("file_path", sa.String(length=512), nullable=True))
    op.add_column("reports", sa.Column("file_size_bytes", sa.Integer(), nullable=True))
    op.add_column(
        "reports",
        sa.Column("metrics_summary", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=True),
    )
    op.add_column("reports", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
    op.add_column("reports", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "reports_created_by_user_id_fkey",
        "reports",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 6. Change default status to 'pending'
    op.alter_column("reports", "status", server_default="pending")

    # 7. Add indexes
    op.create_index("ix_reports_org_id", "reports", ["org_id"])
    op.create_index("ix_reports_plant_id", "reports", ["plant_id"])
    op.create_index("ix_reports_created_at", "reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_created_at", table_name="reports")
    op.drop_index("ix_reports_plant_id", table_name="reports")
    op.drop_index("ix_reports_org_id", table_name="reports")

    op.drop_constraint("reports_created_by_user_id_fkey", "reports", type_="foreignkey")
    op.drop_constraint("reports_org_id_fkey", "reports", type_="foreignkey")

    op.drop_column("reports", "completed_at")
    op.drop_column("reports", "created_by_user_id")
    op.drop_column("reports", "error_message")
    op.drop_column("reports", "metrics_summary")
    op.drop_column("reports", "file_size_bytes")
    op.drop_column("reports", "file_path")

    op.alter_column("reports", "end_date", new_column_name="period_end", existing_type=sa.Date())
    op.alter_column("reports", "start_date", new_column_name="period_start", existing_type=sa.Date())
    op.alter_column("reports", "report_type", new_column_name="period_type", existing_type=sa.String(length=32), type_=sa.Text())

    op.drop_column("reports", "title")
    op.drop_column("reports", "org_id")
