
"""Knowledge Base ingestion and vector storage."""

import os
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.db.session import SessionLocal

from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeSource,
)
from app.models.knowledge_chunk import KnowledgeChunk

from app.services.knowledge.extractor import (
    extract_file,
    extract_manual_text,
)
from app.services.knowledge.website import extract_website
from app.services.knowledge.chunker import chunk_text

from app.services.knowledge.embeddings import (
    EMBEDDING_MODEL,
    generate_embeddings,
)


logger = logging.getLogger(__name__)

UPLOAD_ROOT = Path(
    os.getenv(
        "KNOWLEDGE_UPLOAD_ROOT",
        "uploads/knowledge_base",
    )
)


class KnowledgeIngestionError(Exception):
    """Raised when source ingestion fails."""


def extract_source_content(
    source: KnowledgeSource,
) -> str:
    """Extract content according to source type."""

    if source.source_type == "text":

        return extract_manual_text(
            source.content or ""
        )

    if source.source_type == "url":

        if not source.url:
            raise KnowledgeIngestionError(
                "Source URL is missing."
            )

        return extract_website(source.url)

    if source.source_type == "file":

        if not source.file_name:
            raise KnowledgeIngestionError(
                "Source filename is missing."
            )

        extension = Path(
            source.file_name
        ).suffix.lower()

        file_path = (
            UPLOAD_ROOT
            / str(source.knowledge_base_id)
            / f"{source.id}{extension}"
        )

        return extract_file(file_path)

    raise KnowledgeIngestionError(
        "Unsupported knowledge source type."
    )


def ingest_source(
    db: Session,
    source_id: uuid.UUID,
    client_id: uuid.UUID,
) -> dict:
    """Process and store embeddings for an owned source."""

    try:
        source = db.scalar(
            select(KnowledgeSource)
            .join(
                KnowledgeBase,
                KnowledgeBase.id
                == KnowledgeSource.knowledge_base_id,
            )
            .where(
                KnowledgeSource.id == source_id,
                KnowledgeBase.client_id == client_id,
                KnowledgeBase.status == "active",
            )
            .with_for_update(of=KnowledgeSource)
        )

        if source is None:
            raise KnowledgeIngestionError(
                "Active knowledge source not found."
            )

        if source.status != "active":
            raise KnowledgeIngestionError(
                "Knowledge source is inactive."
            )

        # Extract readable source content.
        content = extract_source_content(source)

        # Split content into searchable chunks.
        chunks = chunk_text(content)

        if not chunks:
            raise KnowledgeIngestionError(
                "No chunks generated from source."
            )

        # Generate embeddings before replacing old chunks.
        embeddings = generate_embeddings(
            [chunk.content for chunk in chunks]
        )

        if len(embeddings) != len(chunks):
            raise KnowledgeIngestionError(
                "Chunk and embedding counts do not match."
            )

        # Replace previous chunks atomically.
        db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.source_id == source.id
            )
        )

        for chunk, embedding in zip(
            chunks,
            embeddings,
        ):

            record = KnowledgeChunk(
                knowledge_base_id=source.knowledge_base_id,
                source_id=source.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                embedding=embedding,
                embedding_model=EMBEDDING_MODEL,
            )

            db.add(record)

        source.processing_status = "completed"
        source.processing_error = None
        source.chunk_count = len(chunks)
        result = {
            "source_id": str(source.id),
            "knowledge_base_id": str(
                source.knowledge_base_id
            ),
            "chunks_created": len(chunks),
            "total_tokens": sum(
                chunk.token_count
                for chunk in chunks
            ),
            "embedding_model": EMBEDDING_MODEL,
            "status": "completed",
        }

        db.commit()

        logger.info(
            "Knowledge source %s ingested: %s chunks",
            source_id,
            len(chunks),
        )

        return result

    except KnowledgeIngestionError:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Knowledge ingestion failed for source %s",
            source_id,
        )

        raise KnowledgeIngestionError(
            "Knowledge source ingestion failed."
        ) from exc


def process_source_background(
    source_id: uuid.UUID,
    client_id: uuid.UUID,
) -> None:
    """Process a queued knowledge source in a separate session."""

    with SessionLocal() as db:

        try:
            source = db.scalar(
                select(KnowledgeSource)
                .join(
                    KnowledgeBase,
                    KnowledgeBase.id
                    == KnowledgeSource.knowledge_base_id,
                )
                .where(
                    KnowledgeSource.id == source_id,
                    KnowledgeBase.client_id == client_id,
                    KnowledgeBase.status == "active",
                    KnowledgeSource.status == "active",
                    KnowledgeSource.processing_status == "pending",
                )
                .with_for_update(of=KnowledgeSource)
            )

            if source is None:
                return

            source.processing_status = "processing"
            source.processing_error = None

            db.commit()

            ingest_source(
                db=db,
                source_id=source_id,
                client_id=client_id,
            )

            logger.info(
                "Background knowledge processing completed: %s",
                source_id,
            )

        except Exception:

            db.rollback()

            logger.exception(
                "Background knowledge processing failed: %s",
                source_id,
            )

            try:
                failed_source = db.scalar(
                    select(KnowledgeSource)
                    .join(
                        KnowledgeBase,
                        KnowledgeBase.id
                        == KnowledgeSource.knowledge_base_id,
                    )
                    .where(
                        KnowledgeSource.id == source_id,
                        KnowledgeBase.client_id == client_id,
                        KnowledgeSource.processing_status
                        == "processing",
                    )
                    .with_for_update(of=KnowledgeSource)
                )

                if failed_source is not None:

                    failed_source.processing_status = "failed"

                    failed_source.processing_error = (
                        "Knowledge processing failed. "
                        "Check the source and retry."
                    )

                    db.commit()

            except Exception:

                db.rollback()

                logger.exception(
                    "Could not update knowledge processing status."
                )
