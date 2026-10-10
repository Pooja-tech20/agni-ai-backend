"""Schemas for /inbound — routing rules + provider webhook payloads."""
import uuid
from datetime import date, datetime, time

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema


# ------------------------------------------------------------
# Inbound route (Campaign → "Inbound Calls" screen)
# ------------------------------------------------------------

class InboundRouteCreateRequest(BaseSchema):
    phone_number_id: uuid.UUID
    agent_id: uuid.UUID

    timezone: str = Field("UTC", max_length=64)
    max_concurrent_calls: int = Field(1, ge=1, le=5)
    budget_credits: int | None = Field(None, ge=0)

    start_date: date | None = None
    end_date: date | None = None

    call_window_start: time | None = None
    call_window_end: time | None = None

    active_days: list[str] = Field(default_factory=list)
    is_active: bool = True

    @field_validator("active_days")
    @classmethod
    def _check_days(cls, v: list[str]) -> list[str]:
        allowed = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        bad = [d for d in v if d not in allowed]
        if bad:
            raise ValueError(f"active_days must be one of {sorted(allowed)}; got {bad}")
        return v


class InboundRouteUpdateRequest(BaseSchema):
    phone_number_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    timezone: str | None = Field(None, max_length=64)
    max_concurrent_calls: int | None = Field(None, ge=1, le=5)
    budget_credits: int | None = Field(None, ge=0)
    start_date: date | None = None
    end_date: date | None = None
    call_window_start: time | None = None
    call_window_end: time | None = None
    active_days: list[str] | None = None
    is_active: bool | None = None


class InboundRouteResponse(BaseSchema):
    id: uuid.UUID
    client_id: uuid.UUID
    phone_number_id: uuid.UUID
    agent_id: uuid.UUID
    timezone: str
    max_concurrent_calls: int
    budget_credits: int | None
    start_date: date | None
    end_date: date | None
    call_window_start: time | None
    call_window_end: time | None
    active_days: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InboundRouteListResponse(BaseSchema):
    total: int
    items: list[InboundRouteResponse]


# ------------------------------------------------------------
# Webhook — what the provider (Exotel/Twilio/Plivo) POSTs to us
# ------------------------------------------------------------

class InboundWebhookRequest(BaseSchema):
    """Generic shape; the router normalizes provider field names onto this."""
    From: str | None = None
    To: str | None = None
    CallSid: str | None = None
    Direction: str | None = None
    CallStatus: str | None = None
    provider: str | None = None


class InboundWebhookResponse(BaseSchema):
    call_id: str | None
    status: str
    message: str
    agent_id: str | None = None
    received_at: datetime