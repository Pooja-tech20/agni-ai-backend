# import re
# import uuid
# from datetime import datetime
# from typing import Any, Literal

# from pydantic import BaseModel, ConfigDict, Field


# # ============================================================
# # COMMON
# # ============================================================

# AgentStatus = Literal[
#     "active",
#     "inactive",
# ]

# DEFAULT_AGENT_NAME = "Unnamed Agent"


# class BaseSchema(BaseModel):
#     model_config = ConfigDict(
#         from_attributes=True,
#     )


# class StrictSchema(BaseModel):
#     model_config = ConfigDict(
#         from_attributes=True,
#         extra="forbid",
#     )


# # ============================================================
# # AGENT BUILDER
# # ============================================================

# class Toggle(StrictSchema):
#     enabled: bool = False


# class Ref(StrictSchema):
#     id: str = Field(
#         min_length=1,
#         max_length=255,
#     )

#     name: str | None = Field(
#         default=None,
#         max_length=255,
#     )

#     gender: str | None = Field(
#         default=None,
#         max_length=50,
#     )


# class Accent(StrictSchema):
#     country: str | None = Field(
#         default=None,
#         max_length=100,
#     )

#     language: str | None = Field(
#         default=None,
#         max_length=100,
#     )

#     languages: list[str] = Field(
#         default_factory=list,
#     )


# class Welcome(StrictSchema):
#     enabled: bool = True
#     message: str | None = None


# class Calendar(StrictSchema):
#     enabled: bool = False

#     calendar_ids: list[str] = Field(
#         default_factory=list,
#     )


# class CrmSync(StrictSchema):
#     enabled: bool = False

#     provider: str | None = None

#     configuration: dict[str, Any] = Field(
#         default_factory=dict,
#     )


# class KnowledgeBaseRef(StrictSchema):
#     enabled: bool = False

#     knowledge_base_ids: list[uuid.UUID] = Field(
#         default_factory=list,
#     )


# # ============================================================
# # SPEECH
# # ============================================================

# class Silence(StrictSchema):
#     enabled: bool = False

#     timeout_seconds: int | None = Field(
#         default=None,
#         ge=1,
#         le=300,
#     )


# class Speech(StrictSchema):
#     language: str | None = None

#     speed: float | None = Field(
#         default=None,
#         ge=0.1,
#         le=5.0,
#     )

#     pitch: float | None = None

#     silence: Silence = Field(
#         default_factory=Silence,
#     )


# # ============================================================
# # CALL SETTINGS
# # ============================================================

# class MaxDuration(StrictSchema):
#     enabled: bool = False

#     seconds: int | None = Field(
#         default=None,
#         ge=1,
#     )


# class Fallback(StrictSchema):
#     enabled: bool = False

#     message: str | None = None


# class CallSettings(StrictSchema):
#     recording_enabled: bool = False

#     transcription_enabled: bool = False

#     max_duration: MaxDuration = Field(
#         default_factory=MaxDuration,
#     )

#     fallback: Fallback = Field(
#         default_factory=Fallback,
#     )


# # ============================================================
# # POST CALL
# # ============================================================

# class ExtractField(StrictSchema):
#     name: str = Field(
#         min_length=1,
#         max_length=100,
#     )

#     description: str = Field(
#         default="",
#         max_length=500,
#     )

#     type: str = Field(
#         default="string",
#         max_length=50,
#     )

#     required: bool = False


# class PostCall(StrictSchema):
#     enabled: bool = False

#     fields: list[ExtractField] = Field(
#         default_factory=list,
#     )


# # ============================================================
# # WEBHOOK
# # ============================================================

# class Webhook(StrictSchema):
#     url: str | None = None

#     method: str = "POST"

#     headers: dict[str, str] = Field(
#         default_factory=dict,
#     )

#     timeout_seconds: int = Field(
#         default=10,
#         ge=1,
#         le=120,
#     )


# class Webhooks(StrictSchema):
#     enabled: bool = False

