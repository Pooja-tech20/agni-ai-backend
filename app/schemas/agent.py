# import uuid
# from datetime import datetime
# from typing import Literal

# from pydantic import Field, field_validator

# from app.schemas.base import BaseSchema

# AgentStatus = Literal["active", "inactive"]


# class AgentCreateRequest(BaseSchema):
#     name: str = Field(min_length=1, max_length=255)
#     status: AgentStatus = "active"
#     # Superadmin only: which organization the agent belongs to.
#     # Admins always create agents in their own organization.
#     client_id: uuid.UUID | None = None

#     @field_validator("name")
#     @classmethod
#     def strip_name(cls, value: str) -> str:
#         value = value.strip()
#         if not value:
#             raise ValueError("must not be blank")
#         return value


# class AgentUpdateRequest(BaseSchema):
#     name: str | None = Field(default=None, min_length=1, max_length=255)
#     status: AgentStatus | None = None

#     @field_validator("name")
#     @classmethod
#     def strip_name(cls, value: str | None) -> str | None:
#         if value is None:
#             return value
#         value = value.strip()
#         if not value:
#             raise ValueError("must not be blank")
#         return value


# class AgentResponse(BaseSchema):
#     id: uuid.UUID
#     name: str
#     status: str
#     client_id: uuid.UUID
#     total_calls: int
#     created_at: datetime
#     updated_at: datetime


# class AgentListResponse(BaseSchema):
#     total: int
#     items: list[AgentResponse]

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

AgentStatus = Literal["active", "inactive"]
DEFAULT_AGENT_NAME = "Unnamed Agent"


def _strip_name(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class AgentConfig(BaseSchema):
    """Everything configurable in the agent builder."""

    system_prompt: str | None = Field(default=None, max_length=50_000)
    welcome_message: str | None = Field(default=None, max_length=2_000)
    llm_model: str | None = Field(default=None, max_length=100)
    voice: str | None = Field(default=None, max_length=100)
    memory_enabled: bool = False
    emotion: str | None = Field(default=None, max_length=50)
    accent: str | None = Field(default=None, max_length=50)
    timezone: str = Field(default="UTC", max_length=64)

    functions: list[dict[str, Any]] = Field(default_factory=list)
    calendars: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_base: list[dict[str, Any]] = Field(default_factory=list)
    crm_sync: dict[str, Any] = Field(default_factory=dict)
    speech_settings: dict[str, Any] = Field(default_factory=dict)
    call_settings: dict[str, Any] = Field(default_factory=dict)
    post_call_extraction: dict[str, Any] = Field(default_factory=dict)
    webhook_settings: dict[str, Any] = Field(default_factory=dict)
    prompt_variables: dict[str, str] = Field(default_factory=dict)
    agent_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCreateRequest(AgentConfig):
    # Optional: the builder creates a blank draft, so the server picks
    # "Unnamed Agent", "Unnamed Agent 2", ... when no name is given.
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: AgentStatus = "active"
    # Superadmin only: which organization the agent belongs to.
    client_id: uuid.UUID | None = None

    _strip = field_validator("name")(classmethod(lambda cls, v: _strip_name(v)))


class AgentUpdateRequest(BaseSchema):
    """Partial update used by auto-save: only fields that are sent are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: AgentStatus | None = None

    system_prompt: str | None = Field(default=None, max_length=50_000)
    welcome_message: str | None = Field(default=None, max_length=2_000)
    llm_model: str | None = Field(default=None, max_length=100)
    voice: str | None = Field(default=None, max_length=100)
    memory_enabled: bool | None = None
    emotion: str | None = Field(default=None, max_length=50)
    accent: str | None = Field(default=None, max_length=50)
    timezone: str | None = Field(default=None, max_length=64)

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

    _strip = field_validator("name")(classmethod(lambda cls, v: _strip_name(v)))


class AgentResponse(AgentConfig):
    id: uuid.UUID
    name: str
    status: AgentStatus
    client_id: uuid.UUID
    total_calls: int = 0
    created_at: datetime
    updated_at: datetime


class AgentSummary(BaseSchema):
    """Lightweight row for the agents list (no prompt or config blobs)."""

    id: uuid.UUID
    name: str
    status: AgentStatus
    client_id: uuid.UUID
    voice: str | None = None
    llm_model: str | None = None
    total_calls: int = 0
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseSchema):
    total: int
    items: list[AgentSummary]