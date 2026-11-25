"""One place that turns "a call ended" into all of its consequences.

finalize_call()        status/duration -> billing -> campaign progress
emit_call_completed()  after post-call analysis -> signed webhook event
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.call_message import CallMessage
from app.models.campaign import Campaign
from app.models.campaign_contact import CampaignContact
from app.services.billing import settle_call
from app.services.webhook_service import enqueue_event

logger = logging.getLogger(__name__)

# end reasons where trying the contact again later makes sense
RETRYABLE_REASONS = {"no_answer", "busy", "provider_error", "failed", "unreachable"}

# The call never connected (or we cannot tell): never charge for ring/stuck time.
UNBILLED_REASONS = {"no_answer", "busy", "canceled", "provider_error", "unreachable", "timeout"}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def finalize_call(
    db: Session,
    call_id: uuid.UUID,
    status: str,
    end_reason: str | None = None,
    *,
    provider_duration: int | None = None,
    recording_url: str | None = None,
    ended_at: datetime | None = None,
) -> Call | None:
    """Close a call exactly once. Safe to call repeatedly (later calls no-op)."""
    call = db.execute(
        select(Call).where(Call.id == call_id).with_for_update()
    ).scalar_one_or_none()
    if call is None or call.status != "in_progress":
        return None

    now = ended_at or datetime.now(timezone.utc)
    call.status = status
    call.ended_at = now
    call.end_reason = end_reason
    if recording_url:
        call.recording_url = recording_url

    if provider_duration is not None:
        call.duration_seconds = max(0, int(provider_duration))
    elif end_reason in UNBILLED_REASONS:
        call.duration_seconds = 0
    elif call.started_at is not None:
        call.duration_seconds = max(0, int((now - _aware(call.started_at)).total_seconds()))
    else:
        call.duration_seconds = 0

    db.flush()
    # Only calls that actually connected cost anything (duration > 0).
    settle_call(db, call)
    _advance_campaign(db, call)
    if status == "failed":
        enqueue_event(db, call.client_id, "call.failed", _call_summary(call))
    db.commit()
    return call


def _advance_campaign(db: Session, call: Call) -> None:
    if call.campaign_id is None:
        return
    campaign = db.get(Campaign, call.campaign_id)
    if campaign is None:
        return

    campaign.running_calls = max(0, (campaign.running_calls or 0) - 1)
    if call.status == "completed":
        campaign.successful_calls = (campaign.successful_calls or 0) + 1

    cc = db.execute(
        select(CampaignContact).where(CampaignContact.last_call_id == call.id)
    ).scalar_one_or_none()
    if cc is not None:
        cfg = campaign.settings or {}
        max_attempts = int(cfg.get("max_attempts", 3))
        retry_minutes = int(cfg.get("retry_delay_minutes", 30))
        if call.status == "completed":
            cc.status = "completed"
        elif (call.end_reason in RETRYABLE_REASONS or call.status == "failed") and cc.attempts < max_attempts:
            cc.status = "pending"
            cc.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=retry_minutes)
        else:
            cc.status = "no_answer" if call.end_reason in ("no_answer", "busy") else "failed"
        db.flush()

    _complete_campaign_if_done(db, campaign)


def _complete_campaign_if_done(db: Session, campaign: Campaign) -> None:
    if campaign.status != "active":
        return
    open_rows = db.execute(
        select(func.count()).select_from(CampaignContact).where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_(("pending", "calling")),
        )
    ).scalar_one()
    if open_rows == 0:
        campaign.status = "completed"
        enqueue_event(
            db, campaign.client_id, "campaign.completed",
            {
                "campaign_id": str(campaign.id),
                "name": campaign.name,
                "total_calls": campaign.total_calls,
                "successful_calls": campaign.successful_calls,
            },
        )


def _call_summary(call: Call) -> dict:
    return {
        "call_id": str(call.id),
        "agent_id": str(call.agent_id),
        "campaign_id": str(call.campaign_id) if call.campaign_id else None,
        "direction": call.direction,
        "channel": call.channel,
        "status": call.status,
        "end_reason": call.end_reason,
        "caller_number": call.caller_number,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "duration_seconds": call.duration_seconds,
    }


def build_call_payload(db: Session, call: Call) -> dict:
    """Full after-call payload (Ravan-style): transcript, recording, analysis."""
    messages = db.execute(
        select(CallMessage).where(CallMessage.call_id == call.id).order_by(CallMessage.created_at)
    ).scalars().all()
    payload = _call_summary(call)
    payload.update(
        {
            "recording_url": call.recording_url,
            "summary": call.summary,
            "sentiment": call.sentiment,
            "converted": call.converted,
            "post_call_extraction": call.post_call_extraction_result,
            "transcript": [
                {"role": m.role, "content": m.content, "interrupted": m.interrupted}
                for m in messages
            ],
        }
    )
    return payload


def emit_call_completed(db: Session, call_id: uuid.UUID) -> int:
    """Queue `call.completed` (after analysis) for every subscribed endpoint."""
    call = db.get(Call, call_id)
    if call is None:
        return 0
    n = enqueue_event(db, call.client_id, "call.completed", build_call_payload(db, call))
    db.commit()
    return n
