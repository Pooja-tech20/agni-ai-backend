
"""Token-based chunking for Knowledge Base content."""

from dataclasses import dataclass

import tiktoken


CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

TOKENIZER = tiktoken.get_encoding("cl100k_base")


@dataclass
class TextChunk:
    chunk_index: int
    content: str
    token_count: int


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:

    if chunk_size <= 0:
        raise ValueError(
            "Chunk size must be greater than zero."
        )

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            "Overlap must be smaller than chunk size."
        )

    text = text.strip()

    if not text:
        return []

    tokens = TOKENIZER.encode(
        text,
        disallowed_special=(),
    )

    token_bytes = [
        TOKENIZER.decode_single_token_bytes(token)
        for token in tokens
    ]

    chunks = []
    start = 0
    total_tokens = len(tokens)

    def valid_boundary(index: int) -> bool:
        if index == 0 or index == total_tokens:
            return True

        first_byte = token_bytes[index][0]

        return not (0x80 <= first_byte <= 0xBF)

    while start < total_tokens:

        end = min(
            start + chunk_size,
            total_tokens,
        )

        # Preserve multilingual UTF-8 characters.
        while end > start and not valid_boundary(end):
            end -= 1

        if end == start:
            raise ValueError(
                "Chunk size is too small for this text."
            )

        content = b"".join(
            token_bytes[start:end]
        ).decode("utf-8").strip()

        if content:
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    content=content,
                    token_count=len(
                        TOKENIZER.encode(
                            content,
                            disallowed_special=(),
                        )
                    ),
                )
            )

        if end == total_tokens:
            break

        next_start = max(
            start + 1,
            end - overlap,
        )

        while next_start < end and not valid_boundary(
            next_start
        ):
            next_start += 1

        start = next_start

    return chunks
