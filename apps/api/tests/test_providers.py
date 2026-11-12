"""Provider contract tests: no API keys, no network.

Every outbound call goes through providers.http_json / the injected transport, so these
prove the adapters' behaviour exactly. Live-key verification is the one thing this file
cannot do — see docs/limitations.md.
"""
from __future__ import annotations

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("PLACEPILOT_DB", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "test", "providers.db"))

from app import agent, providers  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch):
    """No test may inherit a provider or key from another test or the developer's shell."""
    for key in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                "PLACEPILOT_LLM", "PLACEPILOT_JOBS", "PLACEPILOT_MODEL"):
        monkeypatch.delenv(key, raising=False)
    # belt and braces: no test may reach the network even if a key leaks back in
    monkeypatch.setattr(providers, "http_json", _no_network)
    monkeypatch.setattr(providers, "FREE_MODELS", [])
    yield


def _no_network(url, **kwargs):
    raise AssertionError(f"test attempted a real network call: {url}")


@pytest.fixture()
def anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PLACEPILOT_LLM", "anthropic")
    return "anthropic"


@pytest.fixture()
def adzuna(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    return "adzuna"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def make_student(client):
    sid = client.post("/api/students").json()["id"]
    client.headers["X-Student-Id"] = sid
    client.post("/api/onboarding/sample")
    client.patch("/api/students/me", json={"roles": ["ai"], "locations": ["Pune"]})
    return sid


def wait(client, run_id, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


# ---------------------------------------------------------------- mode selection

def test_no_keys_means_mock_and_no_llm(monkeypatch):
    for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert providers.jobs_mode() == "mock"
    assert providers.llm_mode() == "off"
    assert not providers.llm_available()


def test_keys_present_selects_them(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert providers.jobs_mode() == "adzuna"
    assert providers.llm_available()
    # explicit off wins over the presence of a key
    monkeypatch.setenv("PLACEPILOT_LLM", "off")
    assert providers.llm_mode() == "off"


def test_adzuna_requested_without_keys_falls_back(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.setenv("PLACEPILOT_JOBS", "adzuna")
    assert providers.jobs_mode() == "mock"
    with pytest.raises(providers.ProviderError):
        providers.adzuna_search("ml intern")


# ---------------------------------------------------------------- adzuna mapping

def test_adzuna_maps_response_into_internal_job_shape(adzuna, monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")

    captured = {}

    def fake_transport(url):
        captured["url"] = url
        return {"results": [{
            "id": "12345",
            "title": "Machine Learning Intern",
            "company": {"display_name": "Northwind Labs"},
            "location": {"display_name": "Pune, Maharashtra"},
            "description": "<p>Python, SQL and scikit-learn. Remote friendly.</p>",
            "redirect_url": "https://example.com/job/12345",
            "created": "2026-11-01T09:00:00Z",
        }]}

    jobs = providers.adzuna_search("ml intern", "Pune", transport=fake_transport)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "adzuna" and job["id"] == "adz_12345"
    assert job["company"] == "Northwind Labs"
    assert job["posted_at"] == "2026-11-01"
    assert "<p>" not in job["description"]
    assert "python" in json.loads(job["required_json"])
    assert job["seniority"] == "intern"
    # credentials and query actually went into the request
    assert "app_id=id" in captured["url"] and "what=ml+intern" in captured["url"]


def test_adzuna_http_failure_degrades_to_seed_set(adzuna, monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")

    def boom(url, **kw):
        raise providers.ProviderError("HTTP 429 rate limited")

    monkeypatch.setattr(providers, "http_json", boom)

    class Conn:
        def execute(self, *a, **k):
            class R:
                def __init__(self, rows):
                    self.rows = rows

                def __iter__(self):
                    return iter(self.rows)

            return R([{"id": "job_mock_001", "source": "mock"}])

    jobs, meta = providers.merge_jobs(Conn(), "ml", "Pune", 5)
    assert meta["source"] == "mock"
    assert "adzuna_unavailable" in meta["fallback"]
    assert jobs  # seed set still usable


def test_live_jobs_get_persisted_and_used(adzuna, monkeypatch, client):
    make_student(client)
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setenv("PLACEPILOT_LLM", "off")

    def fake_transport(url, **kw):
        return {"results": [{
            "id": "live-1", "title": "AI Intern", "company": {"display_name": "Deccan Cloud"},
            "location": {"display_name": "Pune"}, "description": "Python and pandas work.",
            "redirect_url": "https://example.com/live-1", "created": "2026-11-09T00:00:00Z",
        }]}

    monkeypatch.setattr(providers, "http_json", fake_transport)
    run = client.post("/api/runs", json={"command": "find 5 ai internships in Pune"}).json()
    body = wait(client, run["run_id"])
    assert body["status"] == "done", body
    obs = [e for e in body["events"] if e["tool"] == "search_jobs"][0]
    assert obs["payload"]["source"] == "adzuna+mock"
    assert any("Deccan Cloud" == a["job"]["company"] for a in body["outcome"]["applications"])


# ---------------------------------------------------------------- llm planner

def test_parse_plan_accepts_tool_use_and_json_text():
    tool_use = {"content": [{"type": "tool_use", "name": "search_jobs", "input": {"roles": ["ai"]}}]}
    assert providers.parse_plan(tool_use) == {"tool": "search_jobs", "args": {"roles": ["ai"]}}

    as_text = {"content": [{"type": "text", "text": '```json\n{"tool":"rank_jobs","args":{"limit":3}}\n```'}]}
    assert providers.parse_plan(as_text)["tool"] == "rank_jobs"

    done = {"content": [{"type": "text", "text": '{"done": true, "summary": "ranked"}'}]}
    assert providers.parse_plan(done)["done"] is True


# ---------------------------------------------------------------- openrouter

def test_openrouter_plan_from_tool_calls():
    payload = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "search_jobs", "arguments": '{"roles":["ai"]}'}}]}}]}
    assert providers.parse_openrouter_plan(payload) == {"tool": "search_jobs", "args": {"roles": ["ai"]}}


