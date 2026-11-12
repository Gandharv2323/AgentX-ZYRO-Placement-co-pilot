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
        self.last_error: str | None = None

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
        """One audited tool call: timing, status, persisted args/result.

        Small/free models routinely send `roles` as the string '["ai"]' or invent keys
        like `count`. Coercing here — once, for every tool — is what keeps a sloppy
        planner from producing four failed calls in a row.
        """
        args = _coerce_args(fn, args)
        started = time.perf_counter()
        try:
            result = fn(**args)
            status, error = "ok", None
        except Exception as exc:  # tool failures become observations, never crashes
            result, status, error = None, "error", str(exc)
        self.last_error = error
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


def _coerce_args(fn, args: dict) -> dict:
    """Make a model's sloppy arguments fit the tool's signature.

    - drop keys the tool does not accept (a model inventing `count`/`location`)
    - decode JSON-looking strings into lists/dicts/ints ('["ai"]' -> ["ai"])
    - map obvious singular/plural near-misses onto real parameter names
    """
    import inspect

    if not isinstance(args, dict):
        return {}
    params = [p for p in inspect.signature(fn).parameters.values()
              if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    allowed = {p.name: p for p in params}
    clean: dict = {}
    for key, value in args.items():
        target = key if key in allowed else None
        if target is None:
            # near-miss matching: location->locations, role->roles, limit->count
            for candidate in (f"{key}s", key.rstrip("s"), {"role": "roles", "location": "locations",
                                                           "limit": "count", "num": "count",
                                                           "n": "count"}.get(key, "")):
                if candidate and candidate in allowed:
                    target = candidate
                    break
        if target is None:
            continue  # silently ignored: the tool, not the model, decides its inputs
        if isinstance(value, str) and value[:1] in "[{":
            try:
                value = json.loads(value)
            except ValueError:
                pass
        # Numeric coercion must key off the default's type, not the annotation: these
        # tool signatures are unannotated, so `recency_days="60"` would otherwise reach
        # `int - str` comparisons and blow up.
        ann = allowed[target].annotation
        default = allowed[target].default
        wants_number = ann in (int, float) or (
            ann is inspect.Parameter.empty and isinstance(default, (int, float)) and not isinstance(default, bool)
        )
        if wants_number and isinstance(value, str):
            try:
                value = float(value) if "." in value else int(float(value))
            except ValueError:
                continue
        # Only flatten a list of scalars (roles/locations). A list of dicts is real payload
        # — score_fit/rank_jobs take job objects — and stringifying it silently breaks the run.
        if isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
            value = [str(v) for v in value][:8]
        clean[target] = value
    return clean


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
        """Seeded listings, plus live Adzuna ones when configured and reachable.

        Adzuna failures degrade to the seed set with the reason recorded, never a crash.
        """
        from . import providers

        query = " ".join(roles or []) or "internship"
        where = (locations or ["India"])[0]
        live, meta = providers.merge_jobs(self.conn, query, where, count=25)
        for job in live:
            self.conn.execute(
                "INSERT OR IGNORE INTO jobs(id,source,external_id,title,company,location,remote,employment,"
                "seniority,stipend_month,description,url,apply_by,posted_at,required_json,nice_json,tags_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job["id"], job["source"], job["external_id"], job["title"], job["company"], job["location"],
                 job["remote"], job["employment"], job["seniority"], job["stipend_month"], job["description"],
                 job["url"], job["apply_by"], job["posted_at"], job["required_json"], job["nice_json"],
                 job["tags_json"]))
        self.conn.commit()

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
                # live listings are tagged "adzuna", so match their text too
                hay = f"{job['title']} {job.get('description', '')}".lower()
                if not (tags & {r.lower() for r in roles}) and not any(r.lower() in hay for r in roles):
                    continue
            out.append(job)
        return {"jobs": out, "count": len(out), "excluded_expired": expired, "considered": len(rows),
                "source": meta["source"], "fallback": meta["fallback"], "live": meta["live"]}

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
    from . import providers

    # An LLM plans when configured; its failure falls back to the deterministic plan below
    # and says so in the trace. It cannot bypass the approval gate either way.
    if providers.llm_available():
        try:
            return run_search_llm(conn, run, goal)
        except Exception as exc:  # noqa: BLE001 - any provider failure must degrade, not kill the run
            run.event("verify", "planner_fallback", "Planner fell back to deterministic",
                      f"LLM planner unavailable: {str(exc)[:160]}", status="warn")
    return run_search_deterministic(conn, run, goal)


