
"""Authenticated LiveKit session API backed by Agent and Call records."""

from __future__ import annotations

import asyncio
import logging
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
from app.services.agent_session_manager import (
    AgentSession,
    AgentSessionManager,
    SUPPORTED_AGENT_LANGUAGES,
)
from app.services.call_analysis import analyze_call  # noqa: F401  (kept for /calls/{id}/analyze users)
from app.services.call_lifecycle import finalize_call
from app.services.post_call import run_post_call_pipeline
from app.services.billing import ensure_can_call, ensure_concurrency_room

logger = logging.getLogger(__name__)

NOT_FOUND = "Agent session not found"


class CreateSessionRequest(BaseModel):
    agent_id: uuid.UUID
    caller_name: str | None = Field(default=None, max_length=255)
    caller_number: str | None = Field(default=None, max_length=50)
    language: str | None = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()

        if normalized not in SUPPORTED_AGENT_LANGUAGES:
            supported = ", ".join(sorted(SUPPORTED_AGENT_LANGUAGES))
            raise ValueError(f"language must be one of: {supported}")

        return normalized


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
    transcript: list[TranscriptMessageResponse] = Field(default_factory=list)
    realtime: RealtimeStateResponse | None = None


class EndSessionResponse(BaseModel):
    session_id: str
    call_id: uuid.UUID
    status: str


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def _user_display_name(user: User) -> str | None:
    name = (
        f"{getattr(user, 'first_name', '') or ''} "
        f"{getattr(user, 'last_name', '') or ''}"
    ).strip()

    return name or None


def _agent_language(agent: Agent) -> str:
    """Resolve the default language from the Agent Builder configuration."""
    builder = (agent.agent_metadata or {}).get("builder", {})
    accent_languages = builder.get("accent_languages", [])

    if isinstance(accent_languages, str):
        accent_languages = [accent_languages]

    for label in accent_languages:
        if not isinstance(label, str):
            continue

        normalized = label.lower()

        for language in ("hinglish", "hindi", "marathi", "english", "auto"):
            if language in normalized:
                return language

    return "english"


def _finish_call(
    call_id: uuid.UUID,
    call_status: str,
    end_reason: str | None = None,
) -> None:
    """Close the call once: duration, credit billing, campaign progress."""
    with SessionLocal() as db:
        finalize_call(db, call_id, call_status, end_reason)


def create_sessions_router(session_manager: AgentSessionManager) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["sessions"])

    calls: dict[str, uuid.UUID] = {}
    ended_by_api: set[str] = set()
    timed_out: set[str] = set()
    watcher_tasks: dict[str, asyncio.Task] = {}

    async def watch(
        session: AgentSession,
        call_id: uuid.UUID,
        max_seconds: int | None,
    ) -> None:
        """Wait for worker termination, persist the call, then run analysis."""
        session_id = session.session_id

        try:
            try:
                await asyncio.wait_for(
                    session.process.wait(),
                    timeout=max_seconds,
                )

            except asyncio.TimeoutError:
                timed_out.add(session_id)
                ended_by_api.add(session_id)

                await session_manager.end_session(session_id)

            clean = (
                session.process.returncode == 0
                or session_id in ended_by_api
            )

            if session_id in timed_out:
                end_reason = "max_duration"
            elif session_id in ended_by_api:
                end_reason = "user_hangup"
            else:
                end_reason = "user_hangup" if clean else "error"

            _finish_call(
                call_id,
                "completed" if clean else "failed",
                end_reason,
            )

            # call_analysis owns summary, sentiment and post-call extraction.
            # It reads the persisted CallMessage transcript.
            # Analysis, then the signed `call.completed` webhook.
            await run_post_call_pipeline(call_id)

        except Exception:
            logger.exception(
                "Failed while finalizing session %s",
                session_id,
            )

            try:
                _finish_call(call_id, "failed", "error")

            except Exception:
                logger.exception(
                    "Could not persist failed call %s",
                    call_id,
                )

        finally:
            ended_by_api.discard(session_id)
            timed_out.discard(session_id)

    def owned_call(
        db: Session,
        session_id: str,
        user: User,
    ) -> Call:
        call_id = calls.get(session_id)
        call = db.get(Call, call_id) if call_id else None

        if call is None or (
            not _is_super(user)
            and call.client_id != user.client_id
        ):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                NOT_FOUND,
            )

        return call

    @router.post(
        "",
        response_model=CreateSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_session(
        request: CreateSessionRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        agent = db.get(Agent, request.agent_id)

        if agent is None or (
            not _is_super(current_user)
            and agent.client_id != current_user.client_id
        ):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Agent not found",
            )

        if agent.status != "active":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Agent is inactive",
            )

        org = ensure_can_call(db, agent.client_id)
        ensure_concurrency_room(db, org)

        call = Call(
            client_id=agent.client_id,
            agent_id=agent.id,
            status="in_progress",
            direction="inbound",
            channel="web",
            caller_name=(request.caller_name or "").strip()
            or _user_display_name(current_user),
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
                call_id=str(call.id),
            )

        except (ValueError, RuntimeError) as exc:
            _finish_call(call.id, "failed", "error")

            code = (
                status.HTTP_422_UNPROCESSABLE_CONTENT
                if isinstance(exc, ValueError)
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            )

            raise HTTPException(code, str(exc)) from exc

        except Exception as exc:
            _finish_call(call.id, "failed", "error")

            logger.exception(
                "Could not create session for call %s",
                call.id,
            )

            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Could not start the voice session",
            ) from exc

        calls[session.session_id] = call.id

        duration_config = (
            agent.call_settings or {}
        ).get("max_duration") or {}

        max_seconds = (
            int(duration_config.get("duration_minutes", 0)) * 60
            if duration_config.get("enabled")
            else None
        )

        watcher = asyncio.create_task(
            watch(session, call.id, max_seconds or None)
        )

        watcher_tasks[session.session_id] = watcher

        def remove_watcher(
            done_task: asyncio.Task,
            sid: str = session.session_id,
        ) -> None:
            if watcher_tasks.get(sid) is done_task:
                watcher_tasks.pop(sid, None)

        watcher.add_done_callback(remove_watcher)

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
            tracks=TrackContractResponse(
                microphone="microphone",
                agent_audio="voice-output",
            ),
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
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                NOT_FOUND,
            )

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

        session = session_manager.get_session(session_id)

        if session is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                NOT_FOUND,
            )

        ended_by_api.add(session_id)

        await session_manager.end_session(session_id)

        watcher = watcher_tasks.get(session_id)

        if watcher is not None:
            await watcher

        ended_by_api.discard(session_id)
        timed_out.discard(session_id)

        return EndSessionResponse(
            session_id=session.session_id,
            call_id=call.id,
            status=session.status,
        )

    return router

