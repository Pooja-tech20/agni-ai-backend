
"""Keyword fallback for authorized Knowledge Base retrieval."""

import logging
import re
import uuid

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeSource,
)
from app.models.knowledge_chunk import KnowledgeChunk

from app.services.knowledge.retrieval import RetrievedChunk


logger = logging.getLogger(__name__)


QUERY_SYNONYMS = (
    (r"\bcustomer service\b", "support"),
    (r"\bcustomer support\b", "support"),
    (r"\bopening times?\b", "hours"),
    (r"\bopening hours\b", "hours"),
    (r"\boperating hours\b", "hours"),
    (r"\bsupport timings?\b", "support hours"),
    (r"\brefund processing time\b", "refund period"),
    (r"\brefund processing duration\b", "refund period"),
    (r"\brefund waiting period\b", "refund period"),
)


def normalize_search_query(query: str) -> str:
    """Normalize common business terminology."""

    query = query.strip().lower()

    for pattern, replacement in QUERY_SYNONYMS:

        query = re.sub(
            pattern,
            replacement,
            query,
        )

    query = re.sub(r"\s+", " ", query)

    query = re.sub(
        r"\s+starting at what time\??$",
        "",
        query,
    )

    return query.strip()


def retrieve_by_keywords(
    db: Session,
    query: str,
    client_id: uuid.UUID,
    knowledge_base_ids: list[uuid.UUID],
    top_k: int = 4,
) -> list[RetrievedChunk]:
    """Retrieve keyword matches from authorized sources."""

    query = normalize_search_query(query)

    if not query or not knowledge_base_ids:
        return []

    if client_id is None:
        raise ValueError("Organization ID is required.")

    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

    language = literal_column("'english'::regconfig")

    document = func.to_tsvector(
        language,
        KnowledgeChunk.content,
    )

    search_query = func.plainto_tsquery(
        language,
        query,
    )

    rank = func.ts_rank(
        document,
        search_query,
    ).label("keyword_rank")

    statement = (
        select(
            KnowledgeChunk,
            KnowledgeSource.title,
            rank,
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
            KnowledgeChunk.knowledge_base_id.in_(
                knowledge_base_ids
            ),
            KnowledgeBase.client_id == client_id,
            KnowledgeBase.status == "active",
            KnowledgeSource.status == "active",
            KnowledgeSource.knowledge_base_id
            == KnowledgeChunk.knowledge_base_id,
            document.op("@@")(search_query),
        )
        .order_by(
            rank.desc(),
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

                # Keyword rank is not cosine similarity.
                # Keep this field neutral.
                similarity=0.0,
            )
        )

    logger.info(
        "Knowledge keyword retrieval completed: %s chunks",
        len(results),
    )

    return results
