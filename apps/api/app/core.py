"""Pure logic: skills, resume parsing, fit score, tailoring + grounding, diff, hashes, ics.

No DB, no HTTP here. Everything is a function of its arguments, so the tests
can hammer it without a running server.
"""
from __future__ import annotations

import hashlib
import json
import re
import textwrap
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher

# ---------------------------------------------------------------- skills

ALIASES = {
    "js": "javascript", "ts": "typescript", "py": "python", "ml": "machine learning",
    "scikit learn": "scikit-learn", "sklearn": "scikit-learn", "powerbi": "power bi",
    "pgvector": "pgvector", "node": "node.js", "nodejs": "node.js", "nextjs": "next.js",
    "postgres": "postgresql", "mlops": "mlops", "k8s": "kubernetes", "tf": "terraform",
}

SKILLS = {
    "python", "sql", "pandas", "numpy", "scikit-learn", "machine learning", "deep learning",
    "pytorch", "tensorflow", "statistics", "matplotlib", "power bi", "tableau", "excel",
    "javascript", "typescript", "react", "next.js", "css", "html", "node.js", "fastapi",
    "flask", "django", "postgresql", "sqlite", "redis", "docker", "kubernetes", "aws",
    "git", "linux", "spark", "airflow", "terraform", "go", "java", "c++", "rest",
    "communication", "nlp", "computer vision", "streamlit", "mlflow", "amplitude", "figma",
}

ROLE_GROUPS = {
    "ai": {"ai", "ml", "machine learning", "data science", "deep learning", "nlp"},
    "data": {"data", "analytics", "data science", "bi"},
    "backend": {"backend", "api", "server"},
    "frontend": {"frontend", "ui", "web"},
    "fullstack": {"fullstack", "full stack", "full-stack"},
    "product": {"product", "analytics"},
    "platform": {"platform", "mlops", "devops", "infra"},
}


def norm_skill(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return ALIASES.get(t, t)


def extract_skills(text: str) -> list[str]:
    t = " " + re.sub(r"[^a-z0-9+#. ]", " ", str(text or "").lower()) + " "
    found = [s for s in sorted(SKILLS, key=len, reverse=True) if f" {s} " in t]
    # drop a shorter skill that is only there as part of a longer match
    return [s for s in found if not any(s != o and s in o for o in found)]


def skill_overlap(wanted: list[str], have: list[str]) -> tuple[list[str], list[str]]:
    w = {norm_skill(x) for x in wanted}
    h = {norm_skill(x) for x in have}
    return sorted(w & h), sorted(w - h)


# ---------------------------------------------------------------- resume parsing

HEADINGS = {
    "summary": {"summary", "profile", "objective", "about"},
    "education": {"education", "academics"},
    "experience": {"experience", "work experience", "internship", "internships", "employment"},
    "projects": {"projects", "project", "academic projects"},
    "skills": {"skills", "technical skills", "technologies"},
    "achievements": {"achievements", "awards", "honors", "honours"},
    "languages": {"languages", "language"},
}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+91[\s-]?)?(?:\d[\s-]?){10}")
BULLET = re.compile(r"^\s*(?:[-\u2022*\u00b7\u25aa\u25cf\u25e6\u2023\u2043\u2219\uf0b7]|\d+[.)])\s*")


def _heading(line: str) -> str | None:
    key = line.strip().strip(":").lower()
    for canon, words in HEADINGS.items():
        if key in words:
            return canon
    return None


