import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema


KnowledgeBaseStatus = Literal["active", "inactive"]
SourceType = Literal["text", "url", "file"]


class KnowledgeBaseCreateRequest(BaseSchema):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("must not be blank")

        return value


class KnowledgeBaseUpdateRequest(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: KnowledgeBaseStatus | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return value

        value = value.strip()

        if not value:
            raise ValueError("must not be blank")

        return value


class KnowledgeBaseResponse(BaseSchema):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseListResponse(BaseSchema):
    total: int
    items: list[KnowledgeBaseResponse]


class KnowledgeSourceCreateRequest(BaseSchema):
    title: str | None = Field(default=None, max_length=255)
    source_type: SourceType

    content: str | None = None
    url: str | None = None

    file_name: str | None = Field(default=None, max_length=255)
    file_size: int | None = Field(default=None, ge=0)


class KnowledgeSourceResponse(BaseSchema):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID

    title: str | None
    source_type: str

    content: str | None
    url: str | None

    file_name: str | None
    file_size: int | None

    status: str
    created_at: datetime
    updated_at: datetime


class KnowledgeSourceListResponse(BaseSchema):
    total: int
    items: list[KnowledgeSourceResponse]