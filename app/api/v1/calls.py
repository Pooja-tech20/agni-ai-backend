# """Call history: GET /calls (list) and GET /calls/{id} (details + transcript)."""
# import uuid
# from datetime import datetime

# from fastapi import APIRouter, Depends, HTTPException, Query, status
# from sqlalchemy import func
# from sqlalchemy.orm import Session

# from app.api.dependencies import get_current_user
# from app.db.session import get_db
# from app.models.call import Call
# from app.models.call_message import CallMessage
# from app.models.roles import UserRole
# from app.models.user import User
# from app.schemas.base import BaseSchema

# router = APIRouter(prefix="/calls", tags=["Calls"])


# class CallSummary(BaseSchema):
#     id: uuid.UUID
#     agent_id: uuid.UUID
#     status: str
#     direction: str
#     converted: bool
#     started_at: datetime | None
#     ended_at: datetime | None
#     duration_seconds: int | None


# class MessageOut(BaseSchema):
#     id: uuid.UUID
#     role: str
#     content: str
#     created_at: datetime


# class CallDetail(CallSummary):
#     messages: list[MessageOut]


# class CallListResponse(BaseSchema):
#     total: int
#     items: list[CallSummary]


# def _is_super(user: User) -> bool:
#     return user.role == UserRole.SUPERADMIN.value


# @router.get("", response_model=CallListResponse)
# def list_calls(
#     agent_id: uuid.UUID | None = None,
#     status_filter: str | None = Query(None, alias="status"),
#     limit: int = Query(20, ge=1, le=100),
#     offset: int = Query(0, ge=0),
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     q = db.query(Call)
#     if not _is_super(current_user):
#         q = q.filter(Call.client_id == current_user.client_id)
#     if agent_id:
#         q = q.filter(Call.agent_id == agent_id)
#     if status_filter:
#         q = q.filter(Call.status == status_filter)
#     total = q.with_entities(func.count(Call.id)).scalar() or 0
#     items = q.order_by(Call.started_at.desc().nullslast(), Call.id).offset(offset).limit(limit).all()
#     return CallListResponse(total=total, items=[CallSummary.model_validate(c) for c in items])


# @router.get("/{call_id}", response_model=CallDetail)
# def get_call(
#     call_id: uuid.UUID,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     call = db.get(Call, call_id)
#     if not call or (not _is_super(current_user) and call.client_id != current_user.client_id):
#         raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")
#     messages = (
#         db.query(CallMessage)
#         .filter(CallMessage.call_id == call.id)
#         .order_by(CallMessage.created_at, CallMessage.id)
#         .all()
#     )
#     return CallDetail(
#         **CallSummary.model_validate(call).model_dump(),
#         messages=[MessageOut.model_validate(m) for m in messages],
#     )