#     events: list[str] = Field(
#         default_factory=list,
#     )

#     configuration: Webhook = Field(
#         default_factory=Webhook,
#     )


# # ============================================================
# # FUNCTIONS
# # ============================================================

# FUNCTION_TYPES = {
#     "end_call": "end_call",
#     "transfer_call": "transfer_call",
#     "ivr_press_digit": "press_digit",
#     "custom_function": "webhook",
# }


# class FunctionItem(StrictSchema):

#     type: Literal[
#         "end_call",
#         "transfer_call",
#         "ivr_press_digit",
#         "custom_function",
#     ]

#     name: str = Field(
#         min_length=1,
#         max_length=100,
#     )

#     description: str = Field(
#         default="",
#         max_length=1_000,
#     )

#     enabled: bool = True

#     configuration: dict[str, Any] = Field(
#         default_factory=dict,
#     )

#     @property
#     def backend_type(self) -> str:
#         return FUNCTION_TYPES[self.type]

#     def backend_config(self) -> dict[str, Any]:

#         config = dict(
#             self.configuration
#         )

#         # IVR / Press Digit
#         if (
#             self.type == "ivr_press_digit"
#             and "digit" in config
#         ):
#             config["digits"] = str(
#                 config.pop("digit")
#             )

#         # Transfer Call
#         if (
#             self.type == "transfer_call"
#             and isinstance(
#                 config.get("phone_number"),
#                 str,
#             )
#         ):
#             config["phone_number"] = re.sub(
#                 r"[\s\-()]",
#                 "",
#                 config["phone_number"],
#             )

#         # Custom Function
#         if (
#             self.type == "custom_function"
#             and not config.get("parameters")
#         ):
#             config.pop(
#                 "parameters",
#                 None,
#             )

#         return config


# # ============================================================
# # COMPLETE AGENT CREATE REQUEST
# #
# # POST /api/v1/agents
# # ============================================================

# class AgentCreateRequest(StrictSchema):

#     # --------------------------------------------------------
#     # BASIC
#     # --------------------------------------------------------

#     name: str | None = Field(
#         default=None,
#         min_length=1,
#         max_length=255,
#     )

#     status: AgentStatus = "active"

#     client_id: uuid.UUID | None = None

#     timezone: str = Field(
#         default="UTC",
#         max_length=64,
#     )

#     # --------------------------------------------------------
#     # MODEL
#     # --------------------------------------------------------

#     model: Ref | None = None

#     # --------------------------------------------------------
#     # VOICE
#     # --------------------------------------------------------

#     voice: Ref | None = None

#     # --------------------------------------------------------
#     # MEMORY
#     # --------------------------------------------------------

#     memory: Toggle = Field(
#         default_factory=Toggle,
#     )

#     # --------------------------------------------------------
#     # EMOTION
#     # --------------------------------------------------------

#     emotion: Toggle = Field(
#         default_factory=Toggle,
#     )

#     # --------------------------------------------------------
#     # ACCENT
#     # --------------------------------------------------------

#     accent: Accent = Field(
#         default_factory=Accent,
#     )

#     # --------------------------------------------------------
#     # WELCOME
#     # --------------------------------------------------------

#     welcome_message: Welcome = Field(
#         default_factory=Welcome,
#     )

#     # --------------------------------------------------------
#     # SYSTEM PROMPT
#     # --------------------------------------------------------

#     system_prompt: dict[str, str | None] = Field(
#         default_factory=dict,
#     )

#     # --------------------------------------------------------
#     # FUNCTIONS
#     # --------------------------------------------------------

#     functions: list[FunctionItem] = Field(
#         default_factory=list,
#         max_length=30,
#     )

#     # --------------------------------------------------------
#     # CALENDAR
#     # --------------------------------------------------------

#     calendar: Calendar = Field(
#         default_factory=Calendar,
#     )

#     # --------------------------------------------------------
#     # CRM
#     # --------------------------------------------------------

#     crm_sync: CrmSync = Field(
#         default_factory=CrmSync,
#     )

