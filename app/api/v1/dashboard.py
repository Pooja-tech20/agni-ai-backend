# import math
# from datetime import datetime, timedelta, timezone
# from typing import Literal

# from fastapi import APIRouter, Depends, Query
# from sqlalchemy import func
# from sqlalchemy.orm import Session

# from app.api.dependencies import get_current_user
# from app.db.session import get_db
# from app.models.agent import Agent
# from app.models.call import Call
# from app.models.user import User
# from app.schemas.dashboard import (
#     CallOutcomes,
#     DashboardOverviewResponse,
#     Greeting,
#     Kpis,
#     UsagePoint,
#     UsageTrends,
#     WeeklyOutcome,
# )

# router = APIRouter(
#     prefix="/dashboard",
#     tags=["Dashboard"],
# )

# SUCCESS_STATUSES = ("completed",)
# FAILED_STATUSES = ("failed", "errored")


# def _utc(dt: datetime) -> datetime:
#     return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# def _pct(part: int, whole: int) -> float:
#     return round(part * 100 / whole, 2) if whole else 0.0


# @router.get("/overview", response_model=DashboardOverviewResponse)
# def dashboard_overview(
#     period: Literal["day", "week", "month"] = Query(
#         "month", alias="range", description="Usage Trends range: day=24h, week=7d, month=30d"
#     ),
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     now = datetime.now(timezone.utc)
#     client_id = current_user.client_id

#     def calls():
#         # Users without an organization see an empty dashboard
#         return db.query(Call).filter(Call.client_id == client_id)

#     # ---------------- Month-to-date numbers (greeting + KPI cards)
#     month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
#     month = calls().filter(Call.created_at >= month_start)

#     status_rows = (
#         month.with_entities(Call.status, func.count(Call.id))
#         .group_by(Call.status)
#         .all()
#     )
#     by_status = {s: c for s, c in status_rows}
#     month_total = sum(by_status.values())
#     month_success = sum(by_status.get(s, 0) for s in SUCCESS_STATUSES)
#     month_failed = sum(by_status.get(s, 0) for s in FAILED_STATUSES)
#     month_success_rate = _pct(month_success, month_success + month_failed)

#     total_seconds = (
#         month.with_entities(func.coalesce(func.sum(Call.duration_seconds), 0)).scalar()
#     )
#     total_minutes = round(float(total_seconds) / 60, 2)
#     converted = month.filter(Call.converted.is_(True)).count()

#     active_agents = (
#         db.query(Agent)
#         .filter(Agent.client_id == client_id, Agent.status == "active")
#         .count()
#     )
#     live_calls = by_status.get("in_progress", 0)

#     # ---------------- Usage trends
#     if period == "day":
#         step, count = timedelta(hours=1), 24
#         first = now.replace(minute=0, second=0, microsecond=0) - step * (count - 1)
#     else:
#         step, count = timedelta(days=1), 7 if period == "week" else 30
#         first = now.replace(hour=0, minute=0, second=0, microsecond=0) - step * (count - 1)

#     trend_rows = (
#         calls()
#         .filter(Call.created_at >= first)
#         .with_entities(Call.created_at, Call.duration_seconds)
#         .all()
#     )
#     buckets = [
#         {"bucket": first + step * i, "calls": 0, "seconds": 0} for i in range(count)
#     ]
#     for created_at, duration in trend_rows:
#         idx = int((_utc(created_at) - first) / step)
#         if 0 <= idx < count:
#             buckets[idx]["calls"] += 1
#             buckets[idx]["seconds"] += duration or 0
#     points = [
#         UsagePoint(bucket=b["bucket"], calls=b["calls"], minutes=round(b["seconds"] / 60, 2))
#         for b in buckets
#     ]

#     # ---------------- Call outcomes (last 4 weeks, weeks start Monday)
#     today = now.replace(hour=0, minute=0, second=0, microsecond=0)
#     this_monday = today - timedelta(days=today.weekday())
#     weeks_start = this_monday - timedelta(weeks=3)

#     outcome_rows = (
#         calls()
#         .filter(Call.created_at >= weeks_start)
#         .with_entities(Call.created_at, Call.status, Call.direction)
#         .all()
#     )
#     weekly = [
#         {"week_start": (weeks_start + timedelta(weeks=i)).date(), "success": 0, "failed": 0}
#         for i in range(4)
#     ]
#     inbound = outbound = 0
#     for created_at, status, direction in outcome_rows:
#         idx = (_utc(created_at) - weeks_start).days // 7
#         if status in SUCCESS_STATUSES:
#             weekly[idx]["success"] += 1
#         elif status in FAILED_STATUSES:
#             weekly[idx]["failed"] += 1
#         if direction == "outbound":
#             outbound += 1
#         else:
#             inbound += 1
#     o_success = sum(w["success"] for w in weekly)
#     o_failed = sum(w["failed"] for w in weekly)

#     return DashboardOverviewResponse(
#         greeting=Greeting(
#             first_name=current_user.first_name,
#             calls_this_month=month_total,
#             success_rate_this_month=month_success_rate,
#         ),
#         kpis=Kpis(
#             total_minutes=total_minutes,
#             active_agents=active_agents,
#             live_calls=live_calls,
#             # Assumption: 1 credit per started minute. Change to your pricing rule.
#             credits_used=math.ceil(total_minutes),
#             credits_balance=current_user.credits,
#             success_rate=month_success_rate,
#             conversion_rate=_pct(converted, month_total),
#         ),
#         usage_trends=UsageTrends(range=period, points=points),
#         call_outcomes=CallOutcomes(
#             total=len(outcome_rows),
#             success=o_success,
#             failed=o_failed,
#             inbound=inbound,
#             outbound=outbound,
#             success_rate=_pct(o_success, o_success + o_failed),
#             weekly=[WeeklyOutcome(**w) for w in weekly],
#         ),
#     )

