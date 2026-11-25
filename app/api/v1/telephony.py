"""Provider callbacks (no JWT; protected by a shared secret)."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.webhook_auth import verify_provider_secret
from app.db.session import get_db
from app.models.call import Call
from app.services.call_lifecycle import finalize_call
from app.services.post_call import run_post_call_pipeline
from app.services.telephony.exotel_provider import EXOTEL_STATUS_MAP

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telephony", tags=["Telephony"])


async def _payload(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    form = await request.form()
    return {k: v for k, v in form.items() if isinstance(v, str)}


@router.post("/exotel/status")
async def exotel_status(
    request: Request,
    background: BackgroundTasks,
    token: str | None = Query(None),
    x_webhook_secret: str | None = Header(None, alias="X-Webhook-Secret"),
    db: Session = Depends(get_db),
):
    """Terminal call status from Exotel -> close the call, bill it, run analysis."""
    verify_provider_secret(x_webhook_secret, token)
    data = await _payload(request)

    sid = data.get("CallSid") or data.get("Sid")
    raw_status = (data.get("Status") or data.get("CallStatus") or "").lower()
    if not sid:
        return {"ok": False, "reason": "missing CallSid"}
    if raw_status not in EXOTEL_STATUS_MAP:
        return {"ok": True, "ignored": f"non-terminal status '{raw_status}'"}

    call = db.execute(select(Call).where(Call.provider_call_id == sid)).scalars().first()
    if call is None:
        logger.warning("Exotel callback for unknown CallSid %s", sid)
        return {"ok": True, "ignored": "unknown call"}

    call_status, end_reason = EXOTEL_STATUS_MAP[raw_status]
    duration = data.get("ConversationDuration") or data.get("Duration")
    try:
        duration = int(duration) if duration not in (None, "") else None
    except ValueError:
        duration = None

    finished = finalize_call(
        db, call.id, call_status, end_reason,
        provider_duration=duration, recording_url=data.get("RecordingUrl") or None,
    )
    if finished is not None:
        background.add_task(run_post_call_pipeline, call.id)
    return {"ok": True, "call_id": str(call.id), "status": call_status}