"""All Calls History API.

GET /calls               list + stat cards (total / completed / failed / in progress)
GET /calls/export        same filters, downloaded as CSV
GET /calls/{id}          one call with its full transcript

GET /calls/{id}/transcript   transcript download (txt or json)
POST /calls/{id}/analyze     (re)generate the summary + sentiment (admins)

Everything is limited to the caller's organization; a superadmin sees all.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Query as OrmQuery
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.agent import Agent
from app.models.call import Call
from app.models.call_message import CallMessage
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.base import BaseSchema
from app.services.call_analysis import analyze_call

router = APIRouter(prefix="/calls", tags=["Calls"])

EXPORT_MAX_ROWS = 5000

# Text for the status badge and its (i) tooltip, so the frontend needs no mapping.
STATUS_LABELS = {"completed": "Completed", "failed": "Failed", "in_progress": "In Progress"}
END_REASON_LABELS = {
    "user_hangup": "User Hangup",
    "agent_hangup": "Agent Hangup",
    "max_duration": "Max Duration Reached",
    "error": "Technical Error",
}
END_REASON_HELP = {
    "user_hangup": "The caller ended the call.",
    "agent_hangup": "The agent ended the call.",
    "max_duration": "The call reached the agent's maximum duration and was ended automatically.",
    "error": "The call stopped because of a technical error.",
}
admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)

StatusT = Literal["in_progress", "completed", "failed"]
ChannelT = Literal["web", "phone"]
DirectionT = Literal["inbound", "outbound"]
SentimentT = Literal["positive", "neutral", "negative"]
PeriodT = Literal["all", "today", "yesterday", "7d", "30d", "90d", "custom"]
SortT = Literal["time", "duration", "status", "caller", "agent", "model"]


# ---------------------------------------------------------------- schemas
class CallSummary(BaseSchema):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str | None = None
    model: str | None = None            # "Agni Premium" column
    status: str                         # in_progress | completed | failed
    status_label: str = ""              # "Completed"
    end_reason: str | None = None       # user_hangup | max_duration | error ...
    end_reason_label: str | None = None # "User Hangup"  (the grey badge)
    end_reason_help: str | None = None  # text for the (i) tooltip
    channel: str = "web"                # web | phone
    direction: str                      # inbound | outbound
    converted: bool
    caller_name: str | None = None
    caller_number: str | None = None
    caller_display: str = "Unknown"
    caller_initials: str = "?"
    sentiment: str | None = None        # positive | neutral | negative | null
    summary: str | None = None          # after-call summary (null until analysed)
    analyzed: bool = False
    recording_url: str | None = None
    has_recording: bool = False         # frontend: enable the play button
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None


class MessageOut(BaseSchema):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class CallDetail(CallSummary):
    messages: list[MessageOut]


class CallStats(BaseSchema):
    total: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0


class CallListResponse(BaseSchema):
    total: int                          # rows matching ALL filters ("1 calls total")
    limit: int
    offset: int
    has_more: bool
    items: list[CallSummary]
    stats: CallStats                    # cards; ignores the status filter on purpose
    credits_balance: int | None = None  # header "9.867 credits"
    client_id: uuid.UUID | None = None


# ---------------------------------------------------------------- helpers
def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def _initials(name: str | None, number: str | None) -> str:
    words = (name or "").split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    return digits[-2:] if digits else "?"


def _summary(call: Call, agent_name: str | None, agent_model: str | None) -> CallSummary:
    return CallSummary(
        id=call.id,
        agent_id=call.agent_id,
        agent_name=agent_name,
        model=call.model_name or agent_model,
        status=call.status,
        status_label=STATUS_LABELS.get(call.status, call.status.replace("_", " ").title()),
        end_reason=call.end_reason,
        end_reason_label=END_REASON_LABELS.get(call.end_reason) if call.end_reason else None,
        end_reason_help=END_REASON_HELP.get(call.end_reason) if call.end_reason else None,
        channel=call.channel or "web",
        direction=call.direction,
        converted=call.converted,
        caller_name=call.caller_name,
        caller_number=call.caller_number,
        caller_display=call.caller_name or call.caller_number or "Unknown",
        caller_initials=_initials(call.caller_name, call.caller_number),
        sentiment=call.sentiment,
        summary=call.summary,
        analyzed=call.analyzed_at is not None,
        recording_url=call.recording_url,
        has_recording=bool(call.recording_url),
        started_at=call.started_at,
        ended_at=call.ended_at,
        duration_seconds=call.duration_seconds,
    )


def _like(term: str) -> str:
    """Escape % _ \\ so the search box is a plain text search."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _period_range(
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
    tz_offset_minutes: int,
) -> tuple[datetime | None, datetime | None]:
    """UTC [start, end) for the 'All Time' dropdown. 'today' follows the user's timezone."""
    if period == "all":
        return None, None
    if period == "custom":
        if date_from is None and date_to is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "custom period needs date_from and/or date_to")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from must be before date_to")
        return date_from, date_to

    now = datetime.now(timezone.utc)
    offset = timedelta(minutes=tz_offset_minutes)
    local_midnight = (now + offset).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = local_midnight - offset
    if period == "today":
        return today_start, None
    if period == "yesterday":
        return today_start - timedelta(days=1), today_start
    days = {"7d": 7, "30d": 30, "90d": 90}[period]
    return now - timedelta(days=days), None


