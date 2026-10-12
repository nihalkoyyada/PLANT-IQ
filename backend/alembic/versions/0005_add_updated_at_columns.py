"""Add updated_at column to entities matching SQLAlchemy models.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 19:45:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "organizations",
    "plants",
    "users",
    "assets",
    "channels",
    "files",
    "mapping_templates",
]


def upgrade() -> None:
    """Add updated_at column to entity tables."""
    for table_name in TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )


def downgrade() -> None:
    """Remove updated_at column from entity tables."""
    for table_name in reversed(TABLES):
        op.drop_column(table_name, "updated_at")