import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.call import Call
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.dashboard import (
    CallOutcomes,
    DashboardOverviewResponse,
    Greeting,
    Kpis,
    UsagePoint,
    UsageTrends,
    WeeklyOutcome,
)

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)

SUCCESS_STATUSES = ("completed",)
FAILED_STATUSES = ("failed", "errored")


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pct(part: int, whole: int) -> float:
    return round(part * 100 / whole, 2) if whole else 0.0


@router.get("/overview", response_model=DashboardOverviewResponse)
def dashboard_overview(
    period: Literal["day", "week", "month"] = Query(
        "month", alias="range", description="Usage Trends range: day=24h, week=7d, month=30d"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    client_id = current_user.client_id

    # A superadmin has no organization of their own and sees every organization.
    is_super = current_user.role == UserRole.SUPERADMIN.value

    def calls():
        # Other users without an organization see an empty dashboard
        q = db.query(Call)
        return q if is_super else q.filter(Call.client_id == client_id)

    def agents():
        q = db.query(Agent)
        return q if is_super else q.filter(Agent.client_id == client_id)

    # ---------------- Month-to-date numbers (greeting + KPI cards)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = calls().filter(Call.created_at >= month_start)

    status_rows = (
        month.with_entities(Call.status, func.count(Call.id))
        .group_by(Call.status)
        .all()
    )
    by_status = {s: c for s, c in status_rows}
    month_total = sum(by_status.values())
    month_success = sum(by_status.get(s, 0) for s in SUCCESS_STATUSES)
    month_failed = sum(by_status.get(s, 0) for s in FAILED_STATUSES)
    month_success_rate = _pct(month_success, month_success + month_failed)

    total_seconds = (
        month.with_entities(func.coalesce(func.sum(Call.duration_seconds), 0)).scalar()
    )
    total_minutes = round(float(total_seconds) / 60, 2)
    converted = month.filter(Call.converted.is_(True)).count()

    agent_counts = dict(
        agents().with_entities(Agent.status, func.count(Agent.id)).group_by(Agent.status).all()
    )
    active_agents = agent_counts.get("active", 0)
    inactive_agents = agent_counts.get("inactive", 0)
    total_agents = sum(agent_counts.values())
    # Live = running right now, whatever month it started in.
    live_calls = calls().filter(Call.status == "in_progress").count()

    # ---------------- Usage trends
    if period == "day":
        step, count = timedelta(hours=1), 24
        first = now.replace(minute=0, second=0, microsecond=0) - step * (count - 1)
    else:
        step, count = timedelta(days=1), 7 if period == "week" else 30
        first = now.replace(hour=0, minute=0, second=0, microsecond=0) - step * (count - 1)

    trend_rows = (
        calls()
        .filter(Call.created_at >= first)
        .with_entities(Call.created_at, Call.duration_seconds)
        .all()
    )
    buckets = [
        {"bucket": first + step * i, "calls": 0, "seconds": 0} for i in range(count)
    ]
    for created_at, duration in trend_rows:
        idx = int((_utc(created_at) - first) / step)
        if 0 <= idx < count:
            buckets[idx]["calls"] += 1
            buckets[idx]["seconds"] += duration or 0
    points = [
        UsagePoint(bucket=b["bucket"], calls=b["calls"], minutes=round(b["seconds"] / 60, 2))
        for b in buckets
    ]

    # ---------------- Call outcomes (last 4 weeks, weeks start Monday)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    this_monday = today - timedelta(days=today.weekday())
    weeks_start = this_monday - timedelta(weeks=3)

    outcome_rows = (
        calls()
        .filter(Call.created_at >= weeks_start)
        .with_entities(Call.created_at, Call.status, Call.direction)
        .all()
    )
    weekly = [
        {"week_start": (weeks_start + timedelta(weeks=i)).date(), "success": 0, "failed": 0}
        for i in range(4)
    ]
    inbound = outbound = 0
    for created_at, status, direction in outcome_rows:
        idx = (_utc(created_at) - weeks_start).days // 7
        if status in SUCCESS_STATUSES:
            weekly[idx]["success"] += 1
        elif status in FAILED_STATUSES:
            weekly[idx]["failed"] += 1
        if direction == "outbound":
            outbound += 1
        else:
            inbound += 1
    o_success = sum(w["success"] for w in weekly)
    o_failed = sum(w["failed"] for w in weekly)

    return DashboardOverviewResponse(
        greeting=Greeting(
            first_name=current_user.first_name,
            calls_this_month=month_total,
            success_rate_this_month=month_success_rate,
        ),
        kpis=Kpis(
            total_minutes=total_minutes,
            active_agents=active_agents,
            total_agents=total_agents,
            inactive_agents=inactive_agents,
            live_calls=live_calls,
            # Assumption: 1 credit per started minute. Change to your pricing rule.
            credits_used=math.ceil(total_minutes),
            credits_balance=current_user.credits,
            success_rate=month_success_rate,
            conversion_rate=_pct(converted, month_total),
        ),
        usage_trends=UsageTrends(range=period, points=points),
        call_outcomes=CallOutcomes(
            total=len(outcome_rows),
            success=o_success,
            failed=o_failed,
            inbound=inbound,
            outbound=outbound,
            success_rate=_pct(o_success, o_success + o_failed),
            weekly=[WeeklyOutcome(**w) for w in weekly],
        ),
    )