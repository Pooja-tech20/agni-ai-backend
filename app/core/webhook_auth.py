"""Shared-secret check for provider callbacks (Exotel can't send a Bearer token)."""
import hmac

from fastapi import HTTPException, status

from app.core.config import settings


def verify_provider_secret(header_value: str | None, query_token: str | None) -> None:
    secret = settings.INBOUND_WEBHOOK_SECRET
    if not secret:
        if settings.is_production_like:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "INBOUND_WEBHOOK_SECRET is not configured")
        return  # development convenience only
    supplied = header_value or query_token or ""
    if not hmac.compare_digest(supplied, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook secret")
