"""
Conversation memory for a voice session.

Rather than inventing a new store, this reuses the `CallMessage` table
already defined on Day 1 (app/models/call_message.py) — a voice session's
transcript *is* the call's message history. That gives us durability for
free (survives process restarts) and keeps the DB as the single source of
truth for what was actually said.
"""
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.call_message import CallMessage

logger = get_logger(__name__)


class ConversationMemoryService:
    def __init__(self, db: Session):
        self.db = db

    def add_message(self, call_id: uuid.UUID, role: str, content: str) -> CallMessage:
        message = CallMessage(call_id=call_id, role=role, content=content)
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_history(self, call_id: uuid.UUID, limit: int | None = None) -> list[CallMessage]:
        limit = limit or settings.MAX_CONVERSATION_HISTORY
        rows = (
            self.db.query(CallMessage)
            .filter(CallMessage.call_id == call_id)
            .order_by(CallMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))  # oldest -> newest, ready for the LLM

    @staticmethod
    def format_for_llm(history: list[CallMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in history]