#     # --------------------------------------------------------
#     # KNOWLEDGE BASE
#     # --------------------------------------------------------

#     knowledge_base: KnowledgeBaseRef = Field(
#         default_factory=KnowledgeBaseRef,
#     )

#     # --------------------------------------------------------
#     # SPEECH
#     # --------------------------------------------------------

#     speech_settings: Speech = Field(
#         default_factory=Speech,
#     )

#     # --------------------------------------------------------
#     # CALL SETTINGS
#     # --------------------------------------------------------

#     call_settings: CallSettings = Field(
#         default_factory=CallSettings,
#     )

#     # --------------------------------------------------------
#     # POST CALL
#     # --------------------------------------------------------

#     post_call_data_extraction: PostCall = Field(
#         default_factory=PostCall,
#     )

#     # --------------------------------------------------------
#     # WEBHOOK
#     # --------------------------------------------------------

#     webhook_settings: Webhooks = Field(
#         default_factory=Webhooks,
#     )

#     # --------------------------------------------------------
#     # PROMPT VARIABLES
#     # --------------------------------------------------------

#     prompt_variables: dict[str, str] = Field(
#         default_factory=dict,
#     )

#     # --------------------------------------------------------
#     # METADATA
#     # --------------------------------------------------------

#     metadata: dict[str, Any] = Field(
#         default_factory=dict,
#     )

#     # ========================================================
#     # DATABASE CONVERSION
#     # ========================================================

#     def to_agent_columns(self) -> dict[str, Any]:

#         # System prompt
#         system_prompt_value = (
#             self.system_prompt.get("content")
#         )

#         # Welcome message
#         welcome_message_value = None

#         if self.welcome_message.enabled:
#             welcome_message_value = (
#                 self.welcome_message.message
#             )

#         # Model
#         llm_model = None

#         if self.model:
#             llm_model = self.model.id

#         # Voice
#         voice_value = None

#         if self.voice:
#             voice_value = self.voice.id

#         # Emotion
#         emotion_value = (
#             "enabled"
#             if self.emotion.enabled
#             else None
#         )

#         # Accent
#         accent_value = self.accent.country

#         # Calendar
#         calendars = []

#         if self.calendar.enabled:

#             calendars = [
#                 {
#                     "id": calendar_id,
#                 }
#                 for calendar_id
#                 in self.calendar.calendar_ids
#             ]

#         # Knowledge base
#         knowledge_base = []

#         if self.knowledge_base.enabled:

#             knowledge_base = [
#                 {
#                     "id": str(kb_id),
#                 }
#                 for kb_id
#                 in self.knowledge_base.knowledge_base_ids
#             ]

#         # Builder metadata
#         builder_metadata = {
#             "model_name": (
#                 self.model.name
#                 if self.model
#                 else None
#             ),
#             "voice_name": (
#                 self.voice.name
#                 if self.voice
#                 else None
#             ),
#             "gender": (
#                 self.voice.gender
#                 if self.voice
#                 else None
#             ),
#             "accent_languages": (
#                 self.accent.languages
#             ),
#         }

#         return {
#             "status": self.status,

#             "timezone": self.timezone,

#             "system_prompt": system_prompt_value,

#             "welcome_message": welcome_message_value,

#             "llm_model": llm_model,

#             "voice": voice_value,

#             "memory_enabled": (
#                 self.memory.enabled
#             ),

#             "emotion": emotion_value,

#             "accent": accent_value,

#             "calendars": calendars,

#             "knowledge_base": knowledge_base,

#             "crm_sync": (
#                 self.crm_sync.model_dump()
#             ),

#             "speech_settings": (
#                 self.speech_settings.model_dump()
#             ),

#             "call_settings": (
#                 self.call_settings.model_dump()
#             ),

#             "post_call_extraction": (
#                 self.post_call_data_extraction.model_dump()
#             ),

#             "webhook_settings": (
#                 self.webhook_settings.model_dump()
#             ),

#             "prompt_variables": (
#                 self.prompt_variables
#             ),

