# import json
# import re
# import uuid
# from datetime import datetime
# from typing import Any, Literal

# from pydantic import BaseModel, ConfigDict, Field, field_validator

# from app.core.url_safety import check_public_http_url
# from app.schemas.base import BaseSchema

# FunctionType = Literal["webhook", "transfer_call", "end_call", "press_digit"]

# # Tool names must be safe for LLM tool-calling APIs
# NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
# MASK = "••••"


# # --------------------------------------------------------------------------
# # Per-type config
# # --------------------------------------------------------------------------
# class _Config(BaseModel):
#     model_config = ConfigDict(extra="forbid")


# class WebhookConfig(_Config):
#     url: str = Field(max_length=2000)
#     method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
#     headers: dict[str, str] = Field(default_factory=dict)
#     timeout_seconds: int = Field(default=10, ge=1, le=30)
#     # JSON-Schema object describing the arguments the LLM must provide
#     parameters: dict[str, Any] = Field(
#         default_factory=lambda: {"type": "object", "properties": {}}
#     )

#     @field_validator("url")
#     @classmethod
#     def _url(cls, v: str) -> str:
#         return check_public_http_url(v)

#     @field_validator("headers")
#     @classmethod
#     def _headers(cls, v: dict[str, str]) -> dict[str, str]:
#         if len(v) > 20:
#             raise ValueError("at most 20 headers")
#         for name, value in v.items():
#             if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name):
#                 raise ValueError(f"invalid header name '{name}'")
#             if len(value) > 2000 or "\r" in value or "\n" in value:
#                 raise ValueError(f"invalid value for header '{name}'")
#         return v

#     @field_validator("parameters")
#     @classmethod
#     def _parameters(cls, v: dict[str, Any]) -> dict[str, Any]:
#         if v.get("type") != "object":
#             raise ValueError("parameters must be a JSON Schema with type 'object'")
#         if not isinstance(v.get("properties", {}), dict):
#             raise ValueError("parameters.properties must be an object")
#         if len(json.dumps(v)) > 20_000:
#             raise ValueError("parameters schema is too large")
#         return v


# class TransferCallConfig(_Config):
#     phone_number: str = Field(pattern=r"^\+[1-9]\d{6,14}$", description="E.164, e.g. +919876543210")
#     announcement: str | None = Field(default=None, max_length=500)


# class EndCallConfig(_Config):
#     message: str | None = Field(default=None, max_length=500)


# class PressDigitConfig(_Config):
#     digits: str = Field(pattern=r"^[0-9*#]{1,20}$")


# # Order and wording match the "Add Function" dropdown in the UI.
# CONFIG_MODELS: dict[str, type[_Config]] = {
#     "end_call": EndCallConfig,
#     "transfer_call": TransferCallConfig,
#     "press_digit": PressDigitConfig,
#     "webhook": WebhookConfig,
# }

# TYPE_INFO = {
#     "end_call": ("End Call", "Terminate the call at a specific point"),
#     "transfer_call": ("Transfer Call", "Transfer the call to a phone number"),
#     "press_digit": ("IVR / Press Digit", "Navigate an IVR menu by pressing a digit"),
#     "webhook": ("Custom Function", "Webhook / HTTP API call"),
# }


# def validate_config(type_: str, config: dict[str, Any]) -> dict[str, Any]:
#     """Validate and normalize a config for its type. Raises pydantic ValidationError."""
#     return CONFIG_MODELS[type_].model_validate(config).model_dump()


# # --------------------------------------------------------------------------
# # Secret handling for webhook headers
# # --------------------------------------------------------------------------
# def _mask(value: str) -> str:
#     return MASK + value[-4:] if len(value) > 8 else MASK * 2


# def mask_config(type_: str, config: dict[str, Any]) -> dict[str, Any]:
#     """Copy of the config that is safe to send to the browser."""
#     if type_ != "webhook":
#         return config
#     out = dict(config)
#     out["headers"] = {k: _mask(v) for k, v in (config.get("headers") or {}).items()}
#     return out


# # --------------------------------------------------------------------------
# # Requests / responses
# # --------------------------------------------------------------------------
# def _clean_description(v: str | None) -> str | None:
#     return v.strip() if v is not None else v


# class FunctionCreateRequest(BaseSchema):
#     name: str = Field(pattern=NAME_PATTERN)
#     description: str = Field(default="", max_length=1000)
#     type: FunctionType
#     config: dict[str, Any] = Field(default_factory=dict)
#     enabled: bool = True
#     # Superadmin only: organization to create it in
#     client_id: uuid.UUID | None = None

#     _strip = field_validator("description")(classmethod(lambda cls, v: _clean_description(v)))


# class FunctionUpdateRequest(BaseSchema):
#     """Partial update. `type` cannot be changed (delete and re-create instead).
#     If `config` is sent it replaces the whole config."""

#     model_config = ConfigDict(extra="forbid", from_attributes=True)

