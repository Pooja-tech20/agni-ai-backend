"""
Voice session lifecycle + runtime state.

A "voice session" is the live, in-memory counterpart of a `Call` DB row
(app/models/call.py). The DB row is the durable record (who called whom,
when, final status); this manager tracks the things that only matter while
the call is actually happening: is the agent currently speaking (needed for
barge-in), how many turns have happened, last-activity time for timeout
detection, etc.

Kept as a simple in-process dict behind a lock. For a multi-worker
deployment this would move to Redis, but the interface below is written so
that swap is a drop-in (nothing outside this module touches the dict).
"""
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.core.config import settings
from app.core.exceptions import (
    SessionAlreadyEndedError,
    SessionExpiredError,
    SessionNotFoundError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"
    ERROR = "error"


@dataclass
class SessionState:
    session_id: str
    call_id: uuid.UUID
    client_id: uuid.UUID
    agent_id: uuid.UUID
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    turn_count: int = 0
    # Barge-in support: true while TTS audio is (conceptually) being played to the caller.
    is_agent_speaking: bool = False
    metadata: dict = field(default_factory=dict)


class SessionManager:
    def __init__(self, timeout_seconds: int | None = None):
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._timeout_seconds = timeout_seconds or settings.SESSION_TIMEOUT_SECONDS

    def create_session(
        self, call_id: uuid.UUID, client_id: uuid.UUID, agent_id: uuid.UUID, metadata: dict | None = None
    ) -> SessionState:
        session_id = uuid.uuid4().hex
        state = SessionState(
            session_id=session_id,
            call_id=call_id,
            client_id=client_id,
            agent_id=agent_id,
            metadata=metadata or {},
        )
        with self._lock:
            self._sessions[session_id] = state
        logger.info("Session created session_id=%s call_id=%s", session_id, call_id)
        return state

    def get_session(self, session_id: str, *, touch: bool = True) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                raise SessionNotFoundError(f"No active session with id '{session_id}'")

            if state.status == SessionStatus.ENDED:
                raise SessionAlreadyEndedError(f"Session '{session_id}' has already ended")

            if self._is_expired(state):
                state.status = SessionStatus.ERROR
                raise SessionExpiredError(
                    f"Session '{session_id}' timed out after {self._timeout_seconds}s of inactivity"
                )

            if touch:
                state.last_activity_at = datetime.now(timezone.utc)
            return state

    def _is_expired(self, state: SessionState) -> bool:
        elapsed = (datetime.now(timezone.utc) - state.last_activity_at).total_seconds()
        return elapsed > self._timeout_seconds

    def increment_turn(self, session_id: str) -> int:
        with self._lock:
            state = self._sessions[session_id]
            state.turn_count += 1
            return state.turn_count

    def set_agent_speaking(self, session_id: str, speaking: bool) -> None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state:
                state.is_agent_speaking = speaking

    def is_agent_speaking(self, session_id: str) -> bool:
        with self._lock:
            state = self._sessions.get(session_id)
            return bool(state and state.is_agent_speaking)

    def end_session(self, session_id: str) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                raise SessionNotFoundError(f"No active session with id '{session_id}'")
            if state.status == SessionStatus.ENDED:
                raise SessionAlreadyEndedError(f"Session '{session_id}' has already ended")
            state.status = SessionStatus.ENDED
            state.is_agent_speaking = False
            logger.info("Session ended session_id=%s turns=%s", session_id, state.turn_count)
            return state

    def cleanup_expired(self) -> int:
        """Sweep + mark stale sessions as errored. Call periodically (e.g. background task)."""
        removed = 0
        with self._lock:
            for state in self._sessions.values():
                if state.status == SessionStatus.ACTIVE and self._is_expired(state):
                    state.status = SessionStatus.ERROR
                    removed += 1
        if removed:
            logger.info("Swept %d expired session(s)", removed)
        return removed


# Process-wide singleton — imported by the routes/controller.
session_manager = SessionManager()
