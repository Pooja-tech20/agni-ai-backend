"""Platform features: orgs/superadmin, credits, API keys, webhooks, dialer,
telephony callbacks, contacts extras, analytics, integrations, security.

Uses an isolated in-memory SQLite database (JSONB mapped to JSON).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import Base, get_db
from app.main import app
from app.models import (
    Agent, ApiKey, Call, Campaign, CampaignContact, Client, Contact,
    CreditTransaction, PhoneNumber, User, WebhookDelivery, WebhookEndpoint,
)
from app.models.billing import TxType
from app.services import billing, dialer
from app.services.call_lifecycle import finalize_call
from app.services.webhook_service import (
    deliver_due, enqueue_event, sign_payload, verify_signature,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


for _t in Base.metadata.tables.values():
    for _c in _t.columns:
        if _c.server_default is not None and "::jsonb" in str(_c.server_default.arg).lower():
            _c.server_default = None

# Set TEST_DATABASE_URL=postgresql+psycopg2://... to run this suite on real PostgreSQL
# (exercises JSONB, Numeric and FOR UPDATE SKIP LOCKED); default is in-memory SQLite.
_PG = os.environ.get("TEST_DATABASE_URL")
engine = (
    create_engine(_PG)
    if _PG
    else create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
)
Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _user(db, org, email, role="admin"):
    u = User(
        email=email, hashed_password=hash_password("pw-12345678"), first_name="T", last_name="U",
        organization_name=org.name if org else "Agni", phone_country_code="+91", phone_number="9999999999",
        role=role, client_id=org.id if org else None, is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _hdr(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.fixture()
def env(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "INBOUND_WEBHOOK_SECRET", None)
    monkeypatch.setattr(settings, "RUN_BACKGROUND_WORKERS", False)

    async def _noop_pipeline(call_id):  # the real one opens its own DB session
        return None

    monkeypatch.setattr("app.api.v1.telephony.run_post_call_pipeline", _noop_pipeline)
    db = Session()

    org_a = Client(name="Org A", credit_balance=Decimal("100"))
    org_b = Client(name="Org B", credit_balance=Decimal("100"))
    db.add_all([org_a, org_b])
    db.flush()
    admin_a = _user(db, org_a, "a@x.com", "admin")
    member_a = _user(db, org_a, "ma@x.com", "user")
    admin_b = _user(db, org_b, "b@x.com", "admin")
    root = _user(db, None, "root@x.com", "superadmin")
    agent = Agent(name="Bot", client_id=org_a.id, status="active", llm_model="m")
    pn = PhoneNumber(client_id=org_a.id, number="+911111111111", provider="mock")
    db.add_all([agent, pn])
    db.commit()
    for o in (org_a, org_b, admin_a, member_a, admin_b, root, agent, pn):
        db.refresh(o)

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as c:
            yield dict(c=c, db=db, org_a=org_a, org_b=org_b, admin_a=admin_a, member_a=member_a,
                       admin_b=admin_b, root=root, agent=agent, pn=pn)
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        Base.metadata.drop_all(engine)


def _call(db, org, agent, secs=120, status="in_progress", **kw):
    c = Call(
        client_id=org.id, agent_id=agent.id, status=status, direction=kw.pop("direction", "outbound"),
        channel=kw.pop("channel", "phone"), caller_number=kw.pop("caller_number", "+919876543210"),
        started_at=kw.pop("started_at", datetime.now(timezone.utc) - timedelta(seconds=secs)), **kw,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ============================================================ billing
def test_cost_math_and_settlement_is_idempotent(env):
    db, org = env["db"], env["org_a"]
    call = _call(db, org, env["agent"], secs=90)
    finalize_call(db, call.id, "completed", "user_hangup", provider_duration=90)
    db.refresh(org)
    assert org.credit_balance == Decimal("98.500")  # 1.5 min * 1 credit/min
    finalize_call(db, call.id, "completed", "user_hangup", provider_duration=90)  # no double charge
    billing.settle_call(db, db.get(Call, call.id))
    db.commit()
    rows = db.execute(select(CreditTransaction).where(CreditTransaction.type == TxType.USAGE)).scalars().all()
    assert len(rows) == 1 and rows[0].amount == Decimal("-1.500") and rows[0].balance_after == Decimal("98.500")


def test_per_org_rate_override(env):
    db, org = env["db"], env["org_a"]
    org.credits_per_minute = Decimal("2.5")
    db.commit()
    assert billing.cost_for_seconds(org, 60) == Decimal("2.500")
    assert billing.cost_for_seconds(org, 0) == Decimal("0")


def test_cannot_call_when_suspended_or_broke(env):
    db, org = env["db"], env["org_a"]
    billing.ensure_can_call(db, org.id)
    org.credit_balance = Decimal("0")
    db.commit()
    with pytest.raises(billing.BillingError) as e:
        billing.ensure_can_call(db, org.id)
    assert e.value.code == "INSUFFICIENT_CREDITS" and e.value.status_code == 402
    org.credit_balance, org.status = Decimal("5"), "suspended"
    db.commit()
    with pytest.raises(billing.BillingError) as e:
        billing.ensure_can_call(db, org.id)
    assert e.value.code == "ORG_SUSPENDED"


def test_only_usage_may_go_negative(env):
    db, org = env["db"], env["org_a"]
    with pytest.raises(billing.BillingError):
        billing.apply_transaction(db, org.id, type=TxType.ADJUSTMENT, amount=Decimal("-500"))
    billing.apply_transaction(db, org.id, type=TxType.USAGE, amount=Decimal("-500"))
    db.commit()
    db.refresh(org)
    assert org.credit_balance == Decimal("-400")


def test_low_credit_webhook_fires_once_when_crossing_threshold(env):
    db, org = env["db"], env["org_a"]
    org.credit_balance = Decimal("6")
    db.add(WebhookEndpoint(client_id=org.id, url="https://example.com/h", secret="s", events=["credits.low"]))
    db.commit()
    c1 = _call(db, org, env["agent"], secs=120)
    finalize_call(db, c1.id, "completed", provider_duration=120)  # 6 -> 4, crosses 5
    c2 = _call(db, org, env["agent"], secs=60)
    finalize_call(db, c2.id, "completed", provider_duration=60)   # 4 -> 3, already below
    assert db.query(WebhookDelivery).filter_by(event="credits.low").count() == 1


# ============================================ organizations / superadmin
def test_superadmin_creates_org_with_admin_and_credits(env):
    c, root = env["c"], env["root"]
    r = c.post("/api/v1/admin/organizations", headers=_hdr(root), json={
        "name": "Acme", "plan": "pro", "initial_credits": "25", "admin_email": "boss@acme.com",
        "admin_password": "supersecret1", "admin_first_name": "Boss"})
    assert r.status_code == 201, r.text
    org_id = r.json()["id"]
    assert Decimal(r.json()["credit_balance"]) == Decimal("25")
    login = c.post("/api/v1/auth/login", json={"email": "boss@acme.com", "password": "supersecret1"})
    assert login.status_code == 200
    tx = c.get(f"/api/v1/admin/organizations/{org_id}/transactions", headers=_hdr(root)).json()
    assert tx["total"] == 1 and tx["items"][0]["type"] == "grant"
    assert c.get("/api/v1/admin/stats", headers=_hdr(root)).json()["organizations_total"] >= 3


def test_org_admin_cannot_use_superadmin_endpoints(env):
    c = env["c"]
    for path in ("/api/v1/admin/organizations", "/api/v1/admin/stats", "/api/v1/admin/audit-logs"):
        assert c.get(path, headers=_hdr(env["admin_a"])).status_code == 403
    assert c.get("/api/v1/admin/organizations").status_code == 401


def test_suspend_locks_out_org_and_activate_restores(env):
    c, root, org = env["c"], env["root"], env["org_a"]
    assert c.get("/api/v1/organization", headers=_hdr(env["admin_a"])).status_code == 200
    r = c.post(f"/api/v1/admin/organizations/{org.id}/suspend", headers=_hdr(root), json={"reason": "unpaid"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert c.get("/api/v1/organization", headers=_hdr(env["admin_a"])).status_code == 403
    assert c.get("/api/v1/organization", headers=_hdr(env["admin_b"])).status_code == 200  # others unaffected
    c.post(f"/api/v1/admin/organizations/{org.id}/activate", headers=_hdr(root))
    assert c.get("/api/v1/organization", headers=_hdr(env["admin_a"])).status_code == 200


def test_credit_grant_rules(env):
    c, root, org = env["c"], env["root"], env["org_b"]
    ok = c.post(f"/api/v1/admin/organizations/{org.id}/credits", headers=_hdr(root),
                json={"type": "grant", "amount": "50", "description": "promo"})
    assert ok.status_code == 201 and Decimal(ok.json()["balance_after"]) == Decimal("150")
    bad = c.post(f"/api/v1/admin/organizations/{org.id}/credits", headers=_hdr(root),
                 json={"type": "grant", "amount": "-5"})
    assert bad.status_code == 400
    over = c.post(f"/api/v1/admin/organizations/{org.id}/credits", headers=_hdr(root),
                  json={"type": "adjustment", "amount": "-9999"})
    assert over.status_code == 400
    logs = c.get("/api/v1/admin/audit-logs", headers=_hdr(root)).json()
    assert any(l["action"] == "credits.changed" for l in logs)


def test_billing_endpoints_are_org_scoped(env):
    c = env["c"]
    r = c.get("/api/v1/billing/balance", headers=_hdr(env["admin_a"]))
    assert r.status_code == 200 and r.json()["client_id"] == str(env["org_a"].id)
    # passing another org's id is refused
    r = c.get(f"/api/v1/billing/balance?client_id={env['org_b'].id}", headers=_hdr(env["admin_a"]))
    assert r.status_code == 403
    # superadmin must name the org
    assert c.get("/api/v1/billing/balance", headers=_hdr(env["root"])).status_code == 400
    assert c.get(f"/api/v1/billing/balance?client_id={env['org_b'].id}", headers=_hdr(env["root"])).status_code == 200
    assert c.get("/api/v1/billing/usage?days=7", headers=_hdr(env["admin_a"])).status_code == 200


def test_agent_limit_enforced(env):
    from fastapi import HTTPException
    from app.api.scope import enforce_agent_limit
    db, org = env["db"], env["org_a"]
    org.max_agents = 1
    db.commit()
    with pytest.raises(HTTPException) as e:
        enforce_agent_limit(db, org.id)
    assert e.value.status_code == 403


# ================================================================ api keys
def test_api_key_lifecycle(env):
    c = env["c"]
    r = c.post("/api/v1/api-keys", headers=_hdr(env["admin_a"]), json={"name": "ci"})
    assert r.status_code == 201
    key, kid = r.json()["key"], r.json()["id"]
    assert key.startswith("agni_")
    stored = env["db"].query(ApiKey).one()
    assert key not in (stored.key_hash, stored.prefix) and len(stored.key_hash) == 64  # hashed
    listed = c.get("/api/v1/api-keys", headers=_hdr(env["admin_a"])).json()
    assert "key" not in listed[0]
    me = c.get("/api/v1/organization", headers={"X-Api-Key": key})
    assert me.status_code == 200 and me.json()["id"] == str(env["org_a"].id)
    # a member cannot mint keys, another org cannot revoke it
    assert c.post("/api/v1/api-keys", headers=_hdr(env["member_a"]), json={"name": "x"}).status_code == 403
    assert c.delete(f"/api/v1/api-keys/{kid}", headers=_hdr(env["admin_b"])).status_code == 404
    assert c.delete(f"/api/v1/api-keys/{kid}", headers=_hdr(env["admin_a"])).status_code == 204
    assert c.get("/api/v1/organization", headers={"X-Api-Key": key}).status_code == 401
    assert c.get("/api/v1/organization", headers={"X-Api-Key": "agni_nope"}).status_code == 401


def test_expired_api_key_rejected(env):
    c = env["c"]
    key = c.post("/api/v1/api-keys", headers=_hdr(env["admin_a"]), json={"name": "t", "expires_in_days": 1}).json()["key"]
    row = env["db"].query(ApiKey).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    env["db"].commit()
    assert c.get("/api/v1/organization", headers={"X-Api-Key": key}).status_code == 401


def test_api_key_of_suspended_org_is_blocked(env):
    c = env["c"]
    key = c.post("/api/v1/api-keys", headers=_hdr(env["admin_a"]), json={"name": "t"}).json()["key"]
    env["org_a"].status = "suspended"
    env["db"].commit()
    assert c.get("/api/v1/organization", headers={"X-Api-Key": key}).status_code == 403


# =============================================================== webhooks
def test_signature_roundtrip_and_tamper_detection():
    body, ts = b'{"a":1}', int(datetime.now(timezone.utc).timestamp())
    header = sign_payload("whsec_x", ts, body)
    assert verify_signature("whsec_x", header, body)
    assert not verify_signature("whsec_x", header, b'{"a":2}')
    assert not verify_signature("other", header, body)
    old = sign_payload("whsec_x", ts - 4000, body)
    assert not verify_signature("whsec_x", old, body)


def test_webhook_crud_validation_and_secret_shown_once(env):
    c, h = env["c"], _hdr(env["admin_a"])
    assert c.post("/api/v1/webhooks", headers=h, json={"url": "http://localhost/x"}).status_code == 400
    assert c.post("/api/v1/webhooks", headers=h, json={"url": "http://10.0.0.5/x"}).status_code == 400
    assert c.post("/api/v1/webhooks", headers=h, json={"url": "https://e.com/x", "events": ["nope"]}).status_code == 400
    r = c.post("/api/v1/webhooks", headers=h, json={"url": "https://e.com/x", "events": ["call.completed"]})
    assert r.status_code == 201 and r.json()["secret"].startswith("whsec_")
    wid = r.json()["id"]
    assert "secret" not in c.get("/api/v1/webhooks", headers=h).json()[0]
    assert c.get("/api/v1/webhooks/events", headers=h).json()["events"]
    assert c.delete(f"/api/v1/webhooks/{wid}", headers=_hdr(env["admin_b"])).status_code == 404
    rot = c.post(f"/api/v1/webhooks/{wid}/rotate-secret", headers=h)
    assert rot.json()["secret"] != r.json()["secret"]


def _endpoint(db, org, events=None):
    ep = WebhookEndpoint(client_id=org.id, url="https://hooks.example.com/in", secret="whsec_test", events=events or [])
    db.add(ep)
    db.commit()
    return ep


def test_delivery_success_signs_payload(env, monkeypatch):
    db = env["db"]
    ep = _endpoint(db, env["org_a"])
    monkeypatch.setattr("app.services.webhook_service._assert_public_destination", lambda url: None)
    enqueue_event(db, env["org_a"].id, "call.completed", {"call_id": "1"})
    db.commit()
    seen = {}

    def handler(request: httpx.Request):
        seen["body"], seen["sig"] = request.content, request.headers["X-Agni-Signature"]
        seen["event"] = request.headers["X-Agni-Event"]
        return httpx.Response(200)

    n = deliver_due(db, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert n == 1 and seen["event"] == "call.completed"
    assert verify_signature("whsec_test", seen["sig"], seen["body"])
    d = db.query(WebhookDelivery).one()
    assert d.status == "delivered" and d.attempts == 1 and d.delivered_at is not None


def test_delivery_retries_with_backoff_then_gives_up(env, monkeypatch):
    db = env["db"]
    _endpoint(db, env["org_a"])
    monkeypatch.setattr("app.services.webhook_service._assert_public_destination", lambda url: None)
    monkeypatch.setattr(settings, "WEBHOOK_MAX_ATTEMPTS", 3)
    enqueue_event(db, env["org_a"].id, "call.failed", {})
    db.commit()
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    deliver_due(db, client=http)
    d = db.query(WebhookDelivery).one()
    assert d.status == "pending" and d.attempts == 1 and d.last_status_code == 500
    assert deliver_due(db, client=http) == 0  # not due yet (backoff)
    for expected_attempts in (2, 3):
        d.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        deliver_due(db, client=http)
        db.refresh(d)
        assert d.attempts == expected_attempts
    assert d.status == "failed" and d.next_attempt_at is None


def test_delivery_refuses_private_destination(env):
    db = env["db"]
    ep = WebhookEndpoint(client_id=env["org_a"].id, url="http://127.0.0.1:9/x", secret="s", events=[])
    db.add(ep)
    db.commit()
    d = WebhookDelivery(client_id=ep.client_id, endpoint_id=ep.id, event="x", payload={})
    from app.services.webhook_service import send_one
    ok, code, err = send_one(ep, d)
    assert not ok and code is None
    assert "internal" in err.lower() or "private" in err.lower()


def test_event_filtering_per_endpoint(env):
    db = env["db"]
    _endpoint(db, env["org_a"], events=["call.completed"])
    _endpoint(db, env["org_a"], events=[])
    _endpoint(db, env["org_b"], events=[])
    assert enqueue_event(db, env["org_a"].id, "call.failed", {}) == 1      # only the catch-all
    assert enqueue_event(db, env["org_a"].id, "call.completed", {}) == 2   # both


# ================================================================== dialer
def test_call_window_logic():
    sat_2am_utc = datetime(2026, 11, 28, 2, 0, tzinfo=timezone.utc)  # Saturday
    assert dialer.in_call_window({}, sat_2am_utc)
    cfg = {"timezone": "Asia/Kolkata", "call_window_start": "09:00", "call_window_end": "18:00"}
    assert dialer.in_call_window(cfg, datetime(2026, 11, 25, 5, 0, tzinfo=timezone.utc))      # 10:30 IST
    assert not dialer.in_call_window(cfg, datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc))  # 19:30 IST
    assert not dialer.in_call_window({"active_days": ["Mon", "Tue"]}, sat_2am_utc)
    night = {"call_window_start": "22:00", "call_window_end": "06:00"}
    assert dialer.in_call_window(night, sat_2am_utc) and not dialer.in_call_window(night, sat_2am_utc.replace(hour=12))


def _campaign(db, env, n_contacts=2, **settings_):
    camp = Campaign(client_id=env["org_a"].id, name="C", agent_id=env["agent"].id,
                    phone_number_id=env["pn"].id, status="active", settings=settings_)
    db.add(camp)
    db.flush()
    for i in range(n_contacts):
        ct = Contact(client_id=env["org_a"].id, phone=f"+91900000000{i}", name=f"P{i}")
        db.add(ct)
        db.flush()
        db.add(CampaignContact(client_id=env["org_a"].id, campaign_id=camp.id, contact_id=ct.id))
    db.commit()
    return camp


def test_dialer_runs_campaign_to_completion_with_mock_provider(env, monkeypatch):
    monkeypatch.setattr(settings, "TELEPHONY_PROVIDER", "mock")
    from app.services.telephony import factory
    factory.get_telephony_provider.cache_clear()
    db = env["db"]
    camp = _campaign(db, env, n_contacts=3, max_concurrent=5)
    db.add(WebhookEndpoint(client_id=env["org_a"].id, url="https://e.com/h", secret="s", events=["campaign.completed"]))
    db.commit()
    started = dialer.dial_tick(db)
    assert started == 3
    db.refresh(camp)
    assert camp.status == "completed" and camp.total_calls == 3 and camp.running_calls == 0
    assert db.query(CampaignContact).filter_by(status="completed").count() == 3
    assert db.query(WebhookDelivery).filter_by(event="campaign.completed").count() == 1


def test_dialer_respects_campaign_concurrency(env, monkeypatch):
    from app.services.telephony.base import CallInitiationResult, TelephonyProvider

    class Real(TelephonyProvider):
        name = "fake"
        def initiate_call(self, **kw):
            return CallInitiationResult("fake", "sid-" + uuid.uuid4().hex[:6], "queued", kw["to_number"], kw["from_number"])
        def end_call(self, i): return True
        def get_call_status(self, i): return {}

    monkeypatch.setattr(dialer, "get_telephony_provider", lambda: Real())
    db = env["db"]
    camp = _campaign(db, env, n_contacts=4, max_concurrent=2)
    assert dialer.dial_tick(db) == 2           # only 2 slots
    assert dialer.dial_tick(db) == 0           # both still ringing
    first = db.query(Call).first()
    finalize_call(db, first.id, "completed", "user_hangup", provider_duration=30)
    assert dialer.dial_tick(db) == 1           # one slot freed
    db.refresh(camp)
    assert camp.total_calls == 3 and camp.running_calls == 2


def test_dialer_retries_no_answer_then_gives_up(env, monkeypatch):
    from app.services.telephony.base import CallInitiationResult, TelephonyProvider

    class Real(TelephonyProvider):
        name = "fake"
        def initiate_call(self, **kw):
            return CallInitiationResult("fake", "sid-" + uuid.uuid4().hex[:6], "queued", kw["to_number"], kw["from_number"])
        def end_call(self, i): return True
        def get_call_status(self, i): return {}

    monkeypatch.setattr(dialer, "get_telephony_provider", lambda: Real())
    db = env["db"]
    camp = _campaign(db, env, n_contacts=1, max_attempts=2, retry_delay_minutes=10)
    dialer.dial_tick(db)
    call = db.query(Call).one()
    finalize_call(db, call.id, "failed", "no_answer")
    cc = db.query(CampaignContact).one()
    assert cc.status == "pending" and cc.attempts == 1 and cc.next_attempt_at is not None
    assert dialer.dial_tick(db) == 0           # waiting out the retry delay
    cc.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert dialer.dial_tick(db) == 1
    db.refresh(cc)
    finalize_call(db, cc.last_call_id, "failed", "no_answer")
    db.refresh(cc)
    db.refresh(camp)
    assert cc.status == "no_answer" and cc.attempts == 2
    assert camp.status == "completed"


def test_dialer_pauses_campaign_when_out_of_credits(env):
    db = env["db"]
    camp = _campaign(db, env, n_contacts=2)
    env["org_a"].credit_balance = Decimal("0")
    db.commit()
    assert dialer.dial_tick(db) == 0
    db.refresh(camp)
    assert camp.status == "paused" and "credits" in camp.settings["paused_reason"].lower()


def test_dialer_skips_outside_window_and_reaps_stuck_calls(env, monkeypatch):
    db = env["db"]
    camp = _campaign(db, env, n_contacts=1, call_window_start="03:00", call_window_end="03:01", timezone="UTC")
    assert dialer.dial_tick(db, now=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)) == 0
    stuck = _call(db, env["org_a"], env["agent"], secs=3 * 3600, campaign_id=camp.id)
    assert dialer.reap_stuck_calls(db, datetime.now(timezone.utc)) == 1
    db.refresh(stuck)
    assert stuck.status == "failed" and stuck.end_reason == "timeout"


def test_start_campaign_validations_and_resume(env):
    c, h, db = env["c"], _hdr(env["admin_a"]), env["db"]
    camp = Campaign(client_id=env["org_a"].id, name="N", agent_id=env["agent"].id, status="draft")
    db.add(camp)
    db.commit()
    assert c.post(f"/api/v1/campaigns/{camp.id}/start", headers=h).status_code == 400  # no caller ID
    camp.phone_number_id = env["pn"].id
    db.commit()
    assert c.post(f"/api/v1/campaigns/{camp.id}/start", headers=h).status_code == 400  # no contacts
    ct = Contact(client_id=env["org_a"].id, phone="+919000000001")
    other = Contact(client_id=env["org_b"].id, phone="+919000000002")
    db.add_all([ct, other])
    db.commit()
    r = c.post(f"/api/v1/campaigns/{camp.id}/contacts", headers=h,
               json={"contact_ids": [str(ct.id), str(other.id), str(uuid.uuid4())]})
    assert r.json() == {"added": 1, "already_in_campaign": 0, "not_found": 2}  # other org's contact refused
    assert c.post(f"/api/v1/campaigns/{camp.id}/contacts", headers=h,
                  json={"contact_ids": [str(ct.id)]}).json()["already_in_campaign"] == 1
    assert c.post(f"/api/v1/campaigns/{camp.id}/start", headers=h).status_code == 200
    assert c.post(f"/api/v1/campaigns/{camp.id}/resume", headers=h).status_code == 409
    c.post(f"/api/v1/campaigns/{camp.id}/pause", headers=h)
    assert c.post(f"/api/v1/campaigns/{camp.id}/resume", headers=h).json()["status"] == "active"
    lst = c.get(f"/api/v1/campaigns/{camp.id}/contacts", headers=h).json()
    assert lst["total"] == 1 and lst["items"][0]["phone"] == "+919000000001"
    assert c.get(f"/api/v1/campaigns/{camp.id}/contacts", headers=_hdr(env["admin_b"])).status_code == 404


# ================================================================ telephony
def test_exotel_callback_requires_secret_and_finalizes_call(env, monkeypatch):
    monkeypatch.setattr(settings, "INBOUND_WEBHOOK_SECRET", "s3cret")
    ran = []

    async def fake_pipeline(call_id):
        ran.append(call_id)

    monkeypatch.setattr("app.api.v1.telephony.run_post_call_pipeline", fake_pipeline)
    c, db = env["c"], env["db"]
    call = _call(db, env["org_a"], env["agent"], provider_call_id="EX123")
    form = {"CallSid": "EX123", "Status": "completed", "ConversationDuration": "120",
            "RecordingUrl": "https://rec.example/1.mp3"}
    assert c.post("/api/v1/telephony/exotel/status", data=form).status_code == 401
    assert c.post("/api/v1/telephony/exotel/status?token=wrong", data=form).status_code == 401
    r = c.post("/api/v1/telephony/exotel/status?token=s3cret", data=form)
    assert r.status_code == 200 and r.json()["status"] == "completed"
    db.refresh(call)
    assert call.status == "completed" and call.duration_seconds == 120 and call.recording_url
    db.refresh(env["org_a"])
    assert env["org_a"].credit_balance == Decimal("98.000")
    assert ran == [call.id]
    # replayed callback: no second charge, no second pipeline run
    c.post("/api/v1/telephony/exotel/status?token=s3cret", data=form)
    db.refresh(env["org_a"])
    assert env["org_a"].credit_balance == Decimal("98.000") and len(ran) == 1


def test_exotel_non_terminal_and_unknown_calls_ignored(env, monkeypatch):
    c = env["c"]
    r = c.post("/api/v1/telephony/exotel/status", data={"CallSid": "X", "Status": "in-progress"})
    assert r.json().get("ignored")
    r = c.post("/api/v1/telephony/exotel/status", data={"CallSid": "nope", "Status": "completed"})
    assert r.json().get("ignored") == "unknown call"


def test_exotel_failed_status_maps_reason(env):
    db = env["db"]
    call = _call(db, env["org_a"], env["agent"], provider_call_id="EX9")
    env["c"].post("/api/v1/telephony/exotel/status", data={"CallSid": "EX9", "Status": "no-answer"})
    db.refresh(call)
    assert call.status == "failed" and call.end_reason == "no_answer"
    db.refresh(env["org_a"])
    assert env["org_a"].credit_balance == Decimal("100")  # unanswered = free


def test_inbound_webhook_secret_and_gating(env, monkeypatch):
    c, db = env["c"], env["db"]
    from app.models import InboundRoute
    db.add(InboundRoute(client_id=env["org_a"].id, phone_number_id=env["pn"].id, agent_id=env["agent"].id))
    db.commit()
    body = {"From": "+919811111111", "To": env["pn"].number, "CallSid": "IN1"}
    monkeypatch.setattr(settings, "INBOUND_WEBHOOK_SECRET", "abc")
    assert c.post("/api/v1/inbound/webhook", json=body).status_code == 401
    ok = c.post("/api/v1/inbound/webhook", json=body, headers={"X-Webhook-Secret": "abc"})
    assert ok.status_code == 200 and ok.json()["status"] == "received" and ok.json()["call_id"]
    env["org_a"].credit_balance = Decimal("0")
    db.commit()
    rej = c.post("/api/v1/inbound/webhook", json=body, headers={"X-Webhook-Secret": "abc"})
    assert rej.json()["status"] == "rejected" and rej.json()["call_id"] is None
    assert db.query(Call).count() == 1  # the rejected call was never created


def test_exotel_provider_builds_request_and_parses_response(monkeypatch):
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", "acct")
    monkeypatch.setattr(settings, "EXOTEL_API_KEY", "k")
    monkeypatch.setattr(settings, "EXOTEL_API_TOKEN", "t")
    monkeypatch.setattr(settings, "EXOTEL_FLOW_URL", "http://my.exotel.com/acct/exoml/start_voice/1")
    monkeypatch.setattr(settings, "EXOTEL_WEBHOOK_BASE_URL", "https://api.agni.test")
    monkeypatch.setattr(settings, "INBOUND_WEBHOOK_SECRET", "s3")
    captured = {}

    def handler(request: httpx.Request):
        captured["url"], captured["body"] = str(request.url), request.content.decode()
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"Call": {"Sid": "CA1", "Status": "queued"}})

    from app.services.telephony.exotel_provider import ExotelTelephonyProvider
    p = ExotelTelephonyProvider(http=httpx.Client(transport=httpx.MockTransport(handler)))
    res = p.initiate_call(to_number="+919876543210", from_number="+911111111111", agent_id="a", call_id="c1")
    assert res.provider_call_id == "CA1" and res.status == "queued"
    assert "/v1/Accounts/acct/Calls/connect.json" in captured["url"]
    from urllib.parse import parse_qs, unquote
    form = parse_qs(captured["body"])
    assert form["From"] == ["+919876543210"] and form["CallerId"] == ["+911111111111"]
    assert form["StatusCallback"][0].endswith("/api/v1/telephony/exotel/status?token=s3")
    assert json.loads(form["CustomField"][0])["call_id"] == "c1"
    assert captured["auth"].startswith("Basic ")


def test_exotel_provider_refuses_to_run_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", None)
    from app.services.telephony.exotel_provider import ExotelTelephonyProvider
    with pytest.raises(RuntimeError, match="not configured"):
        ExotelTelephonyProvider().initiate_call(to_number="1", from_number="2", agent_id="a", call_id="c")


def test_outbound_call_blocked_without_credits(env):
    c, db = env["c"], env["db"]
    env["org_a"].credit_balance = Decimal("0")
    db.commit()
    r = c.post("/api/v1/outbound/call", headers=_hdr(env["admin_a"]), json={
        "agent_id": str(env["agent"].id), "phone_number_id": str(env["pn"].id), "to_number": "+919800000000"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "INSUFFICIENT_CREDITS"
    assert db.query(Call).count() == 0


# ========================================================== contacts extras
def test_contact_notes_stats_activity_and_isolation(env):
    c, db = env["c"], env["db"]
    ct = Contact(client_id=env["org_a"].id, phone="+919876543210", name="Ravi")
    db.add(ct)
    db.commit()
    h = _hdr(env["member_a"])
    n = c.post(f"/api/v1/contacts/{ct.id}/notes", headers=h, json={"body": "Prefers evenings"})
    assert n.status_code == 201
    _call(db, env["org_a"], env["agent"], status="completed", duration_seconds=60, sentiment="positive", caller_number="9876543210")
    _call(db, env["org_a"], env["agent"], status="failed", duration_seconds=0, caller_number="+919876543210")
    st = c.get(f"/api/v1/contacts/{ct.id}/stats", headers=h).json()
    assert st["total_calls"] == 2 and st["completed_calls"] == 1 and st["sentiment"] == {"positive": 1}
    acts = c.get(f"/api/v1/contacts/{ct.id}/activities", headers=h).json()
    assert {a["type"] for a in acts} == {"call", "note"}
    assert c.get(f"/api/v1/contacts/{ct.id}/calls", headers=h).json()["total"] == 2
    other = _hdr(env["admin_b"])
    assert c.get(f"/api/v1/contacts/{ct.id}/notes", headers=other).status_code == 404
    assert c.post(f"/api/v1/contacts/{ct.id}/notes", headers=other, json={"body": "x"}).status_code == 404


def test_bulk_delete_only_touches_own_org(env):
    c, db = env["c"], env["db"]
    mine = Contact(client_id=env["org_a"].id, phone="+911000000001")
    theirs = Contact(client_id=env["org_b"].id, phone="+911000000002")
    db.add_all([mine, theirs])
    db.commit()
    r = c.post("/api/v1/contacts/bulk-delete", headers=_hdr(env["admin_a"]), json={"ids": [str(mine.id), str(theirs.id)]})
    assert r.json() == {"deleted": 1}
    assert db.get(Contact, theirs.id) is not None
    assert c.post("/api/v1/contacts/bulk-delete", headers=_hdr(env["member_a"]), json={"ids": [str(mine.id)]}).status_code == 403


# ============================================================ agents/models
def test_agent_status_toggle_scoped_and_models_list(env):
    c = env["c"]
    aid = env["agent"].id
    assert c.patch(f"/api/v1/agents/{aid}/status", headers=_hdr(env["admin_b"]), json={"status": "inactive"}).status_code == 404
    assert c.patch(f"/api/v1/agents/{aid}/status", headers=_hdr(env["member_a"]), json={"status": "inactive"}).status_code == 403
    r = c.patch(f"/api/v1/agents/{aid}/status", headers=_hdr(env["admin_a"]), json={"status": "inactive"})
    assert r.json()["status"] == "inactive"
    assert c.patch(f"/api/v1/agents/{aid}/status", headers=_hdr(env["admin_a"]), json={"status": "bogus"}).status_code == 422
    m = c.get("/api/v1/models", headers=_hdr(env["member_a"]))
    assert m.status_code == 200 and m.json()["models"]


# ================================================================ analytics
def test_analytics_numbers_and_scoping(env):
    c, db = env["c"], env["db"]
    a, now = env["agent"], datetime.now(timezone.utc)
    _call(db, env["org_a"], a, status="completed", duration_seconds=120, converted=True, sentiment="positive", caller_number="+919800000001")
    _call(db, env["org_a"], a, status="completed", duration_seconds=60, sentiment="negative", direction="inbound", caller_number="+14155550100")
    _call(db, env["org_a"], a, status="failed", duration_seconds=0, caller_number="+919800000002")
    other_agent = Agent(name="x", client_id=env["org_b"].id, status="active")
    db.add(other_agent)
    db.commit()
    _call(db, env["org_b"], other_agent, status="completed", duration_seconds=999)  # must not leak into org A numbers
    h = _hdr(env["admin_a"])
    o = c.get("/api/v1/analytics/overview", headers=h).json()
    assert o["total_calls"] == 3 and o["completed"] == 2 and o["failed"] == 1
    assert o["converted"] == 1 and o["inbound"] == 1 and o["outbound"] == 2
    assert o["total_minutes"] == 3.0 and o["success_rate"] == 66.67
    assert c.get("/api/v1/analytics/sentiment", headers=h).json() == {"positive": 1, "neutral": 0, "negative": 1}
    countries = {r["country"]: r["calls"] for r in c.get("/api/v1/analytics/top-countries", headers=h).json()}
    assert countries["India"] >= 2 and countries["United States / Canada"] == 1
    assert sum(p["calls"] for p in c.get("/api/v1/analytics/timeseries", headers=h).json()) == 3
    hours = c.get("/api/v1/analytics/channels-by-hour", headers=h).json()
    assert len(hours) == 24
    perf = c.get("/api/v1/analytics/agents", headers=h).json()
    assert perf[0]["agent_name"] == "Bot"
    assert c.get("/api/v1/analytics/overview", headers=_hdr(env["root"])).status_code == 400


# ============================================================ integrations
def test_integration_credentials_encrypted_and_never_returned(env, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())

    class FakeCal:
        def __init__(self, key): self.key = key
        def me(self): return {"id": 1}
        def event_types(self): return [{"id": 5, "title": "Demo"}]

    monkeypatch.setattr("app.api.v1.integrations.CalcomClient", FakeCal)
    c, h = env["c"], _hdr(env["admin_a"])
    r = c.post("/api/v1/integrations/calcom/connect", headers=h, json={"api_key": "cal_live_supersecret123"})
    assert r.status_code == 201 and "credential" not in r.text and "supersecret" not in r.text
    from app.models import IntegrationAccount
    row = env["db"].query(IntegrationAccount).one()
    assert "supersecret" not in row.credential_encrypted  # encrypted at rest
    listed = c.get("/api/v1/integrations", headers=h)
    assert "supersecret" not in listed.text and listed.json()[0]["provider"] == "calcom"
    assert c.get("/api/v1/integrations/calcom/event-types", headers=h).json()[0]["title"] == "Demo"
    assert c.get("/api/v1/integrations", headers=_hdr(env["admin_b"])).json() == []
    assert c.post("/api/v1/integrations/calcom/connect", headers=_hdr(env["member_a"]), json={"api_key": "x" * 12}).status_code == 403


def test_connect_without_encryption_key_is_503_not_plaintext(env, monkeypatch):
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", None)

    class FakeCal:
        def __init__(self, key): ...
        def me(self): return {}

    monkeypatch.setattr("app.api.v1.integrations.CalcomClient", FakeCal)
    r = env["c"].post("/api/v1/integrations/calcom/connect", headers=_hdr(env["admin_a"]), json={"api_key": "k" * 12})
    assert r.status_code == 503
    assert env["db"].query(__import__("app.models", fromlist=["IntegrationAccount"]).IntegrationAccount).count() == 0


def test_agent_appointment_endpoint_auth_and_booking(env, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "AGENT_INTERNAL_SECRET", "agent-secret")

    class FakeCal:
        def __init__(self, key): ...
        def me(self): return {}
        def slots(self, *a, **k): return {"2026-12-01": [{"start": "2026-12-01T10:00:00Z"}]}
        def book(self, event_type_id, start, name, email, tz, phone=None, notes=None):
            return {"uid": "bk_1", "end": "2026-12-01T10:30:00Z"}

    monkeypatch.setattr("app.api.v1.integrations.CalcomClient", FakeCal)
    c = env["c"]
    c.post("/api/v1/integrations/calcom/connect", headers=_hdr(env["admin_a"]), json={"api_key": "k" * 12})
    db = env["db"]
    db.add(WebhookEndpoint(client_id=env["org_a"].id, url="https://e.com/h", secret="s", events=["appointment.booked"]))
    db.commit()
    body = {"org_id": str(env["org_a"].id), "action": "book", "event_type_id": "5",
            "start": "2026-12-01T10:00:00Z", "attendee_name": "Ravi", "attendee_email": "r@e.com"}
    assert c.post("/api/v1/appointments/agent", json=body).status_code == 401
    assert c.post("/api/v1/appointments/agent", json=body, headers={"X-Agent-Secret": "nope"}).status_code == 401
    ok = c.post("/api/v1/appointments/agent", json=body, headers={"X-Agent-Secret": "agent-secret"})
    assert ok.status_code == 200 and ok.json()["provider_booking_id"] == "bk_1"
    appts = c.get("/api/v1/appointments", headers=_hdr(env["admin_a"])).json()
    assert appts["total"] == 1 and appts["items"][0]["attendee_name"] == "Ravi"
    assert c.get("/api/v1/appointments", headers=_hdr(env["admin_b"])).json()["total"] == 0
    assert db.query(WebhookDelivery).filter_by(event="appointment.booked").count() == 1
    av = c.post("/api/v1/appointments/agent", headers={"X-Agent-Secret": "agent-secret"},
                json={"org_id": str(env["org_a"].id), "action": "check_availability", "event_type_id": "5"})
    assert av.status_code == 200 and "slots" in av.json()
    # suspended org: the agent can no longer book
    env["org_a"].status = "suspended"
    db.commit()
    assert c.post("/api/v1/appointments/agent", json=body, headers={"X-Agent-Secret": "agent-secret"}).status_code == 403


def test_agent_appointment_endpoint_closed_when_secret_unset(env, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_INTERNAL_SECRET", None)
    r = env["c"].post("/api/v1/appointments/agent", json={"org_id": str(env["org_a"].id), "action": "book"},
                      headers={"X-Agent-Secret": ""})
    assert r.status_code == 503


# ================================================================ security
def test_production_refuses_insecure_defaults(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "change-this-secret-key")
    monkeypatch.setattr(settings, "INBOUND_WEBHOOK_SECRET", None)
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", None)
    with pytest.raises(RuntimeError) as e:
        settings.assert_safe_for_environment()
    for needle in ("JWT_SECRET_KEY", "INBOUND_WEBHOOK_SECRET", "SECRETS_ENCRYPTION_KEY", "DEBUG"):
        assert needle in str(e.value)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    settings.assert_safe_for_environment()  # dev is allowed


def test_production_webhook_secret_missing_is_503_not_open(env, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "INBOUND_WEBHOOK_SECRET", None)
    r = env["c"].post("/api/v1/telephony/exotel/status", data={"CallSid": "x", "Status": "completed"})
    assert r.status_code == 503


def test_chat_rate_limit(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.core.rate_limit import rate_limit_chat, reset_rate_limits
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT_PER_MINUTE", 3)
    reset_rate_limits()
    req = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))
    for _ in range(3):
        rate_limit_chat(req)
    with pytest.raises(HTTPException) as e:
        rate_limit_chat(req)
    assert e.value.status_code == 429
    rate_limit_chat(SimpleNamespace(client=SimpleNamespace(host="5.6.7.8")))  # other IP unaffected
    reset_rate_limits()


def test_every_org_scoped_list_endpoint_isolates_tenants(env):
    """Smoke: org B's admin sees none of org A's data on any list endpoint."""
    db, c = env["db"], env["c"]
    ct = Contact(client_id=env["org_a"].id, phone="+911234567890")
    db.add(ct)
    _call(db, env["org_a"], env["agent"], status="completed", duration_seconds=10)
    db.commit()
    hb = _hdr(env["admin_b"])
    for path in ("/api/v1/contacts", "/api/v1/calls", "/api/v1/agents", "/api/v1/campaigns",
                 "/api/v1/phone-numbers", "/api/v1/webhooks", "/api/v1/api-keys", "/api/v1/appointments"):
        r = c.get(path, headers=hb)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        body = r.json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        assert items == [] or items == {}, (path, items)


def test_unanswered_and_timed_out_calls_are_never_billed(env):
    db, org = env["db"], env["org_a"]
    for reason in ("no_answer", "busy", "timeout", "provider_error"):
        c = _call(db, org, env["agent"], secs=600)
        finalize_call(db, c.id, "failed", reason)
    db.refresh(org)
    assert org.credit_balance == Decimal("100")
    # a call that connected and then errored IS billed for the time it ran
    c = _call(db, org, env["agent"], secs=60)
    finalize_call(db, c.id, "failed", "error")
    db.refresh(org)
    assert org.credit_balance == Decimal("99.000")
