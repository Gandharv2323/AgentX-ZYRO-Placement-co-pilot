"""FastAPI surface. Thin routes; behaviour lives in core.py / agent.py / interview.py."""
from __future__ import annotations

import io
import json
import os
import threading
import uuid
from datetime import date, timedelta

from fastapi import FastAPI, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pypdf import PdfReader

from . import agent, config, core, db, interview  # config first: it loads .env into os.environ
from .errors import ApiError, api_error_handler, unhandled_error_handler

_ = config  # imported for its side effect (load_env) before any provider check

app = FastAPI(title="PlacePilot", version="1.0.0")
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.add_middleware(
    CORSMiddleware,
    # ponytail: any localhost port — the app is a local demo, not a public origin
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)

DEMO = os.environ.get("PLACEPILOT_DEMO", "1") != "0"


@app.on_event("startup")
def _startup() -> None:
    db.init()


def student(x_student_id: str | None) -> dict:
    if not x_student_id:
        raise ApiError(401, "student_required", "Missing X-Student-Id header.",
                       "Open the app once so it creates a local student profile.")
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM students WHERE id=?", (x_student_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise ApiError(404, "student_not_found", "Unknown student.",
                       "Your local profile was deleted. Onboard again.")
    out = dict(row)
    out["roles"] = json.loads(out.get("roles_json") or "[]")
    out["locations"] = json.loads(out.get("locations_json") or "[]")
    return out


def _job(row) -> dict:
    j = dict(row)
    for k in ("required_json", "nice_json", "tags_json"):
        j[k.replace("_json", "")] = json.loads(j.pop(k) or "[]")
    return j


def _app_bundle(conn, row) -> dict:
    app_id = row["id"]
    job = _job(conn.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone())
    docs = {}
    for d in conn.execute("SELECT * FROM docs WHERE application_id=? AND is_current=1", (app_id,)):
        d = dict(d)
        docs[d["kind"]] = {"id": d["id"], "version": d["version"], "text": d["content_text"],
                           "content": json.loads(d["content_json"] or "{}"),
                           "hash": d["content_hash"], "passed": bool(d["passed"]),
                           "grounding": json.loads(d["grounding_json"] or "{}"),
                           "generated_by": d["generated_by"], "created_at": d["created_at"]}
    approval = conn.execute(
        "SELECT * FROM approvals WHERE application_id=? ORDER BY requested_at DESC LIMIT 1", (app_id,)).fetchone()
    outbox = conn.execute("SELECT * FROM outbox WHERE application_id=?", (app_id,)).fetchone()
    return {
        "id": app_id, "status": row["status"], "fit": json.loads(row["fit_json"] or "{}"),
        "deadline": row["deadline"], "created_at": row["created_at"],
        "job": job, "docs": docs,
        "approval": (dict(approval) if approval else None),
        "outbox": (dict(outbox) if outbox else None),
        "reminders": [dict(r) for r in conn.execute(
            "SELECT * FROM reminders WHERE application_id=? ORDER BY due_at", (app_id,))],
        "diff": (core.diff_docs(docs["resume"]["text"], docs["resume"]["text"])
                 if not docs else _diff_for(conn, app_id, docs)),
    }


def _diff_for(conn, app_id: str, docs: dict) -> dict:
    base = conn.execute("SELECT * FROM resumes WHERE student_id=(SELECT student_id FROM applications WHERE id=?) "
                        "ORDER BY created_at DESC LIMIT 1", (app_id,)).fetchone()
    base_text = base["text"] if base else ""
    if not base_text or "resume" not in docs:
        return {"ops": [], "summary": {"added": 0, "trimmed": 0, "kept": 0}}
    return core.diff_docs(base_text, docs["resume"]["text"])


# ---------------------------------------------------------------- system

@app.get("/healthz")
def healthz() -> dict:
    from . import providers

    conn = db.connect()
    try:
        jobs = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        live = conn.execute("SELECT COUNT(*) c FROM jobs WHERE source='adzuna'").fetchone()["c"]
        students = conn.execute("SELECT COUNT(*) c FROM students").fetchone()["c"]
    finally:
        conn.close()
    return {"ok": True, "jobs": jobs, "live_jobs": live, "students": students,
            "planner": providers.llm_mode(),
            "jobs_source": providers.jobs_mode(),
            "llm_configured": providers.llm_available(),
            "adzuna_configured": providers.adzuna_configured(),
            "send_mode": "record", "version": app.version, "time": db.iso()}


