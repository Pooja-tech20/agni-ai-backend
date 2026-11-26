
"""Extract text from Knowledge Base source documents."""

import re
from pathlib import Path

import pymupdf
from docx import Document


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
}

MAX_EXTRACTED_CHARACTERS = 2_000_000


class KnowledgeExtractionError(Exception):
    """Raised when source content cannot be extracted."""


def clean_text(text: str) -> str:
    """Normalize text while preserving useful line breaks."""

    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def validate_content(text: str) -> str:
    """Validate extracted text before ingestion."""

    text = clean_text(text)

    if not text:
        raise KnowledgeExtractionError(
            "No readable text found in the source."
        )

    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise KnowledgeExtractionError(
            "Extracted content exceeds the allowed size."
        )

    return text


def extract_pdf(file_path: Path) -> str:
    """Extract readable text from PDF pages."""

    pages = []
    total_length = 0

    with pymupdf.open(str(file_path)) as document:

        if document.needs_pass:
            raise KnowledgeExtractionError(
                "Password-protected PDFs are not supported."
            )

        for page in document:
            text = page.get_text("text")
            total_length += len(text)

            if total_length > MAX_EXTRACTED_CHARACTERS:
                raise KnowledgeExtractionError(
                    "PDF content exceeds the allowed size."
                )

            if text.strip():
                pages.append(text)

    return "\n\n".join(pages)


def extract_docx(file_path: Path) -> str:
    """Extract paragraphs and tables from Word documents."""

    document = Document(str(file_path))
    sections = []

    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            sections.append(paragraph.text)

    for table in document.tables:
        for row in table.rows:
            values = [
                cell.text.strip()
                for cell in row.cells
            ]

            sections.append(" | ".join(values))

    return "\n\n".join(sections)


def extract_plain_text(file_path: Path) -> str:
    """Extract text from TXT and Markdown files."""

    try:
        return file_path.read_text(encoding="utf-8-sig")

    except UnicodeDecodeError:
        raise KnowledgeExtractionError(
            "Text files must use UTF-8 encoding."
        )


def extract_file(file_path: str | Path) -> str:
    """Extract and validate text from a supported file."""

    path = Path(file_path)

    if not path.is_file():
        raise KnowledgeExtractionError(
            "Source file does not exist."
        )

    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise KnowledgeExtractionError(
            f"Unsupported file type: {extension}"
        )

    try:
        if extension == ".pdf":
            text = extract_pdf(path)

        elif extension == ".docx":
            text = extract_docx(path)

        else:
            text = extract_plain_text(path)

        return validate_content(text)

    except KnowledgeExtractionError:
        raise

    except Exception as exc:
        raise KnowledgeExtractionError(
            "Failed to extract source content."
        ) from exc


def extract_manual_text(content: str) -> str:
    """Validate manually entered Knowledge Base text."""

    return validate_content(content)
