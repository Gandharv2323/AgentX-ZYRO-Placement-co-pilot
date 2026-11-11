# Deck → build traceability

Every claim on the submission deck, and where it lives in the build. Slide numbers follow
`ZYRO_PlacePilot_AgentX_PS06.pptx.pdf` (page 1 = cover, then 01…05).

| Deck | Claim | In the app | Proof |
|---|---|---|---|
| 1 | "Resume in, tailored applications out" | `/onboarding` → `/desk` → `/applications/[id]` | `e2e.mjs` steps 2, 5 |
| 1 | "sends nothing without their yes" | Approval gate | `test_send_is_blocked_with_422_until_approved` |
| 01 | One generic resume to hundreds of openings | Fit-ranked shortlist with named gaps | `test_fit_score_is_deterministic_and_explainable` |
| 01 | Deadlines hide in tabs | Tracker + `.ics` feed + T-3/T-1 reminders | `/tracker`, `core.make_ics` tests |
| 01 | Mock interviews give no scored feedback | 6-question rubric-scored mock | `test_interview_scores_topics_and_reopens_weak_ones` |
| 02 | "Plans its own steps" | Persisted run events, phase per step | `/desk` trace column, `run_events` |
| 02 | "It sends nothing without a yes" | 422 + DB trigger | `test_database_trigger_blocks_unapproved_insert` |
| 02 | "Remembers across sessions" | `topics`, `memories` tables fed into the next plan/interview | `test_..._reopens_weak_ones`, `/memory` |
| 02 | Optional Hindi–English practice | `language=hi` questions + `hi-IN` speech | `test_hindi_questions_are_served_in_hindi` |
| 03 | Input / Process / Output / Action | Onboarding → run trace → ranked list → approve/track | `e2e.mjs` steps 2–9 |
| 03 | Next.js · FastAPI · SQLite | `apps/web`, `apps/api`, `apps/api/data/*.db` | repo layout |
| 03 | Claude tool use | **Not wired** (no key). Deterministic planner is the shipped path; the tool registry it would call is exposed at `/api/agent/tools` | `docs/limitations.md` |
| 03 | Adzuna + mock jobs | **Mock only**, 50 seeded listings; source column ready | `test_search_run_traces_every_step_and_replans` |
| 03 | Calendar `.ics`/API | `GET /api/calendar.ics`, per-application reminders | `test_ics_folds_long_lines_and_has_alarm` |
| 03 | "Every tool call is logged" | `tool_calls` + `/api/memory` history | `/memory` tool table |
| 03 | "send blocked at the API layer (HTTP 422)" | Exactly that | `e2e.mjs` step 6, screenshot `06-blocked-422.png` |
| 03 | plan → act → observe → verify → memory | Same five phases emitted as events | `test_search_run_traces_every_step_and_replans` |
| 04 | Jobs API limits → cache + mock fallback | 50-listing seed used first; no external call at runtime | `healthz.jobs == 50` |
| 04 | LLM invents resume facts → tailor only from facts, show diff | Grounding validator + "not claimed" list + line diff | `test_grounding_rejects_skills_outside_facts` |
| 04 | Data stays local, one-click delete | SQLite + `DELETE /api/students/me` | `test_delete_removes_every_row_for_the_student` |
| 04 | Reuse ProbeIQ interviewer + session store | Adapted the typed session/score idea; **code not vendored** (unlicensed, LLM-only) | `docs/limitations.md` |
| 05 | 44% not job-ready (India Skills Report 2026) | Quoted on landing with source | landing copy |
| 05 | <5 min per tailored application | One action tailors up to 3 bundles; generation time shown per draft | review header `draft v1, generated deterministic` |
| 05 | 100% approval at the API layer | Gate above | as above |
| 05 | References (ProbeIQ, LinguaSwitch, approval-gate pattern) | README + limitations, credited | `docs/limitations.md` |

## Deliberate deviations

- **No live Claude/Adzuna.** No keys exist in this environment, so shipping untested network code
  as the demo path would have been a lie. The deterministic planner is the product; adapters are the next step.
- **No ProbeIQ import.** It has no license, needs OpenRouter, and its interviewer is LLM-first.
  The *pattern* (typed session, per-topic 1–5 scores, session store) is what was reused.
- **Send = local outbox.** The deck promises an approval gate, not a mail server. A demo that
  quietly emails strangers would be worse than one that records honestly.
