"""Schemas for organizations, billing, API keys, webhooks, contacts extras,
campaign contacts, integrations, appointments, analytics."""
import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.base import BaseSchema


# ------------------------------------------------------------ organizations
class OrgCreateRequest(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    plan: str = Field("free", max_length=50)
    initial_credits: Decimal = Field(Decimal("0"), ge=0)
    max_concurrent_calls: int = Field(5, ge=1, le=1000)
    max_agents: int | None = Field(None, ge=1)
    credits_per_minute: Decimal | None = Field(None, gt=0)
    # First admin of the organization
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8, max_length=128)
    admin_first_name: str = Field(..., min_length=1, max_length=100)
    admin_last_name: str = Field("", max_length=100)
    admin_phone_country_code: str = Field("+91", max_length=8)
    admin_phone_number: str = Field("0000000000", max_length=20)


class OrgUpdateRequest(BaseSchema):
    name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    plan: str | None = Field(None, max_length=50)
    max_concurrent_calls: int | None = Field(None, ge=1, le=1000)
    max_agents: int | None = Field(None, ge=1)
    credits_per_minute: Decimal | None = Field(None, gt=0)
    settings: dict | None = None


class OrgSelfUpdateRequest(BaseSchema):
    """What an organization admin may change about their own org."""
    name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    low_credit_threshold: Decimal | None = Field(None, ge=0)


class SuspendRequest(BaseSchema):
    reason: str | None = Field(None, max_length=255)


class CreditAdjustType(str, Enum):
    GRANT = "grant"
    PURCHASE = "purchase"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class CreditAdjustRequest(BaseSchema):
    type: CreditAdjustType = CreditAdjustType.GRANT
    amount: Decimal = Field(..., description="Positive adds credits. Negative only for type=adjustment.")
    description: str | None = Field(None, max_length=500)
    reference: str | None = Field(None, max_length=120)


class OrgResponse(BaseSchema):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    status: str
    suspended_reason: str | None
    plan: str
    credit_balance: Decimal
    credits_per_minute: Decimal | None
    max_concurrent_calls: int
    max_agents: int | None
    settings: dict
    created_at: datetime


class OrgListItem(OrgResponse):
    users_count: int = 0
    agents_count: int = 0


class OrgListResponse(BaseSchema):
    total: int
    items: list[OrgListItem]


class OrgProfileResponse(OrgResponse):
    """Ravan-style organization profile: effective plan, limits, credits."""
    effective_credits_per_minute: Decimal
    agents_count: int
    active_calls: int


class PlatformStats(BaseSchema):
    organizations_total: int
    organizations_active: int
    organizations_suspended: int
    users_total: int
    agents_total: int
    calls_30d: int
    minutes_30d: float
    credits_spent_30d: Decimal
    active_calls_now: int


# ------------------------------------------------------------------ billing
class TransactionResponse(BaseSchema):
    id: uuid.UUID
    type: str
    amount: Decimal
    balance_after: Decimal
    description: str | None
    call_id: uuid.UUID | None
    created_by: uuid.UUID | None
    reference: str | None
    created_at: datetime


class TransactionListResponse(BaseSchema):
    total: int
    items: list[TransactionResponse]


class BalanceResponse(BaseSchema):
    client_id: uuid.UUID
    credit_balance: Decimal
    credits_per_minute: Decimal
    low_credit_threshold: Decimal
    credits_spent_this_month: Decimal
    minutes_this_month: float


class UsagePoint(BaseSchema):
    date: str
    calls: int
    minutes: float
    credits: Decimal


# ----------------------------------------------------------------- api keys
class ApiKeyCreateRequest(BaseSchema):
    name: str = Field(..., min_length=1, max_length=120)
    expires_in_days: int | None = Field(None, ge=1, le=3650)


class ApiKeyResponse(BaseSchema):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str = Field(..., description="Shown ONCE. Store it now.")


# ----------------------------------------------------------------- webhooks
class WebhookCreateRequest(BaseSchema):
    url: str = Field(..., max_length=1000)
    description: str | None = Field(None, max_length=255)
    events: list[str] = Field(default_factory=list, description="Empty = all events")


class WebhookUpdateRequest(BaseSchema):
    url: str | None = Field(None, max_length=1000)
    description: str | None = Field(None, max_length=255)
    events: list[str] | None = None
    is_active: bool | None = None


class WebhookResponse(BaseSchema):
    id: uuid.UUID
    url: str
    description: str | None
    events: list
    is_active: bool
    created_at: datetime


