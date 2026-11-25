"""Credits: balance, ledger, usage."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.scope import resolve_client_id
from app.db.session import get_db
from app.models.billing import CreditTransaction, TxType
from app.models.call import Call
from app.models.client import Client
from app.models.user import User
from app.schemas.platform import (
    BalanceResponse,
    TransactionListResponse,
    TransactionResponse,
    UsagePoint,
)
from app.services.billing import rate_for

router = APIRouter(prefix="/billing", tags=["Billing"])


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/balance", response_model=BalanceResponse)
def get_balance(
    client_id: uuid.UUID | None = Query(None, description="Superadmin only"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    org = db.get(Client, cid)
    start = _month_start()
    spent = db.execute(
        select(func.coalesce(func.sum(-CreditTransaction.amount), 0)).where(
            CreditTransaction.client_id == cid,
            CreditTransaction.type == TxType.USAGE,
            CreditTransaction.created_at >= start,
        )
    ).scalar_one()
    secs = db.execute(
        select(func.coalesce(func.sum(Call.duration_seconds), 0)).where(
            Call.client_id == cid, Call.started_at >= start
        )
    ).scalar_one()
    return BalanceResponse(
        client_id=cid,
        credit_balance=org.credit_balance,
        credits_per_minute=rate_for(org),
        low_credit_threshold=Decimal(str((org.settings or {}).get("low_credit_threshold", 5))),
        credits_spent_this_month=Decimal(spent),
        minutes_this_month=round(float(secs) / 60, 2),
    )


@router.get("/transactions", response_model=TransactionListResponse)
def list_transactions(
    client_id: uuid.UUID | None = Query(None),
    type: str | None = Query(None, description="grant|purchase|usage|refund|adjustment"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    q = select(CreditTransaction).where(CreditTransaction.client_id == cid)
    if type:
        q = q.where(CreditTransaction.type == type)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(CreditTransaction.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return TransactionListResponse(total=total, items=[TransactionResponse.model_validate(r) for r in rows])


@router.get("/usage", response_model=list[UsagePoint])
def usage_by_day(
    client_id: uuid.UUID | None = Query(None),
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    calls = db.execute(
        select(Call.started_at, Call.duration_seconds).where(Call.client_id == cid, Call.started_at >= since)
    ).all()
    credits = db.execute(
        select(CreditTransaction.created_at, CreditTransaction.amount).where(
            CreditTransaction.client_id == cid,
            CreditTransaction.type == TxType.USAGE,
            CreditTransaction.created_at >= since,
        )
    ).all()

    buckets: dict[str, dict] = {}
    for i in range(days + 1):
        d = (since + timedelta(days=i)).date().isoformat()
        buckets[d] = {"calls": 0, "secs": 0, "credits": Decimal("0")}
    for started, secs in calls:
        key = started.date().isoformat()
        if key in buckets:
            buckets[key]["calls"] += 1
            buckets[key]["secs"] += secs or 0
    for at, amount in credits:
        key = at.date().isoformat()
        if key in buckets:
            buckets[key]["credits"] += -Decimal(amount)
    return [
        UsagePoint(date=d, calls=v["calls"], minutes=round(v["secs"] / 60, 2), credits=v["credits"])
        for d, v in sorted(buckets.items())
    ]