#     name: str | None = Field(default=None, pattern=NAME_PATTERN)
#     description: str | None = Field(default=None, max_length=1000)
#     config: dict[str, Any] | None = None
#     enabled: bool | None = None

#     _strip = field_validator("description")(classmethod(lambda cls, v: _clean_description(v)))


# class FunctionResponse(BaseSchema):
#     id: uuid.UUID
#     client_id: uuid.UUID
#     name: str
#     description: str
#     type: FunctionType
#     config: dict[str, Any]
#     enabled: bool
#     created_at: datetime
#     updated_at: datetime


# class FunctionListResponse(BaseSchema):
#     total: int
#     items: list[FunctionResponse]


# class FunctionTypeInfo(BaseSchema):
#     type: FunctionType
#     label: str
#     description: str
#     config_schema: dict[str, Any]


import json
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.url_safety import check_public_http_url
from app.schemas.base import BaseSchema


# ============================================================
# FUNCTION TYPES
# ============================================================

FunctionType = Literal[
    "webhook",
    "transfer_call",
    "end_call",
    "press_digit",
]

# Tool names must be safe for LLM tool-calling APIs
NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"

MASK = "••••"


# ============================================================
# COMMON CONFIG
# ============================================================

class _Config(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )


# ============================================================
# END CALL
# ============================================================

class EndCallConfig(_Config):

    execution_message: str | None = Field(
        default=None,
        max_length=500,
    )

    # Keep compatibility with old API
    message: str | None = Field(
        default=None,
        max_length=500,
    )


# ============================================================
# TRANSFER CALL
# ============================================================

class TransferSchedule(_Config):

    timezone: str | None = None

    start_time: str | None = None

    end_time: str | None = None


class TransferCallConfig(_Config):

    on_hold_music: bool = False

    execution_message: str | None = Field(
        default=None,
        max_length=500,
    )

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

    # Compatibility with previous API
    announcement: str | None = Field(
        default=None,
        max_length=500,
    )

    @field_validator("phone_number", "client_transfer_number")
    @classmethod
    def _phone_number(
        cls,
        v: str | None,
    ) -> str | None:

        if v is None:
            return v

        cleaned = re.sub(
            r"[\s\-()]",
            "",
            v,
        )

        if not re.fullmatch(
            r"\+[1-9]\d{6,14}",
            cleaned,
        ):
            raise ValueError(
                "phone number must be in E.164 format, "
                "for example +919876543210"
            )

        return cleaned


# ============================================================
# IVR / PRESS DIGIT
# ============================================================

class PressDigitConfig(_Config):

    # Agent Builder UI field
    digit: str | None = Field(
        default=None,
        min_length=1,
        max_length=1,
    )

    pause_detection_delay_ms: int = Field(
        default=1000,
        ge=0,
        le=60000,
    )

    # Compatibility with existing backend API
    digits: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
    )

    @field_validator("digit")
    @classmethod
    def _digit(
        cls,
        v: str | None,
    ) -> str | None:

        if v is None:
            return v

        if not re.fullmatch(
            r"[0-9*#]",
            v,
        ):
            raise ValueError(
                "digit must be a number, * or #"
            )

        return v

    @field_validator("digits")
    @classmethod
    def _digits(
        cls,
        v: str | None,
    ) -> str | None:

        if v is None:
            return v

        if not re.fullmatch(
            r"[0-9*#]{1,20}",
            v,
        ):
            raise ValueError(
                "digits can contain only numbers, * or #"
            )

        return v


# ============================================================
# CUSTOM FUNCTION / WEBHOOK
# ============================================================

class WebhookConfig(_Config):

    # Agent Builder
    function_type: Literal[
        "custom",
        "client",
    ] = "custom"

    url: str | None = Field(
        default=None,
        max_length=2000,
    )

    method: Literal[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ] = "POST"

    headers: dict[str, str] = Field(
        default_factory=dict,
    )

    # JSON Schema describing parameters
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
        }
    )

    execution_message: str | None = Field(
        default=None,
        max_length=500,
    )

    # Agent Builder / UI may use these names
    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=30,
    )

    # Existing webhook API compatibility
    retries: int = Field(
        default=0,
        ge=0,
    )

    @field_validator("url")
    @classmethod
    def _url(
        cls,
        v: str | None,
    ) -> str | None:

        if v is None or v == "":
            return v

        return check_public_http_url(v)

    @field_validator("headers")
    @classmethod
    def _headers(
        cls,
        v: dict[str, str],
    ) -> dict[str, str]:

        if len(v) > 20:
            raise ValueError(
                "at most 20 headers"
            )

        for name, value in v.items():

            if not re.fullmatch(
                r"[A-Za-z0-9-]{1,64}",
                name,
            ):
                raise ValueError(
                    f"invalid header name '{name}'"
                )

            if (
                len(value) > 2000
                or "\r" in value
                or "\n" in value
            ):
                raise ValueError(
                    f"invalid value for header '{name}'"
                )

        return v

    @field_validator("parameters")
    @classmethod
    def _parameters(
        cls,
        v: dict[str, Any],
    ) -> dict[str, Any]:

        if v.get("type") != "object":

            raise ValueError(
                "parameters must be a JSON Schema "
                "with type 'object'"
            )

        if not isinstance(
            v.get("properties", {}),
            dict,
        ):

            raise ValueError(
                "parameters.properties must be an object"
            )

        if len(json.dumps(v)) > 20_000:

            raise ValueError(
                "parameters schema is too large"
            )

        return v


