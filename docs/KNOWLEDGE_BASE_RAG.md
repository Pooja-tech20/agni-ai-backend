
# Knowledge Base and RAG Integration

## 1. Overview

The Knowledge Base feature enables Agni AI voice agents to
retrieve organization-specific information from uploaded
documents, websites and manually entered text.

The implementation uses Retrieval-Augmented Generation (RAG)
to provide relevant reference information to the existing
OpenAI voice response pipeline.

## 2. Supported Knowledge Sources

- Manual text
- PDF documents
- DOCX documents
- TXT files
- Markdown files
- Website URLs

The maximum file upload size is 20 MB.

Website extraction supports publicly accessible static content.
Scanned PDFs requiring OCR are not currently supported.

## 3. Architecture

Knowledge source
    -> Text extraction
    -> Text cleaning
    -> Token-based chunking
    -> OpenAI embeddings
    -> PostgreSQL / pgvector storage

Voice pipeline:

Microphone
    -> LiveKit
    -> Deepgram STT
    -> Authorized Knowledge Base retrieval
    -> OpenAI LLM
    -> ElevenLabs TTS
    -> LiveKit audio playback

## 4. Technology Stack

- FastAPI
- PostgreSQL
- pgvector
- SQLAlchemy
- Alembic
- OpenAI text-embedding-3-small
- PyMuPDF
- python-docx
- BeautifulSoup
- tiktoken
- certifi

## 5. Retrieval Configuration

- Embedding dimensions: 1536
- Target chunk size: 500 tokens
- Chunk overlap: 100 tokens
- Default top-k: 4
- Minimum cosine similarity: 0.30
- Maximum context length: 12000 characters

Retrieval stages:

1. Direct semantic vector retrieval.
2. Multilingual query rewriting when required.
3. Semantic retrieval using the rewritten query.
4. Normalized PostgreSQL full-text keyword fallback.

Each fallback runs only when the previous search returns
no matching chunks.

The original user transcript is preserved for response generation.

## 6. Database Setup

PostgreSQL must have the pgvector extension available.

A tested development image is:

    pgvector/pgvector:pg18-trixie

The database account running migrations must have permission
to create the vector extension, or an administrator must
provision the extension beforehand.

Install dependencies:

    python -m pip install -r requirements.txt

Back up the target database before applying migrations.

Verify migration history:

    python -m alembic current
    python -m alembic heads

Apply migrations:

    python -m alembic upgrade head

New migration revisions:

- 5efd644511b2: Knowledge chunks and vector storage.
- ce5a4cc56e3e: Knowledge source processing status.

Existing Knowledge Base sources may require reprocessing
to generate embeddings.

Do not apply these migrations to shared or production
databases without coordinating with the backend team.

## 7. Environment Configuration

Required existing configuration:

- DATABASE_URL
- OPENAI_API_KEY
- Existing LiveKit configuration
- Existing Deepgram configuration
- Existing ElevenLabs configuration

Optional RAG configuration:

    KNOWLEDGE_UPLOAD_ROOT=uploads/knowledge_base
    RUN_KNOWLEDGE_RECOVERY=false
    KNOWLEDGE_TRANSLATION_MODEL=<supported OpenAI model>

RUN_KNOWLEDGE_RECOVERY enables startup recovery of pending
and interrupted source-processing jobs.

Enable recovery only in a coordinated single-instance
deployment with no competing ingestion workers.

Uploaded documents and database credentials must not
be committed to Git.

## 8. API Integration

Base path:

    /api/v1/knowledge-bases

Existing Knowledge Base CRUD endpoints are preserved.

Add manual text or website URL:

    POST /{knowledge_base_id}/sources

Upload a document using multipart/form-data:

    POST /{knowledge_base_id}/sources/upload

List knowledge sources:

    GET /{knowledge_base_id}/sources

Delete a source:

    DELETE /{knowledge_base_id}/sources/{source_id}

Retry or reprocess an existing source:

    POST /{knowledge_base_id}/sources/{source_id}/reprocess

The reprocess endpoint returns HTTP 202 Accepted.

Source creation and file upload return HTTP 201 Created,
but indexing may still be running in the background.

## 9. Source Processing Status

Knowledge source responses include:

- processing_status
- processing_error
- chunk_count

Processing status values:

- pending
- processing
- completed
- failed

The frontend should poll the source listing endpoint to
check indexing progress.

A completed source indicates successful indexing.

Failed sources can be reprocessed after correcting the
underlying problem.

