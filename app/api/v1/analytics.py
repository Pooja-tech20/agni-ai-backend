"""Analytics: volume, outcomes, sentiment, channel/hour, countries, per-agent."""
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.scope import resolve_client_id
from app.db.session import get_db
from app.models.agent import Agent
from app.models.billing import CreditTransaction, TxType
from app.models.call import Call
from app.models.user import User
from app.schemas.platform import AgentPerformance, AnalyticsOverview, CountryStat, TimePoint

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Longest-prefix-first dial codes for the countries we expect. Extend as needed.
_DIAL_CODES = {
    "91": "India", "1": "United States / Canada", "44": "United Kingdom", "971": "UAE",
    "65": "Singapore", "61": "Australia", "49": "Germany", "33": "France", "966": "Saudi Arabia",
    "977": "Nepal", "880": "Bangladesh", "94": "Sri Lanka", "92": "Pakistan",
}


def country_for(number: str | None) -> str:
    if not number:
        return "Unknown"
    digits = number.strip().lstrip("+")
    if not number.strip().startswith("+") and len(digits) == 10:
        return "India"  # 10-digit local numbers: assumed domestic
    for code in sorted(_DIAL_CODES, key=len, reverse=True):
        if digits.startswith(code):
            return _DIAL_CODES[code]
    return "Other"


def _range(frm: datetime | None, to: datetime | None) -> tuple[datetime, datetime]:
    end = to or datetime.now(timezone.utc)
    return (frm or end - timedelta(days=30)), end


def _calls(db: Session, cid, frm, to, agent_id=None) -> list[Call]:
    q = select(Call).where(Call.client_id == cid, Call.started_at >= frm, Call.started_at <= to)
    if agent_id:
        q = q.where(Call.agent_id == agent_id)
    return list(db.execute(q).scalars())


@router.get("/overview", response_model=AnalyticsOverview)
def overview(
    client_id: uuid.UUID | None = Query(None), agent_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    frm, to = _range(date_from, date_to)
    calls = _calls(db, cid, frm, to, agent_id)
    completed = sum(c.status == "completed" for c in calls)
    failed = sum(c.status == "failed" for c in calls)
    converted = sum(bool(c.converted) for c in calls)
    secs = sum(c.duration_seconds or 0 for c in calls)
    finished = completed + failed
    spent = db.execute(
        select(CreditTransaction.amount).where(
            CreditTransaction.client_id == cid, CreditTransaction.type == TxType.USAGE,
            CreditTransaction.created_at >= frm, CreditTransaction.created_at <= to,
        )
    ).scalars().all()
    return AnalyticsOverview(
        total_calls=len(calls), completed=completed, failed=failed,
        in_progress=sum(c.status == "in_progress" for c in calls),
        success_rate=round(100 * completed / finished, 2) if finished else 0.0,
        total_minutes=round(secs / 60, 2),
        avg_duration_seconds=round(secs / len(calls), 1) if calls else 0.0,
        converted=converted,
        conversion_rate=round(100 * converted / len(calls), 2) if calls else 0.0,
        inbound=sum(c.direction == "inbound" for c in calls),
        outbound=sum(c.direction == "outbound" for c in calls),
        web=sum(c.channel == "web" for c in calls),
        credits_spent=-sum((Decimal(a) for a in spent), Decimal("0")),
    )


@router.get("/timeseries", response_model=list[TimePoint])
def timeseries(
    granularity: str = Query("day", pattern="^(hour|day|week)$"),
    client_id: uuid.UUID | None = Query(None), agent_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    frm, to = _range(date_from, date_to)
    buckets: dict[str, dict] = defaultdict(lambda: {"calls": 0, "secs": 0, "success": 0, "failed": 0})
    for c in _calls(db, cid, frm, to, agent_id):
        t = c.started_at
        if granularity == "hour":
            key = t.strftime("%Y-%m-%d %H:00")
        elif granularity == "week":
            key = (t - timedelta(days=t.weekday())).strftime("%Y-%m-%d")
        else:
            key = t.strftime("%Y-%m-%d")
        b = buckets[key]
        b["calls"] += 1
        b["secs"] += c.duration_seconds or 0
        b["success"] += c.status == "completed"
        b["failed"] += c.status == "failed"
    return [
        TimePoint(bucket=k, calls=v["calls"], minutes=round(v["secs"] / 60, 2), success=v["success"], failed=v["failed"])
        for k, v in sorted(buckets.items())
    ]


@router.get("/sentiment")
def sentiment(
    client_id: uuid.UUID | None = Query(None), agent_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    frm, to = _range(date_from, date_to)
    counts = Counter(c.sentiment for c in _calls(db, cid, frm, to, agent_id) if c.sentiment)
    return {"positive": counts.get("positive", 0), "neutral": counts.get("neutral", 0), "negative": counts.get("negative", 0)}


@router.get("/channels-by-hour")
def channels_by_hour(
    client_id: uuid.UUID | None = Query(None), day: datetime | None = Query(None),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Calls per hour for one day, split by inbound / outbound / web (the 'Today's Activity' chart)."""
    cid = resolve_client_id(user, client_id)
    d = (day or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [{"hour": h, "inbound": 0, "outbound": 0, "web": 0} for h in range(24)]
    for c in _calls(db, cid, d, d + timedelta(days=1)):
        key = "web" if c.channel == "web" else c.direction
        if key in ("inbound", "outbound", "web"):
            rows[c.started_at.hour][key] += 1
    return rows


@router.get("/top-countries", response_model=list[CountryStat])
def top_countries(
    client_id: uuid.UUID | None = Query(None), limit: int = Query(10, ge=1, le=50),
    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    frm, to = _range(date_from, date_to)
    counts = Counter(country_for(c.caller_number) for c in _calls(db, cid, frm, to) if c.channel == "phone")
    return [CountryStat(country=k, calls=v) for k, v in counts.most_common(limit)]


@router.get("/agents", response_model=list[AgentPerformance])
def agent_performance(
    client_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    frm, to = _range(date_from, date_to)
    names = {a.id: a.name for a in db.execute(select(Agent).where(Agent.client_id == cid)).scalars()}
    stats: dict[uuid.UUID, dict] = defaultdict(lambda: {"calls": 0, "ok": 0, "fin": 0, "secs": 0})
    for c in _calls(db, cid, frm, to):
        s = stats[c.agent_id]
        s["calls"] += 1
        s["secs"] += c.duration_seconds or 0
        if c.status in ("completed", "failed"):
            s["fin"] += 1
            s["ok"] += c.status == "completed"
    return sorted(
        (
            AgentPerformance(
                agent_id=aid, agent_name=names.get(aid, "(deleted)"), calls=s["calls"],
                success_rate=round(100 * s["ok"] / s["fin"], 2) if s["fin"] else 0.0,
                minutes=round(s["secs"] / 60, 2),
            )
            for aid, s in stats.items()
        ),
        key=lambda r: r.calls, reverse=True,
    )
