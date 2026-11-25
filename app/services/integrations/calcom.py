"""Cal.com API v2 client.

Endpoints/versions follow Cal.com's public API v2 reference. NOT yet exercised
against a live Cal.com account from this repo - run the connect + availability
+ book flow once with a test account and adjust field names if Cal.com's API
has moved on (each endpoint pins its own `cal-api-version` header).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.services.integrations.base import IntegrationError

BASE = "https://api.cal.com/v2"


class CalcomClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self.api_key = api_key
        self._http = http

    def _request(self, method: str, path: str, version: str, **kw) -> Any:
        headers = {"Authorization": f"Bearer {self.api_key}", "cal-api-version": version}
        client = self._http or httpx.Client(timeout=20)
        try:
            resp = client.request(method, BASE + path, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Cal.com unreachable: {exc}") from exc
        finally:
            if self._http is None:
                client.close()
        if resp.status_code in (401, 403):
            raise IntegrationError("Cal.com rejected the API key", 400)
        if resp.status_code >= 400:
            raise IntegrationError(f"Cal.com error {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        return body.get("data", body)

    def me(self) -> dict:
        return self._request("GET", "/me", "2024-08-13")

    def event_types(self) -> list[dict]:
        data = self._request("GET", "/event-types", "2024-06-14")
        return data if isinstance(data, list) else data.get("eventTypeGroups", data)

    def bookings(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else None
        data = self._request("GET", "/bookings", "2024-08-13", params=params)
        return data if isinstance(data, list) else []

    def slots(self, event_type_id: str, start: datetime, end: datetime, tz: str) -> Any:
        return self._request(
            "GET", "/slots", "2024-09-04",
            params={
                "eventTypeId": event_type_id, "start": start.isoformat(),
                "end": end.isoformat(), "timeZone": tz,
            },
        )

    def book(
        self, event_type_id: str, start: datetime, name: str, email: str,
        tz: str, phone: str | None = None, notes: str | None = None,
    ) -> dict:
        attendee: dict[str, Any] = {"name": name, "email": email, "timeZone": tz}
        if phone:
            attendee["phoneNumber"] = phone
        body: dict[str, Any] = {
            "start": start.astimezone().isoformat() if start.tzinfo else start.isoformat() + "Z",
            "eventTypeId": int(event_type_id),
            "attendee": attendee,
        }
        if notes:
            body["bookingFieldsResponses"] = {"notes": notes}
        return self._request("POST", "/bookings", "2024-08-13", json=body)

    def cancel(self, booking_uid: str, reason: str | None = None) -> dict:
        return self._request(
            "POST", f"/bookings/{booking_uid}/cancel", "2024-08-13",
            json={"cancellationReason": reason or "Cancelled by assistant"},
        )
