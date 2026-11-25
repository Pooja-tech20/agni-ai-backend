"""After a call ends: AI analysis, then the `call.completed` webhook."""
import logging
import uuid

from app.db.session import SessionLocal
from app.services.call_analysis import analyze_call
from app.services.call_lifecycle import emit_call_completed

logger = logging.getLogger(__name__)


async def run_post_call_pipeline(call_id: uuid.UUID) -> None:
    try:
        await analyze_call(call_id)
    except Exception:
        logger.exception("After-call analysis failed for call %s", call_id)
    # Always notify, even if analysis failed: the transcript/duration still matter.
    try:
        with SessionLocal() as db:
            emit_call_completed(db, call_id)
    except Exception:
        logger.exception("Could not queue call.completed webhook for call %s", call_id)
