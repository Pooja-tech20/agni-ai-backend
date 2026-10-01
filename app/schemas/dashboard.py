from datetime import date, datetime

from app.schemas.base import BaseSchema


class Greeting(BaseSchema):
    first_name: str
    calls_this_month: int
    success_rate_this_month: float


class Kpis(BaseSchema):
    total_minutes: float
    active_agents: int
    live_calls: int
    credits_used: int
    credits_balance: int
    success_rate: float
    conversion_rate: float


class UsagePoint(BaseSchema):
    bucket: datetime
    calls: int
    minutes: float


class UsageTrends(BaseSchema):
    range: str
    points: list[UsagePoint]


class WeeklyOutcome(BaseSchema):
    week_start: date
    success: int
    failed: int


class CallOutcomes(BaseSchema):
    total: int
    success: int
    failed: int
    inbound: int
    outbound: int
    success_rate: float
    weekly: list[WeeklyOutcome]


class DashboardOverviewResponse(BaseSchema):
    greeting: Greeting
    kpis: Kpis
    usage_trends: UsageTrends
    call_outcomes: CallOutcomes