def test_openrouter_plan_from_json_content():
    payload = {"choices": [{"message": {"content": '{"done": true, "summary": "ok"}'}}]}
    assert providers.parse_openrouter_plan(payload)["done"] is True


@pytest.mark.parametrize("bad", [
    {},
    {"choices": []},
    {"choices": [{"message": {"content": "I refuse."}}]},
    {"choices": [{"message": {"tool_calls": [{"function": {"name": "x", "arguments": "{bad json"}}]}}]},
])
def test_openrouter_plan_rejects_malformed(bad):
    with pytest.raises(providers.ProviderError):
        providers.parse_openrouter_plan(bad)


def test_openrouter_key_selects_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("PLACEPILOT_LLM", raising=False)
    assert providers.llm_mode() == "openrouter"
    # an explicit anthropic request without that key is off, not silently openrouter
    monkeypatch.setenv("PLACEPILOT_LLM", "anthropic")
    assert providers.llm_mode() == "off"


def test_openrouter_request_shape(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("PLACEPILOT_MODEL", "test/free-model:free")
    seen = {}

    def fake(url, *, method="GET", headers=None, body=None, timeout=20.0):
        seen.update({"url": url, "headers": headers, "body": body})
        return {"choices": [{"message": {"content": '{"done": true, "summary": "x"}'}}]}

    providers.plan_step([{"role": "user", "content": "go"}], agent.tool_specs(), transport=fake)
    assert seen["url"] == providers.OPENROUTER_URL
    assert seen["headers"]["Authorization"] == "Bearer sk-or-test"
    assert seen["body"]["messages"][0]["role"] == "system"
    assert seen["body"]["tools"][0]["type"] == "function"


def test_openrouter_falls_back_across_models(monkeypatch):
    """A 429 on one free model must not end the run."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    attempted = []

    def fake(url, *, method="GET", headers=None, body=None, timeout=20.0):
        attempted.append(body["model"])
        if len(attempted) == 1:
            raise providers.ProviderError("HTTP 429 Too Many Requests")
        return {"choices": [{"message": {"content": '{"done": true}'}}]}

    monkeypatch.setattr(providers, "FREE_MODELS", ["first:free", "second:free"])
    monkeypatch.setattr(providers, "_LLM_PREFERENCE", [])
    plan = providers.plan_step([{"role": "user", "content": "go"}], agent.tool_specs(), transport=fake)
    assert plan["done"] is True
    assert attempted == ["first:free", "second:free"]


def test_env_file_loader_does_not_override_real_env(tmp_path, monkeypatch):
    from app import config

    env = tmp_path / ".env"
    env.write_text("PLACEPILOT_LLM=openrouter\nSOME_NEW_KEY=abc\n# comment\n\n", encoding="utf8")
    monkeypatch.setattr(config, "CANDIDATES", [env])
    monkeypatch.setenv("PLACEPILOT_LLM", "off")
    monkeypatch.delenv("SOME_NEW_KEY", raising=False)
    config.load_env()
    assert os.environ["PLACEPILOT_LLM"] == "off"   # real env wins
    assert os.environ["SOME_NEW_KEY"] == "abc"     # missing value filled in


@pytest.mark.parametrize("bad", [
    {"content": []},
    {"content": [{"type": "text", "text": "I cannot do that."}]},
    {"nope": 1},
    {"content": [{"type": "tool_use", "name": "search_jobs", "input": "not-a-dict"}]},
])
def test_parse_plan_rejects_malformed(bad):
    with pytest.raises(providers.ProviderError):
        providers.parse_plan(bad)


def test_plan_step_sends_tools_and_key(anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = {}

    def fake(url, *, method="GET", headers=None, body=None, timeout=20.0):
        seen.update({"url": url, "method": method, "headers": headers, "body": body})
        return {"content": [{"type": "tool_use", "name": "search_jobs", "input": {}}]}

    out = providers.plan_step([{"role": "user", "content": "go"}], agent.tool_specs(), transport=fake)
    assert out["tool"] == "search_jobs"
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"]
    names = [t["name"] for t in seen["body"]["tools"]]
    assert "send_application" in names  # exposed but always guard-blocked
    assert "delete_student_data" not in names


def test_llm_planner_drives_a_real_run(anthropic, monkeypatch, client):
    make_student(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PLACEPILOT_LLM", "anthropic")
    monkeypatch.setenv("PLACEPILOT_JOBS", "mock")

    script = iter([
        {"content": [{"type": "tool_use", "name": "search_jobs",
                      "input": {"roles": ["ai"], "locations": ["Pune"], "recency_days": 90}}]},
        {"content": [{"type": "text", "text": '{"done": true, "summary": "done"}'}]},
    ])

    def fake(url, **kw):
        return next(script)

    monkeypatch.setattr(providers, "http_json", fake)
    run = client.post("/api/runs", json={"command": "find 3 ai internships in Pune"}).json()
    body = wait(client, run["run_id"])
    assert body["status"] == "done", body
    assert body["outcome"]["planner"] == "anthropic"
    tools_called = [c for c in body["events"] if c["tool"]]
    assert any(e["tool"] == "search_jobs" for e in tools_called)


def test_llm_planner_failure_falls_back_with_a_visible_trace(anthropic, monkeypatch, client):
    make_student(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PLACEPILOT_LLM", "anthropic")

    def down(url, **kw):
        raise providers.ProviderError("HTTP 500 upstream exploded")

    monkeypatch.setattr(providers, "http_json", down)
    run = client.post("/api/runs", json={"command": "find 3 ai internships in Pune"}).json()
    body = wait(client, run["run_id"])
    assert body["status"] == "done", body
    phases = [(e["tool"], e["title"]) for e in body["events"]]
    assert any(t == "planner_fallback" for t, _ in phases)
    assert body["outcome"]["planner"] == "deterministic"


def test_llm_cannot_invent_a_tool(anthropic, monkeypatch, client):
    make_student(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PLACEPILOT_LLM", "anthropic")

    def fake(url, **kw):
        return {"content": [{"type": "tool_use", "name": "wire_money_to_self", "input": {}}]}

    monkeypatch.setattr(providers, "http_json", fake)
    run = client.post("/api/runs", json={"command": "find 3 ai internships"}).json()
    body = wait(client, run["run_id"])
    # unknown tool is rejected, then the deterministic planner completes the run
    assert any("unknown tool" in e["title"].lower() for e in body["events"])
    assert body["status"] == "done"
    assert body["outcome"]["planner"] == "deterministic"


def test_llm_send_attempt_still_blocked_by_approval(anthropic, monkeypatch, client):
    """The tool the model most wants to abuse must still hit the 422."""
    sid = make_student(client)
    run = client.post("/api/runs", json={"command": "find 1 ai internship in Pune"}).json()
    body = wait(client, run["run_id"])
    app_id = body["outcome"]["applications"][0]["application_id"]

    conn = __import__("app.db", fromlist=["connect"]).connect()
    try:
        tk = agent.Toolkit(agent.Run(conn, "probe", sid, "", "send"))
        from app.errors import ApiError
        with pytest.raises(ApiError) as exc:
            tk.send_application(app_id)
        assert exc.value.status == 422
        assert exc.value.code == "approval_required"
        # scoped to this application: other tests in the session may have sent their own
        assert conn.execute("SELECT COUNT(*) c FROM outbox WHERE application_id=?",
                            (app_id,)).fetchone()["c"] == 0
    finally:
        conn.close()
