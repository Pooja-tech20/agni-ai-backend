
"""
Stop a worker and retain its transcript.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from livekit import api

from app.voice.voice_registry import get_voice_profile


load_dotenv(".env.local", override=True)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


SUPPORTED_AUTO_RESPONSE_LANGUAGES = {
    "english",
    "hindi",
    "hinglish",
    "marathi",
}


SUPPORTED_AGENT_LANGUAGES = {
    "auto",
    *SUPPORTED_AUTO_RESPONSE_LANGUAGES,
}


class _AgentProcess:
    """Async-friendly wrapper around Popen for Windows compatibility."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self._process = process

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._process.wait)


@dataclass
class AgentSession:
    """Runtime state and worker handles for one voice session."""

    session_id: str
    language: str
    voice_id: str | None
    room_name: str
    frontend_identity: str
    agent_identity: str
    process: _AgentProcess
    created_at: datetime
    ready_file: Path
    runtime_file: Path

    status: str = "active"
    ended_at: datetime | None = None

    # Prevent simultaneous end requests from stopping the worker twice.
    end_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
    )

    @property
    def is_ready(self) -> bool:
        """Whether the voice worker has created its readiness marker."""
        return self.ready_file.exists()

    def refresh_status(self) -> str:
        """Refresh status from the worker process."""

        if self.status == "ended":
            return self.status

        return_code = self.process.returncode

        if return_code is None:
            self.status = "active"

        elif return_code == 0:
            self.status = "ended"

            if self.ended_at is None:
                self.ended_at = datetime.now(timezone.utc)

        else:
            self.status = "failed"

            if self.ended_at is None:
                self.ended_at = datetime.now(timezone.utc)

        return self.status

    def runtime_snapshot(self) -> dict[str, Any]:
        """Read transcript and realtime state written by the worker."""

        fallback_state = (
            "ended"
            if self.status in {"ended", "failed"}
            else "starting"
        )

        fallback = {
            "transcript": [],
            "realtime": {
                "state": fallback_state,
                "last_event": None,
                "updated_at": None,
            },
        }

        try:
            with self.runtime_file.open(
                "r",
                encoding="utf-8",
            ) as handle:
                data = json.load(handle)

        except (OSError, json.JSONDecodeError):
            return fallback

        if not isinstance(data, dict):
            return fallback

        transcript = data.get("transcript", [])
        realtime = data.get("realtime", {})

        if not isinstance(transcript, list):
            transcript = []

        if not isinstance(realtime, dict):
            realtime = {}

        return {
            "transcript": transcript,
            "realtime": {
                "state": realtime.get(
                    "state",
                    fallback_state,
                ),
                "last_event": realtime.get("last_event"),
                "updated_at": realtime.get("updated_at"),
            },
        }


