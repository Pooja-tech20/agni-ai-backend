"""GoHighLevel (LeadConnector) API v2 client using a Private Integration token.

Follows GoHighLevel's public API v2 docs (services.leadconnectorhq.com). NOT yet
exercised against a live GHL sub-account from this repo - test connect,
calendars, free-slots and booking once before relying on it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.services.integrations.base import IntegrationError

BASE = "https://services.leadconnectorhq.com"
VERSION = "2021-04-15"


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class GhlClient:
    def __init__(self, token: str, location_id: str, http: httpx.Client | None = None):
        self.token = token
        self.location_id = location_id
        self._http = http

    def _request(self, method: str, path: str, **kw) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Version": VERSION, "Accept": "application/json"}
        client = self._http or httpx.Client(timeout=20)
        try:
            resp = client.request(method, BASE + path, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"GoHighLevel unreachable: {exc}") from exc
        finally:
            if self._http is None:
                client.close()
        if resp.status_code in (401, 403):
            raise IntegrationError("GoHighLevel rejected the token", 400)
        if resp.status_code >= 400:
            raise IntegrationError(f"GoHighLevel error {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def calendars(self) -> list[dict]:
        return self._request("GET", "/calendars/", params={"locationId": self.location_id}).get("calendars", [])

    def free_slots(self, calendar_id: str, start: datetime, end: datetime, tz: str) -> Any:
        return self._request(
            "GET", f"/calendars/{calendar_id}/free-slots",
            params={"startDate": _ms(start), "endDate": _ms(end), "timezone": tz},
        )

    def events(self, calendar_id: str, start: datetime, end: datetime) -> list[dict]:
        return self._request(
            "GET", "/calendars/events",
            params={"locationId": self.location_id, "calendarId": calendar_id,
                    "startTime": _ms(start), "endTime": _ms(end)},
        ).get("events", [])

    def upsert_contact(self, name: str | None, email: str | None, phone: str | None) -> str:
        body = {"locationId": self.location_id, "name": name, "email": email, "phone": phone}
        data = self._request("POST", "/contacts/upsert", json={k: v for k, v in body.items() if v})
        return (data.get("contact") or {}).get("id")

    def book(
        self, calendar_id: str, contact_id: str, start: datetime, end: datetime | None, title: str | None,
    ) -> dict:
        body = {
            "calendarId": calendar_id, "locationId": self.location_id, "contactId": contact_id,
            "startTime": start.isoformat(), "title": title or "Appointment",
            "appointmentStatus": "confirmed", "ignoreDateRange": False, "toNotify": True,
        }
        if end:
            body["endTime"] = end.isoformat()
        return self._request("POST", "/calendars/events/appointments", json=body)

    def cancel(self, event_id: str) -> dict:
        return self._request(
            "PUT", f"/calendars/events/appointments/{event_id}", json={"appointmentStatus": "cancelled"}
        )
