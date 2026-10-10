"""add functions

Revision ID: 29b48e5af3ac
Revises: e7711f95cbca
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '29b48e5af3ac'
down_revision: Union[str, None] = 'e7711f95cbca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "functions",
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_functions_client_id"), "functions", ["client_id"], unique=False)
    op.create_index(
        "uq_functions_client_lower_name",
        "functions",
        ["client_id", sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_functions_client_lower_name", table_name="functions")
    op.drop_index(op.f("ix_functions_client_id"), table_name="functions")
    op.drop_table("functions")