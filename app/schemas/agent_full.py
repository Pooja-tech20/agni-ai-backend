"""Nested request body for POST /agents/full (one call creates a fully configured agent).
`to_agent_columns()` flattens it onto the existing Agent columns - no migration needed."""
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.url_safety import check_public_http_url
from app.schemas.agent import AgentStatus

E164 = re.compile(r"^\+[1-9]\d{6,14}$")
# builder function type -> type stored by the functions API
FUNCTION_TYPES = {
    "end_call": "end_call",
    "transfer_call": "transfer_call",
    "ivr_press_digit": "press_digit",
    "custom_function": "webhook",
}


def _need(ok: bool, msg: str) -> None:
    if not ok:
        raise ValueError(msg)


def _phone(v: str | None) -> str | None:
    if v is None:
        return None
    v = re.sub(r"[\s\-()]", "", v)
    _need(bool(E164.match(v)), "phone_number must be E.164, e.g. +919876543210")
    return v


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")  # typos fail instead of vanishing


class Toggle(_S):
    enabled: bool = False


class Ref(_S):
    id: str = Field(min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=100)
    gender: Literal["male", "female"] | None = None  # voices only


class Accent(_S):
    country: str | None = Field(default=None, max_length=50)
    languages: list[str] = Field(default_factory=list, max_length=10)


class Welcome(_S):
    enabled: bool = False
    message: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def _v(self):
        _need(not self.enabled or bool((self.message or "").strip()), "message is required when enabled")
        return self


class FunctionItem(_S):
    type: Literal["end_call", "transfer_call", "ivr_press_digit", "custom_function"]
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1_000)  # tells the LLM when to call it
    enabled: bool = True
    configuration: dict[str, Any] = Field(default_factory=dict)

    @property
    def backend_type(self) -> str:
        return FUNCTION_TYPES[self.type]

    def backend_config(self) -> dict[str, Any]:
        cfg = dict(self.configuration)
        if self.type == "ivr_press_digit" and "digit" in cfg:
            cfg["digits"] = str(cfg.pop("digit"))
        if self.type == "transfer_call" and isinstance(cfg.get("phone_number"), str):
            cfg["phone_number"] = re.sub(r"[\s\-()]", "", cfg["phone_number"])
        if self.type == "custom_function" and not cfg.get("parameters"):
            cfg.pop("parameters", None)  # use the empty JSON Schema default
        return cfg


class Calendar(_S):
    enabled: bool = False
    calendar_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _v(self):
        _need(not self.enabled or bool(self.calendar_id), "calendar_id is required when enabled")
        return self


class CrmSync(_S):
    enabled: bool = False
    provider: str | None = Field(default=None, max_length=50)
    connection_id: str | None = Field(default=None, max_length=255)
    sync_leads: bool = False

    @model_validator(mode="after")
    def _v(self):
        _need(not self.enabled or bool(self.provider and self.connection_id), "provider and connection_id are required when enabled")
        return self


class KnowledgeBaseRef(_S):
    enabled: bool = False
    knowledge_base_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _v(self):
        self.knowledge_base_ids = list(dict.fromkeys(self.knowledge_base_ids))
        _need(not self.enabled or bool(self.knowledge_base_ids), "knowledge_base_ids is required when enabled")
        return self


class Reminder(_S):
    enabled: bool = False
    interval_seconds: int = Field(default=10, ge=1, le=600)
    max_reminders: int = Field(default=1, ge=1, le=10)
    message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _v(self):
        _need(not self.enabled or bool((self.message or "").strip()), "message is required when enabled")
        return self


class Speech(_S):
    transcription_language: str = Field(default="auto", max_length=20)
    background_sound: str = Field(default="none", max_length=50)
    interruption_sensitivity: float = Field(default=0.5, ge=0, le=1)
    speech_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    reminder_message: Reminder = Field(default_factory=Reminder)


class Silence(_S):
    enabled: bool = False
    timeout_seconds: int = Field(default=10, ge=1, le=600)


class MaxDuration(_S):
    enabled: bool = False
    duration_minutes: int = Field(default=30, ge=1, le=240)


class Fallback(_S):
    enabled: bool = False
    phone_number: str | None = None

    @model_validator(mode="after")
    def _v(self):
        self.phone_number = _phone(self.phone_number)
        _need(not self.enabled or bool(self.phone_number), "phone_number is required when enabled")
        return self


class CallSettings(_S):
    voicemail_detection: bool = False
    end_call_on_silence: Silence = Field(default_factory=Silence)
    max_duration: MaxDuration = Field(default_factory=MaxDuration)
    emergency_fallback: Fallback = Field(default_factory=Fallback)
    advanced: dict[str, Any] = Field(default_factory=dict)


