"""
The voice-agent controller: the single place that coordinates every stage
of a call — session lifecycle, STT, conversation memory, LLM, and TTS — for
both the simple request/response endpoints (Day 2) and the full-duplex
streaming path with interruption/barge-in (Day 3).

Design:
- `handle_text_turn` / `handle_audio_turn`: one request-in, one response-out.
  Used by the plain REST endpoints (/voice/message, /voice/audio) and by
  anything that doesn't need real-time streaming.
- `run_streaming_session`: drives a WebSocket connection end-to-end. Reads
  audio frames as they arrive, and races them against an in-flight TTS
  stream so that new caller audio immediately interrupts ("barges in on")
  whatever the agent is currently saying.
"""
import asyncio
import base64
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import SessionNotFoundError
from app.core.logging import get_logger, session_id_ctx_var
from app.services.conversation_memory import ConversationMemoryService
from app.services.llm_service import LLMService, get_llm_service
from app.services.session_manager import SessionManager, session_manager
from app.services.stt_service import STTService, decode_audio_base64, get_stt_service
from app.services.tts_service import TTSService, get_tts_service

logger = get_logger(__name__)


class VoiceAgentController:
    def __init__(
        self,
        db: Session,
        stt: STTService | None = None,
        llm: LLMService | None = None,
        tts: TTSService | None = None,
        sessions: SessionManager | None = None,
    ):
        self.db = db
        self.stt = stt or get_stt_service()
        self.llm = llm or get_llm_service()
        self.tts = tts or get_tts_service()
        self.sessions = sessions or session_manager
        self.memory = ConversationMemoryService(db)

    # --- Session lifecycle ---------------------------------------------
        # --- Session lifecycle ---------------------------------------------
    def start_session(self, client_id: uuid.UUID, agent_id: uuid.UUID, metadata: dict | None = None):
        from datetime import datetime, timezone

        from app.core.exceptions import AgentInactiveError, ResourceNotFoundError
        from app.models.agent import Agent
        from app.models.call import Call  # local import avoids a module-level cycle
        from app.models.client import Client

        if not self.db.get(Client, client_id):
            raise ResourceNotFoundError(f"Client '{client_id}' not found")
        agent = self.db.get(Agent, agent_id)
        if not agent or agent.client_id != client_id:
            raise ResourceNotFoundError(f"Agent '{agent_id}' not found for this client")
        if agent.status != "active":
            raise AgentInactiveError(f"Agent '{agent.name}' is inactive")

        call = Call(
            client_id=client_id,
            agent_id=agent_id,
            status="in_progress",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(call)
        self.db.commit()
        self.db.refresh(call)

        state = self.sessions.create_session(
            call_id=call.id, client_id=client_id, agent_id=agent_id, metadata=metadata
        )
        logger.info("Voice session started session_id=%s call_id=%s", state.session_id, call.id)
        return state, call

    def end_session(self, session_id: str):
        from datetime import datetime, timezone

        from app.models.call import Call

        state = self.sessions.end_session(session_id)
        call = self.db.query(Call).filter(Call.id == state.call_id).first()
        if call:
            call.status = "completed"
            call.ended_at = datetime.now(timezone.utc)
            if call.started_at:
                started = call.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                call.duration_seconds = int((call.ended_at - started).total_seconds())
            self.db.commit()  # <-- this line was missing in your copy
        return state

    # --- Single-turn request/response (Day 2, and the non-streaming Day 3 path) ---
    async def handle_text_turn(self, session_id: str, text: str) -> tuple[str, int]:
        """session -> conversation memory -> LLM. Returns (reply_text, turn_count)."""
        session_id_ctx_var.set(session_id)
        state = self.sessions.get_session(session_id)

        self.memory.add_message(state.call_id, role="user", content=text)
        history = self.memory.get_history(state.call_id)
        reply_text = await self.llm.generate_reply(self.memory.format_for_llm(history))
        self.memory.add_message(state.call_id, role="agent", content=reply_text)

        turn_count = self.sessions.increment_turn(session_id)
        return reply_text, turn_count

    async def handle_audio_turn(
        self, session_id: str, audio_base64: str, audio_format: str = "wav"
    ) -> tuple[str, str, bytes, int]:
        """
        session -> audio input -> STT -> conversation memory -> LLM -> TTS.
        Returns (transcript, reply_text, reply_audio_bytes, turn_count).
        """
        session_id_ctx_var.set(session_id)
        state = self.sessions.get_session(session_id)

        audio_bytes = decode_audio_base64(audio_base64)
        transcript = await self.stt.transcribe(audio_bytes, audio_format)

        self.memory.add_message(state.call_id, role="user", content=transcript)
        history = self.memory.get_history(state.call_id)
        reply_text = await self.llm.generate_reply(self.memory.format_for_llm(history))
        self.memory.add_message(state.call_id, role="agent", content=reply_text)

        self.sessions.set_agent_speaking(session_id, True)
        try:
            reply_audio = await self.tts.synthesize(reply_text)
        finally:
            self.sessions.set_agent_speaking(session_id, False)

        turn_count = self.sessions.increment_turn(session_id)
        return transcript, reply_text, reply_audio, turn_count

    # --- Full-duplex streaming with barge-in (Day 3: complete controller) ---
    async def run_streaming_session(self, session_id: str, websocket) -> None:
        """
        Drives one WebSocket connection for the lifetime of the call.

        Incoming messages (JSON) are one of:
          {"type": "audio_chunk", "audio_base64": "...", "format": "wav"}
          {"type": "end_utterance"}   -- caller finished speaking, run the turn
          {"type": "end_session"}     -- caller hung up

        Outgoing messages:
          {"type": "transcript", "text": "..."}
          {"type": "agent_audio_chunk", "audio_base64": "..."}
          {"type": "agent_done"}
          {"type": "interrupted"}     -- agent speech was barged in on
          {"type": "error", "code": "...", "message": "..."}
        """
        session_id_ctx_var.set(session_id)
        audio_buffer = bytearray()
        speaking_task: asyncio.Task | None = None

        try:
            while True:
                message = await websocket.receive_json()
                msg_type = message.get("type")

                if msg_type == "audio_chunk":
                    # Barge-in: caller audio arriving while the agent is talking
                    # immediately cancels the in-flight TTS stream.
                    if speaking_task and not speaking_task.done():
                        speaking_task.cancel()
                        self.sessions.set_agent_speaking(session_id, False)
                        await websocket.send_json({"type": "interrupted"})
                        logger.info("Barge-in on session_id=%s", session_id)

                    audio_buffer.extend(decode_audio_base64(message["audio_base64"]))

                elif msg_type == "end_utterance":
                    if not audio_buffer:
                        await websocket.send_json(
                            {"type": "error", "code": "INVALID_AUDIO", "message": "No audio received."}
                        )
                        continue

                    transcript, reply_text, _reply_audio, turn_count = await self._process_utterance(
                        session_id, bytes(audio_buffer)
                    )
                    audio_buffer = bytearray()
                    await websocket.send_json({"type": "transcript", "text": transcript})

                    speaking_task = asyncio.create_task(
                        self._stream_reply_audio(session_id, reply_text, websocket)
                    )

                elif msg_type == "end_session":
                    if speaking_task and not speaking_task.done():
                        speaking_task.cancel()
                    self.end_session(session_id)
                    break

                else:
                    await websocket.send_json(
                        {"type": "error", "code": "UNKNOWN_MESSAGE_TYPE", "message": str(msg_type)}
                    )

        except SessionNotFoundError as exc:
            await websocket.send_json({"type": "error", "code": exc.code, "message": exc.message})
        except Exception:
            logger.exception("Streaming session %s crashed", session_id)
            await websocket.send_json(
                {"type": "error", "code": "INTERNAL_ERROR", "message": "Voice session failed."}
            )
        finally:
            if speaking_task and not speaking_task.done():
                speaking_task.cancel()

    async def _process_utterance(self, session_id: str, audio_bytes: bytes):
        state = self.sessions.get_session(session_id)
        transcript = await self.stt.transcribe(audio_bytes)

        self.memory.add_message(state.call_id, role="user", content=transcript)
        history = self.memory.get_history(state.call_id)
        reply_text = await self.llm.generate_reply(self.memory.format_for_llm(history))
        self.memory.add_message(state.call_id, role="agent", content=reply_text)

        turn_count = self.sessions.increment_turn(session_id)
        return transcript, reply_text, None, turn_count

    async def _stream_reply_audio(self, session_id: str, reply_text: str, websocket) -> None:
        """Streams TTS audio chunk-by-chunk; cancellable mid-flight for barge-in."""
        self.sessions.set_agent_speaking(session_id, True)
        try:
            async for chunk in self.tts.synthesize_stream(reply_text):
                await websocket.send_json(
                    {"type": "agent_audio_chunk", "audio_base64": base64.b64encode(chunk).decode()}
                )
            await websocket.send_json({"type": "agent_done"})
        except asyncio.CancelledError:
            logger.info("TTS stream cancelled (barge-in) session_id=%s", session_id)
        finally:
            self.sessions.set_agent_speaking(session_id, False)
