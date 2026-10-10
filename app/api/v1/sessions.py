# """
# Agni AI - Voice Session API

# A LiveKit session is now a real call: it starts from an Agent (prompt, welcome
# message, voice and language come from the agent's saved config), creates a
# `Call` row, enforces the agent's max call duration, and closes the Call
# (status + ended_at + duration) when the session ends for any reason.
# """

# from __future__ import annotations

# import asyncio
# import uuid
# from datetime import datetime, timezone

# from fastapi import APIRouter, Depends, HTTPException, status
# from pydantic import BaseModel, field_validator
# from sqlalchemy.orm import Session

# from app.api.dependencies import get_current_user
# from app.db.session import SessionLocal, get_db
# from app.models.agent import Agent
# from app.models.call import Call
# from app.models.roles import UserRole
# from app.models.user import User
# from app.services.agent_session_manager import (
#     AgentSession,
#     AgentSessionManager,
#     SUPPORTED_AGENT_LANGUAGES,
# )

# NOT_FOUND = "Agent session not found"


# class CreateSessionRequest(BaseModel):
#     agent_id: uuid.UUID
#     # Optional override; by default it comes from the agent's accent languages.
#     language: str | None = None

#     @field_validator("language")
#     @classmethod
#     def validate_language(cls, value: str | None) -> str | None:
#         if value is None:
#             return None
#         value = value.strip().lower()
#         if value not in SUPPORTED_AGENT_LANGUAGES:
#             raise ValueError("language must be one of: english, hindi, hinglish, marathi")
#         return value


# class LiveKitConnectionResponse(BaseModel):
#     url: str
#     room_name: str
#     token: str


# class TrackContractResponse(BaseModel):
#     microphone: str
#     agent_audio: str


# class CreateSessionResponse(BaseModel):
#     session_id: str
#     call_id: uuid.UUID
#     agent_id: uuid.UUID
#     status: str
#     language: str
#     voice_id: str | None
#     livekit: LiveKitConnectionResponse
#     tracks: TrackContractResponse
#     created_at: datetime


# class SessionResponse(BaseModel):
#     session_id: str
#     call_id: uuid.UUID
#     agent_id: uuid.UUID
#     status: str
#     call_status: str
#     language: str
#     voice_id: str | None
#     room_name: str
#     frontend_identity: str
#     agent_identity: str
#     created_at: datetime
#     ended_at: datetime | None


# class EndSessionResponse(BaseModel):
#     session_id: str
#     call_id: uuid.UUID
#     status: str


# def _is_super(user: User) -> bool:
#     return user.role == UserRole.SUPERADMIN.value


# def _agent_language(agent: Agent) -> str:
#     """First language of the agent's accent setting ('Indian English' -> english)."""
#     for label in (agent.agent_metadata or {}).get("builder", {}).get("accent_languages", []):
#         for key in ("hinglish", "hindi", "marathi", "english"):
#             if key in label.lower():
#                 return key
#     return "english"


# def _finish_call(call_id: uuid.UUID, call_status: str) -> None:
#     """Close the Call once (own DB session: this runs outside any request)."""
#     with SessionLocal() as db:
#         call = db.get(Call, call_id)
#         if call is None or call.status != "in_progress":
#             return
#         now = datetime.now(timezone.utc)
#         call.status = call_status
#         call.ended_at = now
#         if call.started_at:
#             call.duration_seconds = max(0, int((now - call.started_at).total_seconds()))
#         db.commit()


# def create_sessions_router(session_manager: AgentSessionManager) -> APIRouter:
#     router = APIRouter(prefix="/sessions", tags=["sessions"])

#     calls: dict[str, uuid.UUID] = {}  # session_id -> call_id
#     ended_by_api: set[str] = set()    # ended on purpose (DELETE or max duration)
#     tasks: set[asyncio.Task] = set()