#             "agent_metadata": {
#                 "builder": builder_metadata,
#                 **self.metadata,
#             },
#         }


# # ============================================================
# # AGENT RESPONSE / EXISTING API SCHEMAS
# # ============================================================

# class AgentConfig(BaseSchema):

#     system_prompt: str | None = None

#     welcome_message: str | None = None

#     llm_model: str | None = None

#     voice: str | None = None

#     memory_enabled: bool = False

#     emotion: str | None = None

#     accent: str | None = None

#     timezone: str = "UTC"

#     functions: list[dict[str, Any]] = Field(
#         default_factory=list,
#     )

#     calendars: list[dict[str, Any]] = Field(
#         default_factory=list,
#     )

#     knowledge_base: list[dict[str, Any]] = Field(
#         default_factory=list,
#     )

#     crm_sync: dict[str, Any] = Field(
#         default_factory=dict,
#     )

#     speech_settings: dict[str, Any] = Field(
#         default_factory=dict,
#     )

#     call_settings: dict[str, Any] = Field(
#         default_factory=dict,
#     )

#     post_call_extraction: dict[str, Any] = Field(
#         default_factory=dict,
#     )

#     webhook_settings: dict[str, Any] = Field(
#         default_factory=dict,
#     )

#     prompt_variables: dict[str, str] = Field(
#         default_factory=dict,
#     )

#     agent_metadata: dict[str, Any] = Field(
#         default_factory=dict,
#     )


# class AgentUpdateRequest(BaseSchema):

#     name: str | None = Field(
#         default=None,
#         min_length=1,
#         max_length=255,
#     )

#     status: AgentStatus | None = None

#     client_id: uuid.UUID | None = None

#     system_prompt: str | None = None

#     welcome_message: str | None = None

#     llm_model: str | None = None

#     voice: str | None = None

#     memory_enabled: bool | None = None

#     emotion: str | None = None

#     accent: str | None = None

#     timezone: str | None = Field(
#         default=None,
#         max_length=64,
#     )

#     functions: list[dict[str, Any]] | None = None

#     calendars: list[dict[str, Any]] | None = None

#     knowledge_base: list[dict[str, Any]] | None = None

#     crm_sync: dict[str, Any] | None = None

#     speech_settings: dict[str, Any] | None = None

#     call_settings: dict[str, Any] | None = None

#     post_call_extraction: dict[str, Any] | None = None

#     webhook_settings: dict[str, Any] | None = None

#     prompt_variables: dict[str, str] | None = None

#     agent_metadata: dict[str, Any] | None = None


# class AgentResponse(AgentConfig):

#     id: uuid.UUID

#     name: str

#     status: AgentStatus

#     client_id: uuid.UUID

#     total_calls: int = 0

#     created_at: datetime

#     updated_at: datetime


# class AgentSummary(BaseSchema):

#     id: uuid.UUID

#     name: str

#     status: AgentStatus

#     client_id: uuid.UUID

#     total_calls: int = 0

#     created_at: datetime

#     updated_at: datetime


# class AgentListResponse(BaseSchema):

#     items: list[AgentSummary]

#     total: int

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# COMMON
# ============================================================

AgentStatus = Literal[
    "active",
    "inactive",
]

DEFAULT_AGENT_NAME = "Unnamed Agent"


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )


class StrictSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
    )


# ============================================================
# AGENT BUILDER
# ============================================================

class Toggle(StrictSchema):
    enabled: bool = False


class Ref(StrictSchema):
    id: str = Field(
        min_length=1,
        max_length=255,
    )

    name: str | None = Field(
        default=None,
        max_length=255,
    )

    gender: str | None = Field(
        default=None,
        max_length=50,
    )


class Accent(StrictSchema):
    country: str | None = Field(
        default=None,
        max_length=100,
    )

    language: str | None = Field(
        default=None,
        max_length=100,
    )

    languages: list[str] = Field(
        default_factory=list,
    )


