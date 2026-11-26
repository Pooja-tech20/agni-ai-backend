
"""Add knowledge source processing status.

Revision ID: ce5a4cc56e3e
Revises: 5efd644511b2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ce5a4cc56e3e"
down_revision: Union[str, None] = "5efd644511b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.add_column(
        "knowledge_sources",
        sa.Column(
            "processing_status",
            sa.String(30),
            server_default="pending",
            nullable=False,
        ),
    )

    op.add_column(
        "knowledge_sources",
        sa.Column(
            "processing_error",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "knowledge_sources",
        sa.Column(
            "chunk_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )

    # Backfill sources that have already been indexed.
    op.execute(
        """
        UPDATE knowledge_sources AS source
        SET
            processing_status = 'completed',
            processing_error = NULL,
            chunk_count = indexed.total
        FROM (
            SELECT
                source_id,
                COUNT(*)::integer AS total
            FROM knowledge_chunks
            GROUP BY source_id
        ) AS indexed
        WHERE source.id = indexed.source_id
        """
    )


def downgrade() -> None:

    op.drop_column(
        "knowledge_sources",
        "chunk_count",
    )

    op.drop_column(
        "knowledge_sources",
        "processing_error",
    )

    op.drop_column(
        "knowledge_sources",
        "processing_status",
    )