def run_search_llm(conn, run: Run, goal: dict, max_steps: int = 8) -> dict:
    """Real tool-use loop: the model picks tools, we execute them and feed back results."""
    from . import providers

    tk = Toolkit(run)
    tools = tool_specs()
    # send_application stays exposed but is always guard-blocked, which is the point.
    memory, _, _ = run.call("load_memory", {}, tk.load_memory)
    roles = goal.get("roles") or memory["student"].get("roles") or []
    locations = goal.get("locations") or memory["student"].get("locations") or []
    history: list[dict] = [{
        "role": "user",
        "content": (
            f"Goal: {json.dumps(goal)}. Student roles={roles} locations={locations}. "
            "Call search_jobs ONCE with keys roles (array), locations (array), recency_days (int). "
            "Then call rank_jobs with limit (int). Then reply "
            '{"done": true, "summary": "..."} in plain JSON. Do not repeat a call that succeeded.'
        ),
    }]
    results: list[dict] = []
    scored: list[dict] = []
    steps, repeated = 0, 0
    last_signature = None
    while steps < max_steps:
        steps += 1
        decision = providers.plan_step(history, tools)
        if decision.get("done"):
            break
        name = decision.get("tool")
        raw_args = decision.get("args") or {}
        if name not in {t["name"] for t in tools}:
            run.event("error", str(name), "Rejected unknown tool",
                      f"The planner asked for {name!r}, which is not an allowed tool.", status="error")
            break
        # A model cannot carry job objects between turns, so we thread them: rank_jobs
        # scores whatever search_jobs returned, exactly like the deterministic planner.
        if name == "score_fit":
            raw_args.setdefault("jobs", results)
            raw_args.setdefault("verified_skills", (memory.get("student") or {}).get("skills", []))
        if name == "rank_jobs":
            if not scored:
                scored = _score_current(conn, run, tk, results) or []
            raw_args.setdefault("jobs", scored)
        args = _coerce_args(getattr(tk, name, lambda **k: None), raw_args)
        signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if signature == last_signature:
            repeated += 1
            if repeated >= 2:
                run.event("observe", name, "Repeated call stopped",
                          "The planner repeated an identical call; moving on.", status="warn")
                break
        last_signature = signature
        fn = getattr(tk, name, None)
        if fn is None:
            run.event("error", name, "Tool not implemented", name, status="error")
            break
        result, status, ms = run.call(name, args, fn)
        label = {
            "search_jobs": lambda r: f"{r.get('count', 0)} matches of {r.get('considered', 0)} · source {r.get('source', '?')}",
            "rank_jobs": lambda r: f"{len(r)} ranked",
            "score_fit": lambda r: f"{len(r)} scored",
            "load_memory": lambda r: f"{len(r.get('facts', []))} facts",
        }.get(name, lambda r: "ok")(result) if status == "ok" and result is not None else (
            f"error: {run.last_error}" if status != "ok" else "ok")
        run.event("act", name, name, f"{label} · {ms}ms", status=status,
                  payload={"args": args, **({"error": run.last_error} if status != "ok" else {})})
        if status != "ok":
            # One bad call is enough: hand back to the deterministic planner rather than
            # burning the remaining budget on a model that keeps mis-calling this tool.
            raise providers.ProviderError(f"{name} failed: {run.last_error}")
        history.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{steps}", "name": name, "input": args}]})
        history.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{steps}",
             "content": json.dumps(result if status == "ok" else {"error": label}, default=str)[:4000]}]})
        if name in ("search_jobs", "rank_jobs") and result:
            if isinstance(result, dict) and result.get("jobs"):
                results = result["jobs"]
            elif isinstance(result, list):
                results = result
        if name == "score_fit" and isinstance(result, list):
            scored = result
    if not results:
        raise providers.ProviderError("LLM planner produced no jobs")
    return _finish_search(conn, run, tk, goal, results, planner=providers.llm_mode())


