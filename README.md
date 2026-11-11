# PlacePilot — a placement agent that asks before it applies

AgentX Hackathon 2026 · PS-06 · Team ZYRO (team code 79257B)
Built from `ZYRO_PlacePilot_AgentX_PS06.pptx.pdf`.

One resume in, ranked openings, tailored applications that can only use facts you verified,
a deadline tracker, and mock interviews that remember your weak topics.
**Nothing is sent until you approve the exact bundle — enforced in the API and again in the database.**

## Run it

Two processes. The API and the web app are separate on purpose (FastAPI + Next.js, as the deck claims).

```powershell
# 1. API  (terminal 1)
cd apps\api
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --port 8010

# 2. Web  (terminal 2)
cd apps\web
npm run build; npm run start -- -p 3210
```

Open <http://127.0.0.1:3210>. Nothing else is required — no API keys, no network.

If your ports are taken, use any pair; the web app finds the API on `http://127.0.0.1:8010` by
default, or from `?api=http://127.0.0.1:PORT` once, which it remembers.

### First run only

```powershell
# API deps (uv is used because venv's ensurepip is unavailable on this machine)
uv venv apps\api\.venv --python "C:\Users\sidde\AppData\Local\Programs\Python\Python313\python.exe"
uv pip install --python apps\api\.venv\Scripts\python.exe -r apps\api\requirements.txt

# sample resume PDF + seed the 50 listings
cd apps\api; .\.venv\Scripts\python.exe -m app.sample
```

The database is created at `apps\api\data\placepilot.db` and seeded with 50 listings on first start.

## The three-minute demo

1. **Landing → "Upload a resume" → Load sample.** 13 facts appear, each one you can uncheck. Say the line: *"only verified facts can enter a tailored resume."*
2. **Desk → "Find 10 AI/ML internships in Pune".** Watch the trace: plan → tool call → observe → **re-plan** (it widens recency, then drops the location filter, and says how many listings were past deadline) → verify → ranked list with fit breakdown and named gaps.
3. **Select one → Tailor.** The diff opens. Show *"Deliberately not claimed"* — Kubernetes/Tableau are listed as gaps, never written in.
4. **Click "Try sending now".** `HTTP 422 approval_required` appears, with the bundle hash. Say: *"this is not a disabled button, it's the endpoint refusing."*
5. **Approve → Send.** Recorded in the local demo outbox: *no email left this machine.* Tracker and `.ics` update.
6. **Interview → Start mock.** Answer badly on purpose. Scorecard shows per-topic scores; DBMS/ML drop into memory. Start another mock — **those topics reopen first, with the score that put them there.**
7. **Memory → Delete all.** The response shows `Remaining for this student: 0` and zero FK violations. Export first if you want to show the evidence.

## Verify it yourself

```powershell
cd apps\api; .\.venv\Scripts\python.exe -m pytest        # 13 tests
cd apps\web; npm run build                                # typecheck + production build
node scripts\e2e.mjs                                      # full golden path, 13 checks + 17 screenshots
node scripts\qa.mjs                                       # overflow/contrast/tap targets on 6 pages × 3 viewports
```

`docs/screens/` holds the screenshots the E2E wrote.

## What is real, what is simulated

| Real | Simulated / labelled |
|---|---|
| Resume parsing from a PDF, fact extraction, verification state | The 50 job listings (fictional companies, `example.com` URLs) |
| Deterministic fit score with a published breakdown | "Sending" writes to a local outbox; no email is dispatched |
| Tailoring + grounding validator (unsupported claims are rejected) | Interview scoring is rubric keyword coverage, not an LLM judge |
| Bundle hashing, approval state, staleness detection | Adzuna and Anthropic adapters are **not wired** — no keys, so no live calls |
| HTTP 422 on unapproved send, plus a SQLite trigger that blocks bypass | Hindi questions are authored, scoring keywords are Hindi variants |

The approval gate is the one claim worth checking hardest:

- route layer: `POST /api/applications/{id}/send` → 422 `approval_required`
- agent tool layer: `send_application` goes through the same guard
- database layer: `outbox_needs_approval` trigger aborts a raw insert without a matching approved bundle

All three have tests (`apps/api/tests/test_flow.py`).

## Boundaries

- Single local student, no auth. Identity is a browser-generated id sent as `X-Student-Id`.
- Sending is `record` mode only; there is no SMTP configuration to turn on.
- Scanned/image PDFs are rejected with a clear error rather than guessed at.
- English UI; Hindi exists for interview questions.
- Richer stats from the deck (44% not job-ready, <5 min per application) are quoted with their source;
  the fit score is a heuristic, not a hiring prediction.

## Ports used

This machine already had something on :3000 and :8000, so the project runs on :8010 (API) and :3210 (web). scripts\dev.ps1 uses the same pair; override with PLACEPILOT_API_PORT / PLACEPILOT_WEB_PORT.
