"""
Agni AI - Integrated LiveKit Voice Pipeline

Realtime flow:

    Microphone
        ↓
    LiveKit
        ↓
    Streaming STT
        ↓
    Deepgram
        ↓
    Completed User Utterance
        ↓
    OpenAI LLM
        ↓
    ElevenLabs TTS
        ↓
    LiveKit voice-output
        ↓
    Caller / Listener

Important behavior:
- Deepgram connects only after a microphone track exists.
- Only completed utterances are sent to OpenAI.
- Deepgram speech_final is used as the fast turn-completion signal.
- Deepgram utterance_end remains as a fallback.
- OpenAI text can be forwarded to TTS while the LLM is still generating.
- Microphone audio continues to reach STT while Agni is speaking.
- User speech can interrupt the current AI response.
- Response latency is measured without making extra API calls.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from livekit import api, rtc
from scipy.signal import resample_poly

from app.services.call_transcript import log_message
from app.services.knowledge.voice_context import (
    get_voice_knowledge_context,
)
from app.voice.elevenlabs_tts_provider import ElevenLabsTTSProvider
from app.voice.livekit_audio_output import LiveKitAudioOutput
from app.voice.openai_llm_provider import OpenAILLMProvider
from app.voice.session_runtime_state import SessionRuntimeState
from app.voice.stt_stream_adapter import STTStreamAdapter


load_dotenv(".env.local", override=False)


# ---------------------------------------------------------------------------
# LiveKit configuration
# ---------------------------------------------------------------------------

ROOM_NAME = (
    os.getenv("AGNI_SESSION_ROOM_NAME")
    or os.getenv("LIVEKIT_ROOM_NAME", "agni-ai-voice-poc")
)

PARTICIPANT_IDENTITY = (
    os.getenv("AGNI_SESSION_PARTICIPANT_IDENTITY")
    or os.getenv("LIVEKIT_SUBSCRIBER_IDENTITY", "agni-audio-subscriber")
)


# ---------------------------------------------------------------------------
# STT and session configuration
# ---------------------------------------------------------------------------

STT_SAMPLE_RATE = 16_000

STT_STREAM_ENDPOINT = os.getenv(
    "STT_STREAM_ENDPOINT",
    "ws://127.0.0.1:8000/api/v1/stt/stream",
)

SESSION_LANGUAGE_ALIASES = {
    "auto": "auto",
    "multi": "auto",
    "en": "english",
    "en-in": "english",
    "english": "english",
    "hi": "hindi",
    "hindi": "hindi",
    "hinglish": "hinglish",
    "mr": "marathi",
    "marathi": "marathi",
}

SUPPORTED_SESSION_LANGUAGES = {
    "auto",
    "english",
    "hindi",
    "hinglish",
    "marathi",
}

_requested_session_language = (
    os.getenv("AGNI_SESSION_LANGUAGE")
    or os.getenv("AGNI_STT_LANGUAGE", "auto")
).strip().lower()

SESSION_LANGUAGE = SESSION_LANGUAGE_ALIASES.get(
    _requested_session_language,
    _requested_session_language,
)

if SESSION_LANGUAGE not in SUPPORTED_SESSION_LANGUAGES:
    raise RuntimeError(
        "Unsupported AGNI_SESSION_LANGUAGE: "
        f"{_requested_session_language}. "
        "Use auto, english, hindi, hinglish, or marathi."
    )

SYSTEM_PROMPT = os.getenv("AGNI_SESSION_SYSTEM_PROMPT") or None
WELCOME_MESSAGE = os.getenv("AGNI_SESSION_WELCOME_MESSAGE") or None
SESSION_VOICE_ID = os.getenv("AGNI_SESSION_VOICE_ID") or None
SESSION_VOICE_GENDER = os.getenv("AGNI_SESSION_VOICE_GENDER") or None

SESSION_READY_FILE = os.getenv("AGNI_SESSION_READY_FILE")
SESSION_RUNTIME_FILE = os.getenv("AGNI_SESSION_RUNTIME_FILE")

SESSION_ID = os.getenv("AGNI_SESSION_ID")
CALL_ID = os.getenv("AGNI_SESSION_CALL_ID")

METRICS_DIR = (
    Path(tempfile.gettempdir())
    / "agni-ai"
    / "session-metrics"
)

METRICS_FILE = (
    METRICS_DIR / f"{SESSION_ID}.json"
    if SESSION_ID
    else None
)

metrics = {
    "session_id": SESSION_ID,
    "started_at": time.time(),
    "ended_at": None,
    "user_turns": 0,
    "assistant_turns": 0,
    "interruptions": 0,
    "turns": [],
}


def save_metrics() -> None:
    """Persist session-level voice metrics when a session ID exists."""
    if METRICS_FILE is None:
        return

    try:
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        METRICS_FILE.write_text(
            json.dumps(metrics, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[METRICS WARNING] Could not save session metrics: {exc}")


# Keep STT multilingual so callers can switch languages during a call.
STT_LANGUAGE = "multi"

separator = "&" if "?" in STT_STREAM_ENDPOINT else "?"

STT_STREAM_ENDPOINT_WITH_LANGUAGE = (
    f"{STT_STREAM_ENDPOINT}{separator}language={STT_LANGUAGE}"
)


# ---------------------------------------------------------------------------
# TTS configuration
# ---------------------------------------------------------------------------

TTS_SAMPLE_RATE = 16_000
TTS_CHANNELS = 1


# ---------------------------------------------------------------------------
# LiveKit authentication
# ---------------------------------------------------------------------------

def create_access_token() -> str:
    """Create a LiveKit token for the configured room and participant."""
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not api_key or not api_secret:
        raise RuntimeError(
            "LIVEKIT_API_KEY or LIVEKIT_API_SECRET "
            "is missing from .env.local"
        )

    return (
        api.AccessToken(api_key, api_secret)
        .with_identity(PARTICIPANT_IDENTITY)
        .with_name("Agni AI Voice Agent")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=ROOM_NAME,
                can_publish=True,
                can_subscribe=True,
            )
        )
        .to_jwt()
    )


# ---------------------------------------------------------------------------
# Audio conversion
# ---------------------------------------------------------------------------

def convert_audio_frame_to_stt_format(
    audio_frame: rtc.AudioFrame,
) -> bytes:
    """
    Convert LiveKit audio to 16 kHz, mono, PCM16 for STT.
    """
    input_sample_rate = int(audio_frame.sample_rate)
    input_channels = int(audio_frame.num_channels)
    pcm_bytes = bytes(audio_frame.data)

    if not pcm_bytes:
        return b""

    samples = np.frombuffer(pcm_bytes, dtype=np.int16)

    # Convert multi-channel audio to mono.
    if input_channels > 1:
        samples = samples.reshape(-1, input_channels).astype(np.int32)
        samples = np.mean(samples, axis=1)
        samples = np.clip(samples, -32768, 32767).astype(np.int16)

    # Resample audio to the STT sample rate.
    if input_sample_rate != STT_SAMPLE_RATE:
        samples_float = samples.astype(np.float32)
        resampled = resample_poly(
            samples_float,
            STT_SAMPLE_RATE,
            input_sample_rate,
        )
        samples = np.clip(resampled, -32768, 32767).astype(np.int16)

    return samples.tobytes()


# ---------------------------------------------------------------------------
# AI response worker
# ---------------------------------------------------------------------------

async def process_ai_responses(
    response_queue: asyncio.Queue[
        tuple[str, float, float | None]
    ],
    llm_provider: OpenAILLMProvider,
    tts_provider: ElevenLabsTTSProvider,
    audio_output: LiveKitAudioOutput,
    ai_speaking: asyncio.Event,
    interrupt_event: asyncio.Event,
    runtime_state: SessionRuntimeState,
    room: rtc.Room,
) -> None:
    """
    Process completed user utterances sequentially.

    OpenAI streams text into a queue while ElevenLabs consumes that
    queue and streams generated audio to LiveKit. Confirmed user speech
    can interrupt the active response.
    """
    while True:
        transcript, utterance_ready_at, last_final_at = (
            await response_queue.get()
        )

        llm_task: asyncio.Task | None = None

        try:
            transcript = transcript.strip()

            if not transcript:
                continue

            await runtime_state.set_realtime(
                "processing",
                "assistant_processing",
            )

            # Start a fresh response and clear the previous interrupt flag.
            interrupt_event.clear()
            audio_output.begin_response()

            # Resume the receiving client's audio output for this response.
            await room.local_participant.publish_data(
                b"resume",
                reliable=True,
                topic="agni/audio-control",
            )

            ai_speaking.set()
            worker_started_at = time.perf_counter()

            print()
            print("=" * 72)
            print("AGNI AI - VOICE RESPONSE")
            print("=" * 72)
            print()
            print("User:")
            print(transcript)

            log_message("user", transcript)

            print()
            print("Generating AI response and streaming speech...")

            # -----------------------------------------------------------
            # LLM -> TTS streaming bridge
            # -----------------------------------------------------------

            llm_started_at = time.perf_counter()
            first_llm_chunk_at: float | None = None
            llm_completed_at: float | None = None

            response_chunks: list[str] = []
            text_queue: asyncio.Queue[str | None] = asyncio.Queue()

            async def produce_llm_text() -> None:
                nonlocal first_llm_chunk_at
                nonlocal llm_completed_at

                try:
                    rag_started_at = time.perf_counter()

                    knowledge = await asyncio.to_thread(
                        get_voice_knowledge_context,
                        CALL_ID,
                        transcript,
                    )

                    rag_latency_ms = (
                        time.perf_counter() - rag_started_at
                    ) * 1000

                    print(
                        "[RAG] "
                        f"enabled={knowledge.enabled} | "
                        f"chunks={knowledge.chunk_count} | "
                        f"failed={knowledge.failed} | "
                        f"latency={rag_latency_ms:.2f} ms"
                    )

                    if interrupt_event.is_set():
                        return

                    llm_stream = llm_provider.stream_response(
                        transcript,
                        knowledge_context=knowledge.context,
                        knowledge_enabled=knowledge.enabled,
                        knowledge_failed=knowledge.failed,
                    )

                    async with contextlib.aclosing(llm_stream):

                        async for text_chunk in llm_stream:
                            if interrupt_event.is_set():
                                return

                            if not text_chunk:
                                continue

                            if first_llm_chunk_at is None:
                                first_llm_chunk_at = time.perf_counter()

                            response_chunks.append(text_chunk)
                            await text_queue.put(text_chunk)

                finally:
                    llm_completed_at = time.perf_counter()
                    await text_queue.put(None)

            async def llm_text_stream():
                while True:
                    item = await text_queue.get()

                    try:
                        if item is None or interrupt_event.is_set():
                            return

                        yield item
                    finally:
                        text_queue.task_done()

            llm_task = asyncio.create_task(produce_llm_text())

            # -----------------------------------------------------------
            # Streaming TTS
            # -----------------------------------------------------------

            tts_started_at = time.perf_counter()
            first_tts_chunk_at: float | None = None
            chunk_count = 0
            total_audio_bytes = 0

            tts_stream = tts_provider.synthesize_streaming_text(
                llm_text_stream()
            )

            async def consume_tts_audio() -> None:
                nonlocal first_tts_chunk_at
                nonlocal chunk_count
                nonlocal total_audio_bytes

                async for audio_chunk in tts_stream:
                    if interrupt_event.is_set():
                        return

                    if first_tts_chunk_at is None:
                        first_tts_chunk_at = time.perf_counter()

                        await runtime_state.set_realtime(
                            "assistant_speaking",
                            "assistant_speech_started",
                        )

                    chunk_count += 1
                    total_audio_bytes += len(audio_chunk.data)

                    await audio_output.send_chunk(audio_chunk)

            tts_task = asyncio.create_task(consume_tts_audio())
            interrupt_wait_task = asyncio.create_task(interrupt_event.wait())

            try:
                await asyncio.wait(
                    {tts_task, interrupt_wait_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Stop LLM and TTS immediately after a confirmed interruption.
                if interrupt_event.is_set():
                    if llm_task is not None and not llm_task.done():
                        llm_task.cancel()
                        await asyncio.gather(
                            llm_task,
                            return_exceptions=True,
                        )

                    llm_task = None

                    if not tts_task.done():
                        tts_task.cancel()

                    await asyncio.gather(
                        tts_task,
                        return_exceptions=True,
                    )

                    audio_output.interrupt()

                    print()
                    print("[BARGE-IN] Current AI response cancelled.")

                    partial_response = "".join(response_chunks).strip()

                    if partial_response:
                        await runtime_state.add_message(
                            "assistant",
                            partial_response,
                            interrupted=True,
                        )

                    continue

                interrupt_wait_task.cancel()
                await asyncio.gather(
                    interrupt_wait_task,
                    return_exceptions=True,
                )

                # Surface any actual TTS error.
                await tts_task

                tts_generation_completed_at = time.perf_counter()

            finally:
                for task in (tts_task, interrupt_wait_task):
                    if not task.done():
                        task.cancel()

                await asyncio.gather(
                    tts_task,
                    interrupt_wait_task,
                    return_exceptions=True,
                )

            # -----------------------------------------------------------
            # Confirm LLM completion
            # -----------------------------------------------------------

            await llm_task
            llm_task = None

            if interrupt_event.is_set():
                print()
                print("[BARGE-IN] Current AI response cancelled.")
                continue

            if llm_completed_at is None:
                llm_completed_at = time.perf_counter()

            response_text = "".join(response_chunks).strip()

            if not response_text:
                print("LLM returned an empty response.")
                continue

            print()
            print("Agni AI:")
            print(response_text)
            print()

            # -----------------------------------------------------------
            # Wait for LiveKit playback to finish
            # -----------------------------------------------------------

            await audio_output.wait_for_playout()

            if interrupt_event.is_set():
                await runtime_state.add_message(
                    "assistant",
                    response_text,
                    interrupted=True,
                )

                print()
                print("[BARGE-IN] AI playback interrupted.")
                continue

            playback_completed_at = time.perf_counter()

            await runtime_state.add_message(
                "assistant",
                response_text,
                interrupted=False,
            )

            log_message("agent", response_text)

            await runtime_state.set_realtime(
                "listening",
                "assistant_speech_ended",
            )

            metrics["assistant_turns"] += 1
            metrics["turns"].append(
                {
                    "response_text": response_text,
                    "llm_latency_ms": (
                        (llm_completed_at - llm_started_at) * 1000
                    ),
                    "tts_latency_ms": (
                        (tts_generation_completed_at - tts_started_at)
                        * 1000
                    ),
                    "response_latency_ms": (
                        (playback_completed_at - utterance_ready_at)
                        * 1000
                    ),
                }
            )

            print(f"TTS chunks: {chunk_count}")
            print(f"TTS audio bytes: {total_audio_bytes}")
            print("AI voice response completed.")

            # -----------------------------------------------------------
            # Latency report
            # -----------------------------------------------------------

            print()
            print("-" * 72)
            print("RESPONSE LATENCY")
            print("-" * 72)

            if last_final_at is not None:
                final_to_turn_ready = utterance_ready_at - last_final_at
                print(
                    "Final transcript -> turn ready: "
                    f"{final_to_turn_ready:.3f} s"
                )

            queue_delay = worker_started_at - utterance_ready_at
            print(f"Pipeline queue delay: {queue_delay:.3f} s")

            if first_llm_chunk_at is not None:
                llm_first_chunk = first_llm_chunk_at - llm_started_at
                print(f"LLM first text chunk: {llm_first_chunk:.3f} s")

            llm_total = llm_completed_at - llm_started_at
            print(f"LLM complete response: {llm_total:.3f} s")

            if first_tts_chunk_at is not None:
                response_start_latency = (
                    first_tts_chunk_at - utterance_ready_at
                )
                print(
                    "Turn ready -> first AI audio: "
                    f"{response_start_latency:.3f} s"
                )

                if first_llm_chunk_at is not None:
                    llm_to_audio = (
                        first_tts_chunk_at - first_llm_chunk_at
                    )
                    print(
                        "First LLM text -> first AI audio: "
                        f"{llm_to_audio:.3f} s"
                    )

                if first_tts_chunk_at < llm_completed_at:
                    overlap = llm_completed_at - first_tts_chunk_at
                    print(
                        "TTS started before LLM completed by: "
                        f"{overlap:.3f} s"
                    )
                else:
                    print("TTS started after LLM completed.")

            tts_generation_time = (
                tts_generation_completed_at - tts_started_at
            )
            print(
                "TTS streaming session: "
                f"{tts_generation_time:.3f} s"
            )

            total_response_time = (
                playback_completed_at - utterance_ready_at
            )
            print(
                "Turn ready -> playback complete: "
                f"{total_response_time:.3f} s"
            )

            print("-" * 72)
            print()

        except asyncio.CancelledError:
            if llm_task is not None and not llm_task.done():
                llm_task.cancel()
                await asyncio.gather(
                    llm_task,
                    return_exceptions=True,
                )
            raise

        except Exception as exc:
            if llm_task is not None and not llm_task.done():
                llm_task.cancel()
                await asyncio.gather(
                    llm_task,
                    return_exceptions=True,
                )

            print()
            print(f"[VOICE PIPELINE ERROR] {exc}")

        finally:
            ai_speaking.clear()
            response_queue.task_done()


# ---------------------------------------------------------------------------
# STT event handling
# ---------------------------------------------------------------------------

async def receive_stt_events(
    stt_adapter: STTStreamAdapter,
    response_queue: asyncio.Queue[
        tuple[str, float, float | None]
    ],
    ai_speaking: asyncio.Event,
    interrupt_event: asyncio.Event,
    audio_output: LiveKitAudioOutput,
    runtime_state: SessionRuntimeState,
    room: rtc.Room,
) -> None:
    """
    Receive normalized STT events and dispatch completed user turns.

    Flux StartOfTurn is a semantic speech-start signal and can trigger
    immediate interruption. Nova speech_started is raw VAD; it requires
    non-empty transcript text before interrupting.
    """
    final_transcript_parts: list[str] = []
    last_final_at: float | None = None
    turn_dispatched = False

    def request_barge_in(reason: str) -> None:
        if not ai_speaking.is_set() or interrupt_event.is_set():
            return

        metrics["interruptions"] += 1

        print()
        print(f"[BARGE-IN] User interrupted Agni ({reason})")

        interrupt_event.set()
        audio_output.interrupt()

        asyncio.create_task(
            room.local_participant.publish_data(
                b"stop",
                reliable=True,
                topic="agni/audio-control",
            )
        )

        asyncio.create_task(
            runtime_state.set_realtime(
                "interrupted",
                "user_interrupted",
            )
        )

    async def dispatch_utterance(trigger: str) -> None:
        nonlocal last_final_at
        nonlocal turn_dispatched

        utterance_ready_at = time.perf_counter()
        final_utterance = " ".join(final_transcript_parts).strip()
        final_transcript_parts.clear()

        if not final_utterance:
            last_final_at = None
            return

        metrics["user_turns"] += 1

        print()
        print(f"[UTTERANCE - {trigger}] {final_utterance}")

        await runtime_state.add_message("user", final_utterance)

        await runtime_state.set_realtime(
            "processing",
            "user_transcript",
        )

        await response_queue.put(
            (
                final_utterance,
                utterance_ready_at,
                last_final_at,
            )
        )

        last_final_at = None
        turn_dispatched = True

    while True:
        event = await stt_adapter.receive_event()
        event_type = event.get("type", "unknown")

        if event_type == "partial":
            transcript = event.get("transcript", "").strip()

            if transcript and ai_speaking.is_set():
                request_barge_in("partial transcript")

            latency = event.get("latency_ms", 0)
            print(f"[PARTIAL] {transcript}  ({latency:.2f} ms)")

        elif event_type == "final":
            transcript = event.get("transcript", "").strip()

            if transcript:
                final_transcript_parts.append(transcript)
                last_final_at = time.perf_counter()

            if transcript and ai_speaking.is_set():
                request_barge_in("final transcript")

            latency = event.get("latency_ms", 0)
            speech_final = bool(event.get("speech_final", False))
            trigger = event.get("trigger")
            end_of_turn_confidence = event.get(
                "end_of_turn_confidence"
            )

            speech_final_label = " [SPEECH FINAL]" if speech_final else ""

            print(
                f"[FINAL] {transcript}  "
                f"({latency:.2f} ms){speech_final_label}"
            )

            if trigger is not None:
                print(
                    "[TURN END] "
                    f"trigger={trigger}, "
                    f"confidence={end_of_turn_confidence}"
                )

            if (
                speech_final
                and final_transcript_parts
                and not turn_dispatched
            ):
                print("[VAD] Speech endpoint detected")
                await dispatch_utterance("speech_final")

        elif event_type == "speech_started":
            turn_dispatched = False
            stt_backend = event.get("stt_backend", "")

            print("[VAD] Speech started")

            await runtime_state.set_realtime(
                "user_speaking",
                "user_speech_started",
            )

            if ai_speaking.is_set() and stt_backend == "flux":
                request_barge_in("Flux StartOfTurn")

        elif event_type == "utterance_end":
            print("[VAD] Utterance ended")

            if turn_dispatched:
                final_transcript_parts.clear()
                last_final_at = None
                turn_dispatched = False
                print(
                    "[VAD] Utterance already processed via speech_final"
                )
                continue

            if final_transcript_parts:
                await dispatch_utterance("utterance_end fallback")
            else:
                last_final_at = None

        elif event_type == "silence":
            final_transcript_parts.clear()
            last_final_at = None
            turn_dispatched = False
            print("[VAD] Silence detected")

        elif event_type == "incomplete_speech":
            transcript = event.get("transcript", "")
            print(f"[STT] Incomplete speech: {transcript}")

        elif event_type == "error":
            print(f"[STT ERROR] {event.get('message', '')}")

        else:
            print(f"[STT EVENT] {event}")


# ---------------------------------------------------------------------------
# LiveKit microphone handling
# ---------------------------------------------------------------------------


async def consume_audio_track(
    track: rtc.Track,
    participant_identity: str,
    stt_adapter: STTStreamAdapter,
) -> None:
    """
    Continuously stream microphone audio to STT, including while Agni speaks.
    """
    if track.kind != rtc.TrackKind.KIND_AUDIO:
        return

    print()
    print(f"Receiving audio from '{participant_identity}'")

    audio_stream = rtc.AudioStream(track)
    frame_count = 0
    total_audio_bytes = 0

    try:
        async for audio_frame_event in audio_stream:
            audio_frame = audio_frame_event.frame
            frame_count += 1

            stt_audio = convert_audio_frame_to_stt_format(audio_frame)

            if not stt_audio:
                continue

            total_audio_bytes += len(stt_audio)

            await stt_adapter.send_audio(stt_audio)

            if frame_count % 100 == 0:
                print(f"Streaming audio frames: {frame_count}")

    finally:
        await audio_stream.aclose()

        print()
        print(
            f"Audio stream ended. Frames received: {frame_count}. "
            f"STT audio bytes sent: {total_audio_bytes}"
        )



def signal_session_ready() -> None:
    """Create the ready marker consumed by the API process."""
    if not SESSION_READY_FILE:
        return

    ready_path = Path(SESSION_READY_FILE)
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.touch(exist_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """
    Run the integrated Agni AI voice pipeline.

    LiveKit connects first. STT connects only after a microphone track
    has been received from a remote participant.
    """
    livekit_url = os.getenv("LIVEKIT_URL")

    if not livekit_url:
        raise RuntimeError(
            "LIVEKIT_URL is missing from .env.local"
        )

    runtime_state = SessionRuntimeState(SESSION_RUNTIME_FILE)
    await runtime_state.initialize()

    print()
    print("=" * 72)
    print("AGNI AI - INTEGRATED VOICE PIPELINE")
    print("=" * 72)
    print()

    # Initialize providers.
    print("Initializing OpenAI LLM provider...")

    llm_provider = OpenAILLMProvider(
        instructions=SYSTEM_PROMPT,
        response_language="auto",
        voice_gender=SESSION_VOICE_GENDER,
    )

    print(f"LLM ready: {llm_provider.model}")
    print(
        "Voice gender: "
        f"{llm_provider.voice_gender or 'unspecified'}"
    )
    print(
        "LLM response language: "
        f"{llm_provider.response_language or 'auto'}"
    )

    print("Initializing ElevenLabs TTS provider...")

    tts_provider = ElevenLabsTTSProvider(
        voice_id=SESSION_VOICE_ID,
    )

    print("TTS provider ready.")

    if WELCOME_MESSAGE:
        print("Welcome message configured.")

    # Initialize LiveKit and pipeline coordination objects.
    room = rtc.Room()

    audio_output = LiveKitAudioOutput(
        sample_rate=TTS_SAMPLE_RATE,
        channels=TTS_CHANNELS,
    )

    response_queue: asyncio.Queue[
        tuple[str, float, float | None]
    ] = asyncio.Queue()

    ai_speaking = asyncio.Event()
    interrupt_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    microphone_track_future: asyncio.Future[
        tuple[rtc.Track, str]
    ] = loop.create_future()

    stt_adapter: STTStreamAdapter | None = None
    audio_task: asyncio.Task | None = None
    stt_event_task: asyncio.Task | None = None
    response_task: asyncio.Task | None = None

    # Capture the first remote microphone track.
    @room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        if publication.name == "voice-output":
            return

        if microphone_track_future.done():
            return

        print()
        print(
            f"Subscribed to track '{publication.name}' "
            f"from '{participant.identity}'"
        )

        microphone_track_future.set_result(
            (track, participant.identity)
        )

    try:
        # Connect to LiveKit.
        print("Connecting to LiveKit...")

        await room.connect(
            livekit_url,
            create_access_token(),
        )

        print("Connected to LiveKit.")
        print(f"Room: {room.name}")
        print(
            "Participant: "
            f"{room.local_participant.identity}"
        )

        # Publish the AI audio output track.
        publication = await audio_output.publish(
            room.local_participant
        )

        print(f"Published AI voice track: {publication.sid}")
        print()
        print("Waiting for microphone track...")

        # Wait until the remote microphone track is available.
        microphone_track, microphone_identity = (
            await microphone_track_future
        )

        print("Microphone track ready.")

        # Connect STT only after the microphone track exists.
        stt_adapter = STTStreamAdapter(
            endpoint=STT_STREAM_ENDPOINT_WITH_LANGUAGE
        )

        print("Connecting to streaming STT...")
        await stt_adapter.connect()
        print("Streaming STT connected.")

        # Start STT event and microphone workers before welcome speech.
        stt_event_task = asyncio.create_task(
            receive_stt_events(
                stt_adapter,
                response_queue,
                ai_speaking,
                interrupt_event,
                audio_output,
                runtime_state,
                room,
            )
        )

        audio_task = asyncio.create_task(
            consume_audio_track(
                microphone_track,
                microphone_identity,
                stt_adapter,
            )
        )

        # Speak the optional welcome message.
        if WELCOME_MESSAGE:
            welcome_text = WELCOME_MESSAGE

            # Generate the welcome message in the selected accent language.
            if SESSION_LANGUAGE not in ("auto", "english"):

                try:
                    welcome_llm = OpenAILLMProvider(
                        instructions=SYSTEM_PROMPT,
                        response_language=SESSION_LANGUAGE,
                        voice_gender=SESSION_VOICE_GENDER,
                    )

                    welcome_chunks = []

                    async for chunk in welcome_llm.stream_response(
                        "Translate the following welcome message into "
                        f"natural spoken {SESSION_LANGUAGE}. "
                        "Preserve its original meaning and agent persona. "
                        "Return only the translated message, without "
                        "explanations or additional text:\n\n"
                        f"{WELCOME_MESSAGE}"
                    ):
                        welcome_chunks.append(chunk)

                    translated_welcome = "".join(welcome_chunks).strip()

                    if translated_welcome:
                        welcome_text = translated_welcome

                except Exception:
                    print(
                        "Welcome translation failed. "
                        "Using the original welcome message."
                    )
            
            print()
            print("Speaking welcome message...")

            interrupt_event.clear()
            audio_output.begin_response()
            ai_speaking.set()

            async def consume_welcome_audio() -> None:
                async for audio_chunk in tts_provider.synthesize(
                    welcome_text
                ):
                    if interrupt_event.is_set():
                        return

                    await audio_output.send_chunk(audio_chunk)

            welcome_tts_task = asyncio.create_task(
                consume_welcome_audio()
            )

            welcome_interrupt_task = asyncio.create_task(
                interrupt_event.wait()
            )

            try:
                await asyncio.wait(
                    {
                        welcome_tts_task,
                        welcome_interrupt_task,
                    },
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if interrupt_event.is_set():
                    if not welcome_tts_task.done():
                        welcome_tts_task.cancel()

                    await asyncio.gather(
                        welcome_tts_task,
                        return_exceptions=True,
                    )

                    audio_output.interrupt()
                    print("Welcome message interrupted.")

                else:
                    welcome_interrupt_task.cancel()

                    await asyncio.gather(
                        welcome_interrupt_task,
                        return_exceptions=True,
                    )

                    await welcome_tts_task
                    await audio_output.wait_for_playout()

                    if interrupt_event.is_set():
                        print("Welcome message interrupted.")
                    else:
                        log_message("agent", welcome_text)

                        await runtime_state.add_message(
                            "assistant",
                            welcome_text,
                        )

                        print("Welcome message finished.")

            finally:
                for task in (
                    welcome_tts_task,
                    welcome_interrupt_task,
                ):
                    if not task.done():
                        task.cancel()

                await asyncio.gather(
                    welcome_tts_task,
                    welcome_interrupt_task,
                    return_exceptions=True,
                )

                ai_speaking.clear()

        # Start the normal response worker.
        response_task = asyncio.create_task(
            process_ai_responses(
                response_queue,
                llm_provider,
                tts_provider,
                audio_output,
                ai_speaking,
                interrupt_event,
                runtime_state,
                room,
            )
        )

        signal_session_ready()

        await runtime_state.set_realtime(
            "listening",
            "session_ready",
        )

        print()
        print(
            "Streaming STT endpoint: "
            f"{STT_STREAM_ENDPOINT_WITH_LANGUAGE}"
        )
        print(f"Session language preference: {SESSION_LANGUAGE}")
        print(
            "STT routing mode: "
            f"Nova-3 multilingual ({STT_LANGUAGE})"
        )
        print(
            "LLM response language: auto "
            "(latest caller utterance)"
        )
        print()
        print("Voice pipeline ready.")
        print("Only completed utterances are sent to OpenAI.")
        print("OpenAI text is streamed toward ElevenLabs in real time.")

        await asyncio.Event().wait()

    finally:
        metrics["ended_at"] = time.time()
        save_metrics()

        print()
        print("Stopping Agni AI voice pipeline...")

        # Stop active AI generation and playback.
        interrupt_event.set()
        audio_output.interrupt()

        if response_task is not None:
            response_task.cancel()
            await asyncio.gather(
                response_task,
                return_exceptions=True,
            )

        # Stop STT event processing.
        if stt_event_task is not None:
            stt_event_task.cancel()
            await asyncio.gather(
                stt_event_task,
                return_exceptions=True,
            )

        # Stop microphone streaming.
        if audio_task is not None:
            audio_task.cancel()
            await asyncio.gather(
                audio_task,
                return_exceptions=True,
            )

        # Close external connections.
        if stt_adapter is not None:
            await stt_adapter.close()

        await audio_output.close()
        await room.disconnect()

        await runtime_state.set_realtime(
            "ended",
            "session_ended",
        )

        print("Disconnected from LiveKit.")


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print()
        print("Agni AI voice pipeline stopped by user.")

    except Exception as exc:
        print()
        print(f"Voice pipeline error: {exc}")