class Welcome(StrictSchema):
    enabled: bool = True

    message: str | None = None


# ============================================================
# CALENDAR
# ============================================================

class Calendar(StrictSchema):
    enabled: bool = False

    calendar_id: str | None = None

    # Also support multiple calendars if needed later.
    calendar_ids: list[str] = Field(
        default_factory=list,
    )


# ============================================================
# CRM
# ============================================================

class CrmSync(StrictSchema):
    enabled: bool = False

    provider: str | None = None

    connection_id: str | None = None

    sync_leads: bool = False

    configuration: dict[str, Any] = Field(
        default_factory=dict,
    )


# ============================================================
# KNOWLEDGE BASE
# ============================================================

class KnowledgeBaseRef(StrictSchema):
    enabled: bool = False

    knowledge_base_ids: list[uuid.UUID] = Field(
        default_factory=list,
    )


# ============================================================
# SPEECH SETTINGS
# ============================================================

class ReminderMessage(StrictSchema):
    enabled: bool = False

    interval_seconds: int = Field(
        default=10,
        ge=1,
    )

    max_reminders: int = Field(
        default=1,
        ge=0,
    )

    message: str | None = None


class Speech(StrictSchema):
    transcription_language: str | None = None

    background_sound: str | None = None

    interruption_sensitivity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    speech_speed: float | None = Field(
        default=None,
        ge=0.1,
        le=5.0,
    )

    # Keep compatibility with previous structure.
    language: str | None = None

    speed: float | None = Field(
        default=None,
        ge=0.1,
        le=5.0,
    )

    pitch: float | None = None

    silence: "Silence" = Field(
        default_factory=lambda: Silence(),
    )

    reminder_message: ReminderMessage = Field(
        default_factory=ReminderMessage,
    )


# ============================================================
# CALL SETTINGS
# ============================================================

class Silence(StrictSchema):
    enabled: bool = False

    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        le=300,
    )


class MaxDuration(StrictSchema):
    enabled: bool = False

    duration_minutes: int | None = Field(
        default=None,
        ge=1,
    )

    # Compatibility with previous structure.
    seconds: int | None = Field(
        default=None,
        ge=1,
    )


class EmergencyFallback(StrictSchema):
    enabled: bool = False

    phone_number: str | None = None


class Fallback(StrictSchema):
    enabled: bool = False

    message: str | None = None


class CallSettings(StrictSchema):
    voicemail_detection: bool = False

    end_call_on_silence: Silence = Field(
        default_factory=Silence,
    )

    max_duration: MaxDuration = Field(
        default_factory=MaxDuration,
    )

    emergency_fallback: EmergencyFallback = Field(
        default_factory=EmergencyFallback,
    )

    advanced: dict[str, Any] = Field(
        default_factory=dict,
    )

    # Compatibility with previous structure.
    recording_enabled: bool = False

    transcription_enabled: bool = False

    fallback: Fallback = Field(
        default_factory=Fallback,
    )


# ============================================================
# POST CALL DATA EXTRACTION
# ============================================================

class ExtractField(StrictSchema):
    name: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str = Field(
        default="",
        max_length=500,
    )

    type: str = Field(
        default="string",
        max_length=50,
    )

    required: bool = False

    allowed_values: list[str] = Field(
        default_factory=list,
    )


class PostCall(StrictSchema):
    enabled: bool = False

    model: str | None = None

    fields: list[ExtractField] = Field(
        default_factory=list,
    )


# ============================================================
# WEBHOOK
# ============================================================

class Webhook(StrictSchema):
    url: str | None = None

    method: str = "POST"

    headers: dict[str, str] = Field(
        default_factory=dict,
    )

    retries: int = Field(
        default=0,
        ge=0,
    )

    timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
    )


class Webhooks(StrictSchema):
    enabled: bool = False

    webhooks: list[Webhook] = Field(
        default_factory=list,
    )

    # Compatibility with previous structure.
    events: list[str] = Field(
        default_factory=list,
    )

    configuration: Webhook = Field(
        default_factory=Webhook,
    )