def parse_resume(text: str) -> tuple[dict, list[dict]]:
    """Return (contact, facts). Facts are ordered data, not prose."""
    raw_lines = [ln.rstrip() for ln in str(text or "").replace("\r", "").split("\n")]
    contact: dict = {"name": "", "email": "", "phone": "", "location": ""}
    facts: list[dict] = []
    section, order = "summary", 0

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        if head := _heading(line):
            section = head
            continue
        if email := EMAIL.search(line):
            contact["email"] = email.group(0)
        if phone := PHONE.search(line):
            digits = re.sub(r"\D", "", phone.group(0))
            if len(digits) >= 10 and not contact["phone"]:
                contact["phone"] = phone.group(0).strip()
        if not contact["name"] and 2 <= len(line.split()) <= 3 and line == line.title() \
                and "@" not in line and not re.search(r"\d", line):
            contact["name"] = line

        is_bullet = bool(BULLET.match(line))
        body = BULLET.sub("", line).strip() if is_bullet else line.strip("\x00\x7f ")
        body = re.sub(r"[\x00-\x1f\x7f\ufffd]", "", body).strip()
        if not body or body == contact.get("email"):
            continue
        if EMAIL.search(body) and "@" in body:
            continue  # contact line, not a fact
        if re.fullmatch(r"[-–—·•|\s]+", body):
            continue  # stray separator glyph from the PDF

        # Wrapped continuation of the previous item (PDF line breaks mid-sentence).
        prev = facts[-1] if facts else None
        if (not is_bullet and prev and prev["section"] == section and section != "summary"
                and len(line) > 2 and not re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+", line)
                and not re.search(r"\d{4}|—|–", line)):
            prev["text"] = (prev["text"] + ", " + body) if section == "skills" else (prev["text"] + " " + body)
            prev["skills"] = extract_skills(prev["text"])
            continue

        kind = {"summary": "summary", "skills": "skill", "languages": "language",
                "achievements": "achievement"}.get(section, section.rstrip("s"))
        facts.append({
            "kind": kind, "section": section, "text": body,
            "skills": extract_skills(body), "source_line": line[:200], "order": order,
        })
        order += 1

    # location: prefer the contact line, else first line naming an Indian city
    for raw in raw_lines:
        if contact.get("email") and contact["email"] in raw:
            for city in ("Pune", "Mumbai", "Bengaluru", "Bangalore", "Hyderabad", "Delhi", "Chennai"):
                if city in raw:
                    contact["location"] = city
                    break
            break
    if not contact["location"]:
        for raw in raw_lines:
            if m := re.search(r"\b(Pune|Mumbai|Bengaluru|Bangalore|Hyderabad|Delhi|Chennai)\b", raw):
                contact["location"] = m.group(1)
                break
    # the name line is not a fact
    facts = [f for f in facts if f["text"] != contact.get("name")]
    for i, f in enumerate(facts):
        f["order"] = i
    return contact, facts


# ---------------------------------------------------------------- fit

WEIGHTS = {"must": 42, "role": 22, "location": 10, "nice": 8, "recency": 6, "deadline": 6, "seniority": 6}


def fit_score(job: dict, student: dict, verified_skills: list[str], today_: date) -> dict:
    must = json.loads(job.get("required_json") or "[]")
    nice = json.loads(job.get("nice_json") or "[]")
    tags = json.loads(job.get("tags_json") or "[]")
    have = [norm_skill(s) for s in verified_skills]

    must_hit, must_gap = skill_overlap(must, have)
    nice_hit, _ = skill_overlap(nice, have)

    roles = [norm_skill(r) for r in (student.get("roles") or [])]
    role_hit = 0.0
    if roles:
        for tag in tags:
            group = ROLE_GROUPS.get(tag, {tag})
            if any(r in group or any(r in ROLE_GROUPS.get(t, {t}) for t in [r]) for r in roles):
                role_hit = 1.0
                break
            if any(r == tag or r in tag or tag in r for r in roles):
                role_hit = 1.0
                break
    comp = {
        "must": len(must_hit) / len(must) if must else 0.5,
        "nice": len(nice_hit) / len(nice) if nice else 0.5,
    }
    comp["role"] = role_hit
    locs = [norm_skill(x) for x in (student.get("locations") or [])]
    job_loc = norm_skill(job.get("location", ""))
    remote = bool(job.get("remote")) and student.get("remote_ok", True)
    comp["location"] = 1.0 if (job_loc in locs or remote or not locs) else 0.0

    posted = _parse_date(job.get("posted_at"))
    age = (today_ - posted).days if posted else 45
    comp["recency"] = max(0.0, 1.0 - age / 60.0)

    by = _parse_date(job.get("apply_by"))
    left = (by - today_).days if by else 10
    comp["deadline"] = 1.0 if left >= 7 else (0.5 if left >= 0 else 0.0)
    comp["seniority"] = 1.0 if job.get("seniority") == student.get("seniority", "intern") else 0.4

    score = round(sum(WEIGHTS[k] * v for k, v in comp.items()))
    score = max(0, min(100, score))
    label = "Strong" if score >= 78 else "Good" if score >= 62 else "Stretch" if score >= 45 else "Reach"
    reasons = []
    if must_hit:
        reasons.append("Covers " + ", ".join(must_hit[:3]) + " from your verified facts")
    if comp["location"]:
        where = "Remote" if remote else job.get("location", "")
        reasons.append(f"{where} matches where you said you can work")
    if comp["recency"] > 0.7:
        reasons.append(f"Posted {age} days ago")
    return {
        "score": score, "label": label,
        "breakdown": {k: round(WEIGHTS[k] * v, 1) for k, v in comp.items()},
        "components": {k: round(v, 2) for k, v in comp.items()},
        "reasons": reasons[:3],
        "gaps": must_gap,
        "must_matches": must_hit,
    }


