"""
Voice-agent endpoints.

Day 2:  POST /voice/session, /voice/audio, /voice/message — isolated,
        request/response pieces of the pipeline, with request validation
        and structured errors.
Day 3:  session -> audio -> STT -> memory -> LLM is fully wired through
        VoiceAgentController; GET /voice/session/{id}/history and
        POST /voice/session/{id}/end round out session-state management;
        WS /voice/session/{id}/stream is the full-duplex STT->LLM->TTS
        controller with barge-in.
"""
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.db.session import get_db
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


@router.post("/session", response_model=VoiceSessionResponse, status_code=201)
async def create_voice_session(
    payload: VoiceSessionCreateRequest,
    controller: VoiceAgentController = Depends(get_controller),
):
    """Starts a new voice session: creates the backing Call record and an
    in-memory session with a fresh session_id."""
    state, call = controller.start_session(
        client_id=payload.client_id, agent_id=payload.agent_id, metadata=payload.metadata
    )
    return VoiceSessionResponse(
        session_id=state.session_id,
        call_id=call.id,
        client_id=payload.client_id,
        agent_id=payload.agent_id,
        status=SessionStatus.ACTIVE,
        created_at=state.created_at,
    )


@router.post("/session/{session_id}/end", response_model=VoiceSessionEndResponse)
async def end_voice_session(
    session_id: str,
    controller: VoiceAgentController = Depends(get_controller),
):
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
):
    state = controller.sessions.get_session(session_id, touch=False)
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
):
    """session -> audio -> STT -> conversation memory -> LLM -> TTS, one turn."""
    import base64

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
):
    """Text-only path: session -> conversation memory -> LLM (no STT/TTS)."""
    reply_text, turn_count = await controller.handle_text_turn(
        session_id=payload.session_id, text=payload.text
    )
    return VoiceMessageResponse(session_id=payload.session_id, reply_text=reply_text, turn_count=turn_count)


@router.websocket("/session/{session_id}/stream")
async def voice_session_stream(
    websocket: WebSocket,
    session_id: str,
    db: Session = Depends(get_db),
):
    """
    Full-duplex voice-agent controller: STT -> LLM -> TTS over one
    connection, with interruption/barge-in support. See
    VoiceAgentController.run_streaming_session for the message protocol.
    """
    await websocket.accept()
    controller = VoiceAgentController(db=db)
    try:
        await controller.run_streaming_session(session_id, websocket)
    except WebSocketDisconnect:
        pass