# ============================================================
# FUNCTIONS
# ============================================================

FUNCTION_TYPES = {
    "end_call": "end_call",
    "transfer_call": "transfer_call",
    "ivr_press_digit": "press_digit",
    "custom_function": "webhook",
}


# ============================================================
# END CALL
# ============================================================

class EndCallConfig(StrictSchema):

    execution_message: str | None = None


# ============================================================
# TRANSFER CALL
# ============================================================

class TransferSchedule(StrictSchema):

    timezone: str | None = None

    start_time: str | None = None

    end_time: str | None = None


class TransferCallConfig(StrictSchema):

    on_hold_music: bool = False

    execution_message: str | None = None

    transfer_mode: Literal[
        "cold_transfer",
        "warm_transfer",
    ] = "cold_transfer"

    assign_human_agent: bool = False

    transfer_to: Literal[
        "static",
        "dynamic",
    ] = "static"

    phone_number: str | None = None

    country_code: str = "+91"

    client_transfer_number: str | None = None

    schedule: TransferSchedule | None = None


# ============================================================
# IVR / PRESS DIGIT
# ============================================================

class IVRPressDigitConfig(StrictSchema):

    digit: str = Field(
        min_length=1,
        max_length=1,
    )

    pause_detection_delay_ms: int = Field(
        default=1000,
        ge=0,
        le=60000,
    )


# ============================================================
# CUSTOM FUNCTION
# ============================================================

class CustomFunctionConfig(StrictSchema):

    function_type: Literal[
        "custom",
        "client",
    ] = "custom"

    method: Literal[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ] = "POST"

    url: str | None = None

    headers: dict[str, str] = Field(
        default_factory=dict,
    )

    parameters: dict[str, Any] = Field(
        default_factory=dict,
    )

    execution_message: str | None = None


# ============================================================
# FUNCTION ITEM
# ============================================================

class FunctionItem(StrictSchema):

    type: Literal[
        "end_call",
        "transfer_call",
        "ivr_press_digit",
        "custom_function",
    ]

    name: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str = Field(
        default="",
        max_length=1_000,
    )

    enabled: bool = True

    configuration: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def backend_type(self) -> str:
        return FUNCTION_TYPES[self.type]

    def backend_config(self) -> dict[str, Any]:

        # ----------------------------------------------------
        # END CALL
        # ----------------------------------------------------

        if self.type == "end_call":

            config = EndCallConfig(
                **self.configuration
            )

            return config.model_dump(
                exclude_none=True
            )

        # ----------------------------------------------------
        # TRANSFER CALL
        # ----------------------------------------------------

        if self.type == "transfer_call":

            config = TransferCallConfig(
                **self.configuration
            )

            data = config.model_dump(
                exclude_none=True
            )

            # Clean phone number
            if isinstance(
                data.get("phone_number"),
                str,
            ):
                data["phone_number"] = re.sub(
                    r"[\s\-()]",
                    "",
                    data["phone_number"],
                )

            if isinstance(
                data.get("client_transfer_number"),
                str,
            ):
                data["client_transfer_number"] = re.sub(
                    r"[\s\-()]",
                    "",
                    data["client_transfer_number"],
                )

            return data

        # ----------------------------------------------------
        # IVR / PRESS DIGIT
        # ----------------------------------------------------

        if self.type == "ivr_press_digit":

            config = IVRPressDigitConfig(
                **self.configuration
            )

            data = config.model_dump(
                exclude_none=True
            )

            # Existing database/backend expects
            # "digits" instead of "digit".
            data["digits"] = data.pop("digit")

            return data

        # ----------------------------------------------------
        # CUSTOM FUNCTION
        # ----------------------------------------------------

        if self.type == "custom_function":

            config = CustomFunctionConfig(
                **self.configuration
            )

            return config.model_dump(
                exclude_none=True
            )

        return {}

# ============================================================
# COMPLETE AGENT CREATE REQUEST
#
# POST /api/v1/agents
# ============================================================

