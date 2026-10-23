"""add post call extraction result to calls

Revision ID: b4c9e2d7f1a6
Revises: afda2b328844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b4c9e2d7f1a6"
down_revision: Union[str, None] = "afda2b328844"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column(
            "post_call_extraction_result",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "calls",
        "post_call_extraction_result",
    )
