"""Add d3_irradiance_residual to ck_detectors_method check constraint.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08 16:05:00.000000

Task: S4-AI-03
Description:
- Expands ck_detectors_method constraint on detectors table to accept:
  'd3_irradiance_residual' alongside existing detector methods.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
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
                'trip', 'flatline', 'clipping', 'soiling',
                'd3_irradiance_residual'
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
            CHECK (method IN (
                'zscore', 'iqr', 'deviation', 'isolation_forest',
                'd1_statistical', 'd2_pr_deviation',
                'trip', 'flatline', 'clipping', 'soiling'
            ));
            """
        )
