"""End-to-end checks over the real app: onboarding -> search -> tailor -> gate -> send -> memory."""
from __future__ import annotations

import io
import json
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "test")
os.makedirs(TMP, exist_ok=True)
# ponytail: one reused test DB — deleting the file while a run thread holds it is what breaks
os.environ.setdefault("PLACEPILOT_DB", os.path.join(TMP, "test.db"))

from app import core, db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """The suite must never touch the network or a developer's .env keys.

    Without this, a configured OPENROUTER/ADZUNA key turns unit tests into live calls:
    slow, flaky, and it would bill the user.
    """
    for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
                "PLACEPILOT_LLM", "PLACEPILOT_JOBS", "PLACEPILOT_MODEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PLACEPILOT_LLM", "off")
    monkeypatch.setenv("PLACEPILOT_JOBS", "mock")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def student(client):
    sid = client.post("/api/students").json()["id"]
    c = client
    c.headers["X-Student-Id"] = sid
    return sid


def wait(client, run_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


# ------------------------------------------------------------------ parsing / scoring

def test_parse_resume_keeps_contact_and_sections():
    text = (
        "Aarav Mehta\naarav@example.com · +91 98765 43210 · Pune, Maharashtra\n"
        "SUMMARY\nFinal-year B.Tech student building ML projects.\n"
        "EXPERIENCE\n• Data Intern, Acme — built a churn model in Python\n"
        "SKILLS\nPython, SQL, pandas\n"
    )
    contact, facts = core.parse_resume(text)
    assert contact == {"name": "Aarav Mehta", "email": "aarav@example.com",
                       "phone": "+91 98765 43210", "location": "Pune"}
    kinds = {f["kind"] for f in facts}
    assert {"experience", "skill"} <= kinds
    assert any("python" in f["skills"] for f in facts)


def test_fit_score_is_deterministic_and_explainable():
    job = {"required_json": '["python","sql","tableau"]', "nice_json": '["docker"]',
           "tags_json": '["ai","ml"]', "location": "Pune", "remote": 0, "seniority": "intern",
           "posted_at": db.today().isoformat(), "apply_by": (db.today()).isoformat()}
    stud = {"roles": ["ai"], "locations": ["Pune"], "seniority": "intern", "remote_ok": 1}
    a = core.fit_score(job, stud, ["python", "sql", "docker"], db.today())
    b = core.fit_score(job, stud, ["python", "sql", "docker"], db.today())
    assert a == b
    assert 0 <= a["score"] <= 100
    assert "tableau" in a["gaps"]
    assert a["must_matches"] == ["python", "sql"]


def test_grounding_rejects_skills_outside_facts():
    facts = [{"id": "f1", "kind": "experience", "text": "Built a churn model in Python", "verified": 1,
              "skills": ["python"], "sort_order": 0}]
    job = {"title": "ML Intern", "company": "Acme", "required_json": '["kubernetes"]', "nice_json": "[]"}
    student = {"name": "A"}
    docs = core.build_docs(facts, job, student)
    assert "kubernetes" in docs["not_claimed"]
    assert "kubernetes" not in docs["resume"]["text"].lower()
    assert core.validate_grounding(docs, facts, job)["passed"]

    tainted = {"resume": {"sections": {"Summary": [{"text": "Expert in Kubernetes", "fact_ids": ["f1"],
                                                    "section": "summary"}]},
                          "text": "Expert in Kubernetes"}, "cover": {"text": "", "paragraphs": []},
               "not_claimed": []}
    result = core.validate_grounding(tainted, facts, job)
    assert not result["passed"]
    assert any("kubernetes" in p["claim"] for p in result["problems"])


def test_ics_folds_long_lines_and_has_alarm():
    ics = core.make_ics([{"uid": "app_1", "date": "2026-12-01",
                          "summary": "Apply: " + "Very Long Title " * 12, "description": "x"}])
    assert ics.startswith("BEGIN:VCALENDAR")
    assert "DTSTART;VALUE=DATE:20261201" in ics
    assert "BEGIN:VALARM" in ics
    assert all(len(line) <= 75 for line in ics.split("\r\n"))
    assert "\r\n " in ics  # folded


# ------------------------------------------------------------------ flows

def test_onboarding_sample_creates_verified_facts(client, student):
    res = client.post("/api/onboarding/sample")
    assert res.status_code == 200, res.text
    facts = client.get("/api/students/me").json()["facts"]
    assert len(facts) >= 10
    assert all(f["verified"] == 1 for f in facts)


def test_search_run_traces_every_step_and_replans(client, student):
    client.patch("/api/students/me", json={"roles": ["ai"], "locations": ["Pune"], "seniority": "intern"})
    run = client.post("/api/runs", json={"command": "find 10 AI/ML internships in Pune"}).json()
    body = wait(client, run["run_id"])
    assert body["status"] == "done", body
    phases = [e["phase"] for e in body["events"]]
    assert {"plan", "act", "observe", "verify", "done"} <= set(phases)
    calls = client.get(f"/api/runs/{run['run_id']}")  # events persist
    assert calls.status_code == 200
    assert len(body["outcome"]["applications"]) == 10
    assert body["outcome"]["attempts"] >= 1
    if body["outcome"]["attempts"] > 1:
        assert any("revising the plan" in e["title"] for e in body["events"])


def test_tailor_produces_grounded_bundle_and_pending_approval(client, student):
    apps = client.get("/api/applications").json()["applications"][:2]
    ids = [a["id"] for a in apps]
    run = client.post("/api/applications", json={"job_ids": []})  # no-op guard for shape
    assert run.status_code in (200, 400, 409)
    tailor = client.post(f"/api/applications/{ids[0]}/regenerate").json()
    body = wait(client, tailor["run_id"])
    assert body["status"] == "done", body
    detail = client.get(f"/api/applications/{ids[0]}").json()
    assert detail["docs"]["resume"]["passed"] is True
    assert detail["approval"]["status"] == "pending"
    assert detail["docs"]["resume"]["content"]["sections"]
    # every resume bullet traces to a fact
    for items in detail["docs"]["resume"]["content"]["sections"].values():
        for item in items:
            assert item["fact_ids"]


def test_send_is_blocked_with_422_until_approved(client, student):
    app_id = client.get("/api/applications").json()["applications"][0]["id"]
    blocked = client.post(f"/api/applications/{app_id}/send")
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "approval_required"
    assert "approve" in blocked.json()["error"]["hint"].lower()

    detail = client.get(f"/api/applications/{app_id}").json()
    bh = detail["approval"]["bundle_hash"]
    approved = client.post(f"/api/applications/{app_id}/approvals",
                           json={"decision": "approve", "bundle_hash": bh, "confirm": True})
    assert approved.status_code == 200, approved.text
    sent = client.post(f"/api/applications/{app_id}/send")
    assert sent.status_code == 200, sent.text
    assert sent.json()["channel"] == "demo-outbox"
    again = client.post(f"/api/applications/{app_id}/send")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_sent"


def test_database_trigger_blocks_unapproved_insert(client, student):
    app_id = client.get("/api/applications").json()["applications"][0]["id"]
    conn = db.connect()
    try:
        with pytest.raises(Exception) as exc:
            conn.execute("INSERT INTO outbox(id,application_id,approval_id,bundle_hash) "
                         "VALUES('out_x',?,'apr_fake','bndl_fake')", (app_id,))
            conn.commit()
        assert "approval_required" in str(exc.value)
    finally:
        conn.close()


def test_editing_a_fact_makes_an_approved_bundle_stale(client, student):
    sid = client.post("/api/students").json()["id"]
    h = {"X-Student-Id": sid}
    client.post("/api/onboarding/sample", headers=h)
    client.patch("/api/students/me", headers=h, json={"roles": ["ai"], "locations": ["Pune"]})
    run = client.post("/api/runs", headers=h, json={"command": "find 1 ai internship in Pune"}).json()
    for _ in range(200):
        body = client.get(f"/api/runs/{run['run_id']}", headers=h).json()
        if body["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    app_id = body["outcome"]["applications"][0]["application_id"]
    regen = client.post(f"/api/applications/{app_id}/regenerate", headers=h).json()
    for _ in range(200):
        r = client.get(f"/api/runs/{regen['run_id']}", headers=h).json()
        if r["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    detail = client.get(f"/api/applications/{app_id}", headers=h).json()
    approved = client.post(f"/api/applications/{app_id}/approvals", headers=h,
                           json={"decision": "approve", "confirm": True,
                                 "bundle_hash": detail["approval"]["bundle_hash"]})
    assert approved.status_code == 200, approved.text

    fact = client.get("/api/students/me", headers=h).json()["facts"][0]
    client.patch(f"/api/facts/{fact['id']}", headers=h, json={"text": fact["text"] + " (edited)"})
    regen2 = client.post(f"/api/applications/{app_id}/regenerate", headers=h).json()
    for _ in range(200):
        r = client.get(f"/api/runs/{regen2['run_id']}", headers=h).json()
        if r["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    stale = client.post(f"/api/applications/{app_id}/send", headers=h)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "approval_stale"


def test_interview_scores_topics_and_reopens_weak_ones(client, student):
    first = client.post("/api/interviews", json={"role": "AI/ML Intern", "language": "en"}).json()
    assert len(first["questions"]) == 6
    for q in first["questions"]:
        client.post(f"/api/interviews/{first['interview_id']}/answers",
                    json={"question_id": q["id"], "text": "I do not know this topic at all."})
    done = client.post(f"/api/interviews/{first['interview_id']}/complete").json()
    assert done["weak"], "all-blank answers should surface weak topics"

    second = client.post("/api/interviews", json={"role": "AI/ML Intern", "language": "en"}).json()
    reopened = [q for q in second["questions"] if "Reopened" in q["provenance"]]
    assert reopened, second["questions"]
    assert any(t in q["provenance"].lower() for q in reopened for t in done["weak"])


def test_hindi_questions_are_served_in_hindi(client, student):
    intv = client.post("/api/interviews", json={"role": "AI/ML Intern", "language": "hi"}).json()
    detail = client.get(f"/api/interviews/{intv['interview_id']}").json()
    assert any(any("\u0900" <= ch <= "\u097f" for ch in q["text"]) for q in detail["questions"])


def test_delete_removes_every_row_for_the_student(client):
    sid = client.post("/api/students").json()["id"]
    h = {"X-Student-Id": sid}
    client.post("/api/onboarding/sample", headers=h)
    client.patch("/api/students/me", headers=h, json={"roles": ["ai"], "locations": ["Pune"]})
    run = client.post("/api/runs", headers=h, json={"command": "find 2 ai internships"}).json()
    for _ in range(200):
        b = client.get(f"/api/runs/{run['run_id']}", headers=h).json()
        if b["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    deleted = client.delete("/api/students/me", headers=h).json()
    assert sum(deleted["remaining"].values()) == 0
    assert deleted["fk_violations"] == 0
    assert client.get("/api/students/me", headers=h).status_code == 404
