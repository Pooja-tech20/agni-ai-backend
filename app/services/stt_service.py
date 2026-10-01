"""
Speech-to-text abstraction.

`STTService` is the interface every provider must satisfy. `MockSTTService`
is the Day 2/3 stand-in so the rest of the pipeline (session -> memory ->
LLM -> TTS) can be built and tested end-to-end before real vendor
credentials (Deepgram / Whisper / Google STT / etc.) are wired in.

To add a real provider: implement `transcribe()` against the vendor SDK,
then switch it on in `get_stt_service()` based on `settings.STT_PROVIDER`.
"""
import base64
from abc import ABC, abstractmethod

from app.core.config import settings
from app.core.exceptions import InvalidAudioError, PayloadTooLargeError, STTProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)


class STTService(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, audio_format: str = "wav") -> str:
        """Return the transcript for a single utterance / audio chunk."""
        raise NotImplementedError


class MockSTTService(STTService):
    """
    Deterministic stand-in transcriber. Real audio bytes aren't actually
    decoded — this just validates the payload and returns a placeholder
    transcript, which is enough to exercise the full STT -> LLM -> TTS wiring.
    """

    async def transcribe(self, audio_bytes: bytes, audio_format: str = "wav") -> str:
        if not audio_bytes:
            raise InvalidAudioError("Received empty audio payload.")
        if len(audio_bytes) > settings.MAX_AUDIO_BYTES:
            raise PayloadTooLargeError(
                f"Audio chunk exceeds max allowed size of {settings.MAX_AUDIO_BYTES} bytes."
            )
        try:
            logger.debug("MockSTT transcribing %d bytes (%s)", len(audio_bytes), audio_format)
            # A real provider call would go here (network I/O, vendor SDK, etc.)
            return f"[transcribed {len(audio_bytes)} bytes of {audio_format} audio]"
        except InvalidAudioError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise STTProcessingError(f"STT provider failed: {exc}") from exc


def decode_audio_base64(audio_base64: str) -> bytes:
    try:
        return base64.b64decode(audio_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise InvalidAudioError(f"audio_base64 could not be decoded: {exc}") from exc


def get_stt_service() -> STTService:
    if settings.STT_PROVIDER == "mock":
        return MockSTTService()
    # TODO: plug in real providers here, e.g.:
    # if settings.STT_PROVIDER == "deepgram": return DeepgramSTTService(settings.STT_API_KEY)
    raise STTProcessingError(f"Unsupported STT_PROVIDER '{settings.STT_PROVIDER}'")
