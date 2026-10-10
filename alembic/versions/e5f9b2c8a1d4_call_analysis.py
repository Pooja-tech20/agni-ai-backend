"""call analysis (summary + analyzed_at)

Revision ID: e5f9b2c8a1d4
Revises: d4e8a1b9c7f3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f9b2c8a1d4"
down_revision: Union[str, None] = "d4e8a1b9c7f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "analyzed_at")
    op.drop_column("calls", "summary")