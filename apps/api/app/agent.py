"""Agent loop: plan -> act -> observe -> verify -> memory. Deterministic by default.

Every tool call is persisted (args, result, status, duration) and every step
becomes a run_event the UI polls. The LLM planner is optional and shares the
same tool registry, so it can never exceed these powers.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import timedelta

from . import core, db

# ---------------------------------------------------------------- goal parsing

ROLE_WORDS = {
    "ai": "ai", "ml": "ai", "machine learning": "ai", "deep learning": "ai",
    "data science": "data science", "data analyst": "data", "analytics": "data",
    "backend": "backend", "frontend": "frontend", "full stack": "fullstack",
    "fullstack": "fullstack", "product": "product", "mlops": "platform",
}
CITIES = ["pune", "mumbai", "bengaluru", "bangalore", "hyderabad", "delhi", "chennai", "remote"]


def parse_goal(command: str) -> dict:
    c = (command or "").lower()
    count = re.search(r"\b(\d{1,2})\b", c)
    goal = {
        "count": min(int(count.group(1)), 15) if count else 8,
        "roles": [],
        "locations": [],
        "recency_days": 60,
        "intent": "search",
    }
    for word, role in ROLE_WORDS.items():
        if word in c and role not in goal["roles"]:
            goal["roles"].append(role)
    for city in CITIES:
        if city in c and (norm := ("Remote" if city == "remote" else city.capitalize())) not in goal["locations"]:
            goal["locations"].append(norm)
    if "week" in c:
        goal["recency_days"] = 7
    elif "month" in c:
        goal["recency_days"] = 30
    if re.search(r"interview|practi[cs]e|mock", c):
        goal["intent"] = "interview"
    elif re.search(r"deadline|remind|this week", c):
        goal["intent"] = "week_plan"
    elif re.search(r"apply|send", c):
        goal["intent"] = "apply_plan"
    elif re.search(r"tailor|prepare", c):
        goal["intent"] = "tailor"
    return goal


# ---------------------------------------------------------------- run plumbing

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Run:
    def __init__(self, conn, run_id: str, student_id: str, command: str, kind: str):
        self.conn = conn
        self.id = run_id
        self.student_id = student_id
        self.command = command
        self.kind = kind
        self.seq = 0
        self.cancelled = False

    def event(self, phase: str, tool: str, title: str, detail: str, status="ok", payload=None) -> dict:
        self.seq += 1
        ev = {
            "seq": self.seq, "run_id": self.id, "phase": phase, "tool": tool, "status": status,
            "title": title, "detail": detail, "payload": payload or {}, "created_at": db.iso(),
        }
        self.conn.execute(
            "INSERT INTO run_events(run_id,seq,phase,tool,title,detail,status,payload_json,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (self.id, self.seq, phase, tool, title, detail, status, json.dumps(ev["payload"]), ev["created_at"]),
        )
        self.conn.commit()
        return ev

    def call(self, tool: str, args: dict, fn):
        """One audited tool call: timing, status, persisted args/result."""
        started = time.perf_counter()
        try:
            result = fn(**args)
            status, error = "ok", None
        except Exception as exc:  # tool failures become observations, never crashes
            result, status, error = None, "error", str(exc)
        ms = int((time.perf_counter() - started) * 1000)
        self.conn.execute(
            "INSERT INTO tool_calls(run_id,student_id,tool,args_json,result_json,status,error,duration_ms,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (self.id, self.student_id, tool, json.dumps(args, default=str)[:4000],
             json.dumps(result, default=str)[:20000], status, error, ms, db.iso()),
        )
        self.conn.commit()
        return result, status, ms


# ---------------------------------------------------------------- tools

def tool_specs() -> list[dict]:
    return [
        {"name": "load_memory", "risk": "read", "detail": "Roles, verified facts, weak topics, past runs"},
        {"name": "search_jobs", "risk": "read", "detail": "Search listings, exclude expired, honour filters"},
        {"name": "score_fit", "risk": "read", "detail": "Explainable 0-100 fit with reasons and gaps"},
        {"name": "rank_jobs", "risk": "read", "detail": "Stable ordering, dedupe, top N"},
        {"name": "read_facts", "risk": "read", "detail": "Verified facts snapshot + facts hash"},
        {"name": "draft_docs", "risk": "write", "detail": "Tailored resume + cover note from verified facts"},
        {"name": "validate_grounding", "risk": "read", "detail": "Reject any claim without a fact"},
        {"name": "request_review", "risk": "write", "detail": "Create the pending approval a send needs"},
        {"name": "send_application", "risk": "destructive", "detail": "Blocked at 422 until you approve"},
        {"name": "record_application", "risk": "write", "detail": "Save draft application to the tracker"},
        {"name": "schedule_reminders", "risk": "write", "detail": "T-3d and T-1d deadline reminders"},
        {"name": "start_interview", "risk": "write", "detail": "Adaptive questions from weak-topic memory"},
    ]


class Toolkit:
    def __init__(self, run: Run):
        self.run = run
        self.conn = run.conn

    # --- reads
    def load_memory(self) -> dict:
        sid = self.run.student_id
        student = self.conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
        student = dict(student) if student else {}
        student["roles"] = json.loads(student.get("roles_json") or "[]")
        student["locations"] = json.loads(student.get("locations_json") or "[]")
        topics = [dict(r) for r in self.conn.execute(
            "SELECT * FROM topics WHERE student_id=? ORDER BY avg_score ASC LIMIT 5", (sid,))]
        facts = [dict(r) for r in self.conn.execute(
            "SELECT * FROM facts WHERE student_id=? ORDER BY sort_order", (sid,))]
        for f in facts:
            f["skills"] = json.loads(f.get("skills_json") or "[]")
        return {"student": student, "facts": facts, "weak_topics": topics,
                "weak": [t["topic"] for t in topics if t["avg_score"] < 3.0]}

    def read_facts(self) -> dict:
        facts = [dict(r) for r in self.conn.execute(
            "SELECT * FROM facts WHERE student_id=? AND verified=1 ORDER BY sort_order", (self.run.student_id,))]
        for f in facts:
            f["skills"] = json.loads(f.get("skills_json") or "[]")
        return {"facts": facts, "facts_hash": core.facts_hash(facts),
                "verified_skills": sorted({s for f in facts for s in f["skills"]})}

    def search_jobs(self, roles=None, locations=None, recency_days=60) -> dict:
        """Joins the seed set; the Adzuna adapter slot in here when keys exist."""
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM jobs ORDER BY id")]
        today = db.today()
        expired = 0
        out = []
        for job in rows:
            by = core._parse_date(job.get("apply_by"))
            if by and by < today:
                expired += 1
                continue
            posted = core._parse_date(job.get("posted_at"))
            if posted and (today - posted).days > recency_days:
                continue
            if locations:
                want = {loc.lower() for loc in locations}
                if not (job["location"].lower() in want or (job["remote"] and "remote" in want)):
                    continue
            if roles:
                tags = {t.lower() for t in json.loads(job.get("tags_json") or "[]")}
                if not tags & {r.lower() for r in roles}:
                    continue
            out.append(job)
        return {"jobs": out, "count": len(out), "excluded_expired": expired, "considered": len(rows)}

    def score_fit(self, jobs: list[dict], student: dict, verified_skills: list[str]) -> list[dict]:
        today = db.today()
        scored = []
        for job in jobs:
            fit = core.fit_score(job, student, verified_skills, today)
            job = dict(job)
            job["fit"] = fit
            scored.append(job)
        return scored

    def rank_jobs(self, jobs: list[dict], limit: int) -> list[dict]:
        def key(j):
            by = j.get("apply_by") or ""
            return (-(j["fit"]["score"]), by, j["company"], j["id"])
        return sorted(jobs, key=key)[:limit]

    # --- writes
    def draft_docs(self, facts: list[dict], job: dict, student: dict) -> dict:
        return core.build_docs(facts, job, student)

    def validate_grounding(self, docs: dict, facts: list[dict], job: dict) -> dict:
        return core.validate_grounding(docs, facts, job)

    def record_application(self, job: dict, fit: dict) -> dict:
        sid = self.run.student_id
        existing = self.conn.execute(
            "SELECT * FROM applications WHERE student_id=? AND job_id=?", (sid, job["id"])).fetchone()
        if existing:
            return {"application_id": existing["id"], "created": False}
        app_id = _new_id("app")
        self.conn.execute(
            "INSERT INTO applications(id,student_id,job_id,status,fit_score,fit_json,deadline,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (app_id, sid, job["id"], "draft", fit["score"], json.dumps(fit), job.get("apply_by"),
             db.iso(), db.iso()))
        self.conn.commit()
        return {"application_id": app_id, "created": True}

    def save_docs(self, application_id: str, docs: dict, grounding: dict, facts: list[dict],
                  student_id: str, job_id: str, generated_by="deterministic") -> dict:
        conn = self.conn
        conn.execute("UPDATE docs SET is_current=0 WHERE application_id=?", (application_id,))
        fhash = core.facts_hash(facts)
        ids = {}
        for kind, payload in (("resume", docs["resume"]), ("cover", docs["cover"])):
            ver = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 v FROM docs WHERE application_id=? AND kind=?",
                (application_id, kind)).fetchone()["v"]
            doc_id = _new_id("doc")
            content = {"text": payload["text"]}
            if kind == "resume":
                content["sections"] = payload["sections"]
            content["not_claimed"] = docs.get("not_claimed", [])
            conn.execute(
                "INSERT INTO docs(id,application_id,kind,version,content_json,content_text,content_hash,"
                "facts_hash,grounding_json,passed,generated_by,created_at,is_current) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (doc_id, application_id, kind, ver, json.dumps(content), payload["text"],
                 core.h(content["text"]), fhash, json.dumps(grounding), int(grounding["passed"]),
                 generated_by, db.iso()))
            ids[kind] = {"doc_id": doc_id, "version": ver, "content_hash": core.h(content["text"])}
        conn.commit()
        bh = core.bundle_hash(student_id, job_id, fhash, docs["resume"]["text"], docs["cover"]["text"])
        return {"docs": ids, "bundle_hash": bh, "facts_hash": fhash}

    def request_review(self, application_id: str, bundle_hash: str) -> dict:
        pending = self.conn.execute(
            "SELECT * FROM approvals WHERE application_id=? AND status='pending'", (application_id,)).fetchone()
        if pending and pending["bundle_hash"] == bundle_hash:
            return {"approval_id": pending["id"], "created": False}
        if pending:
            self.conn.execute("UPDATE approvals SET status='superseded' WHERE id=?", (pending["id"],))
        approval_id = _new_id("apr")
        self.conn.execute(
            "INSERT INTO approvals(id,application_id,bundle_hash,status,requested_at) VALUES(?,?,?,'pending',?)",
            (approval_id, application_id, bundle_hash, db.iso()))
        self.conn.commit()
        return {"approval_id": approval_id, "created": True}

    def schedule_reminders(self, application_id: str, deadline: str) -> dict:
        made = []
        for kind, off in (("deadline_t3", -3), ("deadline_t1", -1)):
            due = core._parse_date(deadline)
            if not due:
                continue
            when = (due + timedelta(days=off)).isoformat()
            rid = _new_id("rem")
            self.conn.execute(
                "INSERT INTO reminders(id,application_id,kind,due_at,status,created_at) VALUES(?,?,?,?,'pending',?)",
                (rid, application_id, kind, when, db.iso()))
            made.append({"id": rid, "kind": kind, "due_at": when})
        self.conn.commit()
        return {"reminders": made}

    def send_application(self, application_id: str) -> dict:
        from .errors import ApiError
        app_row = self.conn.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        if not app_row:
            raise ApiError(404, "job_not_found", "Application not found.")
        if app_row["status"] == "sent":
            raise ApiError(409, "already_sent", "This application was already sent.")
        approval = self.conn.execute(
            "SELECT * FROM approvals WHERE application_id=? AND status='approved'", (application_id,)).fetchone()
        if not approval:
            raise ApiError(422, "approval_required", "Send blocked: this application has no approved bundle.",
                           "A human must approve the exact resume and cover note before anything is sent.",
                           {"application_id": application_id, "approval_url": f"/applications/{application_id}"})
        current = self.conn.execute(
            "SELECT * FROM docs WHERE application_id=? AND is_current=1", (application_id,)).fetchall()
        if not current:
            raise ApiError(409, "approval_stale", "No current document to send.")
        live_hash = core.bundle_hash(
            app_row["student_id"], app_row["job_id"],
            current[0]["facts_hash"],
            next((d["content_text"] for d in current if d["kind"] == "resume"), ""),
            next((d["content_text"] for d in current if d["kind"] == "cover"), ""))
        if live_hash != approval["bundle_hash"]:
            raise ApiError(409, "approval_stale", "The documents changed after you approved them.",
                           "Approve the current version again.",
                           {"approved": approval["bundle_hash"], "current": live_hash})
        outbox_id = _new_id("out")
        body = next((d["content_text"] for d in current if d["kind"] == "cover"), "")
        try:
            self.conn.execute(
                "INSERT INTO outbox(id,application_id,approval_id,bundle_hash,channel,status,body_text,created_at) "
                "VALUES(?,?,?,?,'demo-outbox','recorded',?,?)",
                (outbox_id, application_id, approval["id"], live_hash, body, db.iso()))
        except Exception as exc:
            self.conn.rollback()
            raise ApiError(422, "approval_required", f"Blocked by the database gate: {exc}") from exc
        self.conn.execute("UPDATE applications SET status='sent', updated_at=? WHERE id=?",
                          (db.iso(), application_id))
        self.conn.commit()
        return {"outbox_id": outbox_id, "status": "recorded", "channel": "demo-outbox",
                "recorded_at": db.iso(), "note": "No email was dispatched. This is a local demo outbox."}

    def start_interview(self, student_id: str, role: str, language: str, limit: int = 6) -> dict:
        from .interview import create_interview
        return create_interview(self.conn, student_id, role, language, limit)


# ---------------------------------------------------------------- planner

def run_search(conn, run: Run, goal: dict) -> dict:
    tk = Toolkit(run)
    events = []

    def ev(*a, **k):
        events.append(run.event(*a, **k))

    memory, _, ms = run.call("load_memory", {}, tk.load_memory)
    ev("plan", "load_memory", "Read what the agent remembers",
       f"{len(memory['facts'])} facts on file, {len(memory['weak'])} weak interview topics", payload={"ms": ms})

    roles = goal["roles"] or memory["student"].get("roles") or []
    locations = goal["locations"] or memory["student"].get("locations") or []
    recency = goal["recency_days"]
    count = goal["count"]
    ev("plan", "plan_search", "Plan",
       f"Search {count} roles={roles or ['any']} where={locations or ['anywhere']} posted<{recency}d",
       payload={"goal": goal})

    found, attempts, elapsed = [], 0, 0
    # Each rung relaxes exactly one thing; a rung that changes nothing is skipped.
    ladder = [
        ("initial", recency, locations, roles),
        ("widen recency", max(recency, 90), locations, roles),
        ("drop location filter", max(recency, 90), None, roles),
        ("widen roles", max(recency, 90), None, None),
    ]
    tried: list[tuple] = []
    for label, rec, locs, rls in ladder:
        if (rec, locs, tuple(rls or [])) in tried and label != "initial":
            continue
        tried.append((rec, locs, tuple(rls or [])))
        args = {"roles": rls, "locations": locs, "recency_days": rec}
        res, status, ms = run.call("search_jobs", args, tk.search_jobs)
        attempts += 1
        if status != "ok" or res is None:
            ev("observe", "search_jobs", "Observed", "search_jobs failed", status="error")
            continue
        ev("act" if label == "initial" else "observe", "search_jobs",
           "job_search" if label == "initial" else f"Observed: {label}",
           f"{res['count']} live match of {res['considered']} listings · {res['excluded_expired']} past deadline",
           payload={"args": args, "count": res["count"], "ms": ms})
        if len(res["jobs"]) > len(found):
            found = res["jobs"]
        if len(found) >= count:
            break
        nxt = next((l for l in ladder if (l[1], l[2], tuple(l[3] or [])) not in tried), None)
        if nxt:
            ev("plan", "replan", "Not enough — revising the plan",
               f"short by {count - len(found)}; {nxt[0]}",
               status="warn", payload={"found": len(found), "need": count})

    facts, _, _ = run.call("read_facts", {}, tk.read_facts)
    scored, _, _ = run.call("score_fit", {"jobs": found, "student": memory["student"],
                                          "verified_skills": facts["verified_skills"]}, tk.score_fit)
    ranked, _, _ = run.call("rank_jobs", {"jobs": scored or [], "limit": count}, tk.rank_jobs)

    verified = len(facts["facts"])
    ev("verify", "validate_grounding", "Verified",
       f"{verified} of {len(memory['facts'])} facts verified · ranking is deterministic, not LLM-guessed",
       payload={"verified": verified, "total": len(memory["facts"]), "facts_hash": facts["facts_hash"]})

    created = []
    for job in ranked:
        app, _, _ = run.call("record_application", {"job": job, "fit": job["fit"]}, tk.record_application)
        created.append({"application_id": app["application_id"], "job_id": job["id"],
                        "fit": job["fit"], "job": {k: job[k] for k in
                                                   ("id", "title", "company", "location", "remote", "stipend_month",
                                                    "apply_by", "posted_at", "url", "required_json", "tags_json")}})

    if memory["weak"]:
        run.call("note_observation", {"kind": "memory",
                                      "text": f"Weak interview topics carried forward: {', '.join(memory['weak'])}"},
                 lambda kind, text: conn.execute(
                     "INSERT INTO memories(student_id,kind,text,created_at) VALUES(?,?,?,?)",
                     (run.student_id, kind, text, db.iso())) and {"ok": True})
        ev("memory", "note_observation", "Memory updated",
           f"Interview weak spots steer the next practice: {', '.join(memory['weak'])}")

    outcome = {"applications": created, "count": len(created), "attempts": attempts,
               "short": len(created) < count, "backfill": attempts - 1}
    ev("done", None, "Done", f"{len(created)} openings ranked across {attempts} search attempt(s)",
       payload={"count": len(created)})
    return outcome


def run_tailor(conn, run: Run, application_ids: list[str], note: str = "") -> dict:
    tk = Toolkit(run)
    facts, _, _ = run.call("read_facts", {}, tk.read_facts)
    memory, _, _ = run.call("load_memory", {}, tk.load_memory)
    made = []
    for app_id in application_ids[:3]:
        app_row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        if not app_row:
            continue
        job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (app_row["job_id"],)).fetchone())
        fit = core.fit_score(job, memory["student"], facts["verified_skills"], db.today())
        run.event("act", "draft_docs", f"Tailoring → {job['title']}",
                  f"{job['company']} · {len(facts['facts'])} verified facts available")
        docs, _, ms = run.call("draft_docs", {"facts": facts["facts"], "job": job,
                                              "student": memory["student"]}, tk.draft_docs)
        grounding, _, _ = run.call("validate_grounding", {"docs": docs, "facts": facts["facts"], "job": job},
                                   tk.validate_grounding)
        passed = bool(grounding and grounding.get("passed"))
        run.event("verify", "validate_grounding",
                  "Grounding check passed" if passed else "Grounding check FAILED",
                  (f"{grounding['checked']} claims traced to facts" if passed
                   else f"{len(grounding['problems'])} unsupported claim(s)"),
                  status="ok" if passed else "error", payload={"problems": (grounding or {}).get("problems", [])})
        saved, _, _ = run.call("save_docs", {"application_id": app_id, "docs": docs, "grounding": grounding,
                                             "facts": facts["facts"], "student_id": run.student_id,
                                             "job_id": job["id"]}, tk.save_docs)
        review, _, _ = run.call("request_review", {"application_id": app_id, "bundle_hash": saved["bundle_hash"]},
                                tk.request_review)
        rem, _, _ = run.call("schedule_reminders", {"application_id": app_id, "deadline": job.get("apply_by")},
                             tk.schedule_reminders)
        made.append({"application_id": app_id, "bundle_hash": saved["bundle_hash"], "grounding": grounding,
                     "approval_id": review["approval_id"], "reminders": rem["reminders"],
                     "job": {"title": job["title"], "company": job["company"]}})
    run.event("done", None, "Ready for your review",
              f"{len(made)} bundle(s) waiting. Nothing is sent until you approve.", payload={"count": len(made)})
    return {"applications": made}


def run_week_plan(conn, run: Run) -> dict:
    tk = Toolkit(run)
    rows = [dict(r) for r in conn.execute(
        "SELECT a.*, j.title, j.company, j.apply_by FROM applications a JOIN jobs j ON j.id=a.job_id "
        "WHERE a.student_id=? AND a.status!='sent' ORDER BY j.apply_by", (run.student_id,))]
    run.event("observe", "week_plan", "Reading the tracker", f"{len(rows)} unsent applications")
    urgent = [r for r in rows if (core._parse_date(r["apply_by"]) or db.today()) <= db.today() + timedelta(days=7)]
    for r in urgent[:5]:
        conn.execute("INSERT OR IGNORE INTO reminders(id,application_id,kind,due_at,status,created_at) "
                     "VALUES(?,?,?,?,'pending',?)",
                     (f"rem_{uuid.uuid4().hex[:8]}", r["id"], "week_plan",
                      r["apply_by"], db.iso()))
    conn.commit()
    run.event("done", None, "This week",
              f"{len(urgent)} deadline(s) in the next 7 days, {len(rows) - len(urgent)} later",
              payload={"urgent": [{"title": r["title"], "apply_by": r["apply_by"]} for r in urgent]})
    return {"urgent": urgent, "total": len(rows)}


def execute(run_id: str) -> None:
    """Thread target. Owns its own connection so SQLite stays single-writer friendly."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        run = Run(conn, run_id, row["student_id"], row["command"] or "", row["kind"])
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
        conn.commit()
        try:
            payload = json.loads(row["input_json"] or "{}")
            if row["kind"] == "search":
                outcome = run_search(conn, run, payload.get("goal") or parse_goal(row["command"] or ""))
            elif row["kind"] == "tailor":
                outcome = run_tailor(conn, run, payload.get("application_ids") or [])
            elif row["kind"] == "week_plan":
                outcome = run_week_plan(conn, run)
            else:
                outcome = {"note": "nothing to do"}
            conn.execute("UPDATE runs SET status='done', outcome_json=?, finished_at=? WHERE id=?",
                         (json.dumps(outcome, default=str), db.iso(), run_id))
        except Exception as exc:
            from .errors import ApiError
            if isinstance(exc, ApiError):
                run.event("blocked", "send_application", "Blocked at the API layer", exc.message,
                          status="error", payload=exc.details)
                conn.execute("UPDATE runs SET status='blocked', error=?, finished_at=? WHERE id=?",
                             (exc.message, db.iso(), run_id))
            else:
                run.event("error", None, "Run failed", str(exc)[:300], status="error")
                conn.execute("UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                             (str(exc)[:500], db.iso(), run_id))
        conn.commit()
    finally:
        conn.close()


def start(conn, student_id: str, kind: str, command: str, payload: dict, thread_factory) -> str:
    active = conn.execute(
        "SELECT id FROM runs WHERE student_id=? AND status IN ('queued','running')", (student_id,)).fetchone()
    if active:
        from .errors import ApiError
        raise ApiError(409, "run_in_progress", "A run is already working. Wait for it to finish.")
    run_id = _new_id("run")
    conn.execute(
        "INSERT INTO runs(id,student_id,kind,input_json,command,status,created_at) VALUES(?,?,?,?,?,'queued',?)",
        (run_id, student_id, kind, json.dumps(payload, default=str), command, db.iso()))
    conn.commit()
    thread_factory(execute, run_id)
    return run_id
