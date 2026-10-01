"""
Text-to-speech abstraction. `synthesize()` returns raw audio bytes for the
given text. `MockTTSService` fabricates a small placeholder payload so the
pipeline and streaming/barge-in logic can be exercised without a real
vendor key yet.
"""
import asyncio
from abc import ABC, abstractmethod

from app.core.config import settings
from app.core.exceptions import TTSProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)


class TTSService(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def synthesize_stream(self, text: str, chunk_size: int = 320):
        """Async generator yielding audio chunks as they become available."""
        raise NotImplementedError
        yield b""  # pragma: no cover - makes this a generator for the ABC


class MockTTSService(TTSService):
    async def synthesize(self, text: str) -> bytes:
        if not text:
            raise TTSProcessingError("Cannot synthesize empty text.")
        try:
            logger.debug("MockTTS synthesizing %d chars", len(text))
            # A real provider call (ElevenLabs/Polly/etc.) would go here.
            return text.encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise TTSProcessingError(f"TTS provider failed: {exc}") from exc

    async def synthesize_stream(self, text: str, chunk_size: int = 320):
        """
        Simulates a streaming TTS provider by yielding the payload in small
        chunks with a tiny delay between them — long enough that a
        concurrently-arriving barge-in signal has a real chance to interrupt
        it, same as it would against a real streaming vendor.
        """
        audio = await self.synthesize(text)
        for i in range(0, len(audio), chunk_size):
            await asyncio.sleep(0.05)
            yield audio[i : i + chunk_size]


def get_tts_service() -> TTSService:
    if settings.TTS_PROVIDER == "mock":
        return MockTTSService()
    # TODO: plug in a real provider here, e.g.:
    # if settings.TTS_PROVIDER == "elevenlabs": return ElevenLabsTTSService(settings.TTS_API_KEY)
    raise TTSProcessingError(f"Unsupported TTS_PROVIDER '{settings.TTS_PROVIDER}'")
