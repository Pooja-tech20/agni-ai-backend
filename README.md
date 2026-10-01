# Agni AI Backend — Day 1 Setup

Combined deliverable for:
- **Dev 1 (Pooja)** — FastAPI Backend Foundation
- **Dev 2 (Devita)** — PostgreSQL Database Foundation

Both tracks are merged into one working project, per the "Dev 1's base
structure if merging immediately" dependency.

## Project structure

```
agni_ai/
├── app/
│   ├── main.py                # FastAPI app, CORS, router mounting
│   ├── core/
│   │   └── config.py          # Settings loaded from .env
│   ├── db/
│   │   └── session.py         # SQLAlchemy engine, Base, get_db dependency
│   ├── models/                # clients, agents, calls, call_messages, users
│   ├── schemas/                # Pydantic base + health schemas
│   ├── services/
│   │   └── base_service.py    # Generic CRUD base for future services
│   └── api/
│       └── v1/
│           ├── health.py      # /health and /health/db
│           └── router.py      # v1 router aggregator
├── alembic/                    # migrations (env.py wired to app settings + models)
├── requirements.txt
├── .env.example                # copy to .env
└── .gitignore
```

## 1. Common setup (all 6 devs)

```bash
# clone the repo, then:
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env            # then edit .env with your local Postgres creds
```

## 2. Database setup (Devita's track)

```bash
# create the dev database (adjust user as needed)
createdb agni_ai_dev
# or from psql:
# CREATE DATABASE agni_ai_dev;
```

Make sure `.env` matches your local Postgres user/password/host/port and
that `POSTGRES_DB=agni_ai_dev`.

Run the migration:

```bash
alembic upgrade head
```

This creates all 5 initial tables: `users`, `clients`, `agents`, `calls`,
`call_messages`.

To generate a new migration after changing models:

```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

## 3. Run the API (Pooja's track)

```bash
uvicorn app.main:app --reload
```

Then open:
- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- DB connectivity check: http://localhost:8000/health/db

## End-of-day checklist

- [x] `uvicorn app.main:app --reload` starts with no errors
- [x] Swagger UI opens at `/docs`
- [x] `alembic upgrade head` runs the initial migration successfully
- [x] `/health/db` confirms FastAPI can read from Postgres
- [x] A test record can be inserted and read back via SQLAlchemy (see below)

### Quick manual DB read/write test

```bash
python3 -c "
from app.db.session import SessionLocal
from app.models import Client

db = SessionLocal()
c = Client(name='Test Client', email='test@example.com')
db.add(c); db.commit(); db.refresh(c)
print('Inserted:', c.id)
print('Read back:', db.query(Client).filter(Client.id == c.id).first().name)
db.delete(c); db.commit()
"
```

## Day 2 / Day 3 — Voice agent pipeline

Adds the voice-agent request path on top of the Day 1 foundation, reusing
the existing `Call` / `CallMessage` tables as the durable record of each
session's conversation.

```
app/
├── core/
│   ├── exceptions.py     # AppError hierarchy + structured JSON error handlers
│   ├── logging.py        # centralized logging, request/session-id correlation
│   └── middleware.py     # RequestIDMiddleware — logs + tags every request
├── schemas/
│   └── voice.py          # request/response validation for all /voice/* routes
├── services/
│   ├── session_manager.py       # session IDs + in-memory session state/lifecycle
│   ├── stt_service.py           # STT provider interface (+ mock)
│   ├── llm_service.py           # LLM provider interface (+ mock)
│   ├── tts_service.py           # TTS provider interface (+ mock, incl. streaming)
│   ├── conversation_memory.py   # reads/writes CallMessage as conversation history
│   └── voice_agent_controller.py  # orchestrates session -> STT -> memory -> LLM -> TTS
└── api/v1/
    └── voice.py          # /voice/session, /voice/audio, /voice/message, streaming WS
```

### Endpoints

- `POST /api/v1/voice/session` — starts a session: creates a `Call` row and
  an in-memory session with a fresh `session_id`.
- `POST /api/v1/voice/audio` — one turn of session → audio → STT →
  conversation memory → LLM → TTS. Audio is sent/returned as base64 JSON.
- `POST /api/v1/voice/message` — text-only turn (skips STT/TTS): session →
  memory → LLM. Handy for testing the LLM/memory wiring without audio.
- `GET /api/v1/voice/session/{session_id}/history` — full conversation
  transcript for a session.
- `POST /api/v1/voice/session/{session_id}/end` — ends the session, marks
  the `Call` completed, records duration.
- `WS /api/v1/voice/session/{session_id}/stream` — the full-duplex
  controller: streams STT transcript, LLM reply, and TTS audio chunks over
  one connection, and supports **interruption/barge-in** — new caller audio
  arriving while the agent is "speaking" cancels the in-flight TTS stream
  and emits `{"type": "interrupted"}`.

### Errors

Every error — validation, a missing/expired session, or a pipeline-stage
failure — comes back in one shape:

```json
{
  "error": { "code": "SESSION_NOT_FOUND", "message": "...", "details": {} },
  "request_id": "abc123"
}
```

`X-Request-ID` is also set on every response and matches the request/session
IDs in the server logs, so a failure can be traced end-to-end.

### Swapping in real providers

STT/LLM/TTS are behind small abstract interfaces
(`app/services/{stt,llm,tts}_service.py`) with a `Mock*Service` used by
default (`STT_PROVIDER=mock` / `LLM_PROVIDER=mock` / `TTS_PROVIDER=mock` in
`.env`). Implement the interface against a real vendor SDK, register it in
that file's `get_*_service()` factory, and flip the corresponding
`*_PROVIDER` setting — nothing else in the app needs to change.

### Try it

```bash
uvicorn app.main:app --reload
```

```bash
# 1. Create a client + agent first (see the quick DB test in the section above),
#    then start a session:
curl -X POST localhost:8000/api/v1/voice/session \
  -H "Content-Type: application/json" \
  -d '{"client_id": "<uuid>", "agent_id": "<uuid>"}'

# 2. Send a text turn:
curl -X POST localhost:8000/api/v1/voice/message \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session_id>", "text": "Hello!"}'
```

## Notes for the rest of the team

- Add new resource routers under `app/api/v1/` and register them in
  `app/api/v1/router.py` — don't touch `app/main.py` for new routes.
- Add new models under `app/models/` and import them in
  `app/models/__init__.py` so Alembic picks them up.
- All config (DB creds, CORS origins, etc.) comes from `.env` via
  `app/core/config.py` — never hardcode connection strings.
- CORS origins for local frontend dev are set via `CORS_ORIGINS` in `.env`
  (comma-separated).