#     async def watch(session: AgentSession, call_id: uuid.UUID, max_seconds: int | None) -> None:
#         """Waits for the agent process to stop, enforces max duration, closes the Call."""
#         try:
#             try:
#                 await asyncio.wait_for(session.process.wait(), timeout=max_seconds)
#             except asyncio.TimeoutError:
#                 ended_by_api.add(session.session_id)
#                 await session_manager.end_session(session.session_id)
#         finally:
#             clean = session.process.returncode == 0 or session.session_id in ended_by_api
#             _finish_call(call_id, "completed" if clean else "failed")
#             ended_by_api.discard(session.session_id)

#     def owned_call(db: Session, session_id: str, user: User) -> Call:
#         # Sessions of other organizations look like they don't exist
#         call_id = calls.get(session_id)
#         call = db.get(Call, call_id) if call_id else None
#         if call is None or (not _is_super(user) and call.client_id != user.client_id):
#             raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
#         return call

#     @router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
#     async def create_session(
#         request: CreateSessionRequest,
#         db: Session = Depends(get_db),
#         current_user: User = Depends(get_current_user),
#     ):
#         agent = db.get(Agent, request.agent_id)
#         if agent is None or (not _is_super(current_user) and agent.client_id != current_user.client_id):
#             raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
#         if agent.status != "active":
#             raise HTTPException(status.HTTP_409_CONFLICT, "Agent is inactive")

#         call = Call(
#             client_id=agent.client_id,
#             agent_id=agent.id,
#             status="in_progress",
#             direction="inbound",
#             started_at=datetime.now(timezone.utc),
#         )
#         db.add(call)
#         db.commit()
#         db.refresh(call)

#         try:
#             session, frontend_token = await session_manager.create_session(
#                 language=request.language or _agent_language(agent),
#                 system_prompt=agent.system_prompt,
#                 welcome_message=agent.welcome_message,
#                 voice_id=agent.voice,
#                 call_id=str(call.id),  # the agent process saves the transcript under this id
#             )
#         except (ValueError, RuntimeError) as exc:  # e.g. voice not in the registry
#             _finish_call(call.id, "failed")
#             code = 422 if isinstance(exc, ValueError) else 500
#             raise HTTPException(code, str(exc)) from exc
#         calls[session.session_id] = call.id

#         limit = (agent.call_settings or {}).get("max_duration") or {}
#         max_seconds = int(limit.get("duration_minutes", 0)) * 60 if limit.get("enabled") else None
#         task = asyncio.create_task(watch(session, call.id, max_seconds or None))
#         tasks.add(task)
#         task.add_done_callback(tasks.discard)

#         return CreateSessionResponse(
#             session_id=session.session_id,
#             call_id=call.id,
#             agent_id=agent.id,
#             status=session.status,
#             language=session.language,
#             voice_id=session.voice_id,
#             livekit=LiveKitConnectionResponse(
#                 url=session_manager.livekit_url,
#                 room_name=session.room_name,
#                 token=frontend_token,
#             ),
#             tracks=TrackContractResponse(microphone="microphone", agent_audio="voice-output"),
#             created_at=session.created_at,
#         )

#     @router.get("/{session_id}", response_model=SessionResponse)
#     async def get_session(
#         session_id: str,
#         db: Session = Depends(get_db),
#         current_user: User = Depends(get_current_user),
#     ):
#         call = owned_call(db, session_id, current_user)
#         session = session_manager.get_session(session_id)
#         if session is None:
#             raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
#         return SessionResponse(
#             session_id=session.session_id,
#             call_id=call.id,
#             agent_id=call.agent_id,
#             status=session.status,
#             call_status=call.status,
#             language=session.language,
#             voice_id=session.voice_id,
#             room_name=session.room_name,
#             frontend_identity=session.frontend_identity,
#             agent_identity=session.agent_identity,
#             created_at=session.created_at,
#             ended_at=session.ended_at,
#         )

#     @router.delete("/{session_id}", response_model=EndSessionResponse)
#     async def end_session(
#         session_id: str,
#         db: Session = Depends(get_db),
#         current_user: User = Depends(get_current_user),
#     ):
#         call = owned_call(db, session_id, current_user)
#         ended_by_api.add(session_id)
#         session = await session_manager.end_session(session_id)
#         if session is None:
#             raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
#         return EndSessionResponse(session_id=session.session_id, call_id=call.id, status=session.status)

#     return router