def _score_current(conn, run: Run, tk: Toolkit, jobs: list[dict]) -> list[dict]:
    """Score whatever the model found, using the student's verified skills."""
    facts, _, _ = run.call("read_facts", {}, tk.read_facts)
    memory, _, _ = run.call("load_memory", {}, tk.load_memory)
    scored, _, _ = run.call("score_fit", {"jobs": jobs, "student": memory["student"],
                                          "verified_skills": facts["verified_skills"]}, tk.score_fit)
    return scored or []


def _finish_search(conn, run: Run, tk: Toolkit, goal: dict, found: list[dict], planner: str) -> dict:
    """Shared tail: score, rank, persist applications, record the trust events."""
    memory, _, _ = run.call("load_memory", {}, tk.load_memory)
    facts, _, _ = run.call("read_facts", {}, tk.read_facts)
    scored, _, _ = run.call("score_fit", {"jobs": found, "student": memory["student"],
                                          "verified_skills": facts["verified_skills"]}, tk.score_fit)
    ranked, _, _ = run.call("rank_jobs", {"jobs": scored or [], "limit": goal["count"]}, tk.rank_jobs)

    verified = len(facts["facts"])
    run.event("verify", "validate_grounding", "Verified",
              f"{verified} of {len(memory['facts'])} facts verified · planner={planner}",
              payload={"verified": verified, "total": len(memory["facts"]), "facts_hash": facts["facts_hash"]})

    created = []
    for job in ranked:
        app, _, _ = run.call("record_application", {"job": job, "fit": job["fit"]}, tk.record_application)
        created.append({"application_id": app["application_id"], "job_id": job["id"],
                        "fit": job["fit"], "job": {k: job[k] for k in
                                                   ("id", "title", "company", "location", "remote", "stipend_month",
                                                    "apply_by", "posted_at", "url", "required_json", "tags_json")}})
    if memory["weak"]:
        conn.execute("INSERT INTO memories(student_id,kind,text,created_at) VALUES(?,?,?,?)",
                     (run.student_id, "memory",
                      f"Weak interview topics carried forward: {', '.join(memory['weak'])}", db.iso()))
        conn.commit()
        run.event("memory", "note_observation", "Memory updated",
                  f"Interview weak spots steer the next practice: {', '.join(memory['weak'])}")
    outcome = {"applications": created, "count": len(created), "planner": planner}
    run.event("done", None, "Done", f"{len(created)} openings ranked by the {planner} planner",
              payload={"count": len(created)})
    return outcome


def run_search_deterministic(conn, run: Run, goal: dict) -> dict:
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
        source = res.get("source", "mock")
        fallback = res.get("fallback")
        source_note = f" · source {source}" + (f" (fallback: {fallback})" if fallback else "")
        if label == "initial" and fallback:
            ev("observe", "job_source", "Live source unavailable", fallback, status="warn")
        ev("act" if label == "initial" else "observe", "search_jobs",
           "job_search" if label == "initial" else f"Observed: {label}",
           f"{res['count']} live match of {res['considered']} listings · "
           f"{res['excluded_expired']} past deadline{source_note}",
           payload={"args": args, "count": res["count"], "ms": ms,
                    "source": source, "fallback": fallback})
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
               "short": len(created) < count, "backfill": attempts - 1, "planner": "deterministic"}
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
