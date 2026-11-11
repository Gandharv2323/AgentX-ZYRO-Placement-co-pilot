"""SQLite storage: schema, connection, seed. One file, no ORM."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("PLACEPILOT_DB") or DATA / "placepilot.db")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="seconds").replace("+00:00", "Z")


def today() -> date:
    return utcnow().date()


SCHEMA = """
CREATE TABLE IF NOT EXISTS students(
  id TEXT PRIMARY KEY, name TEXT DEFAULT '', email TEXT DEFAULT '', phone TEXT DEFAULT '',
  location TEXT DEFAULT '', roles_json TEXT DEFAULT '[]', locations_json TEXT DEFAULT '[]',
  seniority TEXT DEFAULT 'intern', remote_ok INTEGER DEFAULT 1, language TEXT DEFAULT 'en',
  created_at TEXT);
CREATE TABLE IF NOT EXISTS resumes(
  id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  filename TEXT, mime TEXT, bytes BLOB, text TEXT, page_count INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS facts(
  id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  resume_id TEXT REFERENCES resumes(id) ON DELETE CASCADE, kind TEXT, section TEXT, text TEXT,
  skills_json TEXT DEFAULT '[]', source_line TEXT, verified INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0,
  created_at TEXT);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, source TEXT, external_id TEXT, title TEXT, company TEXT, location TEXT,
  remote INTEGER DEFAULT 0, employment TEXT, seniority TEXT, stipend_month INTEGER, description TEXT,
  url TEXT, apply_by TEXT, posted_at TEXT, required_json TEXT DEFAULT '[]', nice_json TEXT DEFAULT '[]',
  tags_json TEXT DEFAULT '[]', UNIQUE(source, external_id));
CREATE TABLE IF NOT EXISTS applications(
  id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  job_id TEXT NOT NULL REFERENCES jobs(id), status TEXT NOT NULL DEFAULT 'draft',
  fit_score INTEGER, fit_json TEXT, deadline TEXT, created_at TEXT, updated_at TEXT,
  UNIQUE(student_id, job_id));
CREATE TABLE IF NOT EXISTS docs(
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, version INTEGER NOT NULL, content_json TEXT, content_text TEXT,
  content_hash TEXT, facts_hash TEXT, grounding_json TEXT, passed INTEGER DEFAULT 0,
  generated_by TEXT, created_at TEXT, is_current INTEGER DEFAULT 1,
  UNIQUE(application_id, kind, version));
