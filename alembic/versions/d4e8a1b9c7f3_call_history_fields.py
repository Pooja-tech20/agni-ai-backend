"""call history fields (channel, caller, end reason, sentiment, recording, model)

Revision ID: d4e8a1b9c7f3
Revises: 29b48e5af3ac
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e8a1b9c7f3"
down_revision: Union[str, None] = "29b48e5af3ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("channel", sa.String(length=20), server_default="web", nullable=False))
    op.add_column("calls", sa.Column("caller_name", sa.String(length=255), nullable=True))
    op.add_column("calls", sa.Column("caller_number", sa.String(length=50), nullable=True))
    op.add_column("calls", sa.Column("end_reason", sa.String(length=50), nullable=True))
    op.add_column("calls", sa.Column("sentiment", sa.String(length=20), nullable=True))
    op.add_column("calls", sa.Column("recording_url", sa.String(length=1000), nullable=True))
    op.add_column("calls", sa.Column("model_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    for col in ("model_name", "recording_url", "sentiment", "end_reason",
                "caller_number", "caller_name", "channel"):
        op.drop_column("calls", col)