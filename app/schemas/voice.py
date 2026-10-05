import base64
import uuid
from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"
    ERROR = "error"


# --- POST /voice/session ---------------------------------------------------
class VoiceSessionCreateRequest(BaseSchema):
    client_id: uuid.UUID | None = None
    agent_id: uuid.UUID
    metadata: dict = Field(default_factory=dict)


class VoiceSessionResponse(BaseSchema):
    session_id: str
    call_id: uuid.UUID
    client_id: uuid.UUID
    agent_id: uuid.UUID
    status: SessionStatus
    created_at: datetime


class VoiceSessionEndResponse(BaseSchema):
    session_id: str
    status: SessionStatus
    duration_seconds: int | None = None


# --- POST /voice/audio ------------------------------------------------------
class VoiceAudioRequest(BaseSchema):
    session_id: str
    # Base64-encoded audio chunk. Keeps the endpoint JSON-friendly for Day 2/3;
    # a real-time binary/streaming path is exposed separately over WebSocket.
    audio_base64: str
    # e.g. "wav", "pcm16", "webm" — passed straight through to the STT provider.
    audio_format: str = "wav"

    @field_validator("audio_base64")
    @classmethod
    def must_decode(cls, v: str) -> str:
        if not v:
            raise ValueError("audio_base64 must not be empty")
        try:
            base64.b64decode(v, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"audio_base64 is not valid base64: {exc}") from exc
        return v


class VoiceAudioResponse(BaseSchema):
    session_id: str
    transcript: str
    reply_text: str
    reply_audio_base64: str
    turn_count: int


# --- POST /voice/message ----------------------------------------------------
class VoiceMessageRequest(BaseSchema):
    session_id: str
    text: str = Field(min_length=1, max_length=4000)


class VoiceMessageResponse(BaseSchema):
    session_id: str
    reply_text: str
    turn_count: int


# --- Shared: conversation history -------------------------------------------
class ConversationTurn(BaseSchema):
    role: str
    content: str
    created_at: datetime


class VoiceHistoryResponse(BaseSchema):
    session_id: str
    history: list[ConversationTurn]