CREATE TABLE IF NOT EXISTS approvals(
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  bundle_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', note TEXT,
  requested_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS outbox(
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
  approval_id TEXT NOT NULL REFERENCES approvals(id), bundle_hash TEXT NOT NULL,
  channel TEXT DEFAULT 'demo-outbox', status TEXT DEFAULT 'recorded', body_text TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS reminders(
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  kind TEXT, due_at TEXT, status TEXT DEFAULT 'pending', created_at TEXT);
CREATE TABLE IF NOT EXISTS interviews(
  id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  role TEXT, language TEXT DEFAULT 'en', status TEXT DEFAULT 'active', overall REAL,
  created_at TEXT, completed_at TEXT);
CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY, interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
  idx INTEGER, topic TEXT, text_en TEXT, text_hi TEXT, rubric_json TEXT, provenance TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS answers(
  id TEXT PRIMARY KEY, question_id TEXT NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
  text TEXT, score REAL, matched_json TEXT, feedback_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS topics(
  student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE, topic TEXT NOT NULL,
  attempts INTEGER DEFAULT 0, avg_score REAL DEFAULT 0, best_score REAL DEFAULT 0, last_score REAL DEFAULT 0,
  last_seen TEXT, PRIMARY KEY(student_id, topic));

CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  kind TEXT, input_json TEXT, command TEXT, status TEXT DEFAULT 'queued', outcome_json TEXT,
  error TEXT, created_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS tool_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  student_id TEXT, tool TEXT, args_json TEXT, result_json TEXT, status TEXT, error TEXT,
  duration_ms INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  kind TEXT, text TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS run_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, phase TEXT, tool TEXT, title TEXT, detail TEXT, status TEXT,
  payload_json TEXT, created_at TEXT, UNIQUE(run_id, seq));
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_facts_student ON facts(student_id, sort_order);

-- The gate, enforced where no application code can forget it.
CREATE TRIGGER IF NOT EXISTS outbox_needs_approval BEFORE INSERT ON outbox
BEGIN
  SELECT RAISE(ABORT, 'approval_required')
  WHERE NOT EXISTS (
    SELECT 1 FROM approvals a
    WHERE a.id = NEW.approval_id AND a.application_id = NEW.application_id
      AND a.status = 'approved' AND a.bundle_hash = NEW.bundle_hash);
END;
CREATE TRIGGER IF NOT EXISTS outbox_immutable_u BEFORE UPDATE ON outbox
BEGIN SELECT RAISE(ABORT, 'outbox_immutable'); END;
-- No DELETE trigger on outbox: the student's delete-all is an explicit right and must
-- cascade. Immutability means no API path edits or removes a record one at a time.
CREATE TRIGGER IF NOT EXISTS approval_terminal_u BEFORE UPDATE ON approvals
WHEN OLD.status != 'pending' AND (NEW.status = 'pending' OR NEW.bundle_hash != OLD.bundle_hash)
BEGIN SELECT RAISE(ABORT, 'approval_immutable'); END;
"""

ROLE_TEMPLATES = [
    ("AI/ML Intern", "intern", ["python", "machine learning", "pandas", "sql"], ["docker", "pytorch"], ["ai", "ml"], 25000),
    ("Machine Learning Intern", "intern", ["python", "scikit-learn", "numpy"], ["mlflow", "sql"], ["ai", "ml", "data-science"], 28000),
    ("Data Science Intern", "intern", ["python", "pandas", "statistics", "sql"], ["matplotlib", "power bi"], ["data-science"], 24000),
    ("Data Analyst Intern", "intern", ["sql", "excel", "power bi"], ["python", "tableau"], ["data", "analytics"], 20000),
    ("Backend Developer Intern", "intern", ["python", "fastapi", "sql", "git"], ["docker", "redis"], ["backend"], 26000),
    ("Frontend Developer Intern", "intern", ["javascript", "react", "css", "git"], ["typescript", "next.js"], ["frontend"], 22000),
    ("Full Stack Intern", "intern", ["javascript", "python", "sql", "git"], ["docker", "react"], ["fullstack"], 27000),
    ("Data Engineering Intern", "intern", ["python", "sql", "spark"], ["airflow", "aws"], ["data", "backend"], 30000),
    ("MLOps Intern", "intern", ["python", "docker", "kubernetes"], ["aws", "terraform"], ["ai", "ml", "platform"], 32000),
    ("Product Analyst Intern", "intern", ["sql", "excel", "communication"], ["power bi", "amplitude"], ["product", "analytics"], 21000),
]

COMPANIES = ["Northwind Labs", "Tessellate AI", "Sahyadri Systems", "Indus Quant", "Deccan Cloud"]
LOCATIONS = [("Pune", 0), ("Pune", 0), ("Bengaluru", 0), ("Mumbai", 0), ("Remote", 1)]

DESCRIPTION = (
    "We are hiring a {title} to work with our {team} team. You will build and ship work that "
    "directly reaches users in week one. Must be comfortable with {must}. Nice to have: {nice}. "
    "Mentorship provided; conversion to full-time is possible for strong performers."
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=8000")
    # ponytail: cascading deletes spill to SQLite's temp store; keep it in memory so the
    # sandboxed (non-writable) process temp dir is never touched
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def seed_jobs(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
    if existing:
        return
    base = utcnow()
    i = 0
    for t_idx, (title, seniority, must, nice, tags, stipend) in enumerate(ROLE_TEMPLATES):
        for c_idx, company in enumerate(COMPANIES):
            i += 1
            location, remote = LOCATIONS[(t_idx + c_idx) % len(LOCATIONS)]
            # deliberate spread: a few expired, a few closing soon, rest healthy
            posted_offset = [2, 9, 21, 44, 63][(t_idx + c_idx) % 5]
            by_offset = [3, 11, 24, 33, -4][(t_idx * 2 + c_idx) % 5]
            job_id = f"job_mock_{i:03d}"
            conn.execute(
                "INSERT INTO jobs(id,source,external_id,title,company,location,remote,employment,seniority,"
                "stipend_month,description,url,apply_by,posted_at,required_json,nice_json,tags_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id, "mock", f"mock_{i:03d}", title, company, location, remote, "internship",
                    seniority, stipend,
                    DESCRIPTION.format(title=title, team=tags[0], must=", ".join(must), nice=", ".join(nice)),
                    f"https://example.com/jobs/mock_{i:03d}", (base.date() + timedelta(days=by_offset)).isoformat(),
                    (base.date() - timedelta(days=posted_offset)).isoformat(),
                    json.dumps(must), json.dumps(nice), json.dumps(tags),
                ),
            )
    conn.commit()


def init() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        seed_jobs(conn)
        conn.commit()
    finally:
        conn.close()
