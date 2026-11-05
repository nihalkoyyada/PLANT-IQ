"""Allow NULL for users.org_id to decouple Super Admin from organizations.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-04 14:00:00.000000

Task: Secure Initial Super Admin Account Provisioning
Description:
- Alters users.org_id column to nullable=True.
- Allows Platform Super Admin accounts without tenant binding (org_id=NULL).
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "org_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "org_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

