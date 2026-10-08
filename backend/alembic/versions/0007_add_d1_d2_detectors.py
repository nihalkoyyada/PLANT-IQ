"""Add d1_statistical and d2_pr_deviation to ck_detectors_method check constraint.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 15:40:00.000000

Task: S4-AI-02
Description:
- Expands ck_detectors_method constraint on detectors table to accept:
  'd1_statistical', 'd2_pr_deviation', 'trip', 'flatline', 'clipping', 'soiling'.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE detectors DROP CONSTRAINT IF EXISTS ck_detectors_method;")
        op.execute(
            """
            ALTER TABLE detectors ADD CONSTRAINT ck_detectors_method
            CHECK (method IN (
                'zscore', 'iqr', 'deviation', 'isolation_forest',
                'd1_statistical', 'd2_pr_deviation',
                'trip', 'flatline', 'clipping', 'soiling'
            ));
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE detectors DROP CONSTRAINT IF EXISTS ck_detectors_method;")
        op.execute(
            """
            ALTER TABLE detectors ADD CONSTRAINT ck_detectors_method
            CHECK (method IN ('zscore', 'iqr', 'deviation', 'isolation_forest'));
            """
        )
