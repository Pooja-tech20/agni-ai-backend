"""Pydantic schemas for Contacts (campaign audience)."""
import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema


def _normalize_phone(value: str) -> str:
    v = value.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not v:
        raise ValueError("phone is required")
    digits = v[1:] if v.startswith("+") else v
    if not digits.isdigit():
        raise ValueError("phone must contain only digits and an optional leading +")
    if len(digits) < 6 or len(digits) > 20:
        raise ValueError("phone length looks wrong")
    return ("+" + digits) if v.startswith("+") else digits


# ------------------------------------------------------------
# Requests
# ------------------------------------------------------------

class ContactCreateRequest(BaseSchema):
    phone: str
    name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    attributes: dict = Field(default_factory=dict)

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        return _normalize_phone(v)


class ContactBulkCreateRequest(BaseSchema):
    """Used by the CSV / paste-contacts step."""
    contacts: list[ContactCreateRequest]


class ContactUpdateRequest(BaseSchema):
    name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    attributes: dict | None = None


# ------------------------------------------------------------
# Responses
# ------------------------------------------------------------

class ContactResponse(BaseSchema):
    id: uuid.UUID
    client_id: uuid.UUID
    phone: str
    name: str | None
    email: str | None
    attributes: dict
    created_at: datetime
    updated_at: datetime


class ContactListResponse(BaseSchema):
    total: int
    items: list[ContactResponse]