Existing indexed content may remain available during
reprocessing.

## 10. Agent Integration

Knowledge Bases are attached through the existing agent
configuration APIs.

The voice runtime resolves the active call, associated
agent, organization and attached Knowledge Base IDs.

Only authorized, active Knowledge Bases and active
sources are eligible for retrieval.

Agents without Knowledge Bases bypass embedding,
translation and keyword retrieval requests.

Existing voice session API contracts are preserved.

## 11. Security

- Organization-level Knowledge Base isolation.
- Active agent, Knowledge Base and source validation.
- Restricted file extensions and upload size.
- Website URL and redirect validation.
- Private and restricted network addresses blocked.
- Retrieved content is treated as untrusted reference data.
- Local uploaded documents excluded from Git.
- Source deletion cascades to associated knowledge chunks.

Prompt instructions reduce document-based prompt injection
risk but are not a complete security guarantee.

Production deployments should also enforce network
egress restrictions and appropriate data access controls.

## 12. Testing Completed

Verified in an isolated PostgreSQL development database:

- All six supported knowledge input types.
- Automatic source extraction and indexing.
- OpenAI embedding generation.
- Vector similarity retrieval.
- Keyword retrieval and normalization.
- Unauthorized organization rejection.
- Source reprocessing.
- Source deletion and chunk cleanup.
- Interrupted ingestion recovery.
- Knowledge Base attachment to agents.
- Actual microphone-to-speaker RAG responses.
- English, Hindi, Hinglish and partial Marathi retrieval.
- Barge-in compatibility.
- Agent voice conversation without Knowledge Base.
- No-KB embedding and translation bypass.

Keyword retrieval tests: 9/9 passed.
Keyword normalization tests: 5/5 passed.
No-KB service regression tests: passed.

## 13. Known Limitations

- Multilingual speech recognition can misrecognize
  company names and Hindi or Marathi utterances.
- Multilingual query rewriting is not deterministic.
- Some valid paraphrased queries may return no results.
- Translation fallback increases API usage and latency.
- Retrieved information must be interpreted accurately;
  related policy terms must not be treated as equivalent.
- Keyword normalization currently covers selected
  business terminology.
- Current vector and keyword searches may require
  additional indexing for large Knowledge Bases.
- Website extraction does not execute JavaScript or
  perform authenticated crawling.
- Background ingestion is not a durable distributed queue.
- Startup recovery is intended for coordinated
  single-instance operation.
- Actual frontend browser integration remains unverified.
- Telephony and text chatbot RAG integration have not
  been verified as part of this implementation.
- Full platform regression and SQLite compatibility
  require verification.

## 14. Deployment Checklist

- Install updated Python dependencies.
- Provision PostgreSQL with pgvector support.
- Back up the database.
- Review Alembic migration history.
- Apply the new migrations.
- Configure persistent document storage.
- Configure OpenAI credentials securely.
- Coordinate background ingestion and recovery.
- Reprocess existing Knowledge Base sources.
- Verify source processing completion.
- Test an agent with an attached Knowledge Base.
- Test an agent without an attached Knowledge Base.
- Verify frontend integration and organization isolation.

## 15. Implementation Status

The core Knowledge Base RAG feature is implemented
and verified through actual voice conversations.

Production scalability, multilingual retrieval consistency,
answer grounding and frontend integration remain areas
for further validation and improvement.


## 16. Existing Backend Regression Results

- Knowledge Base security: 6/6 passed.
- Platform regression: 47/47 passed.
- Authentication: 18/18 passed.
- Call analysis: 16/16 passed.
- Agent functions: 41/42 passed.

Total: 128/129 passed.

The remaining Functions API test failure is associated
with corrupted masked-secret characters already present
in baseline revision fdd661d.

The affected test and Functions API files were verified
to be unchanged by the RAG implementation.

Windows timezone support was resolved by adding tzdata.

Regression tests were executed using isolated in-memory
SQLite databases without modifying development databases.

## Main Database Integration

The original local PostgreSQL container was upgraded
to pgvector/pgvector:pg18-trixie.

- Container: agni-postgres
- PostgreSQL: 18.7
- pgvector: 0.8.7
- Port: 5432
- Database: agni_ai_dev
- Original persistent volume: agni_postgres_data
- Migration revision: ce5a4cc56e3e

Existing database record counts were preserved.
Knowledge indexing and semantic retrieval were
successfully verified on the main database.

A separate RAG database is no longer required.