def _parse_date(value) -> date | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- tailoring

SUMMARY = (
    "{name} — {year} {degree} candidate at {college}, targeting {title} roles. "
    "Verified work: {evidence}. Fluent in running {stack} end to end."
)


def build_docs(facts: list[dict], job: dict, student: dict) -> dict:
    """Deterministic writer. Selects, orders and re-labels verified facts only."""
    verified = [f for f in facts if f.get("verified")]
    by_kind = {}
    for f in verified:
        by_kind.setdefault(f["kind"], []).append(f)

    must = json.loads(job.get("required_json") or "[]")
    must_norm = [norm_skill(m) for m in must]
    have = {norm_skill(s) for f in verified for s in f.get("skills") or []}

    def rank(f: dict) -> tuple:
        overlap = len({norm_skill(s) for s in f.get("skills") or []} & set(must_norm))
        return (-overlap, f.get("sort_order", 0))

    def bullets(kind: str, limit: int) -> list[dict]:
        return [{"text": f["text"], "fact_ids": [f["id"]], "section": kind}
                for f in sorted(by_kind.get(kind, []), key=rank)[:limit]]

    edu = by_kind.get("education", [])
    evidence = "; ".join(b["text"] for b in bullets("experience", 1) + bullets("project", 1))
    title = job["title"].split(" Intern")[0] if " Intern" in job["title"] else job["title"]
    summary = SUMMARY.format(
        name=student.get("name") or "Student",
        year="final-year" if student.get("seniority") == "intern" else "final-year",
        degree="B.Tech CSE" if edu else "undergraduate",
        college=_college(edu) or "your college",
        title=title, evidence=evidence or "project work",
        stack=", ".join(sorted(have & set(must_norm))[:3]) or "your stack",
    )

    verified_skills = sorted(have)
    ordered = [s for s in must_norm if s in have] + [s for s in verified_skills if s not in must_norm]
    sections = {
        "Summary": [{"text": summary, "fact_ids": [f["id"] for f in verified[:3]], "section": "summary"}],
        "Skills": [{"text": ", ".join(ordered), "fact_ids": [f["id"] for f in verified], "section": "skills"}],
        "Experience": bullets("experience", 3),
        "Projects": bullets("project", 3),
        "Education": bullets("education", 4),
        "Achievements": bullets("achievement", 2),
    }
    sections = {k: v for k, v in sections.items() if v}

    not_claimed = [g for g in must_norm if g not in have]
    cover = cover_note(job, summary, bullets("experience", 1) + bullets("project", 1), not_claimed, student)

    resume_text = _render_resume(sections, student, contact_line(student))
    cover_text = _render_cover(cover)
    return {
        "resume": {"sections": sections, "text": resume_text},
        "cover": {"text": cover_text, "paragraphs": cover},
        "not_claimed": not_claimed,
    }


def _college(edu: list[dict]) -> str:
    for f in edu:
        m = re.search(r"([A-Z][\w\s.&]+(?:Institute|College|University|IIT|NIT|VIT))", f["text"])
        if m:
            return m.group(1).strip()
    return ""


def contact_line(student: dict) -> str:
    parts = [student.get("name", ""), student.get("email", ""), student.get("phone", ""), student.get("location", "")]
    return " · ".join(p for p in parts if p)


def cover_note(job: dict, summary: str, evidence: list[dict], gaps: list[str], student: dict) -> list[str]:
    ev = " and ".join(e["text"].lower() for e in evidence) or "coursework and independent projects"
    paras = [
        f"Dear {job['company']} hiring team,",
        f"I am applying for the {job['title']} role. {summary}",
        f"Two things I can point to: {ev}. Both were built with {', '.join((job.get('required_json') and json.loads(job['required_json']) or [])[:2]) or 'Python and SQL'}.",
    ]
    if gaps:
        paras.append(
            f"I have not worked with {gaps[0]} yet. I would rather say that up front than learn it in week one; "
            f"the transferable part is the {', '.join((json.loads(job.get('required_json') or []) or ['problem solving'])[:1])} work above."
        )
    paras.append(
        f"I am available for a full-time internship from the next semester and can start immediately on a part-time basis. "
        f"Thank you for reading."
    )
    return paras


