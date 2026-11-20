"""add organization ownership to knowledge bases

Revision ID: f2a7c9d1e4b6
Revises: c1d2e3f4a5b6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2a7c9d1e4b6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("client_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_bases_client_id_clients",
        "knowledge_bases",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_knowledge_bases_client_id",
        "knowledge_bases",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_bases_client_id", table_name="knowledge_bases")
    op.drop_constraint(
        "fk_knowledge_bases_client_id_clients",
        "knowledge_bases",
        type_="foreignkey",
    )
    op.drop_column("knowledge_bases", "client_id")
