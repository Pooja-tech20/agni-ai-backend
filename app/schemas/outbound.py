"""Schemas for /outbound — one-off or campaign-triggered outbound calls."""
import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import BaseSchema


class OutboundCallRequest(BaseSchema):
    """
    Two ways the frontend can trigger an outbound call:
      1. By campaign + contact (preferred)
      2. By campaign only, or explicit to_number (ad-hoc testing)
    """
    campaign_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    phone_number_id: uuid.UUID | None = None
    to_number: str | None = Field(None, description="E.164, required if no contact_id")
    metadata: dict = Field(default_factory=dict)


class OutboundCallResponse(BaseSchema):
    call_id: uuid.UUID
    provider: str
    provider_call_id: str | None
    status: str
    direction: str
    to_number: str | None
    from_number: str | None
    created_at: datetime
    note: str | None = None