"""
Agni AI - Voice Session API

A LiveKit session is now a real call: it starts from an Agent (prompt, welcome
message, voice and language come from the agent's saved config), creates a
`Call` row, enforces the agent's max call duration, and closes the Call
(status + ended_at + duration) when the session ends for any reason.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import SessionLocal, get_db
from app.models.agent import Agent
from app.models.call import Call
from app.models.roles import UserRole
from app.models.user import User
from app.services.call_analysis import analyze_call
from app.services.agent_session_manager import (
    AgentSession,
    AgentSessionManager,
    SUPPORTED_AGENT_LANGUAGES,
)

NOT_FOUND = "Agent session not found"


class CreateSessionRequest(BaseModel):
    agent_id: uuid.UUID
    # Shown in All Calls History. Defaults to the logged-in user's name.
    caller_name: str | None = Field(default=None, max_length=255)
    caller_number: str | None = Field(default=None, max_length=50)
    # Optional override; by default it comes from the agent's accent languages.
    language: str | None = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in SUPPORTED_AGENT_LANGUAGES:
            raise ValueError("language must be one of: english, hindi, hinglish, marathi")
        return value


class LiveKitConnectionResponse(BaseModel):
    url: str
    room_name: str
    token: str


class TrackContractResponse(BaseModel):
    microphone: str
    agent_audio: str


class CreateSessionResponse(BaseModel):
    session_id: str
    call_id: uuid.UUID
    agent_id: uuid.UUID
    status: str
    language: str
    voice_id: str | None
    livekit: LiveKitConnectionResponse
    tracks: TrackContractResponse
    created_at: datetime


class TranscriptMessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
    interrupted: bool = False


class RealtimeStateResponse(BaseModel):
    state: str
    last_event: str | None = None
    updated_at: datetime | None = None


class SessionResponse(BaseModel):
    session_id: str
    call_id: uuid.UUID
    agent_id: uuid.UUID
    status: str
    call_status: str
    language: str
    voice_id: str | None
    room_name: str
    frontend_identity: str
    agent_identity: str
    created_at: datetime
    ended_at: datetime | None
    ready: bool = False
    transcript: list[TranscriptMessageResponse] = []
    realtime: RealtimeStateResponse | None = None


class EndSessionResponse(BaseModel):
    session_id: str
    call_id: uuid.UUID
    status: str


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def _user_display_name(user: User) -> str | None:
    name = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
    return name or None


def _agent_language(agent: Agent) -> str:
    """First language of the agent's accent setting ('Indian English' -> english)."""
    for label in (agent.agent_metadata or {}).get("builder", {}).get("accent_languages", []):
        for key in ("hinglish", "hindi", "marathi", "english"):
            if key in label.lower():
                return key
    return "english"


def _finish_call(call_id: uuid.UUID, call_status: str, end_reason: str | None = None) -> None:
    """Close the Call once (own DB session: this runs outside any request)."""
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        if call is None or call.status != "in_progress":
            return
        now = datetime.now(timezone.utc)
        call.status = call_status
        call.ended_at = now
        call.end_reason = end_reason
        if call.started_at:
            call.duration_seconds = max(0, int((now - call.started_at).total_seconds()))
        db.commit()


