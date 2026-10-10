"""
Mock telephony provider.

No real phone call is placed. Logs the request and returns a fake
provider_call_id so the rest of the pipeline can be exercised
without Exotel.
"""
import logging
import uuid
from typing import Any

from app.services.telephony.base import CallInitiationResult, TelephonyProvider

logger = logging.getLogger(__name__)


class MockTelephonyProvider(TelephonyProvider):
    name = "mock"

    def initiate_call(
        self,
        *,
        to_number: str,
        from_number: str,
        agent_id: str,
        call_id: str,
        metadata: dict | None = None,
    ) -> CallInitiationResult:
        provider_call_id = f"mock-{uuid.uuid4().hex[:16]}"
        logger.info(
            "[MOCK TELEPHONY] initiate_call to=%s from=%s agent=%s call_id=%s provider_call_id=%s",
            to_number, from_number, agent_id, call_id, provider_call_id,
        )
        return CallInitiationResult(
            provider=self.name,
            provider_call_id=provider_call_id,
            status="queued",
            to_number=to_number,
            from_number=from_number,
            raw={"metadata": metadata or {}},
            note=(
                "Mock provider — no real call placed. "
                "Set TELEPHONY_PROVIDER=exotel (once credentials exist) to dial for real."
            ),
        )

    def end_call(self, provider_call_id: str) -> bool:
        logger.info("[MOCK TELEPHONY] end_call provider_call_id=%s", provider_call_id)
        return True

    def get_call_status(self, provider_call_id: str) -> dict[str, Any]:
        return {
            "provider": self.name,
            "provider_call_id": provider_call_id,
            "status": "completed",
            "duration_seconds": 0,
        }