"""Organization credit accounting.

Rules
-----
* The balance lives on `clients.credit_balance`; every change also writes one
  immutable `credit_transactions` row (the ledger), inside the same transaction.
* The client row is locked (SELECT ... FOR UPDATE) while the balance changes,
  so two calls ending at once cannot lose an update.
* A call is billed at most once (unique partial index + an explicit check).
* Calls are blocked *before* they start when the org is suspended or out of
  credits; a call already in progress may push the balance slightly negative.
"""
from __future__ import annotations

import logging
import math
import uuid
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.models.billing import CreditTransaction, TxType
from app.models.call import Call
from app.models.client import Client

logger = logging.getLogger(__name__)

_THREE_DP = Decimal("0.001")


class BillingError(AppError):
    """Raised when an action is refused for billing/account-state reasons.

    Subclasses AppError so the existing handler returns the standard
    {"error": {"code", "message", "details"}, "request_id"} body.
    """

    def __init__(self, message: str, status_code: int = 402, code: str = "BILLING_ERROR"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def rate_for(client: Client) -> Decimal:
    """Credits per minute for this organization."""
    if client.credits_per_minute is not None:
        return _dec(client.credits_per_minute)
    return _dec(settings.CREDITS_PER_MINUTE)


def cost_for_seconds(client: Client, seconds: int | None) -> Decimal:
    """Exact-second billing, rounded up to 0.001 credit."""
    if not seconds or seconds <= 0:
        return Decimal("0")
    minutes = Decimal(int(seconds)) / Decimal(60)
    return (minutes * rate_for(client)).quantize(_THREE_DP, rounding=ROUND_CEILING)


def get_client_locked(db: Session, client_id: uuid.UUID) -> Client:
    client = db.execute(
        select(Client).where(Client.id == client_id).with_for_update()
    ).scalar_one_or_none()
    if client is None:
        raise BillingError("Organization not found", 404, "ORG_NOT_FOUND")
    return client


def apply_transaction(
    db: Session,
    client_id: uuid.UUID,
    *,
    type: str,
    amount,
    description: str | None = None,
    call_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    reference: str | None = None,
) -> CreditTransaction:
    """Change the balance and write the ledger row. Caller commits."""
    amount = _dec(amount)
    if amount == 0:
        raise BillingError("Amount must not be zero", 400, "ZERO_AMOUNT")

    client = get_client_locked(db, client_id)
    new_balance = _dec(client.credit_balance) + amount
    # Only call usage may take the balance below zero.
    if new_balance < 0 and type != TxType.USAGE:
        raise BillingError(
            "Insufficient credits for this adjustment", 400, "NEGATIVE_BALANCE"
        )

    client.credit_balance = new_balance
    tx = CreditTransaction(
        client_id=client_id,
        type=type,
        amount=amount,
        balance_after=new_balance,
        description=description,
        call_id=call_id,
        created_by=created_by,
        reference=reference,
    )
    db.add(tx)
    db.flush()
    return tx


def ensure_can_call(db: Session, client_id: uuid.UUID) -> Client:
    """Raise BillingError unless this org may start another call right now."""
    client = db.get(Client, client_id)
    if client is None:
        raise BillingError("Organization not found", 404, "ORG_NOT_FOUND")
    if not client.is_active:
        raise BillingError("Organization is suspended", 403, "ORG_SUSPENDED")
    if _dec(client.credit_balance) <= _dec(settings.MIN_CREDITS_TO_CALL):
        raise BillingError(
            "Not enough credits to place a call. Please top up.", 402, "INSUFFICIENT_CREDITS"
        )
    return client


def count_active_calls(db: Session, client_id: uuid.UUID) -> int:
    from sqlalchemy import func

    return db.execute(
        select(func.count()).select_from(Call).where(
            Call.client_id == client_id, Call.status == "in_progress"
        )
    ).scalar_one()


def ensure_concurrency_room(db: Session, client: Client) -> None:
    if count_active_calls(db, client.id) >= client.max_concurrent_calls:
        raise BillingError(
            "Concurrent call limit reached for this organization", 429, "CONCURRENCY_LIMIT"
        )


def settle_call(db: Session, call: Call) -> CreditTransaction | None:
    """Charge the organization for a finished call. Idempotent. Caller commits."""
    if not call.duration_seconds or call.duration_seconds <= 0:
        return None

    client = get_client_locked(db, call.client_id)  # lock first, then check
    existing = db.execute(
        select(CreditTransaction).where(
            CreditTransaction.call_id == call.id, CreditTransaction.type == TxType.USAGE
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    cost = cost_for_seconds(client, call.duration_seconds)
    if cost == 0:
        return None
    before = _dec(client.credit_balance)
    tx = apply_transaction(
        db,
        client.id,
        type=TxType.USAGE,
        amount=-cost,
        call_id=call.id,
        description=f"Call {str(call.id)[:8]} - {call.duration_seconds}s",
    )
    threshold = _dec((client.settings or {}).get("low_credit_threshold", 5))
    if before > threshold >= _dec(tx.balance_after):
        from app.services.webhook_service import enqueue_event

        enqueue_event(
            db, client.id, "credits.low",
            {"balance": float(tx.balance_after), "threshold": float(threshold)},
        )
    return tx


def billable_minutes(seconds: int | None) -> int:
    """Whole started minutes (display only)."""
    return math.ceil((seconds or 0) / 60)