def create_sessions_router(session_manager: AgentSessionManager) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["sessions"])

    calls: dict[str, uuid.UUID] = {}  # session_id -> call_id
    ended_by_api: set[str] = set()    # ended on purpose (DELETE or max duration)
    timed_out: set[str] = set()       # ended because max duration was reached
    tasks: set[asyncio.Task] = set()

    def spawn_analysis(call_id: uuid.UUID) -> None:
        """Summary + sentiment after the call, in the background."""
        try:
            task = asyncio.create_task(analyze_call(call_id))
        except RuntimeError:  # event loop is shutting down
            return
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def watch(session: AgentSession, call_id: uuid.UUID, max_seconds: int | None) -> None:
        """Waits for the agent process to stop, enforces max duration, closes the Call."""
        try:
            try:
                await asyncio.wait_for(session.process.wait(), timeout=max_seconds)
            except asyncio.TimeoutError:
                ended_by_api.add(session.session_id)
                timed_out.add(session.session_id)
                await session_manager.end_session(session.session_id)
        finally:
            clean = session.process.returncode == 0 or session.session_id in ended_by_api
            if session.session_id in timed_out:
                reason = "max_duration"
            else:
                reason = "user_hangup" if clean else "error"
            _finish_call(call_id, "completed" if clean else "failed", reason)
            ended_by_api.discard(session.session_id)
            timed_out.discard(session.session_id)
            spawn_analysis(call_id)

    def owned_call(db: Session, session_id: str, user: User) -> Call:
        # Sessions of other organizations look like they don't exist
        call_id = calls.get(session_id)
        call = db.get(Call, call_id) if call_id else None
        if call is None or (not _is_super(user) and call.client_id != user.client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
        return call

    @router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
    async def create_session(
        request: CreateSessionRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        agent = db.get(Agent, request.agent_id)
        if agent is None or (not _is_super(current_user) and agent.client_id != current_user.client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        if agent.status != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, "Agent is inactive")

        call = Call(
            client_id=agent.client_id,
            agent_id=agent.id,
            status="in_progress",
            direction="inbound",
            channel="web",
            caller_name=(request.caller_name or "").strip() or _user_display_name(current_user),
            caller_number=(request.caller_number or "").strip() or None,
            model_name=agent.llm_model,
            started_at=datetime.now(timezone.utc),
        )
        db.add(call)
        db.commit()
        db.refresh(call)

        try:
            session, frontend_token = await session_manager.create_session(
                language=request.language or _agent_language(agent),
                system_prompt=agent.system_prompt,
                welcome_message=agent.welcome_message,
                voice_id=agent.voice,
                call_id=str(call.id),  # the agent process saves the transcript under this id
            )
        except (ValueError, RuntimeError) as exc:  # e.g. voice not in the registry
            _finish_call(call.id, "failed", "error")
            code = 422 if isinstance(exc, ValueError) else 500
            raise HTTPException(code, str(exc)) from exc
        calls[session.session_id] = call.id

        limit = (agent.call_settings or {}).get("max_duration") or {}
        max_seconds = int(limit.get("duration_minutes", 0)) * 60 if limit.get("enabled") else None
        task = asyncio.create_task(watch(session, call.id, max_seconds or None))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

        return CreateSessionResponse(
            session_id=session.session_id,
            call_id=call.id,
            agent_id=agent.id,
            status=session.status,
            language=session.language,
            voice_id=session.voice_id,
            livekit=LiveKitConnectionResponse(
                url=session_manager.livekit_url,
                room_name=session.room_name,
                token=frontend_token,
            ),
            tracks=TrackContractResponse(microphone="microphone", agent_audio="voice-output"),
            created_at=session.created_at,
        )

    @router.get("/{session_id}", response_model=SessionResponse)
    async def get_session(
        session_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        call = owned_call(db, session_id, current_user)
        session = session_manager.get_session(session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
        runtime = session.runtime_snapshot()
        return SessionResponse(
            session_id=session.session_id,
            call_id=call.id,
            agent_id=call.agent_id,
            status=session.status,
            call_status=call.status,
            language=session.language,
            voice_id=session.voice_id,
            room_name=session.room_name,
            frontend_identity=session.frontend_identity,
            agent_identity=session.agent_identity,
            created_at=session.created_at,
            ended_at=session.ended_at,
            ready=session.is_ready,
            transcript=[
                TranscriptMessageResponse(
                    role=message["role"],
                    content=message["content"],
                    created_at=message["created_at"],
                    interrupted=message.get("interrupted", False),
                )
                for message in runtime["transcript"]
                if isinstance(message, dict)
                and message.get("role")
                and message.get("content")
                and message.get("created_at")
            ],
            realtime=RealtimeStateResponse(**runtime["realtime"]),
        )

    @router.delete("/{session_id}", response_model=EndSessionResponse)
    async def end_session(
        session_id: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        call = owned_call(db, session_id, current_user)
        ended_by_api.add(session_id)
        session = await session_manager.end_session(session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
        return EndSessionResponse(session_id=session.session_id, call_id=call.id, status=session.status)

    return router

