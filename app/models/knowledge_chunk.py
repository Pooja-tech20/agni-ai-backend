import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import (
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class KnowledgeChunk(
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
):
    __tablename__ = "knowledge_chunks"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "chunk_index",
            name="uq_knowledge_chunk_source_index",
        ),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge_bases.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge_sources.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    embedding: Mapped[list[float]] = mapped_column(
        Vector(1536),
        nullable=False,
    )

    embedding_model: Mapped[str] = mapped_column(
        String(100),
        default="text-embedding-3-small",
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeChunk "
            f"source={self.source_id} "
            f"index={self.chunk_index}>"
        )