"""
Agni AI - Configuration Catalog API

Exposes frontend-selectable configuration supported by
the Agni backend.

Provider-specific voice identifiers are intentionally
never exposed through these endpoints.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.dependencies import require_role
from app.models.roles import UserRole
from app.models.user import User

from app.services.agent_session_manager import (
    SUPPORTED_AGENT_LANGUAGES,
)

from app.services.voice_preview import (
    get_voice_preview,
)

from app.voice.voice_registry import (
    SUPPORTED_VOICE_GENDERS,
    filter_voices,
    get_selectable_voices,
    get_voice_profile,
)


router = APIRouter(
    prefix="/catalog",
    tags=["catalog"],
)


LANGUAGE_LABELS = {
    "auto": "Auto-detect",
    "english": "English",
    "hindi": "Hindi",
    "hinglish": "Hinglish",
    "marathi": "Marathi",
}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LanguageOptionResponse(BaseModel):
    id: str
    label: str


class LanguagesResponse(BaseModel):
    languages: list[LanguageOptionResponse]


class AccentOptionResponse(BaseModel):
    id: str
    label: str


class AccentsResponse(BaseModel):
    accents: list[AccentOptionResponse]


class VoiceOptionResponse(BaseModel):
    id: str
    name: str
    gender: str
    accent: str
    accent_label: str
    languages: list[str]


class VoicesResponse(BaseModel):
    voices: list[VoiceOptionResponse]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _normalize_language(
    language: str | None,
) -> str | None:

    if language is None:
        return None

    normalized = (
        language
        .strip()
        .lower()
    )

    if (
        normalized
        not in SUPPORTED_AGENT_LANGUAGES
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "language must be one of: "
                "auto, english, hindi, "
                "hinglish, marathi"
            ),
        )

    return normalized


def _normalize_gender(
    gender: str | None,
) -> str | None:

    if gender is None:
        return None

    normalized = (
        gender
        .strip()
        .lower()
    )

    if (
        normalized
        not in SUPPORTED_VOICE_GENDERS
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "gender must be one of: "
                "male, female"
            ),
        )

    return normalized


# ---------------------------------------------------------------------------
# Languages API
# GET /api/v1/catalog/languages
# ---------------------------------------------------------------------------


@router.get(
    "/languages",
    response_model=LanguagesResponse,
)
async def get_languages() -> LanguagesResponse:

    return LanguagesResponse(
        languages=[
            LanguageOptionResponse(
                id=language,
                label=LANGUAGE_LABELS[language],
            )
            for language in sorted(
                SUPPORTED_AGENT_LANGUAGES
            )
        ]
    )


# ---------------------------------------------------------------------------
# Accents API
# GET /api/v1/catalog/accents
# ---------------------------------------------------------------------------


@router.get(
    "/accents",
    response_model=AccentsResponse,
)
async def get_accents(
    language: str | None = Query(
        default=None,
    ),
) -> AccentsResponse:

    normalized_language = (
        _normalize_language(
            language
        )
    )

    voices = [
        voice
        for voice in filter_voices(language=normalized_language)
        if voice.selectable
    ]

    accent_labels = {
        voice.accent: voice.accent_label
        for voice in voices
    }

    return AccentsResponse(
        accents=[
            AccentOptionResponse(
                id=accent,
                label=accent_labels[accent],
            )
            for accent in sorted(accent_labels)
        ]
    )


# ---------------------------------------------------------------------------
# Voices API
# GET /api/v1/catalog/voices
# ---------------------------------------------------------------------------


@router.get(
    "/voices",
    response_model=VoicesResponse,
)
async def get_voices(
    language: str | None = Query(
        default=None,
    ),
    accent: str | None = Query(
        default=None,
    ),
    gender: str | None = Query(
        default=None,
    ),
) -> VoicesResponse:

    normalized_language = (
        _normalize_language(
            language
        )
    )

    normalized_gender = (
        _normalize_gender(
            gender
        )
    )

    normalized_accent = (
        accent.strip().lower()
        if accent is not None
        else None
    )

    voices = [
        voice
        for voice in filter_voices(
            language=normalized_language,
            accent=normalized_accent,
            gender=normalized_gender,
        )
        if voice.selectable
    ]

    return VoicesResponse(
        voices=[
            VoiceOptionResponse(
                id=voice.id,
                name=voice.name,
                gender=voice.gender,
                accent=voice.accent,
                accent_label=(
                    voice.accent_label
                ),
                languages=sorted(
                    voice.languages
                ),
            )
            for voice in sorted(
                voices,
                key=lambda item: item.id,
            )
        ]
    )


# ---------------------------------------------------------------------------
# Combined catalog: one call for the agent builder page
# GET /api/v1/catalog
#
# The three endpoints above stay as they are.
# This endpoint returns everything together so the
# frontend only needs one request and filters locally.
# ---------------------------------------------------------------------------


class CatalogAccentOption(BaseModel):
    id: str
    label: str
    languages: list[str]


class CatalogResponse(BaseModel):
    languages: list[LanguageOptionResponse]
    accents: list[CatalogAccentOption]
    voices: list[VoiceOptionResponse]


@router.get(
    "",
    response_model=CatalogResponse,
)
async def get_catalog() -> CatalogResponse:

    configured_voices = sorted(
        get_selectable_voices(),
        key=lambda item: item.id,
    )

    languages = [
        LanguageOptionResponse(
            id=language,
            label=LANGUAGE_LABELS[language],
        )
        for language in sorted(
            SUPPORTED_AGENT_LANGUAGES
        )
    ]

    # One entry per accent, with the languages it supports
    # so the frontend can filter:
    # Language -> Accent -> Voice.

    accent_labels: dict[str, str] = {}
    accent_languages: dict[str, set[str]] = {}

    for voice in configured_voices:
        accent_labels[voice.accent] = voice.accent_label

        accent_languages.setdefault(
            voice.accent,
            set(),
        ).update(voice.languages)

    accents = [
        CatalogAccentOption(
            id=accent,
            label=accent_labels[accent],
            languages=sorted(
                accent_languages[accent]
            ),
        )
        for accent in sorted(accent_labels)
    ]

    voices = [
        VoiceOptionResponse(
            id=voice.id,
            name=voice.name,
            gender=voice.gender,
            accent=voice.accent,
            accent_label=voice.accent_label,
            languages=sorted(voice.languages),
        )
        for voice in configured_voices
    ]

    return CatalogResponse(
        languages=languages,
        accents=accents,
        voices=voices,
    )


# ---------------------------------------------------------------------------
# NEW: Voice Preview API
# GET /api/v1/catalog/voices/{voice_id}/preview
#
# Generates a short sample using the selected voice.
# Returns browser-compatible WAV audio.
# Reuses cached audio to avoid unnecessary TTS requests.
# Requires Admin or Super Admin authentication.
# ---------------------------------------------------------------------------


@router.get(
    "/voices/{voice_id}/preview",
    response_class=Response,
    responses={
        200: {
            "description": "Voice preview audio",
            "content": {
                "audio/wav": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                    }
                }
            },
        },
        401: {
            "description": "Not authenticated"
        },
        403: {
            "description": "Permission denied"
        },
        404: {
            "description": "Voice not available"
        },
        502: {
            "description": "Preview generation failed"
        },
        504: {
            "description": "Preview generation timed out"
        },
    },
)
async def preview_voice(
    voice_id: str,
    current_user: User = Depends(
        require_role(
            UserRole.ADMIN,
            UserRole.SUPERADMIN,
        )
    ),
) -> Response:

    # Resolve the internal public voice ID.
    voice = get_voice_profile(voice_id)

    # Reject unknown or unconfigured voices.
    if voice is None or not voice.configured:
        raise HTTPException(
            status_code=404,
            detail="Voice not available.",
        )

    # Generate preview audio or reuse cached WAV.
    try:
        audio = await get_voice_preview(voice)

    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Voice preview generation timed out.",
        ) from None

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to generate voice preview.",
        ) from None

    # Return browser-compatible audio.
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition":
                'inline; filename="preview.wav"',
        },
    )
