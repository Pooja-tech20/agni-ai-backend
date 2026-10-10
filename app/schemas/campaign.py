"""Pydantic schemas for Campaigns."""
import uuid
from datetime import datetime
from enum import Enum

from pydantic import Field

from app.schemas.base import BaseSchema


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


# ------------------------------------------------------------
# Requests
# ------------------------------------------------------------

class CampaignCreateRequest(BaseSchema):
    """
    Matches Step 1 of the 'New Campaign' wizard:
      Campaign Name, AI Agent, Caller ID.
    Contacts (Step 2) are added via /campaigns/{id}/contacts.
    """
    name: str = Field(..., min_length=1, max_length=255)
    agent_id: uuid.UUID
    phone_number_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    settings: dict = Field(default_factory=dict)


class CampaignUpdateRequest(BaseSchema):
    name: str | None = Field(None, min_length=1, max_length=255)
    agent_id: uuid.UUID | None = None
    phone_number_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    settings: dict | None = None


class CampaignAddContactsRequest(BaseSchema):
    contact_ids: list[uuid.UUID] = Field(default_factory=list)


# ------------------------------------------------------------
# Responses
# ------------------------------------------------------------

class CampaignSummary(BaseSchema):
    id: uuid.UUID
    name: str
    status: CampaignStatus
    agent_id: uuid.UUID
    phone_number_id: uuid.UUID | None
    scheduled_at: datetime | None
    total_calls: int
    running_calls: int
    successful_calls: int
    created_at: datetime
    updated_at: datetime


class CampaignResponse(CampaignSummary):
    client_id: uuid.UUID
    settings: dict


class CampaignListResponse(BaseSchema):
    total: int
    items: list[CampaignSummary]


class CampaignStatsResponse(BaseSchema):
    """Numbers behind the five dashboard cards."""
    total_calls: int
    running_calls: int
    avg_success: int   # percentage 0-100
    active: int
    scheduled: int