"""Outbound campaign dialer.

One `dial_tick()` pass:
  1. promote `scheduled` campaigns whose time has come,
  2. for every `active` campaign inside its calling window, dial as many
     pending contacts as the campaign / organization concurrency limits and
     the organization's credits allow,
  3. fail calls that never reported back (reaper).

Campaign.settings keys (all optional):
  timezone               IANA name, default "UTC"
  call_window_start/end  "HH:MM" (overnight windows allowed)
  active_days            ["Mon","Tue",...]  empty = every day
  max_concurrent         calls at once for this campaign (default 1)
  max_attempts           per contact (default 3)
  retry_delay_minutes    wait before retrying no-answer/busy (default 30)
  max_call_minutes       reaper timeout (default 30)

Run with: python -m app.workers.run  (or RUN_BACKGROUND_WORKERS=True in dev).
Row locks use SKIP LOCKED so several dialer processes can run safely.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.call import Call
from app.models.campaign import Campaign
from app.models.campaign_contact import CampaignContact
from app.models.contact import Contact
from app.models.phone_number import PhoneNumber
from app.services.billing import BillingError, count_active_calls, ensure_can_call
from app.services.call_lifecycle import finalize_call
from app.services.telephony import get_telephony_provider

logger = logging.getLogger(__name__)

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    hh, mm = value.split(":")[:2]
    return time(int(hh), int(mm))


def in_call_window(cfg: dict, now_utc: datetime) -> bool:
    try:
        tz = ZoneInfo(cfg.get("timezone") or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = now_utc.astimezone(tz)

    days = cfg.get("active_days") or []
    if days and _DAYS[local.weekday()] not in days:
        return False

    start, end = _parse_hhmm(cfg.get("call_window_start")), _parse_hhmm(cfg.get("call_window_end"))
    if start is None or end is None:
        return True
    t = local.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # overnight window, e.g. 22:00-06:00


def _pause_campaign(db: Session, camp: Campaign, reason: str) -> None:
    camp.status = "paused"
    camp.settings = {**(camp.settings or {}), "paused_reason": reason}
    db.commit()
    logger.warning("Campaign %s paused: %s", camp.id, reason)


def dial_one(db: Session, camp: Campaign, cc: CampaignContact, contact: Contact, agent: Agent, pn: PhoneNumber) -> Call:
    call = Call(
        client_id=camp.client_id,
        agent_id=agent.id,
        campaign_id=camp.id,
        status="in_progress",
        direction="outbound",
        channel="phone",
        caller_name=contact.name,
        caller_number=contact.phone,
        model_name=agent.llm_model,
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    db.flush()

    cc.status = "calling"
    cc.attempts += 1
    cc.next_attempt_at = None
    cc.last_call_id = call.id
    camp.total_calls = (camp.total_calls or 0) + 1
    camp.running_calls = (camp.running_calls or 0) + 1
    db.commit()  # persist the call before asking the provider to dial

    provider = get_telephony_provider()
    try:
        result = provider.initiate_call(
            to_number=contact.phone,
            from_number=pn.number,
            agent_id=str(agent.id),
            call_id=str(call.id),
            metadata={"campaign_id": str(camp.id), "contact_id": str(contact.id)},
        )
    except Exception as exc:
        logger.exception("Provider error dialing contact %s", contact.id)
        finalize_call(db, call.id, "failed", "provider_error")
        return call

    call.provider_call_id = result.provider_call_id
    db.commit()
    if result.status == "failed":
        finalize_call(db, call.id, "failed", "provider_error")
    elif provider.name == "mock":
        # No real telephony: close immediately so dev campaigns can finish.
        finalize_call(db, call.id, "completed", "mock", provider_duration=0)
    return call


def dial_tick(db: Session, now: datetime | None = None) -> int:
    """Run one dialing pass. Returns the number of calls started."""
    now = now or datetime.now(timezone.utc)
    started = 0

    # 1) scheduled -> active
    for camp in db.execute(
        select(Campaign).where(Campaign.status == "scheduled", Campaign.scheduled_at <= now)
    ).scalars():
        camp.status = "active"
    db.commit()

    # 2) dial
    for camp in db.execute(select(Campaign).where(Campaign.status == "active")).scalars().all():
        cfg = camp.settings or {}
        if not in_call_window(cfg, now):
            continue

        try:
            client = ensure_can_call(db, camp.client_id)
        except BillingError as exc:
            _pause_campaign(db, camp, exc.message)
            continue

        agent = db.get(Agent, camp.agent_id)
        pn = db.get(PhoneNumber, camp.phone_number_id) if camp.phone_number_id else None
        if agent is None or agent.status != "active" or pn is None or not pn.is_active:
            _pause_campaign(db, camp, "Agent or caller ID missing/inactive")
            continue

        running = db.execute(
            select(func.count()).select_from(Call).where(
                Call.campaign_id == camp.id, Call.status == "in_progress"
            )
        ).scalar_one()
        slots = min(
            int(cfg.get("max_concurrent", 1)) - running,
            client.max_concurrent_calls - count_active_calls(db, client.id),
        )
        if slots <= 0:
            continue

        rows = db.execute(
            select(CampaignContact)
            .where(
                CampaignContact.campaign_id == camp.id,
                CampaignContact.status == "pending",
                (CampaignContact.next_attempt_at.is_(None)) | (CampaignContact.next_attempt_at <= now),
            )
            .order_by(CampaignContact.created_at)
            .limit(slots)
            .with_for_update(skip_locked=True)
        ).scalars().all()

        for cc in rows:
            contact = db.get(Contact, cc.contact_id)
            if contact is None:
                cc.status = "skipped"
                db.commit()
                continue
            dial_one(db, camp, cc, contact, agent, pn)
            started += 1

        if not rows and running == 0:
            # nothing pending, nothing running -> maybe finished
            from app.services.call_lifecycle import _complete_campaign_if_done
            _complete_campaign_if_done(db, camp)
            db.commit()

    # 3) reaper
    reap_stuck_calls(db, now)
    return started


def reap_stuck_calls(db: Session, now: datetime) -> int:
    """Fail phone calls that never got a terminal callback."""
    n = 0
    rows = db.execute(
        select(Call).where(Call.status == "in_progress", Call.channel == "phone")
    ).scalars().all()
    for call in rows:
        limit = 30
        if call.campaign_id:
            camp = db.get(Campaign, call.campaign_id)
            limit = int(((camp.settings if camp else {}) or {}).get("max_call_minutes", 30))
        started = call.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if now - started > timedelta(minutes=limit):
            finalize_call(db, call.id, "failed", "timeout")
            n += 1
    return n
