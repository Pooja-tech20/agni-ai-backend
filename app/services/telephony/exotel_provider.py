"""Exotel provider - real outbound calls and call control.

Outbound flow
-------------
1. We call Exotel's "connect call to an app/flow" API. Exotel dials the
   customer from our ExoPhone (`CallerId`).
2. When the customer answers, Exotel runs the Voice flow at EXOTEL_FLOW_URL.
   That flow must bridge the call into LiveKit SIP (see docs/Agni_AI_Voice_
   Architecture_Notes.docx). Configuring the flow / SIP trunk happens in the
   Exotel + LiveKit dashboards, not in this code.
3. Exotel posts call status changes to
   {EXOTEL_WEBHOOK_BASE_URL}/api/v1/telephony/exotel/status?token=...
   which finalizes the call (duration, billing, campaign progress).

NOTE: Parameter names follow Exotel's public "Calls/connect" REST API as
documented at developer.exotel.com. They have NOT been exercised against a
live Exotel account from this codebase - run one real test call first and
adjust _build_params() if your account/region differs.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.telephony.base import CallInitiationResult, TelephonyProvider

logger = logging.getLogger(__name__)


class ExotelTelephonyProvider(TelephonyProvider):
    name = "exotel"

    def __init__(self, http: httpx.Client | None = None) -> None:
        self.account_sid = settings.EXOTEL_ACCOUNT_SID
        self.api_key = settings.EXOTEL_API_KEY
        self.api_token = settings.EXOTEL_API_TOKEN
        self.subdomain = settings.EXOTEL_SUBDOMAIN
        self._http = http

    # ---------------------------------------------------------------- helpers
    def _assert_configured(self) -> None:
        missing = [
            name for name, value in {
                "EXOTEL_ACCOUNT_SID": self.account_sid,
                "EXOTEL_API_KEY": self.api_key,
                "EXOTEL_API_TOKEN": self.api_token,
                "EXOTEL_FLOW_URL": settings.EXOTEL_FLOW_URL,
                "EXOTEL_WEBHOOK_BASE_URL": settings.EXOTEL_WEBHOOK_BASE_URL,
            }.items() if not value
        ]
        if missing:
            raise RuntimeError("Exotel is not configured. Missing env vars: " + ", ".join(missing))

    def _base(self) -> str:
        return f"https://{self.subdomain}/v1/Accounts/{self.account_sid}"

    def _client(self) -> httpx.Client:
        return self._http or httpx.Client(timeout=20)

    def _status_callback(self) -> str:
        base = settings.EXOTEL_WEBHOOK_BASE_URL.rstrip("/")
        url = f"{base}/api/v1/telephony/exotel/status"
        if settings.INBOUND_WEBHOOK_SECRET:
            url += "?" + urlencode({"token": settings.INBOUND_WEBHOOK_SECRET})
        return url

    def _build_params(self, to_number: str, from_number: str, call_id: str, agent_id: str) -> dict[str, str]:
        return {
            "From": to_number,                      # the party Exotel dials first
            "CallerId": from_number,                # our ExoPhone shown to them
            "Url": settings.EXOTEL_FLOW_URL,        # flow to run on answer
            "StatusCallback": self._status_callback(),
            "StatusCallbackEvents[0]": "terminal",
            "CustomField": json.dumps({"call_id": call_id, "agent_id": agent_id}),
            "CallType": "trans",
        }

    # -------------------------------------------------------------- interface
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
        params = self._build_params(to_number, from_number, call_id, agent_id)
        client = self._client()
        try:
            resp = client.post(
                f"{self._base()}/Calls/connect.json",
                data=params,
                auth=(self.api_key, self.api_token),
            )
        finally:
            if self._http is None:
                client.close()

        if resp.status_code >= 400:
            logger.error("Exotel connect failed: %s %s", resp.status_code, resp.text[:300])
            return CallInitiationResult(
                provider=self.name, provider_call_id=None, status="failed",
                to_number=to_number, from_number=from_number,
                raw={"status_code": resp.status_code, "body": resp.text[:500]},
                note=f"Exotel rejected the request (HTTP {resp.status_code})",
            )
        body: dict[str, Any] = resp.json()
        call = body.get("Call") or {}
        return CallInitiationResult(
            provider=self.name,
            provider_call_id=call.get("Sid"),
            status="queued" if call.get("Sid") else "failed",
            to_number=to_number,
            from_number=from_number,
            raw=body,
        )

    def end_call(self, provider_call_id: str) -> bool:
        self._assert_configured()
        client = self._client()
        try:
            resp = client.post(
                f"{self._base()}/Calls/{provider_call_id}.json",
                data={"Status": "completed"},
                auth=(self.api_key, self.api_token),
            )
        finally:
            if self._http is None:
                client.close()
        return resp.status_code < 400

    def get_call_status(self, provider_call_id: str) -> dict[str, Any]:
        self._assert_configured()
        client = self._client()
        try:
            resp = client.get(
                f"{self._base()}/Calls/{provider_call_id}.json",
                auth=(self.api_key, self.api_token),
            )
        finally:
            if self._http is None:
                client.close()
        resp.raise_for_status()
        return (resp.json() or {}).get("Call", {})


# Exotel terminal status -> (our call.status, end_reason)
EXOTEL_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "completed": ("completed", "user_hangup"),
    "busy": ("failed", "busy"),
    "no-answer": ("failed", "no_answer"),
    "failed": ("failed", "provider_error"),
    "canceled": ("failed", "canceled"),
}
