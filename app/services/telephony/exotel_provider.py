"""
Exotel provider — real calls.

NOT ACTIVE YET. Until Exotel account + credentials exist, this class
raises. All real work goes through `MockTelephonyProvider`.
"""
import logging
from typing import Any

from app.core.config import settings
from app.services.telephony.base import CallInitiationResult, TelephonyProvider

logger = logging.getLogger(__name__)


class ExotelTelephonyProvider(TelephonyProvider):
    name = "exotel"

    def __init__(self) -> None:
        self.account_sid = settings.EXOTEL_ACCOUNT_SID
        self.api_key = settings.EXOTEL_API_KEY
        self.api_token = settings.EXOTEL_API_TOKEN
        self.subdomain = settings.EXOTEL_SUBDOMAIN

    def _assert_configured(self) -> None:
        missing = [
            name for name, value in {
                "EXOTEL_ACCOUNT_SID": self.account_sid,
                "EXOTEL_API_KEY": self.api_key,
                "EXOTEL_API_TOKEN": self.api_token,
            }.items() if not value
        ]
        if missing:
            raise RuntimeError(
                "Exotel is not configured. Missing env vars: " + ", ".join(missing)
            )

    def initiate_call(
        self,
        *,
        to_number: str,
        from_number: str,
        agent_id: str,
        call_id: str,
        metadata: dict | None = None,
    ) -> CallInitiationResult:
        self._assert_configured()
        raise NotImplementedError(
            "Exotel outbound not implemented yet. Use TELEPHONY_PROVIDER=mock."
        )

    def end_call(self, provider_call_id: str) -> bool:
        self._assert_configured()
        raise NotImplementedError("Exotel end_call not implemented yet.")

    def get_call_status(self, provider_call_id: str) -> dict[str, Any]:
        self._assert_configured()
        raise NotImplementedError("Exotel get_call_status not implemented yet.")