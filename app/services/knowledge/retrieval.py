
"""Semantic Knowledge Base retrieval using pgvector."""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeSource,
)
from app.models.knowledge_chunk import KnowledgeChunk

from app.services.knowledge.embeddings import (
    EMBEDDING_MODEL,
    generate_embedding,
)


logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 4
DEFAULT_MIN_SIMILARITY = 0.30
MAX_CONTEXT_CHARACTERS = 12000


class KnowledgeRetrievalError(Exception):
    """Raised when knowledge retrieval fails."""


@dataclass
class RetrievedChunk:

    chunk_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    source_id: uuid.UUID
    source_title: str | None
    content: str
    similarity: float


def retrieve_knowledge(
    db: Session,
    query: str,
    client_id: uuid.UUID,
    knowledge_base_ids: list[uuid.UUID],
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> list[RetrievedChunk]:

    """Retrieve relevant chunks from owned Knowledge Bases."""

    query = query.strip()

    if not query or not knowledge_base_ids:
        return []

    if client_id is None:
        raise ValueError("Organization ID is required.")

    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

    if not 0 <= min_similarity <= 1:
        raise ValueError(
            "Similarity threshold must be between 0 and 1."
        )

    try:

        # Verify that requested Knowledge Bases
        # belong to the agent's organization.
        allowed_ids = list(
            db.scalars(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.id.in_(knowledge_base_ids),
                    KnowledgeBase.client_id == client_id,
                    KnowledgeBase.status == "active",
                )
            )
        )

        if not allowed_ids:
            return []

        # Skip embedding requests when no indexed
        # sources are available.
        filters = (
            KnowledgeChunk.knowledge_base_id.in_(allowed_ids),
            KnowledgeChunk.embedding_model == EMBEDDING_MODEL,
            KnowledgeBase.client_id == client_id,
            KnowledgeBase.status == "active",
            KnowledgeSource.status == "active",
            KnowledgeSource.knowledge_base_id
            == KnowledgeChunk.knowledge_base_id,
        )

        base_query = (
            select(KnowledgeChunk.id)
            .join(
                KnowledgeBase,
                KnowledgeBase.id
                == KnowledgeChunk.knowledge_base_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id
                == KnowledgeChunk.source_id,
            )
            .where(*filters)
        )

        if db.scalar(base_query.limit(1)) is None:
            return []

        # Generate the user question embedding.
        query_embedding = generate_embedding(query)

        distance = (
            KnowledgeChunk.embedding.cosine_distance(
                query_embedding
            )
        )

        similarity = (1 - distance).label("similarity")

        statement = (
            select(
                KnowledgeChunk,
                KnowledgeSource.title,
                similarity,
            )
            .join(
                KnowledgeBase,
                KnowledgeBase.id
                == KnowledgeChunk.knowledge_base_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id
                == KnowledgeChunk.source_id,
            )
            .where(
                *filters,
                similarity >= min_similarity,
            )
            .order_by(
                distance.asc(),
                KnowledgeChunk.id.asc(),
            )
            .limit(top_k)
        )

        rows = db.execute(statement).all()

        results = []

        for chunk, title, score in rows:

            results.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    source_id=chunk.source_id,
                    source_title=title,
                    content=chunk.content,
                    similarity=float(score),
                )
            )

        logger.info(
            "Knowledge retrieval completed: %s chunks",
            len(results),
        )

        return results

    except Exception as exc:

        logger.exception(
            "Knowledge retrieval failed."
        )

        raise KnowledgeRetrievalError(
            "Failed to retrieve Knowledge Base information."
        ) from exc


def build_knowledge_context(
    chunks: list[RetrievedChunk],
) -> str:

    """Format retrieved knowledge for the LLM."""

    if not chunks:
        return ""

    sections = []
    total_length = 0

    for index, chunk in enumerate(chunks, start=1):

        title = chunk.source_title or "Knowledge source"

        section = (
            f"[Source {index}: {title}]\n"
            f"{chunk.content}"
        )

        separator_length = 2 if sections else 0

        if (
            total_length
            + len(section)
            + separator_length
            > MAX_CONTEXT_CHARACTERS
        ):
            break

        sections.append(section)

        total_length += (
            len(section) + separator_length
        )

    return "\n\n".join(sections)