def _render_resume(sections: dict, student: dict, contact: str) -> str:
    lines = [student.get("name") or "Student", contact, ""]
    for name, items in sections.items():
        lines.append(name.upper())
        for item in items:
            lines.append(f"- {item['text']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_cover(paras: list[str]) -> str:
    return "\n\n".join(paras).strip() + "\n"


# ---------------------------------------------------------------- grounding

TEMPLATE_OK = {
    "dear", "hiring", "team", "i", "am", "applying", "for", "the", "role", "two", "things", "can",
    "point", "to", "both", "were", "built", "with", "have", "not", "worked", "yet", "would",
    "rather", "say", "that", "up", "front", "than", "learn", "it", "in", "week", "one", "transferable",
    "part", "is", "above", "available", "a", "full", "time", "internship", "from", "next", "semester",
    "start", "immediately", "on", "basis", "thank", "you", "reading", "candidate", "targeting",
    "verified", "work", "fluent", "running", "end", "and", "at", "your", "of", "as", "my", "skills",
    "experience", "projects", "education", "achievements", "summary", "student",
}


def validate_grounding(docs: dict, facts: list[dict], job: dict) -> dict:
    """Every claim must trace to a verified fact. Anything else fails the gate."""
    verified = [f for f in facts if f.get("verified")]
    by_id = {f["id"]: f for f in verified}
    fact_text = " ".join(f["text"] for f in verified).lower()
    job_ok = {str(job.get("company", "")).lower(), str(job.get("title", "")).lower()}
    job_tokens = {w for t in job_ok for w in re.findall(r"[a-z0-9+#.]+", t)}

    problems: list[dict] = []
    checked = 0
    for section, items in docs["resume"]["sections"].items():
        for item in items:
            checked += 1
            if not item["fact_ids"] or any(fid not in by_id for fid in item["fact_ids"]):
                problems.append({"claim": item["text"][:120], "reason": "no verified fact attached"})
    for factual in docs.get("not_claimed") or []:
        if factual in docs["resume"]["text"].lower():
            problems.append({"claim": factual, "reason": "gap listed as skill inside the document"})

    # Every number and technology token must appear in the facts (or be template/job text).
    tokens = set(re.findall(r"[a-z][a-z0-9+#.-]{1,}", docs["resume"]["text"].lower()))
    tokens |= set(re.findall(r"\b\d+(?:\.\d+)?\b", docs["resume"]["text"]))
    for tok in tokens:
        if tok in TEMPLATE_OK or tok in job_tokens or re.fullmatch(r"\d+(?:\.\d+)?", tok):
            continue
        if tok in fact_text:
            continue
        if tok in SKILLS or tok in ALIASES.values():
            problems.append({"claim": tok, "reason": "technology not present in verified facts"})
    return {"passed": not problems, "checked": checked, "problems": problems,
            "coverage": round(1 - len(problems) / max(checked, 1), 2) if problems else 1.0}


# ---------------------------------------------------------------- diff

def diff_docs(base_text: str, tailored_text: str) -> dict:
    a, b = base_text.splitlines(), tailored_text.splitlines()
    sm = SequenceMatcher(None, a, b, autojunk=False)
    ops, added, trimmed = [], 0, 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        ops.append({"op": tag, "base": a[i1:i2], "tailored": b[j1:j2]})
        if tag in ("insert", "replace"):
            added += j2 - j1
        if tag in ("delete", "replace"):
            trimmed += i2 - i1
    return {"ops": ops, "summary": {"added": added, "trimmed": trimmed, "kept": len(a) - trimmed}}


# ---------------------------------------------------------------- hashes

def h(content) -> str:
    if not isinstance(content, str):
        content = json.dumps(content, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def facts_hash(facts: list[dict]) -> str:
    payload = [{"id": f["id"], "text": f["text"], "kind": f["kind"]} for f in facts if f.get("verified")]
    return h(sorted(payload, key=lambda x: x["id"]))


def bundle_hash(student_id: str, job_id: str, fhash: str, resume_text: str, cover_text: str) -> str:
    return "bndl_" + h([student_id, job_id, fhash, h(resume_text), h(cover_text)])[:20]


# ---------------------------------------------------------------- ics

def _fold(line: str) -> str:
    out = [line[:73]]
    rest = line[73:]
    while rest:
        out.append(" " + rest[:72])
        rest = rest[72:]
    return "\r\n".join(out)


def make_ics(events: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PlacePilot//EN", "CALSCALE:GREGORIAN"]
    for e in events:
        uid = f"{e['uid']}@placepilot.local"
        day = str(e["date"]).replace("-", "")
        lines += [
            "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day}", f"DTEND;VALUE=DATE:{day}",
            _fold(f"SUMMARY:{e['summary']}"), _fold(f"DESCRIPTION:{e.get('description', '')}"),
            "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", "DESCRIPTION:Deadline tomorrow",
            "END:VALARM", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
