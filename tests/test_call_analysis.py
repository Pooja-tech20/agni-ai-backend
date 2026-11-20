"""After-call analysis, status labels and transcript download tests."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import functools
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all ORM models
from app.core.security import create_access_token, hash_password
from app.db.session import Base, get_db
from app.main import app
from app.models.agent import Agent
from app.models.call import Call
from app.models.call_message import CallMessage
from app.models.client import Client
from app.models.user import User
from app.services import call_analysis as ca


NOW = datetime.now(timezone.utc)


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


# PostgreSQL JSONB server defaults are not valid SQLite DDL.
for table in Base.metadata.tables.values():
    for column in table.columns:
        if isinstance(column.type, JSONB) and column.server_default is not None:
            column.server_default = None

_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture()
def env():
    Base.metadata.drop_all(_ENGINE)
    Base.metadata.create_all(_ENGINE)

    db = Session()
    org_a = Client(name="Organization A")
    org_b = Client(name="Organization B")
    db.add_all([org_a, org_b])
    db.flush()

    def make_user(email, org):
        user = User(
            email=email,
            hashed_password=hash_password("test-password"),
            first_name="Test",
            last_name="User",
            organization_name=org.name,
            phone_country_code="+91",
            phone_number="9876543210",
            role="admin",
            client_id=org.id,
        )
        db.add(user)
        db.flush()
        return user

    user_a = make_user("analysis-a@example.test", org_a)
    user_b = make_user("analysis-b@example.test", org_b)

    agent = Agent(
        name="Sales Bot",
        client_id=org_a.id,
        status="active",
        llm_model="gpt-4o-mini",
        post_call_extraction={},
    )
    db.add(agent)
    db.flush()

    c1 = Call(
        client_id=org_a.id,
        agent_id=agent.id,
        status="completed",
        direction="inbound",
        channel="web",
        end_reason="user_hangup",
        started_at=NOW,
        ended_at=NOW,
    )
    c2 = Call(
        client_id=org_a.id,
        agent_id=agent.id,
        status="completed",
        direction="inbound",
        channel="web",
        started_at=NOW,
        ended_at=NOW,
    )
    c3 = Call(
        client_id=org_a.id,
        agent_id=agent.id,
        status="in_progress",
        direction="inbound",
        channel="web",
        started_at=NOW,
    )
    db.add_all([c1, c2, c3])
    db.flush()
    db.add_all([
        CallMessage(
            call_id=c1.id,
            role="user",
            content="hi",
            created_at=NOW,
        ),
        CallMessage(
            call_id=c1.id,
            role="agent",
            content="hello",
            created_at=NOW + timedelta(seconds=1),
        ),
    ])
    db.commit()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    def auth_header(user):
        token = create_access_token(str(user.id), user.role)
        return {"Authorization": f"Bearer {token}"}

    client = TestClient(app)
    yield {
        "db": db,
        "c": client,
        "A": auth_header(user_a),
        "B": auth_header(user_b),
        "org_a": org_a,
        "agent": agent,
        "c1": c1,
        "c2": c2,
        "c3": c3,
    }

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(_ENGINE)


class FakeClient:
    def __init__(self, answer):
        self.answer, self.calls = answer, []
        self.responses = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output_text=self.answer)


GOOD = json.dumps({"summary": "Caller asked about pricing and was satisfied.", "sentiment": "positive"})


# ---------------------------------------------------------------- pure helpers
@pytest.mark.parametrize("raw,expected", [
    (GOOD, ("Caller asked about pricing and was satisfied.", "positive")),
    ("```json\n" + GOOD + "\n```", ("Caller asked about pricing and was satisfied.", "positive")),
    ('{"summary": "x", "sentiment": "ANGRY"}', None),
    ('{"summary": "", "sentiment": "neutral"}', None),
    ('{"sentiment": "neutral"}', None),
    ("not json", None), ("[1,2]", None), (None, None),
])
def test_parse_analysis(raw, expected):
    assert ca.parse_analysis(raw) == expected


def test_summary_is_capped_and_long_transcripts_keep_the_end():
    long = json.dumps({"summary": "a" * 5000, "sentiment": "neutral"})
    assert len(ca.parse_analysis(long)[0]) == ca.MAX_SUMMARY_CHARS
    text = ca.build_transcript_text([("user", "x" * 9000), ("agent", "y" * 9000), ("user", "THE END")])
    assert len(text) < ca.MAX_TRANSCRIPT_CHARS + 100 and text.endswith("THE END") and "omitted" in text


# ---------------------------------------------------------------- service
def run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_analyze_saves_summary_and_sentiment(env):
    client = FakeClient(GOOD)
    assert run(ca.analyze_call(env["c1"].id, client=client, session_factory=Session)) is True
    saved = Session().get(Call, env["c1"].id)
    assert saved.sentiment == "positive" and saved.summary.startswith("Caller asked") and saved.analyzed_at
    sent = client.calls[0]["input"]
    assert "Caller: hi" in sent and "Agent: hello" in sent


def test_second_run_is_skipped_unless_forced(env):
    client = FakeClient(GOOD)
    run(ca.analyze_call(env["c1"].id, client=client, session_factory=Session))
    run(ca.analyze_call(env["c1"].id, client=client, session_factory=Session))
    assert len(client.calls) == 1
    run(ca.analyze_call(env["c1"].id, force=True, client=client, session_factory=Session))
    assert len(client.calls) == 2


def test_failures_return_false_and_never_raise(env, monkeypatch):
    assert run(ca.analyze_call(env["c1"].id, client=FakeClient("garbage"), session_factory=Session)) is False
    assert Session().get(Call, env["c1"].id).sentiment is None

    async def boom(**kw):
        raise RuntimeError("openai is down")
    broken = SimpleNamespace(responses=SimpleNamespace(create=boom))
    assert run(ca.analyze_call(env["c1"].id, client=broken, session_factory=Session)) is False
    assert run(ca.analyze_call(env["c2"].id, client=FakeClient(GOOD), session_factory=Session)) is False
    assert run(ca.analyze_call(uuid.uuid4(), client=FakeClient(GOOD), session_factory=Session)) is False

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert run(ca.analyze_call(env["c1"].id, session_factory=Session)) is False


# ---------------------------------------------------------------- API
def test_list_rows_have_status_and_tooltip_text(env):
    response = env["c"].get("/api/v1/calls", headers=env["A"])
    assert response.status_code == 200
    first = next(
        item for item in response.json()["items"]
        if item["id"] == str(env["c1"].id)
    )
    assert first["status_label"] == "Completed"
    assert first["end_reason_label"] == "User Hangup"
    assert "caller ended" in first["end_reason_help"]
    assert first["summary"] is None and first["analyzed"] is False


def test_analyze_endpoint(env, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.calls.analyze_call",
        functools.partial(ca.analyze_call, client=FakeClient(GOOD), session_factory=Session),
    )
    url = f"/api/v1/calls/{env['c1'].id}/analyze"
    response = env["c"].post(url, headers=env["A"])
    assert response.status_code == 200, response.text
    assert response.json()["sentiment"] == "positive" and response.json()["analyzed"] is True
    assert env["c"].get("/api/v1/calls", params={"sentiment": "positive"}, headers=env["A"]).json()["total"] == 1

    assert env["c"].post(url, headers=env["B"]).status_code == 404
    assert env["c"].post(f"/api/v1/calls/{env['c3'].id}/analyze", headers=env["A"]).status_code == 409
    assert env["c"].post(f"/api/v1/calls/{env['c2'].id}/analyze", headers=env["A"]).status_code == 422
    assert env["c"].post(url).status_code in (401, 403)


def test_analyze_unavailable_returns_503(env, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.calls.analyze_call",
        functools.partial(ca.analyze_call, client=FakeClient("garbage"), session_factory=Session),
    )
    assert env["c"].post(f"/api/v1/calls/{env['c1'].id}/analyze", headers=env["A"]).status_code == 503


def test_transcript_download(env):
    txt = env["c"].get(f"/api/v1/calls/{env['c1'].id}/transcript", headers=env["A"])
    assert txt.status_code == 200 and "attachment" in txt.headers["content-disposition"]
    assert "Caller: hi" in txt.text and "Agent: hello" in txt.text and txt.text.index("hi") < txt.text.index("hello")
    js = env["c"].get(
        f"/api/v1/calls/{env['c1'].id}/transcript",
        params={"format": "json"},
        headers=env["A"],
    ).json()
    assert [m["role"] for m in js["messages"]] == ["Caller", "Agent"] and js["agent"] == "Sales Bot"
    assert env["c"].get(f"/api/v1/calls/{env['c1'].id}/transcript", headers=env["B"]).status_code == 404
    assert env["c"].get(
        f"/api/v1/calls/{env['c1'].id}/transcript",
        params={"format": "pdf"},
        headers=env["A"],
    ).status_code == 422
