"""
Saves the realtime conversation to the `call_messages` table.

Used by the agent subprocess (livekit_poc/audio_subscriber.py). The API sets
AGNI_SESSION_CALL_ID when it starts a session; without it (standalone CLI use)
every call here is a no-op. Writes run on one background thread so they never
block audio and are saved in order.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.db.session import SessionLocal
from app.models import CallMessage  # importing the package registers every mapper

_CALL_ID = os.getenv("AGNI_SESSION_CALL_ID") or None
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transcript")


def _save(role: str, content: str) -> None:
    try:
        with SessionLocal() as db:
            db.add(CallMessage(call_id=uuid.UUID(_CALL_ID), role=role, content=content))
            db.commit()
    except Exception as exc:  # never break the call because of logging
        print(f"[transcript] could not save message: {exc}")


def log_message(role: str, content: str | None) -> None:
    """role: 'user' or 'agent'."""
    if _CALL_ID and content and content.strip():
        _pool.submit(_save, role, content.strip())