"""Pydantic schemas for Caller IDs (phone numbers)."""
import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema


def _normalize_number(value: str) -> str:
    """Keep digits and a leading '+'. Reject empty/garbage."""
    v = value.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not v:
        raise ValueError("number is required")
    if v.startswith("+"):
        digits = v[1:]
    else:
        digits = v
    if not digits.isdigit():
        raise ValueError("number must contain only digits and an optional leading +")
    if len(digits) < 6 or len(digits) > 20:
        raise ValueError("number length looks wrong")
    return ("+" + digits) if value.strip().startswith("+") else digits


# ------------------------------------------------------------
# Requests
# ------------------------------------------------------------

class PhoneNumberCreateRequest(BaseSchema):
    number: str = Field(..., description="E.164 preferred, e.g. +919876543210")
    label: str | None = Field(None, max_length=120)
    provider: str = Field("mock", max_length=50)
    provider_number_id: str | None = Field(None, max_length=120)

    @field_validator("number")
    @classmethod
    def _check_number(cls, v: str) -> str:
        return _normalize_number(v)


class PhoneNumberUpdateRequest(BaseSchema):
    label: str | None = Field(None, max_length=120)
    is_active: bool | None = None
    provider_number_id: str | None = Field(None, max_length=120)


# ------------------------------------------------------------
# Responses
# ------------------------------------------------------------

class PhoneNumberResponse(BaseSchema):
    id: uuid.UUID
    client_id: uuid.UUID
    number: str
    label: str | None
    provider: str
    provider_number_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PhoneNumberListResponse(BaseSchema):
    total: int
    items: list[PhoneNumberResponse]