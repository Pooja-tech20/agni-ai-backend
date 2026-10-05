"""
Voice-agent endpoints (all require login).

POST /voice/session                  start a call (client comes from the token)
POST /voice/session/{id}/end         end the call
GET  /voice/session/{id}/history     transcript so far
POST /voice/audio                    one voice turn (audio in, audio out)
POST /voice/message                  one text turn (no STT/TTS)
WS   /voice/session/{id}/stream?token=<JWT>   live full-duplex call with barge-in
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.exceptions import AppError, SessionNotFoundError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.voice import (
    SessionStatus,
    VoiceAudioRequest,
    VoiceAudioResponse,
    VoiceHistoryResponse,
    VoiceMessageRequest,
    VoiceMessageResponse,
    VoiceSessionCreateRequest,
    VoiceSessionEndResponse,
    VoiceSessionResponse,
)
from app.services.conversation_memory import ConversationMemoryService
from app.services.voice_agent_controller import VoiceAgentController

router = APIRouter(prefix="/voice", tags=["voice"])


def get_controller(db: Session = Depends(get_db)) -> VoiceAgentController:
    return VoiceAgentController(db=db)


def _authorize_session(controller: VoiceAgentController, session_id: str, user: User):
    """Return the session only if it belongs to the caller's organization.
    Others get the same 'not found' as a missing session."""
    state = controller.sessions.get_session(session_id, touch=False)
    if user.role != UserRole.SUPERADMIN.value and state.client_id != user.client_id:
        raise SessionNotFoundError(f"No active session with id '{session_id}'")
    return state


@router.post("/session", response_model=VoiceSessionResponse, status_code=201)
async def create_voice_session(
    payload: VoiceSessionCreateRequest,
    controller: VoiceAgentController = Depends(get_controller),
    current_user: User = Depends(get_current_user),
):
    """Starts a new voice session: creates the backing Call record and an
    in-memory session with a fresh session_id."""
    if current_user.role == UserRole.SUPERADMIN.value:
        client_id = payload.client_id
        if client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "client_id is required")
    else:
        if payload.client_id and payload.client_id != current_user.client_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You can only start calls in your own organization"
            )
        client_id = current_user.client_id
        if client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account has no organization")

    state, call = controller.start_session(
        client_id=client_id, agent_id=payload.agent_id, metadata=payload.metadata
    )
    return VoiceSessionResponse(
        session_id=state.session_id,
        call_id=call.id,
        client_id=client_id,
        agent_id=payload.agent_id,
        status=SessionStatus.ACTIVE,
        created_at=state.created_at,
    )


@router.post("/session/{session_id}/end", response_model=VoiceSessionEndResponse)
async def end_voice_session(
    session_id: str,
    controller: VoiceAgentController = Depends(get_controller),
    current_user: User = Depends(get_current_user),
):
    _authorize_session(controller, session_id, current_user)
    state = controller.end_session(session_id)
    from app.models.call import Call

    call = controller.db.query(Call).filter(Call.id == state.call_id).first()
    return VoiceSessionEndResponse(
        session_id=state.session_id,
        status=SessionStatus.ENDED,
        duration_seconds=call.duration_seconds if call else None,
    )


@router.get("/session/{session_id}/history", response_model=VoiceHistoryResponse)
async def get_voice_session_history(
    session_id: str,
    controller: VoiceAgentController = Depends(get_controller),
    current_user: User = Depends(get_current_user),
):
    state = _authorize_session(controller, session_id, current_user)
    memory = ConversationMemoryService(controller.db)
    history = memory.get_history(state.call_id, limit=1000)
    return VoiceHistoryResponse(
        session_id=session_id,
        history=[{"role": m.role, "content": m.content, "created_at": m.created_at} for m in history],
    )


@router.post("/audio", response_model=VoiceAudioResponse)
async def post_voice_audio(
    payload: VoiceAudioRequest,
    controller: VoiceAgentController = Depends(get_controller),
    current_user: User = Depends(get_current_user),
):
    """session -> audio -> STT -> conversation memory -> LLM -> TTS, one turn."""
    import base64

    _authorize_session(controller, payload.session_id, current_user)
    transcript, reply_text, reply_audio, turn_count = await controller.handle_audio_turn(
        session_id=payload.session_id,
        audio_base64=payload.audio_base64,
        audio_format=payload.audio_format,
    )
    return VoiceAudioResponse(
        session_id=payload.session_id,
        transcript=transcript,
        reply_text=reply_text,
        reply_audio_base64=base64.b64encode(reply_audio).decode(),
        turn_count=turn_count,
    )


@router.post("/message", response_model=VoiceMessageResponse)
async def post_voice_message(
    payload: VoiceMessageRequest,
    controller: VoiceAgentController = Depends(get_controller),
    current_user: User = Depends(get_current_user),
):
    """Text-only path: session -> conversation memory -> LLM (no STT/TTS)."""
    _authorize_session(controller, payload.session_id, current_user)
    reply_text, turn_count = await controller.handle_text_turn(
        session_id=payload.session_id, text=payload.text
    )
    return VoiceMessageResponse(session_id=payload.session_id, reply_text=reply_text, turn_count=turn_count)


@router.websocket("/session/{session_id}/stream")
async def voice_session_stream(
    websocket: WebSocket,
    session_id: str,
    token: str | None = Query(None, description="JWT access token"),
    db: Session = Depends(get_db),
):
    """
    Full-duplex voice-agent controller: STT -> LLM -> TTS over one
    connection, with interruption/barge-in support. See
    VoiceAgentController.run_streaming_session for the message protocol.

    Browsers can't set headers on a WebSocket, so the JWT goes in ?token=.
    Close codes: 4401 not logged in, 4404 session not found / not yours.
    """
    user = None
    if token:
        try:
            user_id = uuid.UUID(str(decode_access_token(token).get("sub")))
            user = db.get(User, user_id)
        except (ValueError, TypeError):
            user = None
    if user is None or not user.is_active:
        await websocket.close(code=4401)
        return

    controller = VoiceAgentController(db=db)
    try:
        _authorize_session(controller, session_id, user)
    except AppError:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    try:
        await controller.run_streaming_session(session_id, websocket)
    except WebSocketDisconnect:
        pass