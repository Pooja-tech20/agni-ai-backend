
"""Recovery of interrupted Knowledge Base ingestion jobs."""

import logging

from sqlalchemy import select

from app.db.session import SessionLocal

from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeSource,
)

from app.services.knowledge.ingestion import (
    process_source_background,
)


logger = logging.getLogger(__name__)


def recover_interrupted_sources() -> int:
    """Recover interrupted jobs during single-instance startup."""

    with SessionLocal() as db:

        rows = db.execute(
            select(
                KnowledgeSource,
                KnowledgeBase.client_id,
            )
            .join(
                KnowledgeBase,
                KnowledgeBase.id
                == KnowledgeSource.knowledge_base_id,
            )
            .where(
                KnowledgeBase.client_id.is_not(None),
                KnowledgeBase.status == "active",
                KnowledgeSource.status == "active",
                KnowledgeSource.processing_status.in_(
                    ["pending", "processing"]
                ),
            )
            .with_for_update(of=KnowledgeSource)
        ).all()

        jobs = []

        for source, client_id in rows:

            source.processing_status = "pending"
            source.processing_error = None

            jobs.append(
                (source.id, client_id)
            )

        db.commit()

    if not jobs:

        logger.info(
            "No interrupted knowledge sources found."
        )

        return 0

    logger.info(
        "Recovering %s interrupted knowledge sources.",
        len(jobs),
    )

    for source_id, client_id in jobs:

        process_source_background(
            source_id,
            client_id,
        )

    return len(jobs)