class CallFilters:
    """Every filter the screen has. Shared by the list and the export."""

    def __init__(
        self,
        agent_id: uuid.UUID | None = None,
        status_filter: StatusT | None = Query(None, alias="status"),
        channel: ChannelT | None = None,          # tab "Web"
        direction: DirectionT | None = None,      # tabs "Inbound" / "Outbound"
        sentiment: SentimentT | None = None,
        converted: bool | None = None,
        search: str | None = Query(None, max_length=100),
        period: PeriodT = "all",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        tz_offset_minutes: int = Query(0, ge=-840, le=840),
        min_duration: int | None = Query(None, ge=0),
        max_duration: int | None = Query(None, ge=0),
    ):
        self.agent_id = agent_id
        self.status = status_filter
        self.channel = channel
        self.direction = direction
        self.sentiment = sentiment
        self.converted = converted
        self.search = (search or "").strip()
        self.start, self.end = _period_range(period, date_from, date_to, tz_offset_minutes)
        self.min_duration = min_duration
        self.max_duration = max_duration
        if min_duration is not None and max_duration is not None and min_duration > max_duration:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "min_duration must be <= max_duration")


def _filtered(db: Session, user: User, f: CallFilters, *, with_status: bool = True) -> OrmQuery:
    q = db.query(Call).join(Agent, Agent.id == Call.agent_id)
    if not _is_super(user):
        q = q.filter(Call.client_id == user.client_id)
    if f.agent_id:
        q = q.filter(Call.agent_id == f.agent_id)
    if with_status and f.status:
        q = q.filter(Call.status == f.status)
    if f.channel:
        q = q.filter(Call.channel == f.channel)
    if f.direction:
        q = q.filter(Call.direction == f.direction)
    if f.sentiment:
        q = q.filter(Call.sentiment == f.sentiment)
    if f.converted is not None:
        q = q.filter(Call.converted == f.converted)
    if f.start:
        q = q.filter(Call.started_at >= f.start)
    if f.end:
        q = q.filter(Call.started_at < f.end)
    if f.min_duration is not None:
        q = q.filter(Call.duration_seconds >= f.min_duration)
    if f.max_duration is not None:
        q = q.filter(Call.duration_seconds <= f.max_duration)
    if f.search:
        pattern = _like(f.search)
        q = q.filter(
            or_(
                Call.caller_name.ilike(pattern, escape="\\"),
                Call.caller_number.ilike(pattern, escape="\\"),
                Agent.name.ilike(pattern, escape="\\"),
                cast(Call.id, String).ilike(pattern, escape="\\"),
            )
        )
    return q


def _sort_column(sort_by: str):
    return {
        "time": Call.started_at,
        "duration": Call.duration_seconds,
        "status": Call.status,
        "caller": func.lower(func.coalesce(Call.caller_name, Call.caller_number, "")),
        "agent": func.lower(Agent.name),
        "model": func.lower(func.coalesce(Call.model_name, Agent.llm_model, "")),
    }[sort_by]


def _ordered(q: OrmQuery, sort_by: str, order: str) -> OrmQuery:
    col = _sort_column(sort_by)
    col = col.asc() if order == "asc" else col.desc()
    return q.order_by(col.nullslast(), Call.id)