class AgentCreateRequest(StrictSchema):

    # --------------------------------------------------------
    # BASIC
    # --------------------------------------------------------

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )

    status: AgentStatus = "active"

    client_id: uuid.UUID | None = None

    timezone: str = Field(
        default="UTC",
        max_length=64,
    )

    # --------------------------------------------------------
    # MODEL
    # --------------------------------------------------------

    model: Ref | None = None

    # --------------------------------------------------------
    # VOICE
    # --------------------------------------------------------

    voice: Ref | None = None

    # --------------------------------------------------------
    # MEMORY
    # --------------------------------------------------------

    memory: Toggle = Field(
        default_factory=Toggle,
    )

    # --------------------------------------------------------
    # EMOTION
    # --------------------------------------------------------

    emotion: Toggle = Field(
        default_factory=Toggle,
    )

    # --------------------------------------------------------
    # ACCENT
    # --------------------------------------------------------

    accent: Accent = Field(
        default_factory=Accent,
    )

    # --------------------------------------------------------
    # WELCOME
    # --------------------------------------------------------

    welcome_message: Welcome = Field(
        default_factory=Welcome,
    )

    # --------------------------------------------------------
    # SYSTEM PROMPT
    # --------------------------------------------------------

    system_prompt: dict[str, str | None] = Field(
        default_factory=dict,
    )

    # --------------------------------------------------------
    # FUNCTIONS
    # --------------------------------------------------------

    functions: list[FunctionItem] = Field(
        default_factory=list,
        max_length=30,
    )

    # --------------------------------------------------------
    # CALENDAR
    # --------------------------------------------------------

    calendar: Calendar = Field(
        default_factory=Calendar,
    )

    # --------------------------------------------------------
    # CRM
    # --------------------------------------------------------

    crm_sync: CrmSync = Field(
        default_factory=CrmSync,
    )

    # --------------------------------------------------------
    # KNOWLEDGE BASE
    # --------------------------------------------------------

    knowledge_base: KnowledgeBaseRef = Field(
        default_factory=KnowledgeBaseRef,
    )

    # --------------------------------------------------------
    # SPEECH
    # --------------------------------------------------------

    speech_settings: Speech = Field(
        default_factory=Speech,
    )

    # --------------------------------------------------------
    # CALL SETTINGS
    # --------------------------------------------------------

    call_settings: CallSettings = Field(
        default_factory=CallSettings,
    )

    # --------------------------------------------------------
    # POST CALL
    # --------------------------------------------------------

    post_call_data_extraction: PostCall = Field(
        default_factory=PostCall,
    )

    # --------------------------------------------------------
    # WEBHOOK
    # --------------------------------------------------------

    webhook_settings: Webhooks = Field(
        default_factory=Webhooks,
    )

    # --------------------------------------------------------
    # PROMPT VARIABLES
    # --------------------------------------------------------

    prompt_variables: dict[str, str] = Field(
        default_factory=dict,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    # ========================================================
    # DATABASE CONVERSION
    # ========================================================

    def to_agent_columns(self) -> dict[str, Any]:

        # System prompt
        system_prompt_value = (
            self.system_prompt.get("content")
        )

        # Welcome message
        welcome_message_value = None

        if self.welcome_message.enabled:
            welcome_message_value = (
                self.welcome_message.message
            )

        # Model
        llm_model = None

        if self.model:
            llm_model = self.model.id

        # Voice
        voice_value = None

        if self.voice:
            voice_value = self.voice.id

        # Emotion
        emotion_value = (
            "enabled"
            if self.emotion.enabled
            else None
        )

        # Accent
        accent_value = self.accent.country

        # Calendar
        calendars = []

        if self.calendar.enabled:

            if self.calendar.calendar_ids:
                calendars = [
                    {
                        "id": calendar_id,
                    }
                    for calendar_id
                    in self.calendar.calendar_ids
                ]

            elif self.calendar.calendar_id:
                calendars = [
                    {
                        "id": self.calendar.calendar_id,
                    }
                ]

        # Knowledge base
        knowledge_base = []

        if self.knowledge_base.enabled:

            knowledge_base = [
                {
                    "id": str(kb_id),
                }
                for kb_id
                in self.knowledge_base.knowledge_base_ids
            ]

        # Builder metadata
        builder_metadata = {
            "model_name": (
                self.model.name
                if self.model
                else None
            ),
            "voice_name": (
                self.voice.name
                if self.voice
                else None
            ),
            "gender": (
                self.voice.gender
                if self.voice
                else None
            ),
            "accent_languages": (
                self.accent.languages
            ),
        }

        return {
            "status": self.status,

            "timezone": self.timezone,

            "system_prompt": system_prompt_value,

            "welcome_message": welcome_message_value,

            "llm_model": llm_model,

            "voice": voice_value,

            "memory_enabled": (
                self.memory.enabled
            ),

            "emotion": emotion_value,

            "accent": accent_value,

            "calendars": calendars,

            "knowledge_base": knowledge_base,

            "crm_sync": (
                self.crm_sync.model_dump()
            ),

            "speech_settings": (
                self.speech_settings.model_dump()
            ),

            "call_settings": (
                self.call_settings.model_dump()
            ),

            "post_call_extraction": (
                self.post_call_data_extraction.model_dump()
            ),

            "webhook_settings": (
                self.webhook_settings.model_dump()
            ),

            "prompt_variables": (
                self.prompt_variables
            ),

            "agent_metadata": {
                "builder": builder_metadata,
                **self.metadata,
            },
        }


# ============================================================
# AGENT RESPONSE / EXISTING API SCHEMAS
# ============================================================

class AgentConfig(BaseSchema):

    system_prompt: str | None = None

    welcome_message: str | None = None

    llm_model: str | None = None

    voice: str | None = None

    memory_enabled: bool = False

    emotion: str | None = None

    accent: str | None = None

    timezone: str = "UTC"

    functions: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    calendars: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    knowledge_base: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    crm_sync: dict[str, Any] = Field(
        default_factory=dict,
    )

    speech_settings: dict[str, Any] = Field(
        default_factory=dict,
    )

    call_settings: dict[str, Any] = Field(
        default_factory=dict,
    )

    post_call_extraction: dict[str, Any] = Field(
        default_factory=dict,
    )

    webhook_settings: dict[str, Any] = Field(
        default_factory=dict,
    )

    prompt_variables: dict[str, str] = Field(
        default_factory=dict,
    )

    agent_metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class AgentUpdateRequest(BaseSchema):

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )

    status: AgentStatus | None = None

    client_id: uuid.UUID | None = None

    system_prompt: str | None = None

    welcome_message: str | None = None

    llm_model: str | None = None

    voice: str | None = None

    memory_enabled: bool | None = None

    emotion: str | None = None

    accent: str | None = None

    timezone: str | None = Field(
        default=None,
        max_length=64,
    )

    functions: list[dict[str, Any]] | None = None

    calendars: list[dict[str, Any]] | None = None

    knowledge_base: list[dict[str, Any]] | None = None

    crm_sync: dict[str, Any] | None = None

    speech_settings: dict[str, Any] | None = None

    call_settings: dict[str, Any] | None = None

    post_call_extraction: dict[str, Any] | None = None

    webhook_settings: dict[str, Any] | None = None

    prompt_variables: dict[str, str] | None = None

    agent_metadata: dict[str, Any] | None = None


class AgentResponse(AgentConfig):

    id: uuid.UUID

    name: str

    status: AgentStatus

    client_id: uuid.UUID

    total_calls: int = 0

    created_at: datetime

    updated_at: datetime


class AgentSummary(BaseSchema):

    id: uuid.UUID

    name: str

    status: AgentStatus

    client_id: uuid.UUID

    total_calls: int = 0

    created_at: datetime

    updated_at: datetime


class AgentListResponse(BaseSchema):

    items: list[AgentSummary]

    total: int
