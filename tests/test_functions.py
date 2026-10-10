"""Functions API tests. Run on in-memory SQLite (Postgres-only types are mapped for the test)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.security import create_access_token, hash_password
from app.core.url_safety import check_public_http_url
from app.db.session import Base, get_db
from app.main import app
from app.models import Agent, Client, User
from app.models.function import AgentFunction


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


for col in Agent.__table__.columns:  # "'[]'::jsonb" defaults are Postgres-only
    if col.server_default is not None and "jsonb" in str(col.server_default.arg):
        col.server_default = None
for col in AgentFunction.__table__.columns:
    if col.server_default is not None and "jsonb" in str(col.server_default.arg):
        col.server_default = None

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

SECRET = "Bearer sk_live_ABCDEFGH12345678"
WEBHOOK = {
    "name": "check_order",
    "description": "Look up an order",
    "type": "webhook",
    "config": {
        "url": "https://api.example.com/orders",
        "headers": {"Authorization": SECRET},
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},
    },
}


@pytest.fixture()
def env():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = Session()
    org_a, org_b = Client(name="A"), Client(name="B")
    db.add_all([org_a, org_b])
    db.flush()

    def mk(email, org, role="admin"):
        u = User(email=email, hashed_password=hash_password("x"), first_name="P", last_name="T",
                 organization_name="A", phone_country_code="+91", phone_number="9",
                 role=role, client_id=org.id)
        db.add(u)
        db.flush()
        return u

    ua, ub, member = mk("a@x.com", org_a), mk("b@x.com", org_b), mk("m@x.com", org_a, role="user")
    db.commit()

    def override():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override
    hdr = lambda u: {"Authorization": f"Bearer {create_access_token(str(u.id), u.role)}"}
    yield dict(db=db, c=TestClient(app), A=hdr(ua), B=hdr(ub), M=hdr(member), org_a=org_a)
    app.dependency_overrides.clear()
    db.close()


def create(env, who="A", body=None):
    return env["c"].post("/api/v1/functions", headers=env[who], json=body or WEBHOOK)


# ---------------------------------------------------------------- types / auth
def test_types_and_auth_required(env):
    r = env["c"].get("/api/v1/functions/types", headers=env["A"])
    assert r.status_code == 200
    assert [(t["type"], t["label"]) for t in r.json()] == [
        ("end_call", "End Call"), ("transfer_call", "Transfer Call"),
        ("press_digit", "IVR / Press Digit"), ("webhook", "Custom Function"),
    ]
    webhook = next(t for t in r.json() if t["type"] == "webhook")
    assert "url" in webhook["config_schema"]["properties"]
    assert env["c"].get("/api/v1/functions").status_code in (401, 403)
    assert env["c"].post("/api/v1/functions", json=WEBHOOK).status_code in (401, 403)


# ---------------------------------------------------------------- create + secrets
def test_create_masks_header_secret_but_stores_it(env):
    r = create(env)
    assert r.status_code == 201, r.text
    j = r.json()
    assert SECRET not in r.text and j["config"]["headers"]["Authorization"].endswith("5678")
    assert j["config"]["method"] == "POST" and j["enabled"] is True
    stored = env["db"].get(AgentFunction, __import__("uuid").UUID(j["id"]))
    assert stored.config["headers"]["Authorization"] == SECRET  # real value kept for sending
    got = env["c"].get(f"/api/v1/functions/{j['id']}", headers=env["A"])
    assert SECRET not in got.text


@pytest.mark.parametrize("patch", [
    {"name": "bad name!"},
    {"name": "1starts_with_digit"},
    {"type": "nope"},
    {"config": {"url": "http://localhost:8000/x"}},
    {"config": {"url": "http://169.254.169.254/latest"}},
    {"config": {"url": "http://10.0.0.5/x"}},
    {"config": {"url": "http://2130706433/x"}},
    {"config": {"url": "ftp://example.com/x"}},
    {"config": {"url": "https://api.example.com", "headers": {"Bad Name": "v"}}},
    {"config": {"url": "https://api.example.com", "headers": {"X": "a\r\nInjected: 1"}}},
    {"config": {"url": "https://api.example.com", "timeout_seconds": 999}},
    {"config": {"url": "https://api.example.com", "parameters": {"type": "string"}}},
    {"config": {"url": "https://api.example.com", "surprise": 1}},
    {"config": {}},
])
def test_create_validation(env, patch):
    body = {**WEBHOOK, "config": dict(WEBHOOK["config"]), **patch}
    r = create(env, body=body)
    assert r.status_code == 422, r.text
    assert SECRET not in r.text  # errors never echo the secret


def test_other_types(env):
    ok = [
        {"name": "to_sales", "type": "transfer_call", "config": {"phone_number": "+919876543210"}},
        {"name": "hang_up", "type": "end_call", "config": {"message": "Bye!"}},
        {"name": "press_one", "type": "press_digit", "config": {"digits": "1#"}},
    ]
    for body in ok:
        assert create(env, body=body).status_code == 201, body
    assert create(env, body={"name": "bad_tr", "type": "transfer_call", "config": {"phone_number": "9876"}}).status_code == 422
    assert create(env, body={"name": "bad_dg", "type": "press_digit", "config": {"digits": "abc"}}).status_code == 422


def test_duplicate_name_is_case_insensitive(env):
    assert create(env).status_code == 201
    assert create(env, body={**WEBHOOK, "name": "CHECK_ORDER"}).status_code == 400
    assert create(env, who="B").status_code == 201  # other org may reuse the name


def test_only_admins_write(env):
    assert create(env, who="M").status_code == 403
    fid = create(env).json()["id"]
    assert env["c"].get("/api/v1/functions", headers=env["M"]).json()["total"] == 1  # members may read
    assert env["c"].patch(f"/api/v1/functions/{fid}", headers=env["M"], json={"enabled": False}).status_code == 403
    assert env["c"].delete(f"/api/v1/functions/{fid}", headers=env["M"]).status_code == 403


# ---------------------------------------------------------------- tenancy
def test_tenant_isolation(env):
    fid = create(env).json()["id"]
    c = env["c"]
    assert c.get("/api/v1/functions", headers=env["B"]).json()["total"] == 0
    assert c.get(f"/api/v1/functions/{fid}", headers=env["B"]).status_code == 404
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["B"], json={"enabled": False}).status_code == 404
    assert c.delete(f"/api/v1/functions/{fid}", headers=env["B"]).status_code == 404
    assert c.get(f"/api/v1/functions/{fid}", headers=env["A"]).status_code == 200


# ---------------------------------------------------------------- list / search
def test_list_search_filter_paginate(env):
    for n, t, cfg in [("alpha_one", "end_call", {}), ("alpha_two", "press_digit", {"digits": "1"}),
                      ("beta", "end_call", {})]:
        create(env, body={"name": n, "type": t, "config": cfg, "description": "greets people" if n == "beta" else ""})
    g = lambda q: env["c"].get(f"/api/v1/functions{q}", headers=env["A"]).json()
    assert g("")["total"] == 3
    assert {i["name"] for i in g("?search=alpha")["items"]} == {"alpha_one", "alpha_two"}
    assert [i["name"] for i in g("?search=greets")["items"]] == ["beta"]
    assert g("?type=end_call")["total"] == 2
    r = g("?limit=2&offset=2")
    assert r["total"] == 3 and len(r["items"]) == 1


# ---------------------------------------------------------------- update
def test_update_keeps_masked_secret_and_blocks_type_change(env):
    j = create(env).json()
    fid = j["id"]
    c = env["c"]
    # the UI sends back exactly what it received (masked) with a changed timeout
    cfg = {**j["config"], "timeout_seconds": 20}
    r = c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"config": cfg, "description": "  New  "})
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "New" and r.json()["config"]["timeout_seconds"] == 20
    stored = env["db"].get(AgentFunction, __import__("uuid").UUID(fid))
    env["db"].refresh(stored)
    assert stored.config["headers"]["Authorization"] == SECRET  # not overwritten with dots
    # a new real secret replaces the old one
    cfg["headers"] = {"Authorization": "Bearer NEWSECRET9999"}
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"config": cfg}).status_code == 200
    env["db"].refresh(stored)
    assert stored.config["headers"]["Authorization"] == "Bearer NEWSECRET9999"
    # masked value for a header that was never stored
    cfg["headers"] = {"X-New": "••••1234"}
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"config": cfg}).status_code == 422
    # forbidden / invalid changes
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"type": "end_call"}).status_code == 422
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"name": None}).status_code == 422
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"config": {"url": "http://localhost/x"}}).status_code == 422
    # rename collision
    create(env, body={"name": "other", "type": "end_call", "config": {}})
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"name": "OTHER"}).status_code == 400
    assert c.patch(f"/api/v1/functions/{fid}", headers=env["A"], json={"name": "Check_Order"}).status_code == 200  # same fn, new case


# ---------------------------------------------------------------- delete
def test_delete_blocked_while_used_by_agent(env):
    fid = create(env).json()["id"]
    db = env["db"]
    agent = Agent(name="Support", client_id=env["org_a"].id, status="active", functions=[{"id": fid}])
    db.add(agent)
    db.commit()
    r = env["c"].delete(f"/api/v1/functions/{fid}", headers=env["A"])
    assert r.status_code == 409
    assert "Support" in r.text
    agent.functions = []
    db.commit()
    assert env["c"].delete(f"/api/v1/functions/{fid}", headers=env["A"]).status_code == 204
    assert env["c"].get(f"/api/v1/functions/{fid}", headers=env["A"]).status_code == 404


# ---------------------------------------------------------------- url safety unit
@pytest.mark.parametrize("url", [
    "https://example.com/hook", "http://api.example.com:8080/x?y=1", "https://8.8.8.8/x",
    "https://face.be/x",
])
def test_url_ok(url):
    assert check_public_http_url(url)


@pytest.mark.parametrize("url", [
    "http://localhost/x", "http://foo.localhost/x", "http://127.0.0.1/x", "http://[::1]/x",
    "http://[::ffff:127.0.0.1]/x", "http://192.168.1.1/x", "http://172.16.0.1/x",
    "http://169.254.169.254/x", "http://0x7f.1/x", "http://2130706433/x", "http://printer.local/x",
    "http://user:pw@example.com/x", "javascript:alert(1)", "https:///nohost", "http://example.com:99999/x",
])
def test_url_blocked(url):
    with pytest.raises(ValueError):
        check_public_http_url(url)