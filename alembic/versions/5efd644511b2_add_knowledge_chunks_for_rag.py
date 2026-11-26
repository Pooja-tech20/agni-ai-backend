
"""Add knowledge chunks for RAG.

Revision ID: 5efd644511b2
Revises: 9a1b2c3d4e5f
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "5efd644511b2"
down_revision: Union[str, None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # Enable pgvector if it is not already enabled.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create the RAG knowledge chunks table.
    op.create_table(
        "knowledge_chunks",

        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),

        sa.Column(
            "knowledge_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "knowledge_bases.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),

        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "knowledge_sources.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),

        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "token_count",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "embedding",
            Vector(1536),
            nullable=False,
        ),

        sa.Column(
            "embedding_model",
            sa.String(100),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),

        sa.UniqueConstraint(
            "source_id",
            "chunk_index",
            name="uq_knowledge_chunk_source_index",
        ),
    )

    # Indexes for efficient Knowledge Base filtering.
    op.create_index(
        "ix_knowledge_chunks_knowledge_base_id",
        "knowledge_chunks",
        ["knowledge_base_id"],
    )

    op.create_index(
        "ix_knowledge_chunks_source_id",
        "knowledge_chunks",
        ["source_id"],
    )


def downgrade() -> None:

    op.drop_index(
        "ix_knowledge_chunks_source_id",
        table_name="knowledge_chunks",
    )

    op.drop_index(
        "ix_knowledge_chunks_knowledge_base_id",
        table_name="knowledge_chunks",
    )

    op.drop_table("knowledge_chunks")

    # Keep pgvector installed because other features
    # may depend on the extension.