class AgentSessionManager:
    """In-memory manager for independent Agni voice-worker sessions."""

    def __init__(self) -> None:
        self.sessions: dict[str, AgentSession] = {}

    # ----------------------------------------------------------
    # LiveKit configuration
    # ----------------------------------------------------------

    @property
    def livekit_url(self) -> str:
        value = os.getenv("LIVEKIT_URL")

        if not value:
            raise RuntimeError(
                "LIVEKIT_URL is missing from .env.local"
            )

        return value

    def _livekit_credentials(self) -> tuple[str, str]:
        api_key = os.getenv("LIVEKIT_API_KEY")
        api_secret = os.getenv("LIVEKIT_API_SECRET")

        if not api_key or not api_secret:
            raise RuntimeError(
                "LIVEKIT_API_KEY or LIVEKIT_API_SECRET "
                "is missing from .env.local"
            )

        return api_key, api_secret

    # ----------------------------------------------------------
    # Frontend LiveKit token
    # ----------------------------------------------------------

    def create_frontend_token(
        self,
        *,
        room_name: str,
        participant_identity: str,
    ) -> str:
        """Create the frontend's scoped LiveKit room token."""

        api_key, api_secret = self._livekit_credentials()

        return (
            api.AccessToken(api_key, api_secret)
            .with_identity(participant_identity)
            .with_name("Agni AI Web User")
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                )
            )
            .to_jwt()
        )

    # ----------------------------------------------------------
    # Create session
    # ----------------------------------------------------------

    async def create_session(
        self,
        language: str,
        system_prompt: str | None = None,
        welcome_message: str | None = None,
        voice_id: str | None = None,
        call_id: str | None = None,
    ) -> tuple[AgentSession, str]:
        """Validate settings, start one worker and return its token."""

        language = (language or "auto").strip().lower()

        if language not in SUPPORTED_AGENT_LANGUAGES:
            raise ValueError(
                "Unsupported language. "
                "Use auto, english, hindi, hinglish, or marathi."
            )

        # Resolve the public voice ID to its private provider voice ID.
        selected_voice_id: str | None = None
        provider_voice_id: str | None = None
        selected_voice_gender: str | None = None

        if voice_id is not None:
            voice = get_voice_profile(voice_id)

            if voice is None:
                raise ValueError("Unknown voice_id.")

            if voice.provider != "elevenlabs":
                raise ValueError(
                    "Selected voice provider is not supported "
                    "by the current TTS runtime."
                )

            # Fixed-language sessions must match registry metadata.
            # Auto mode permits language switching during a call.
            # The eventual production voice must be tested for all
            # four languages before multilingual production use.
            if language != "auto" and language not in voice.languages:
                raise ValueError(
                    f"Selected voice does not support language '{language}'."
                )

            provider_voice_id = voice.provider_voice_id

            if provider_voice_id is None:
                raise ValueError(
                    "Selected voice is not configured. "
                    "Set its provider voice ID first."
                )

            selected_voice_id = voice.id
            selected_voice_gender = voice.gender

        # Validate LiveKit settings before starting the worker.
        _ = self.livekit_url

        session_id = uuid.uuid4().hex
        short_id = session_id[:12]

        room_name = f"agni-session-{short_id}"

        frontend_identity = f"agni-web-{short_id}"
        agent_identity = f"agni-agent-{short_id}"

        session_files_dir = (
            Path(tempfile.gettempdir()) / "agni-ai"
        )

        ready_file = (
            session_files_dir
            / "session-readiness"
            / f"{session_id}.ready"
        )

        runtime_file = (
            session_files_dir
            / "session-runtime"
            / f"{session_id}.json"
        )

        ready_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.parent.mkdir(parents=True, exist_ok=True)

        frontend_token = self.create_frontend_token(
            room_name=room_name,
            participant_identity=frontend_identity,
        )

        # Each worker receives isolated session configuration.
        # AGNI_* names remain unchanged for worker compatibility.
        process_env = os.environ.copy()

        process_env.update(
            {
                "AGNI_SESSION_ROOM_NAME": room_name,
                "AGNI_SESSION_PARTICIPANT_IDENTITY": agent_identity,
                "AGNI_SESSION_LANGUAGE": language,
                "AGNI_SESSION_SYSTEM_PROMPT": system_prompt or "",
                "AGNI_SESSION_WELCOME_MESSAGE": welcome_message or "",
                "AGNI_SESSION_VOICE_ID": provider_voice_id or "",
                "AGNI_SESSION_VOICE_GENDER": selected_voice_gender or "",
                "AGNI_SESSION_CALL_ID": call_id or "",
                "AGNI_SESSION_ID": session_id,
                "AGNI_SESSION_READY_FILE": str(ready_file),
                "AGNI_SESSION_RUNTIME_FILE": str(runtime_file),
                "PYTHONUNBUFFERED": "1",
            }
        )

        # Remove stale files before starting a new worker.
        ready_file.unlink(missing_ok=True)
        runtime_file.unlink(missing_ok=True)

        try:
            popen = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-m",
                    "livekit_poc.audio_subscriber",
                ],
                cwd=str(PROJECT_ROOT),
                env=process_env,
            )

        except OSError as exc:
            raise RuntimeError(
                f"Could not start the voice worker: {exc}"
            ) from exc

        process = _AgentProcess(popen)

        session = AgentSession(
            session_id=session_id,
            language=language,
            voice_id=selected_voice_id,
            room_name=room_name,
            frontend_identity=frontend_identity,
            agent_identity=agent_identity,
            process=process,
            created_at=datetime.now(timezone.utc),
            ready_file=ready_file,
            runtime_file=runtime_file,
        )

        self.sessions[session_id] = session

        return session, frontend_token

    # ----------------------------------------------------------
    # Get session
    # ----------------------------------------------------------

    def get_session(
        self,
        session_id: str,
    ) -> AgentSession | None:
        """Return a known session and refresh its worker status."""

        session = self.sessions.get(session_id)

        if session is None:
            return None

        session.refresh_status()
        return session

    # ----------------------------------------------------------
    # End session
    # ----------------------------------------------------------

    async def end_session(
        self,
        session_id: str,
    ) -> AgentSession | None:
        """Stop a worker and retain its transcript."""

        session = self.sessions.get(session_id)

        if session is None:
            return None

        async with session.end_lock:
            return_code_before_stop = session.process.returncode

            if return_code_before_stop is None:
                try:
                    session.process.terminate()
                except ProcessLookupError:
                    pass

                try:
                    await asyncio.wait_for(
                        session.process.wait(),
                        timeout=5.0,
                    )

                except asyncio.TimeoutError:
                    try:
                        session.process.kill()
                    except ProcessLookupError:
                        pass

                    await session.process.wait()

                # A worker stopped through this API path is an intentional end.
                session.status = "ended"

            else:
                session.refresh_status()

            session.ready_file.unlink(missing_ok=True)

            if session.ended_at is None:
                session.ended_at = datetime.now(timezone.utc)

            return session

    # ----------------------------------------------------------
    # Service shutdown
    # ----------------------------------------------------------

    async def shutdown(self) -> None:
        """Stop all active workers during application shutdown."""

        active_ids = [
            session_id
            for session_id, session in self.sessions.items()
            if session.process.returncode is None
        ]

        for session_id in active_ids:
            await self.end_session(session_id)