# ---------------------------------------------------------------- student

@app.post("/api/students")
def create_student() -> dict:
    conn = db.connect()
    try:
        sid = f"stu_{uuid.uuid4().hex[:10]}"
        conn.execute("INSERT INTO students(id,created_at) VALUES(?,?)", (sid, db.iso()))
        conn.commit()
        return {"id": sid}
    finally:
        conn.close()


@app.get("/api/students/me")
def me(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        return {"student": s, "facts": [dict(r) for r in conn.execute(
            "SELECT * FROM facts WHERE student_id=? ORDER BY sort_order", (s["id"],))]}
    finally:
        conn.close()


@app.patch("/api/students/me")
async def update_me(request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    conn = db.connect()
    try:
        fields = {"name": "name", "email": "email", "phone": "phone", "location": "location",
                  "seniority": "seniority", "language": "language"}
        for key, col in fields.items():
            if key in body:
                conn.execute(f"UPDATE students SET {col}=? WHERE id=?", (str(body[key])[:200], s["id"]))
        if "roles" in body:
            conn.execute("UPDATE students SET roles_json=? WHERE id=?",
                         (json.dumps(body["roles"][:5]), s["id"]))
        if "locations" in body:
            conn.execute("UPDATE students SET locations_json=? WHERE id=?",
                         (json.dumps(body["locations"][:5]), s["id"]))
        if "remote_ok" in body:
            conn.execute("UPDATE students SET remote_ok=? WHERE id=?", (int(bool(body["remote_ok"])), s["id"]))
        conn.commit()
    finally:
        conn.close()
    return me(x_student_id)


@app.delete("/api/students/me")
def delete_me(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        tables = ["facts", "resumes", "applications", "interviews", "topics", "runs", "memories"]
        counts = {t: conn.execute(f"SELECT COUNT(*) c FROM {t} WHERE student_id=?", (s["id"],)).fetchone()["c"]
                  for t in tables}
        conn.execute("DELETE FROM students WHERE id=?", (s["id"],))
        conn.commit()
        left = {}
        for t in ("facts", "resumes", "applications", "interviews", "topics", "runs", "memories",
                  "docs", "approvals", "outbox", "reminders", "questions", "answers",
                  "run_events", "tool_calls"):
            if t in ("docs", "approvals", "outbox", "reminders", "questions", "answers", "run_events", "tool_calls"):
                continue
            left[t] = conn.execute(f"SELECT COUNT(*) c FROM {t} WHERE student_id=?", (s["id"],)).fetchone()["c"]
        remaining = {
            "docs": conn.execute(
                "SELECT COUNT(*) c FROM docs WHERE application_id IN (SELECT id FROM applications WHERE student_id=?)",
                (s["id"],)).fetchone()["c"],
            "approvals": conn.execute(
                "SELECT COUNT(*) c FROM approvals WHERE application_id IN "
                "(SELECT id FROM applications WHERE student_id=?)", (s["id"],)).fetchone()["c"],
            "outbox": conn.execute(
                "SELECT COUNT(*) c FROM outbox WHERE application_id IN "
                "(SELECT id FROM applications WHERE student_id=?)", (s["id"],)).fetchone()["c"],
        }
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        return {"deleted": counts, "remaining": {**left, **remaining}, "fk_violations": len(fk)}
    finally:
        conn.close()


@app.get("/api/export")
def export(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        apps = [dict(r) for r in conn.execute("SELECT * FROM applications WHERE student_id=?", (s["id"],))]
        approvals = [dict(r) for r in conn.execute(
            "SELECT * FROM approvals WHERE application_id IN (SELECT id FROM applications WHERE student_id=?)",
            (s["id"],))]
        outbox = [dict(r) for r in conn.execute(
            "SELECT * FROM outbox WHERE application_id IN (SELECT id FROM applications WHERE student_id=?)",
            (s["id"],))]
        return {"student": s, "applications": apps, "approvals": approvals, "outbox": outbox,
                "topics": [dict(r) for r in conn.execute("SELECT * FROM topics WHERE student_id=?", (s["id"],))],
                "exported_at": db.iso()}
    finally:
        conn.close()


# ---------------------------------------------------------------- onboarding / facts

def _store_resume(conn, student_id: str, filename: str, mime: str, data: bytes) -> dict:
    if len(data) > 5 * 1024 * 1024:
        raise ApiError(413, "file_too_large", "That PDF is over 5 MB.")
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        pages = len(reader.pages)
    except Exception as exc:
        raise ApiError(422, "invalid_pdf", "That file could not be read as a PDF.",
                       "Export a fresh PDF from your editor and try again.") from exc
    if len(text.strip()) < 40:
        raise ApiError(422, "parse_failed", "This PDF has no selectable text.",
                       "PlacePilot cannot read scans in the demo. Export a text PDF, or add facts by hand.")
    contact, facts = core.parse_resume(text)
    resume_id = f"res_{uuid.uuid4().hex[:10]}"
    conn.execute("INSERT INTO resumes(id,student_id,filename,mime,bytes,text,page_count,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?)", (resume_id, student_id, filename, mime, data, text, pages, db.iso()))
    conn.execute("DELETE FROM facts WHERE student_id=?", (student_id,))
    for f in facts:
        conn.execute("INSERT INTO facts(id,student_id,resume_id,kind,section,text,skills_json,source_line,"
                     "verified,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)",
                     (f"fact_{uuid.uuid4().hex[:8]}", student_id, resume_id, f["kind"], f["section"],
                      f["text"], json.dumps(f["skills"]), f["source_line"], f["order"], db.iso()))
    for key in ("name", "email", "phone", "location"):
        if contact.get(key):
            conn.execute(f"UPDATE students SET {key}=? WHERE id=? AND ({key} IS NULL OR {key}='')",
                         (contact[key], student_id))
    conn.commit()
    return {"resume_id": resume_id, "pages": pages, "facts": len(facts), "contact": contact}


@app.post("/api/onboarding/sample")
def onboarding_sample(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    from .sample import SEED
    path = SEED / "sample_resume.pdf"
    if not path.exists():
        raise ApiError(500, "internal", "Sample PDF missing.", "Run: python -m app.sample")
    conn = db.connect()
    try:
        return _store_resume(conn, s["id"], "sample_resume.pdf", "application/pdf", path.read_bytes())
    finally:
        conn.close()


@app.post("/api/onboarding/upload")
async def onboarding_upload(file: UploadFile, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    data = await file.read()
    conn = db.connect()
    try:
        return _store_resume(conn, s["id"], file.filename or "resume.pdf", file.content_type or "application/pdf", data)
    finally:
        conn.close()


@app.post("/api/facts")
async def add_fact(request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "invalid_input", "Fact text is required.")
    conn = db.connect()
    try:
        order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 o FROM facts WHERE student_id=?",
                             (s["id"],)).fetchone()["o"]
        fid = f"fact_{uuid.uuid4().hex[:8]}"
        conn.execute("INSERT INTO facts(id,student_id,kind,section,text,skills_json,source_line,verified,"
                     "sort_order,created_at) VALUES(?,?,?,?,?,?,'Added by you',1,?,?)",
                     (fid, s["id"], body.get("kind", "skill"), body.get("section", "skills"), text,
                      json.dumps(core.extract_skills(text)), order, db.iso()))
        conn.commit()
        return {"id": fid}
    finally:
        conn.close()


@app.patch("/api/facts/{fact_id}")
async def patch_fact(fact_id: str, request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM facts WHERE id=? AND student_id=?", (fact_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "invalid_input", "Fact not found.")
        if "text" in body:
            text = str(body["text"]).strip()
            conn.execute("UPDATE facts SET text=?, skills_json=? WHERE id=?",
                         (text, json.dumps(core.extract_skills(text)), fact_id))
        if "verified" in body:
            conn.execute("UPDATE facts SET verified=? WHERE id=?", (int(bool(body["verified"])), fact_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: str, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM facts WHERE id=? AND student_id=?", (fact_id, s["id"]))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- jobs / runs

@app.get("/api/jobs")
def list_jobs(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT a.id application_id, a.fit_score, a.status, a.fit_json, j.* FROM applications a "
            "JOIN jobs j ON j.id=a.job_id WHERE a.student_id=? "
            "ORDER BY a.fit_score DESC, j.company, j.id", (s["id"],)).fetchall()
        out = []
        for r in rows:
            job = _job(r)
            job.pop("application_id", None)
            out.append({"application_id": r["application_id"], "status": r["status"],
                        "fit_score": r["fit_score"], "_fit": json.loads(r["fit_json"] or "{}"), **job})
        return {"jobs": out}
    finally:
        conn.close()


@app.post("/api/runs")
async def create_run(request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    command = (body.get("command") or "").strip()
    kind = body.get("kind") or "search"
    if kind == "chat":
        goal = agent.parse_goal(command)
        kind = "search" if goal["intent"] in ("search", "apply_plan", "tailor") else (
            "week_plan" if goal["intent"] == "week_plan" else "search")
        payload = {"goal": goal}
    else:
        payload = body.get("payload") or {"goal": agent.parse_goal(command)}
    conn = db.connect()
    try:
        run_id = agent.start(conn, s["id"], kind, command, payload,
                             lambda fn, rid: threading.Thread(target=fn, args=(rid,), daemon=True).start())
        return {"run_id": run_id, "kind": kind}
    finally:
        conn.close()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, after_seq: int = 0, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=? AND student_id=?", (run_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "run_not_found", "No such run.")
        events = [{"seq": e["seq"], "run_id": e["run_id"], "phase": e["phase"], "tool": e["tool"],
                   "title": e["title"], "detail": e["detail"], "status": e["status"],
                   "payload": json.loads(e["payload_json"] or "{}"), "created_at": e["created_at"]}
                  for e in conn.execute("SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq",
                                        (run_id, after_seq))]
        return {"id": row["id"], "status": row["status"], "kind": row["kind"], "command": row["command"],
                "error": row["error"], "outcome": json.loads(row["outcome_json"] or "null"),
                "events": events, "last_seq": events[-1]["seq"] if events else after_seq}
    finally:
        conn.close()


@app.get("/api/agent/tools")
def tools() -> dict:
    return {"tools": agent.tool_specs()}


# ---------------------------------------------------------------- applications / the gate

@app.post("/api/applications")
async def create_applications(request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    ids = [str(x) for x in (body.get("job_ids") or [])][:3]
    if not ids:
        raise ApiError(400, "invalid_input", "Pick at least one opening.")
    conn = db.connect()
    try:
        app_ids = []
        for job_id in ids:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                continue
            existing = conn.execute("SELECT id FROM applications WHERE student_id=? AND job_id=?",
                                    (s["id"], job_id)).fetchone()
            if existing:
                app_ids.append(existing["id"])
                continue
            facts = [dict(r) for r in conn.execute("SELECT * FROM facts WHERE student_id=? AND verified=1", (s["id"],))]
            for f in facts:
                f["skills"] = json.loads(f.get("skills_json") or "[]")
            fit = core.fit_score(dict(job), s, sorted({x for f in facts for x in f["skills"]}), db.today())
            app_id = f"app_{uuid.uuid4().hex[:10]}"
            conn.execute("INSERT INTO applications(id,student_id,job_id,status,fit_score,fit_json,deadline,"
                         "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (app_id, s["id"], job_id, "draft", fit["score"], json.dumps(fit),
                          job["apply_by"], db.iso(), db.iso()))
            app_ids.append(app_id)
        conn.commit()
        run_id = agent.start(conn, s["id"], "tailor", "", {"application_ids": app_ids},
                             lambda fn, rid: threading.Thread(target=fn, args=(rid,), daemon=True).start())
        return {"run_id": run_id, "application_ids": app_ids}
    finally:
        conn.close()


@app.get("/api/applications/{app_id}")
def get_application(app_id: str, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM applications WHERE id=? AND student_id=?", (app_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "job_not_found", "Application not found.")
        return _app_bundle(conn, row)
    finally:
        conn.close()


@app.get("/api/applications")
def list_applications(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT a.*, j.title, j.company, j.location, j.apply_by, j.url FROM applications a "
            "JOIN jobs j ON j.id=a.job_id WHERE a.student_id=? ORDER BY "
            "CASE a.status WHEN 'sent' THEN 3 WHEN 'approved' THEN 2 ELSE 1 END, j.apply_by", (s["id"],)).fetchall()
        out = []
        for r in rows:
            approval = conn.execute("SELECT status FROM approvals WHERE application_id=? "
                                    "ORDER BY requested_at DESC LIMIT 1", (r["id"],)).fetchone()
            out.append({"id": r["id"], "status": r["status"], "fit_score": r["fit_score"],
                        "deadline": r["apply_by"], "title": r["title"], "company": r["company"],
                        "location": r["location"], "url": r["url"],
                        "approval": approval["status"] if approval else None,
                        "days_left": (core._parse_date(r["apply_by"]) - db.today()).days
                        if core._parse_date(r["apply_by"]) else None})
        return {"applications": out}
    finally:
        conn.close()


@app.post("/api/applications/{app_id}/approvals")
async def decide(app_id: str, request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise ApiError(400, "invalid_input", "decision must be approve or reject.")
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM applications WHERE id=? AND student_id=?", (app_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "job_not_found", "Application not found.")
        if row["status"] == "sent":
            raise ApiError(409, "already_sent", "Already sent.")
        if decision == "approve" and not body.get("confirm"):
            raise ApiError(400, "invalid_input", "Set confirm=true after reviewing every claim.")
        approval = conn.execute("SELECT * FROM approvals WHERE application_id=? AND status='pending' "
                                "ORDER BY requested_at DESC LIMIT 1", (app_id,)).fetchone()
        if not approval:
            raise ApiError(409, "draft_stale", "There is no pending review for this application.")
        if body.get("bundle_hash") and body["bundle_hash"] != approval["bundle_hash"]:
            raise ApiError(409, "approval_stale", "The bundle changed since this page loaded.",
                           "Reload and review the current draft.", {"expected": approval["bundle_hash"]})
        docs = conn.execute("SELECT * FROM docs WHERE application_id=? AND is_current=1", (app_id,)).fetchall()
        if any(not d["passed"] for d in docs):
            raise ApiError(422, "grounding_failed", "A claim in this draft is not backed by a verified fact.",
                           "Open the Grounding tab and fix or regenerate.")
        conn.execute("UPDATE approvals SET status=?, decided_at=?, note=? WHERE id=?",
                     ("approved" if decision == "approve" else "rejected", db.iso(),
                      body.get("note", ""), approval["id"]))
        conn.execute("UPDATE applications SET status=?, updated_at=? WHERE id=?",
                     ("approved" if decision == "approve" else "rejected", db.iso(), app_id))
        conn.commit()
        return {"status": decision, "approval_id": approval["id"], "bundle_hash": approval["bundle_hash"],
                "decided_at": db.iso()}
    finally:
        conn.close()


@app.post("/api/applications/{app_id}/send")
def send(app_id: str, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM applications WHERE id=? AND student_id=?", (app_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "job_not_found", "Application not found.")
        run = agent.Run(conn, "send_probe", s["id"], "", "send")
        return agent.Toolkit(run).send_application(app_id)
    finally:
        conn.close()


@app.post("/api/applications/{app_id}/regenerate")
def regenerate(app_id: str, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM applications WHERE id=? AND student_id=?", (app_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "job_not_found", "Application not found.")
        run_id = agent.start(conn, s["id"], "tailor", "", {"application_ids": [app_id]},
                             lambda fn, rid: threading.Thread(target=fn, args=(rid,), daemon=True).start())
        return {"run_id": run_id}
    finally:
        conn.close()


@app.get("/api/applications/{app_id}/resume.html", response_class=PlainTextResponse)
def resume_html(app_id: str, x_student_id: str | None = Header(default=None)) -> PlainTextResponse:
    s = student(x_student_id)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM applications WHERE id=? AND student_id=?", (app_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "job_not_found", "Application not found.")
        doc = conn.execute("SELECT * FROM docs WHERE application_id=? AND kind='resume' AND is_current=1",
                           (app_id,)).fetchone()
        student_row = conn.execute("SELECT * FROM students WHERE id=?", (s["id"],)).fetchone()
        body = "".join(f"<p>{line}</p>" for line in (doc["content_text"] if doc else "").split("\n") if line.strip())
        html = f"""<!doctype html><meta charset=utf-8><title>{student_row['name']} - resume</title>
<style>body{{font-family:Arial,sans-serif;max-width:760px;margin:40px auto;line-height:1.5;color:#111}}
h1{{font-size:22pt;margin:0}} .meta{{color:#555;margin-bottom:18px}}
p{{margin:2px 0}} @media print{{body{{margin:0}}}}</style>
<h1>{student_row['name']}</h1>
<div class="meta">{student_row['email']} · {student_row['phone']} · {student_row['location']}</div>
{body}"""
        return PlainTextResponse(html, media_type="text/html")
    finally:
        conn.close()


# ---------------------------------------------------------------- calendar / tracker

@app.get("/api/calendar.ics")
def calendar_feed(x_student_id: str | None = Header(default=None)) -> Response:
    s = student(x_student_id)
    conn = db.connect()
    try:
        rows = conn.execute("SELECT a.id, a.status, j.title, j.company, j.apply_by FROM applications a "
                            "JOIN jobs j ON j.id=a.job_id WHERE a.student_id=? AND a.status!='sent'", (s["id"],))
        events = [{"uid": r["id"], "date": r["apply_by"],
                   "summary": f"Apply: {r['title']} @ {r['company']}",
                   "description": f"PlacePilot tracker · status {r['status']}"} for r in rows if r["apply_by"]]
        return Response(core.make_ics(events), media_type="text/calendar",
                        headers={"Content-Disposition": 'attachment; filename="placepilot-deadlines.ics"'})
    finally:
        conn.close()


# ---------------------------------------------------------------- interviews

@app.post("/api/interviews")
async def start_interview(request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    conn = db.connect()
    try:
        return interview.create_interview(conn, s["id"], body.get("role") or "AI/ML Intern",
                                          body.get("language") or "en")
    finally:
        conn.close()


@app.get("/api/interviews/weak-topics")
def weak_topics(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        return {"topics": [dict(r) for r in conn.execute(
            "SELECT * FROM topics WHERE student_id=? ORDER BY avg_score ASC", (s["id"],))]}
    finally:
        conn.close()


@app.get("/api/interviews/{interview_id}")
def get_interview(interview_id: str, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM interviews WHERE id=? AND student_id=?", (interview_id, s["id"])).fetchone()
        if not row:
            raise ApiError(404, "interview_incomplete", "Interview not found.")
        qs = [dict(r) for r in conn.execute("SELECT * FROM questions WHERE interview_id=? ORDER BY idx",
                                            (interview_id,))]
        out = []
        for q in qs:
            a = conn.execute("SELECT * FROM answers WHERE question_id=?", (q["id"],)).fetchone()
            out.append({"id": q["id"], "topic": q["topic"], "provenance": q["provenance"],
                        "text": q["text_hi"] if row["language"] == "hi" else q["text_en"],
                        "answer": ({"text": a["text"], "score": a["score"],
                                    **json.loads(a["feedback_json"] or "{}")} if a else None)})
        return {"id": row["id"], "status": row["status"], "language": row["language"], "role": row["role"],
                "overall": row["overall"], "questions": out}
    finally:
        conn.close()


@app.post("/api/interviews/{interview_id}/answers")
async def answer(interview_id: str, request: Request, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    body = await request.json()
    conn = db.connect()
    try:
        q = conn.execute("SELECT q.id FROM questions q JOIN interviews i ON i.id=q.interview_id "
                         "WHERE q.id=? AND i.student_id=?", (body.get("question_id"), s["id"])).fetchone()
        if not q:
            raise ApiError(404, "interview_incomplete", "Question not found.")
        return interview.score_answer(conn, q["id"], body.get("text") or "")
    finally:
        conn.close()


@app.post("/api/interviews/{interview_id}/complete")
def finish(interview_id: str, x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        return interview.complete_interview(conn, s["id"], interview_id)
    finally:
        conn.close()


# ---------------------------------------------------------------- memory / demo

@app.get("/api/memory")
def memory(x_student_id: str | None = Header(default=None)) -> dict:
    s = student(x_student_id)
    conn = db.connect()
    try:
        return {
            "student": s,
            "facts": [dict(r) for r in conn.execute("SELECT * FROM facts WHERE student_id=? ORDER BY sort_order",
                                                    (s["id"],))],
            "topics": [dict(r) for r in conn.execute("SELECT * FROM topics WHERE student_id=?", (s["id"],))],
            "memories": [dict(r) for r in conn.execute("SELECT * FROM memories WHERE student_id=? ORDER BY id DESC "
                                                       "LIMIT 30", (s["id"],))],
            "runs": [dict(r) for r in conn.execute("SELECT id,kind,command,status,created_at FROM runs "
                                                   "WHERE student_id=? ORDER BY created_at DESC LIMIT 10", (s["id"],))],
            "calls": [dict(r) for r in conn.execute(
                "SELECT tool,status,duration_ms,created_at,args_json FROM tool_calls WHERE student_id=? "
                "ORDER BY id DESC LIMIT 40", (s["id"],))],
        }
    finally:
        conn.close()


@app.post("/api/demo/reset")
def demo_reset(x_student_id: str | None = Header(default=None)) -> dict:
    if not DEMO:
        raise ApiError(403, "invalid_input", "Demo endpoints are disabled.")
    s = student(x_student_id)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM students WHERE id=?", (s["id"],))
        conn.commit()
        return {"reset": True}
    finally:
        conn.close()
