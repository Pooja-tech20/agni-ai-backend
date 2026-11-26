
"""OpenAI embedding generation for Knowledge Base RAG."""

import math
import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
EMBEDDING_BATCH_SIZE = 32


class KnowledgeEmbeddingError(Exception):
    """Raised when embedding generation fails."""


@lru_cache(maxsize=1)
def get_embedding_client() -> OpenAI:
    """Initialize and reuse the OpenAI client."""

    load_dotenv(".env", override=False)
    load_dotenv(".env.local", override=False)

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise KnowledgeEmbeddingError(
            "OpenAI API key is not configured."
        )

    return OpenAI(
        api_key=api_key,
        timeout=15.0,
        max_retries=1,
    )


def validate_embedding(
    embedding: list[float],
) -> None:
    """Validate the generated embedding."""

    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise KnowledgeEmbeddingError(
            "Unexpected embedding dimensions."
        )

    if not all(math.isfinite(value) for value in embedding):
        raise KnowledgeEmbeddingError(
            "Embedding contains invalid values."
        )

    if not any(embedding):
        raise KnowledgeEmbeddingError(
            "Embedding must not be a zero vector."
        )


def generate_embeddings(
    texts: list[str],
) -> list[list[float]]:
    """Generate embeddings in batches."""

    if not texts:
        return []

    if any(not text.strip() for text in texts):
        raise KnowledgeEmbeddingError(
            "Cannot generate embeddings for empty text."
        )

    client = get_embedding_client()
    embeddings = []

    try:
        for start in range(
            0,
            len(texts),
            EMBEDDING_BATCH_SIZE,
        ):

            batch = texts[
                start:start + EMBEDDING_BATCH_SIZE
            ]

            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch,
                dimensions=EMBEDDING_DIMENSIONS,
                encoding_format="float",
            )

            results = sorted(
                response.data,
                key=lambda item: item.index,
            )

            if [item.index for item in results] != list(
                range(len(batch))
            ):
                raise KnowledgeEmbeddingError(
                    "Unexpected embedding response indexes."
                )

            for item in results:
                embedding = item.embedding

                validate_embedding(embedding)

                embeddings.append(embedding)

        return embeddings

    except KnowledgeEmbeddingError:
        raise

    except Exception as exc:
        raise KnowledgeEmbeddingError(
            "OpenAI embedding generation failed."
        ) from exc


def generate_embedding(
    text: str,
) -> list[float]:
    """Generate a single embedding."""

    return generate_embeddings([text])[0]
