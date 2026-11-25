"""Outgoing webhooks: signed, retried, auditable.

enqueue_event()  - called inside business transactions; writes pending rows.
deliver_due()    - called by the background worker; sends and records results.

Signature (verify on the receiver):
    X-Agni-Signature: t=<unix>,v1=<hex hmac_sha256(secret, f"{t}.{raw_body}")>
Reject requests whose timestamp is older than ~5 minutes to stop replays.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.url_safety import check_public_http_url
from app.models.webhook import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

# Delay before attempt N+1 (index = attempts already made - 1)
BACKOFF_SECONDS = [30, 120, 600, 3600, 21600]


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify_signature(secret: str, header: str, body: bytes, tolerance_seconds: int = 300) -> bool:
    """Reference implementation for receivers (also used in tests)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        supplied = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs(time.time() - ts) > tolerance_seconds:
        return False
    expected = sign_payload(secret, ts, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, supplied)


def enqueue_event(db: Session, client_id: uuid.UUID, event: str, data: dict) -> int:
    """Create a pending delivery for each matching endpoint. Caller commits."""
    endpoints = db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.client_id == client_id, WebhookEndpoint.is_active.is_(True)
        )
    ).scalars().all()
    count = 0
    for ep in endpoints:
        if ep.events and event not in ep.events:
            continue
        envelope = {
            "id": str(uuid.uuid4()),
            "event": event,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "organization_id": str(client_id),
            "data": data,
        }
        db.add(
            WebhookDelivery(
                client_id=client_id,
                endpoint_id=ep.id,
                event=event,
                payload=envelope,
                status="pending",
                next_attempt_at=datetime.now(timezone.utc),
            )
        )
        count += 1
    return count


# ---------------------------------------------------------------- sending

def _assert_public_destination(url: str) -> None:
    """Re-check at send time: resolve DNS and refuse private/loopback targets."""
    check_public_http_url(url)
    host = urlsplit(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve host: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise ValueError("Destination resolves to a private or internal address")


def send_one(endpoint: WebhookEndpoint, delivery: WebhookDelivery, client: httpx.Client | None = None) -> tuple[bool, int | None, str | None]:
    """POST one delivery. Returns (ok, status_code, error)."""
    body = json.dumps(delivery.payload, separators=(",", ":"), default=str).encode()
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Agni-Webhooks/1.0",
        "X-Agni-Event": delivery.event,
        "X-Agni-Delivery": str(delivery.id),
        "X-Agni-Signature": sign_payload(endpoint.secret, ts, body),
    }
    try:
        _assert_public_destination(endpoint.url)
        http = client or httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False)
        try:
            resp = http.post(endpoint.url, content=body, headers=headers)
        finally:
            if client is None:
                http.close()
        ok = 200 <= resp.status_code < 300
        return ok, resp.status_code, None if ok else f"HTTP {resp.status_code}"
    except Exception as exc:  # network, DNS, SSRF refusal, timeout
        return False, None, str(exc)[:500]


def _record_attempt(delivery: WebhookDelivery, ok: bool, code: int | None, error: str | None) -> None:
    now = datetime.now(timezone.utc)
    delivery.attempts += 1
    delivery.last_status_code = code
    delivery.last_error = error
    if ok:
        delivery.status = "delivered"
        delivery.delivered_at = now
        delivery.next_attempt_at = None
    elif delivery.attempts >= settings.WEBHOOK_MAX_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_attempt_at = None
    else:
        idx = min(delivery.attempts - 1, len(BACKOFF_SECONDS) - 1)
        delivery.next_attempt_at = now + timedelta(seconds=BACKOFF_SECONDS[idx])


def deliver_due(db: Session, limit: int = 50, client: httpx.Client | None = None) -> int:
    """Send every due delivery once. Returns how many were attempted."""
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= now)
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for d in rows:
        ep = db.get(WebhookEndpoint, d.endpoint_id)
        if ep is None or not ep.is_active:
            d.status = "failed"
            d.last_error = "Endpoint removed or disabled"
            d.next_attempt_at = None
            continue
        ok, code, err = send_one(ep, d, client)
        _record_attempt(d, ok, code, err)
    db.commit()
    return len(rows)
