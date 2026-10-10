"""After-call analysis, status labels and transcript download."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import functools
import json
import uuid
from types import SimpleNamespace

import pytest

from app.models.call import Call
from app.services import call_analysis as ca
from tests.test_calls import NOW, Session, env  # noqa: F401  (env is a fixture)


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
    ('{"summary": "x", "sentiment": "ANGRY"}', None),       # not an allowed value
    ('{"summary": "", "sentiment": "neutral"}', None),      # empty summary
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
    return asyncio.new_event_loop().run_until_complete(coro)


def test_analyze_saves_summary_and_sentiment(env):
    client = FakeClient(GOOD)
    assert run(ca.analyze_call(env["c1"].id, client=client, session_factory=Session)) is True
    saved = Session().get(Call, env["c1"].id)
    assert saved.sentiment == "positive" and saved.summary.startswith("Caller asked") and saved.analyzed_at
    sent = client.calls[0]["input"]
    assert "Caller: hi" in sent and "Agent: hello" in sent       # roles are labelled


def test_second_run_is_skipped_unless_forced(env):
    client = FakeClient(GOOD)
    run(ca.analyze_call(env["c1"].id, client=client, session_factory=Session))
    run(ca.analyze_call(env["c1"].id, client=client, session_factory=Session))
    assert len(client.calls) == 1
    run(ca.analyze_call(env["c1"].id, force=True, client=client, session_factory=Session))
    assert len(client.calls) == 2


def test_failures_return_false_and_never_raise(env, monkeypatch):
    assert run(ca.analyze_call(env["c1"].id, client=FakeClient("garbage"), session_factory=Session)) is False
    assert Session().get(Call, env["c1"].id).sentiment is None            # nothing half-saved

    async def boom(**kw):
        raise RuntimeError("openai is down")
    broken = SimpleNamespace(responses=SimpleNamespace(create=boom))
    assert run(ca.analyze_call(env["c1"].id, client=broken, session_factory=Session)) is False
    assert run(ca.analyze_call(env["c2"].id, client=FakeClient(GOOD), session_factory=Session)) is False  # no transcript
    assert run(ca.analyze_call(uuid.uuid4(), client=FakeClient(GOOD), session_factory=Session)) is False

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert run(ca.analyze_call(env["c1"].id, session_factory=Session)) is False  # no key -> skipped


# ---------------------------------------------------------------- API
def test_list_rows_have_status_and_tooltip_text(env):
    first = env["c"].get("/api/v1/calls", headers=env["A"]).json()["items"][0]
    assert first["status_label"] == "Completed"
    assert first["end_reason_label"] == "User Hangup" and "caller ended" in first["end_reason_help"]
    assert first["summary"] is None and first["analyzed"] is False


def test_analyze_endpoint(env, monkeypatch):
    monkeypatch.setattr("app.api.v1.calls.analyze_call",
                        functools.partial(ca.analyze_call, client=FakeClient(GOOD), session_factory=Session))
    url = f"/api/v1/calls/{env['c1'].id}/analyze"
    r = env["c"].post(url, headers=env["A"])
    assert r.status_code == 200, r.text
    assert r.json()["sentiment"] == "positive" and r.json()["analyzed"] is True
    # it now shows up in the list and the sentiment filter works
    assert env["c"].get("/api/v1/calls", params={"sentiment": "positive"}, headers=env["A"]).json()["total"] == 1

    assert env["c"].post(url, headers=env["B"]).status_code == 404                      # other organization
    assert env["c"].post(f"/api/v1/calls/{env['c3'].id}/analyze", headers=env["A"]).status_code == 409   # in progress
    assert env["c"].post(f"/api/v1/calls/{env['c2'].id}/analyze", headers=env["A"]).status_code == 422   # no transcript
    assert env["c"].post(url).status_code in (401, 403)


def test_analyze_unavailable_returns_503(env, monkeypatch):
    monkeypatch.setattr("app.api.v1.calls.analyze_call",
                        functools.partial(ca.analyze_call, client=FakeClient("garbage"), session_factory=Session))
    assert env["c"].post(f"/api/v1/calls/{env['c1'].id}/analyze", headers=env["A"]).status_code == 503


def test_transcript_download(env):
    txt = env["c"].get(f"/api/v1/calls/{env['c1'].id}/transcript", headers=env["A"])
    assert txt.status_code == 200 and "attachment" in txt.headers["content-disposition"]
    assert "Caller: hi" in txt.text and "Agent: hello" in txt.text and txt.text.index("hi") < txt.text.index("hello")
    js = env["c"].get(f"/api/v1/calls/{env['c1'].id}/transcript", params={"format": "json"}, headers=env["A"]).json()
    assert [m["role"] for m in js["messages"]] == ["Caller", "Agent"] and js["agent"] == "Sales Bot"
    assert env["c"].get(f"/api/v1/calls/{env['c1'].id}/transcript", headers=env["B"]).status_code == 404
    assert env["c"].get(f"/api/v1/calls/{env['c1'].id}/transcript", params={"format": "pdf"}, headers=env["A"]).status_code == 422