import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

AgentStatus = Literal["active", "inactive"]


class AgentCreateRequest(BaseSchema):
    name: str = Field(min_length=1, max_length=255)
    status: AgentStatus = "active"
    # Superadmin only: which organization the agent belongs to.
    # Admins always create agents in their own organization.
    client_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class AgentUpdateRequest(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: AgentStatus | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class AgentResponse(BaseSchema):
    id: uuid.UUID
    name: str
    status: str
    client_id: uuid.UUID
    total_calls: int
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseSchema):
    total: int
    items: list[AgentResponse]