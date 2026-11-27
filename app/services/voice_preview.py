
"""Voice preview generation and caching."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import tempfile
import wave
from pathlib import Path

from app.voice.elevenlabs_tts_provider import ElevenLabsTTSProvider
from app.voice.voice_registry import VoiceProfile


CACHE_DIR = Path("uploads/voice_previews")

PREVIEW_TEXT = (
    "Hello! Welcome to Jeeva AI. "
    "I am your AI voice assistant. "
    "How can I help you today?"
)

PREVIEW_TIMEOUT = 30
MAX_PCM_BYTES = 16_000 * 2 * 30

_preview_lock = asyncio.Lock()


def _cache_path(provider: ElevenLabsTTSProvider) -> Path:
    config = json.dumps(
        {
            "voice": provider.voice_id,
            "model": provider.model_id,
            "format": provider.output_format,
            "text": PREVIEW_TEXT,
        },
        sort_keys=True,
    )

    cache_key = hashlib.sha256(
        config.encode("utf-8")
    ).hexdigest()

    return CACHE_DIR / f"{cache_key}.wav"


def _pcm_to_wav(pcm_audio: bytes) -> bytes:
    if not pcm_audio or len(pcm_audio) % 2:
        raise RuntimeError("Invalid PCM preview audio.")

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(pcm_audio)

    return buffer.getvalue()


async def _generate_audio(
    provider: ElevenLabsTTSProvider,
) -> bytes:
    pcm_audio = bytearray()

    async for chunk in provider.synthesize(PREVIEW_TEXT):
        if (
            chunk.sample_rate != 16_000
            or chunk.channels != 1
            or chunk.encoding != "pcm_s16le"
        ):
            raise RuntimeError(
                "Unsupported preview audio format."
            )

        pcm_audio.extend(chunk.data)

        if len(pcm_audio) > MAX_PCM_BYTES:
            raise RuntimeError(
                "Preview audio exceeds size limit."
            )

    return _pcm_to_wav(bytes(pcm_audio))


def _save_cache(path: Path, audio: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            temp.write(audio)

        os.replace(temp_path, path)

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


async def get_voice_preview(voice: VoiceProfile) -> bytes:
    if voice.provider != "elevenlabs":
        raise ValueError("Unsupported voice provider.")

    if not voice.provider_voice_id:
        raise ValueError("Voice is not configured.")

    provider = ElevenLabsTTSProvider(
        voice_id=voice.provider_voice_id,
    )

    cache_path = _cache_path(provider)

    async with _preview_lock:
        if cache_path.is_file():
            return cache_path.read_bytes()

        audio = await asyncio.wait_for(
            _generate_audio(provider),
            timeout=PREVIEW_TIMEOUT,
        )

        _save_cache(cache_path, audio)

        return audio