# ============================================================
# CONFIGURATION MAP
# ============================================================

CONFIG_MODELS: dict[
    str,
    type[_Config],
] = {

    "end_call": EndCallConfig,

    "transfer_call": TransferCallConfig,

    "press_digit": PressDigitConfig,

    "webhook": WebhookConfig,
}


# ============================================================
# FUNCTION INFORMATION
# ============================================================

TYPE_INFO = {

    "end_call": (
        "End Call",
        "Terminate the call at a specific point",
    ),

    "transfer_call": (
        "Transfer Call",
        "Transfer the call to a human agent",
    ),

    "press_digit": (
        "IVR / Press Digit",
        "Navigate an IVR menu by pressing a digit",
    ),

    "webhook": (
        "Custom Function",
        "Webhook / HTTP API call",
    ),
}


# ============================================================
# VALIDATE CONFIG
# ============================================================

def validate_config(
    type_: str,
    config: dict[str, Any],
) -> dict[str, Any]:

    if type_ not in CONFIG_MODELS:

        raise ValueError(
            f"Unsupported function type: {type_}"
        )

    model = CONFIG_MODELS[type_]

    validated = model.model_validate(
        config
    )

    data = validated.model_dump(
        exclude_none=True
    )

    # --------------------------------------------------------
    # Normalize IVR
    # --------------------------------------------------------

    if type_ == "press_digit":

        if data.get("digit"):

            data["digits"] = data.pop(
                "digit"
            )

    # --------------------------------------------------------
    # Normalize Transfer Phone
    # --------------------------------------------------------

    if type_ == "transfer_call":

        for field_name in (
            "phone_number",
            "client_transfer_number",
        ):

            value = data.get(
                field_name
            )

            if isinstance(
                value,
                str,
            ):

                data[field_name] = re.sub(
                    r"[\s\-()]",
                    "",
                    value,
                )

    return data


# ============================================================
# SECRET HANDLING
# ============================================================

def _mask(
    value: str,
) -> str:

    return (
        MASK + value[-4:]
        if len(value) > 8
        else MASK * 2
    )


def mask_config(
    type_: str,
    config: dict[str, Any],
) -> dict[str, Any]:

    if type_ != "webhook":

        return config

    out = dict(
        config
    )

    out["headers"] = {
        k: _mask(v)
        for k, v in (
            config.get("headers")
            or {}
        ).items()
    }

    return out


# ============================================================
# HELPERS
# ============================================================

def _clean_description(
    v: str | None,
) -> str | None:

    return (
        v.strip()
        if v is not None
        else v
    )


# ============================================================
# FUNCTION CREATE REQUEST
# ============================================================

class FunctionCreateRequest(BaseSchema):

    name: str = Field(
        pattern=NAME_PATTERN,
    )

    description: str = Field(
        default="",
        max_length=1000,
    )

    type: FunctionType

    config: dict[str, Any] = Field(
        default_factory=dict,
    )

    enabled: bool = True

    # Superadmin only
    client_id: uuid.UUID | None = None

    _strip = field_validator(
        "description"
    )(
        classmethod(
            lambda cls, v:
            _clean_description(v)
        )
    )


# ============================================================
# FUNCTION UPDATE REQUEST
# ============================================================

class FunctionUpdateRequest(BaseSchema):

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
    )

    name: str | None = Field(
        default=None,
        pattern=NAME_PATTERN,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    config: dict[str, Any] | None = None

    enabled: bool | None = None

    _strip = field_validator(
        "description"
    )(
        classmethod(
            lambda cls, v:
            _clean_description(v)
        )
    )


# ============================================================
# FUNCTION RESPONSE
# ============================================================

class FunctionResponse(BaseSchema):

    id: uuid.UUID

    client_id: uuid.UUID

    name: str

    description: str

    type: FunctionType

    config: dict[str, Any]

    enabled: bool

    created_at: datetime

    updated_at: datetime


# ============================================================
# FUNCTION LIST RESPONSE
# ============================================================

class FunctionListResponse(BaseSchema):

    total: int

    items: list[FunctionResponse]


# ============================================================
# FUNCTION TYPE INFORMATION
# ============================================================

class FunctionTypeInfo(BaseSchema):

    type: FunctionType

    label: str

    description: str

    config_schema: dict[str, Any]
