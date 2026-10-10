"""Return the telephony provider selected by settings.TELEPHONY_PROVIDER."""
from functools import lru_cache

from app.core.config import settings
from app.services.telephony.base import TelephonyProvider
from app.services.telephony.mock_provider import MockTelephonyProvider


@lru_cache
def get_telephony_provider() -> TelephonyProvider:
    provider = (settings.TELEPHONY_PROVIDER or "mock").lower()

    if provider == "mock":
        return MockTelephonyProvider()

    if provider == "exotel":
        from app.services.telephony.exotel_provider import ExotelTelephonyProvider
        return ExotelTelephonyProvider()

    raise ValueError(f"Unknown TELEPHONY_PROVIDER: {provider!r}")