class WebhookCreatedResponse(WebhookResponse):
    secret: str = Field(..., description="Signing secret. Shown ONCE (and on rotate).")


class DeliveryResponse(BaseSchema):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    event: str
    status: str
    attempts: int
    next_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime


class DeliveryListResponse(BaseSchema):
    total: int
    items: list[DeliveryResponse]


class WebhookTestResponse(BaseSchema):
    ok: bool
    status_code: int | None
    error: str | None


# -------------------------------------------------------- campaign contacts
class CampaignContactResponse(BaseSchema):
    id: uuid.UUID
    contact_id: uuid.UUID
    phone: str
    name: str | None
    status: str
    attempts: int
    next_attempt_at: datetime | None
    last_call_id: uuid.UUID | None


class CampaignContactListResponse(BaseSchema):
    total: int
    items: list[CampaignContactResponse]


class CampaignAddContactsResult(BaseSchema):
    added: int
    already_in_campaign: int
    not_found: int


# --------------------------------------------------------- contact extras
class NoteCreateRequest(BaseSchema):
    body: str = Field(..., min_length=1, max_length=5000)


class NoteResponse(BaseSchema):
    id: uuid.UUID
    contact_id: uuid.UUID
    author_id: uuid.UUID | None
    body: str
    created_at: datetime


class BulkDeleteRequest(BaseSchema):
    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=1000)


class BulkDeleteResult(BaseSchema):
    deleted: int


class ContactStats(BaseSchema):
    total_calls: int
    completed_calls: int
    failed_calls: int
    total_seconds: int
    avg_seconds: float
    last_call_at: datetime | None
    sentiment: dict[str, int]


class ContactActivity(BaseSchema):
    type: Literal["call", "note"]
    at: datetime
    id: uuid.UUID
    summary: str | None


# ------------------------------------------------------------ integrations
class CalcomConnectRequest(BaseSchema):
    api_key: str = Field(..., min_length=8, max_length=300)
    label: str | None = Field(None, max_length=120)


class GhlConnectRequest(BaseSchema):
    api_key: str = Field(..., min_length=8, max_length=2000, description="GoHighLevel private integration token")
    location_id: str = Field(..., min_length=3, max_length=120)
    label: str | None = Field(None, max_length=120)


class IntegrationResponse(BaseSchema):
    id: uuid.UUID
    provider: str
    label: str | None
    status: str
    config: dict
    created_at: datetime


# ------------------------------------------------------------ appointments
class AppointmentResponse(BaseSchema):
    id: uuid.UUID
    provider: str
    provider_booking_id: str | None
    agent_id: uuid.UUID | None
    call_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    attendee_name: str | None
    attendee_email: str | None
    attendee_phone: str | None
    title: str | None
    start_time: datetime
    end_time: datetime | None
    status: str
    created_at: datetime


class AppointmentListResponse(BaseSchema):
    total: int
    items: list[AppointmentResponse]


class AgentAppointmentRequest(BaseSchema):
    """Called by the voice agent mid-call (server-to-server)."""
    org_id: uuid.UUID
    action: Literal["check_availability", "book", "cancel"]
    provider: Literal["calcom", "ghl"] = "calcom"
    agent_id: uuid.UUID | None = None
    call_id: uuid.UUID | None = None
    # availability / booking
    event_type_id: str | None = None        # Cal.com event type id | GHL calendar id
    start: datetime | None = None
    end: datetime | None = None
    attendee_name: str | None = None
    attendee_email: str | None = None
    attendee_phone: str | None = None
    timezone: str = "UTC"
    title: str | None = None
    notes: str | None = None
    booking_id: str | None = None           # for cancel
    reason: str | None = None


# ---------------------------------------------------------------- analytics
class AnalyticsOverview(BaseSchema):
    total_calls: int
    completed: int
    failed: int
    in_progress: int
    success_rate: float
    total_minutes: float
    avg_duration_seconds: float
    converted: int
    conversion_rate: float
    inbound: int
    outbound: int
    web: int
    credits_spent: Decimal


class TimePoint(BaseSchema):
    bucket: str
    calls: int
    minutes: float
    success: int
    failed: int


class AgentPerformance(BaseSchema):
    agent_id: uuid.UUID
    agent_name: str
    calls: int
    success_rate: float
    minutes: float


class CountryStat(BaseSchema):
    country: str
    calls: int