class ExtractField(_S):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    description: str = Field(default="", max_length=1_000)
    type: Literal["text", "enum", "number", "boolean"] = "text"
    allowed_values: list[str] | None = None

    @model_validator(mode="after")
    def _v(self):
        _need(self.type != "enum" or bool(self.allowed_values), "allowed_values is required for enum")
        if self.type != "enum":
            self.allowed_values = None
        return self


class PostCall(_S):
    enabled: bool = False
    model: str | None = Field(default=None, max_length=100)
    fields: list[ExtractField] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _v(self):
        names = [f.name.lower() for f in self.fields]
        _need(len(names) == len(set(names)), "field names must be unique")
        return self


class Webhook(_S):
    url: str = Field(max_length=2_000)
    headers: dict[str, str] = Field(default_factory=dict)
    retries: int = Field(default=0, ge=0, le=5)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return check_public_http_url(v)

    @field_validator("headers")
    @classmethod
    def _headers(cls, v: dict[str, str]) -> dict[str, str]:
        _need(len(v) <= 20, "at most 20 headers")
        for k, val in v.items():
            _need(bool(re.fullmatch(r"[A-Za-z0-9-]{1,64}", k)), f"invalid header name '{k}'")
            _need(len(val) <= 2_000 and "\r" not in val and "\n" not in val, f"invalid value for header '{k}'")
        return v


class Webhooks(_S):
    enabled: bool = False
    webhooks: list[Webhook] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _v(self):
        _need(not self.enabled or bool(self.webhooks), "at least one webhook is required when enabled")
        return self


class AgentFullCreateRequest(_S):
    name: str = Field(min_length=1, max_length=255)
    status: AgentStatus = "active"
    client_id: uuid.UUID | None = None  # superadmin only
    timezone: str = Field(default="UTC", max_length=64)

    model: Ref | None = None
    voice: Ref | None = None
    memory: Toggle = Field(default_factory=Toggle)
    emotion: Toggle = Field(default_factory=Toggle)
    accent: Accent = Field(default_factory=Accent)
    welcome_message: Welcome = Field(default_factory=Welcome)
    system_prompt: dict[str, str | None] = Field(default_factory=dict)  # {"content": "..."}

    functions: list[FunctionItem] = Field(default_factory=list, max_length=30)
    calendar: Calendar = Field(default_factory=Calendar)
    crm_sync: CrmSync = Field(default_factory=CrmSync)
    knowledge_base: KnowledgeBaseRef = Field(default_factory=KnowledgeBaseRef)
    speech_settings: Speech = Field(default_factory=Speech)
    call_settings: CallSettings = Field(default_factory=CallSettings)
    post_call_data_extraction: PostCall = Field(default_factory=PostCall)
    webhook_settings: Webhooks = Field(default_factory=Webhooks)

    prompt_variables: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        _need(bool(v), "must not be blank")
        return v

    @field_validator("system_prompt")
    @classmethod
    def _prompt(cls, v: dict) -> dict:
        _need(set(v) <= {"content"}, "only 'content' is allowed")
        _need(len(v.get("content") or "") <= 50_000, "content too long (max 50000)")
        return v

    @field_validator("metadata")
    @classmethod
    def _meta(cls, v: dict) -> dict:
        _need("builder" not in v, "'builder' is a reserved metadata key")
        return v

    def to_agent_columns(self) -> dict[str, Any]:
        """Column values for Agent(...), except name, client_id and functions."""
        cal = self.calendar
        return {
            "status": self.status,
            "timezone": self.timezone,
            "system_prompt": self.system_prompt.get("content"),
            "welcome_message": self.welcome_message.message if self.welcome_message.enabled else None,
            "llm_model": self.model.id if self.model else None,
            "voice": self.voice.id if self.voice else None,
            "memory_enabled": self.memory.enabled,
            "emotion": "enabled" if self.emotion.enabled else None,
            "accent": self.accent.country,
            "calendars": [{"calendar_id": cal.calendar_id, "enabled": cal.enabled}] if cal.calendar_id else [],
            "knowledge_base": (
                [{"id": str(i)} for i in self.knowledge_base.knowledge_base_ids]
                if self.knowledge_base.enabled else []
            ),
            "crm_sync": self.crm_sync.model_dump(),
            "speech_settings": self.speech_settings.model_dump(),
            "call_settings": self.call_settings.model_dump(),
            "post_call_extraction": self.post_call_data_extraction.model_dump(),
            "webhook_settings": self.webhook_settings.model_dump(),
            "prompt_variables": self.prompt_variables,
            "agent_metadata": {
                **self.metadata,
                # display details the flat columns have no room for
                "builder": {
                    "model_name": self.model.name if self.model else None,
                    "voice_name": self.voice.name if self.voice else None,
                    "voice_gender": self.voice.gender if self.voice else None,
                    "accent_languages": self.accent.languages,
                },
            },
        }