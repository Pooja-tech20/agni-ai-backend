
"""Resolve and retrieve Knowledge Base context for voice calls."""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.agent import Agent
from app.models.call import Call

from app.services.knowledge.retrieval import (
    retrieve_knowledge,
    build_knowledge_context,
)
from app.services.knowledge.keyword_retrieval import (
    retrieve_by_keywords,
)
from app.services.knowledge.query_translation import (
    needs_translation,
    translate_query_to_english,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceKnowledgeContext:
    enabled: bool = False
    context: str = ""
    chunk_count: int = 0
    failed: bool = False


def extract_knowledge_base_ids(
    config: list | None,
) -> list[uuid.UUID]:
    """Extract valid Knowledge Base IDs from agent configuration."""

    ids = []

    for item in config or []:

        if not isinstance(item, dict):
            continue

        try:
            kb_id = uuid.UUID(str(item.get("id")))

        except (ValueError, TypeError, AttributeError):
            continue

        if kb_id not in ids:
            ids.append(kb_id)

    return ids


def resolve_voice_context(
    db: Session,
    call_id: uuid.UUID,
    query: str,
) -> VoiceKnowledgeContext:
    """Retrieve knowledge using the call's authorized agent."""

    row = db.execute(
        select(
            Call.client_id,
            Agent.knowledge_base,
        )
        .join(
            Agent,
            Agent.id == Call.agent_id,
        )
        .where(
            Call.id == call_id,
            Call.status == "in_progress",
            Agent.client_id == Call.client_id,
            Agent.status == "active",
        )
    ).one_or_none()

    if row is None:
        return VoiceKnowledgeContext()

    client_id, knowledge_base_config = row

    knowledge_base_ids = extract_knowledge_base_ids(
        knowledge_base_config
    )

    if not knowledge_base_ids:
        return VoiceKnowledgeContext()



    # Stage 1: Direct semantic retrieval.
    chunks = retrieve_knowledge(
        db=db,
        query=query,
        client_id=client_id,
        knowledge_base_ids=knowledge_base_ids,
    )

    search_query = query
    retrieval_method = "semantic" if chunks else "none"

    # Stage 2: Multilingual query rewriting.
    if not chunks and needs_translation(query):

        translated_query = translate_query_to_english(
            query
        )

        if translated_query:

            search_query = translated_query

            logger.info(
                "Voice RAG using multilingual query fallback."
            )

            chunks = retrieve_knowledge(
                db=db,
                query=search_query,
                client_id=client_id,
                knowledge_base_ids=knowledge_base_ids,
            )

            if chunks:
                retrieval_method = "translated_semantic"

    # Stage 3: Keyword fallback.
    if not chunks:

        chunks = retrieve_by_keywords(
            db=db,
            query=search_query,
            client_id=client_id,
            knowledge_base_ids=knowledge_base_ids,
        )

        if chunks:
            retrieval_method = "keyword"

    logger.info(
        "Voice RAG retrieval method: %s",
        retrieval_method,
    )

    context = build_knowledge_context(chunks)



    logger.info(
        "Voice RAG retrieval: call=%s chunks=%s",
        call_id,
        len(chunks),
    )

    return VoiceKnowledgeContext(
        enabled=True,
        context=context,
        chunk_count=len(chunks),
    )


def get_voice_knowledge_context(
    call_id: str | None,
    query: str,
) -> VoiceKnowledgeContext:
    """Retrieve voice knowledge using an independent DB session."""

    if not call_id or not query.strip():
        return VoiceKnowledgeContext()

    try:
        parsed_call_id = uuid.UUID(str(call_id))

        with SessionLocal() as db:

            return resolve_voice_context(
                db=db,
                call_id=parsed_call_id,
                query=query,
            )

    except Exception:

        logger.exception(
            "Voice Knowledge Base retrieval failed."
        )

        return VoiceKnowledgeContext(
            failed=True,
        )