# ---------------------------------------------------------------- routes
@router.get("", response_model=CallListResponse)
def list_calls(
    filters: CallFilters = Depends(),
    sort_by: SortT = "time",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = _filtered(db, current_user, filters)
    total = q.with_entities(func.count(Call.id)).scalar() or 0

    rows = (
        _ordered(q.with_entities(Call, Agent.name, Agent.llm_model), sort_by, order)
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Stat cards follow every filter EXCEPT status, so they keep showing the split.
    counts = dict(
        _filtered(db, current_user, filters, with_status=False)
        .with_entities(Call.status, func.count(Call.id))
        .group_by(Call.status)
        .all()
    )
    stats = CallStats(
        total=sum(counts.values()),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        in_progress=counts.get("in_progress", 0),
    )

    return CallListResponse(
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(rows) < total,
        items=[_summary(call, agent_name, agent_model) for call, agent_name, agent_model in rows],
        stats=stats,
        credits_balance=getattr(current_user, "credits", None),
        client_id=current_user.client_id,
    )


def _csv_safe(value) -> str:
    """Stop spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export")
def export_calls(
    filters: CallFilters = Depends(),
    sort_by: SortT = "time",
    order: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CSV of everything the screen is currently filtered to (max 5000 rows)."""
    q = _filtered(db, current_user, filters)
    rows = (
        _ordered(q.with_entities(Call, Agent.name, Agent.llm_model), sort_by, order)
        .limit(EXPORT_MAX_ROWS)
        .all()
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Call ID", "Caller", "Caller Number", "Status", "End Reason", "Channel", "Direction",
        "Agent", "Model", "Duration (seconds)", "Sentiment", "Summary", "Started At (UTC)", "Ended At (UTC)",
    ])
    for call, agent_name, agent_model in rows:
        s = _summary(call, agent_name, agent_model)
        writer.writerow([
            str(s.id), _csv_safe(s.caller_name), _csv_safe(s.caller_number), s.status,
            s.end_reason or "", s.channel, s.direction, _csv_safe(s.agent_name), _csv_safe(s.model),
            s.duration_seconds if s.duration_seconds is not None else "", s.sentiment or "", _csv_safe(s.summary),
            s.started_at.isoformat() if s.started_at else "", s.ended_at.isoformat() if s.ended_at else "",
        ])

    filename = f"calls_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{call_id}", response_model=CallDetail)
def get_call(
    call_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(Call, Agent.name, Agent.llm_model)
        .join(Agent, Agent.id == Call.agent_id)
        .filter(Call.id == call_id)
        .first()
    )
    # Other organizations' calls look like they don't exist.
    if row is None or (not _is_super(current_user) and row[0].client_id != current_user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")
    call, agent_name, agent_model = row
    messages = (
        db.query(CallMessage)
        .filter(CallMessage.call_id == call.id)
        .order_by(CallMessage.created_at, CallMessage.id)
        .all()
    )
    return CallDetail(
        **_summary(call, agent_name, agent_model).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


def _owned_row(db: Session, user: User, call_id: uuid.UUID):
    row = (
        db.query(Call, Agent.name, Agent.llm_model)
        .join(Agent, Agent.id == Call.agent_id)
        .filter(Call.id == call_id)
        .first()
    )
    # Other organizations' calls look like they don't exist.
    if row is None or (not _is_super(user) and row[0].client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")
    return row


@router.get("/{call_id}/transcript")
def download_transcript(
    call_id: uuid.UUID,
    format: Literal["txt", "json"] = "txt",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The full conversation as a file."""
    call, agent_name, _ = _owned_row(db, current_user, call_id)
    messages = (
        db.query(CallMessage)
        .filter(CallMessage.call_id == call.id)
        .order_by(CallMessage.created_at, CallMessage.id)
        .all()
    )
    who = {"user": "Caller", "agent": "Agent", "assistant": "Agent"}
    name = f"transcript_{str(call.id)[:8]}.{format}"

    if format == "json":
        import json

        body = json.dumps(
            {
                "call_id": str(call.id),
                "agent": agent_name,
                "started_at": call.started_at.isoformat() if call.started_at else None,
                "summary": call.summary,
                "messages": [
                    {"role": who.get(m.role, m.role), "content": m.content, "at": m.created_at.isoformat()}
                    for m in messages
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        media = "application/json"
    else:
        lines = [f"Call {call.id}", f"Agent: {agent_name}", ""]
        lines += [f"[{m.created_at:%H:%M:%S}] {who.get(m.role, m.role)}: {m.content}" for m in messages]
        body = "\n".join(lines) + "\n"
        media = "text/plain"

    return Response(
        content=body,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/{call_id}/analyze", response_model=CallSummary)
async def analyze(
    call_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    """(Re)generate the summary and sentiment of a finished call."""
    call, agent_name, agent_model = _owned_row(db, current_user, call_id)
    if call.status == "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "The call is still in progress")
    has_caller_speech = (
        db.query(CallMessage.id).filter(CallMessage.call_id == call.id, CallMessage.role == "user").first()
    )
    if has_caller_speech is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This call has no transcript to analyse")

    if not await analyze_call(call.id, force=True):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Analysis is unavailable right now. Try again later.")

    db.refresh(call)
    return _summary(call, agent_name, agent_model)