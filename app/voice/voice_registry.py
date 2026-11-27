
"""
Agni AI - Voice Registry

Central source of truth for frontend-selectable voices.

Frontend-facing voice IDs stay stable and provider-neutral.
Actual ElevenLabs voice IDs are loaded from environment variables
and are never exposed through the API.
"""

from __future__ import annotations

import os

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    name: str
    gender: str
    accent: str
    accent_label: str
    languages: frozenset[str]
    provider: str
    provider_voice_env: str
    selectable: bool = True

    @property
    def provider_voice_id(self) -> str | None:
        value = os.getenv(self.provider_voice_env)

        if not value:
            return None

        value = value.strip()

        return value or None

    @property
    def configured(self) -> bool:
        return self.provider_voice_id is not None


# ---------------------------------------------------------------------------
# Supported metadata
# ---------------------------------------------------------------------------

SUPPORTED_VOICE_GENDERS = {
    "male",
    "female",
}


# Languages enabled following multilingual TTS sample testing.

MULTILINGUAL_VOICE_LANGUAGES = frozenset({
    "english",
    "hindi",
    "hinglish",
    "marathi",
})


# ---------------------------------------------------------------------------
# Voice profiles
#
# Each production voice has:
#
# - Stable Agni public ID
# - Display name
# - Gender
# - Accent
# - Supported languages
# - Environment variable containing the provider voice ID
# - Frontend selection visibility
#
# Never hardcode actual ElevenLabs voice IDs in this file.
# ---------------------------------------------------------------------------

VOICE_PROFILES: dict[str, VoiceProfile] = {

    # -----------------------------------------------------------------------
    # Legacy voice - backward compatibility
    #
    # Existing agents can continue using this voice.
    # Excluded from the new selectable voice list.
    # -----------------------------------------------------------------------

    "aarav": VoiceProfile(
        id="aarav",
        name="Aarav",
        gender="male",
        accent="indian",
        accent_label="Indian",
        languages=frozenset({
            "english",
            "hindi",
            "hinglish",
        }),
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID",
        selectable=False,
    ),

    # -----------------------------------------------------------------------
    # Female voices - multilingual
    # -----------------------------------------------------------------------

    "riya": VoiceProfile(
        id="riya",
        name="Riya Rao",
        gender="female",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_RIYA",
    ),

    "monika": VoiceProfile(
        id="monika",
        name="Monika",
        gender="female",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_MONIKA",
    ),

    "muskaan": VoiceProfile(
        id="muskaan",
        name="Muskaan",
        gender="female",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_MUSKAAN",
    ),

    "anika": VoiceProfile(
        id="anika",
        name="Anika",
        gender="female",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_ANIKA",
    ),

    "kalyani": VoiceProfile(
        id="kalyani",
        name="Kalyani",
        gender="female",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_KALYANI",
    ),

    "mugdha": VoiceProfile(
        id="mugdha",
        name="Mugdha",
        gender="female",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_MUGDHA",
    ),

    # -----------------------------------------------------------------------
    # Male voices - multilingual
    # -----------------------------------------------------------------------

    "raju": VoiceProfile(
        id="raju",
        name="Raju",
        gender="male",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_RAJU",
    ),

    "bunty": VoiceProfile(
        id="bunty",
        name="Bunty",
        gender="male",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_BUNTY",
    ),

    "vinayak": VoiceProfile(
        id="vinayak",
        name="Vinayak",
        gender="male",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_VINAYAK",
    ),

    "shrey": VoiceProfile(
        id="shrey",
        name="Shrey",
        gender="male",
        accent="indian",
        accent_label="Indian",
        languages=MULTILINGUAL_VOICE_LANGUAGES,
        provider="elevenlabs",
        provider_voice_env="ELEVENLABS_VOICE_ID_SHREY",
    ),
}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def get_voice_profile(
    voice_id: str,
) -> VoiceProfile | None:

    normalized = (
        voice_id
        .strip()
        .lower()
    )

    return VOICE_PROFILES.get(normalized)


# ---------------------------------------------------------------------------
# Configured voices
#
# Includes legacy voices for backward compatibility.
# ---------------------------------------------------------------------------

def get_configured_voices() -> list[VoiceProfile]:

    return [
        voice
        for voice in VOICE_PROFILES.values()
        if voice.configured
    ]


# ---------------------------------------------------------------------------
# Selectable voices
#
# Only configured voices available for new frontend voice selection.
# Legacy voices are excluded.
# ---------------------------------------------------------------------------

def get_selectable_voices() -> list[VoiceProfile]:

    return [
        voice
        for voice in get_configured_voices()
        if voice.selectable
    ]


# ---------------------------------------------------------------------------
# Accent filtering
# ---------------------------------------------------------------------------

def get_available_accents(
    *,
    language: str | None = None,
) -> set[str]:

    voices = get_configured_voices()

    if language is not None:
        normalized_language = (
            language
            .strip()
            .lower()
        )

        # Auto-detect is a session mode, not a spoken language.
        # All configured voices are available in auto mode.
        if normalized_language != "auto":
            voices = [
                voice
                for voice in voices
                if normalized_language in voice.languages
            ]

    return {
        voice.accent
        for voice in voices
    }


# ---------------------------------------------------------------------------
# Voice filtering
# ---------------------------------------------------------------------------

def filter_voices(
    *,
    language: str | None = None,
    accent: str | None = None,
    gender: str | None = None,
) -> list[VoiceProfile]:

    voices = get_configured_voices()

    # Language filtering
    if language is not None:
        normalized_language = (
            language
            .strip()
            .lower()
        )

        # Auto mode permits all configured voices.
        # Fixed-language sessions retain strict language filtering.
        if normalized_language != "auto":
            voices = [
                voice
                for voice in voices
                if normalized_language in voice.languages
            ]

    # Accent filtering
    if accent is not None:
        normalized_accent = (
            accent
            .strip()
            .lower()
        )

        voices = [
            voice
            for voice in voices
            if voice.accent == normalized_accent
        ]

    # Gender filtering
    if gender is not None:
        normalized_gender = (
            gender
            .strip()
            .lower()
        )

        voices = [
            voice
            for voice in voices
            if voice.gender == normalized_gender
        ]

    return voices
