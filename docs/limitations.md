# Limitations, stated plainly

0. **Adzuna and the Claude planner are implemented but never ran live.** No API keys existed in
   this environment, so both are proven only through fake-transport contract tests (16 of them,
   `tests/test_providers.py`). The request construction, response mapping, fallback behaviour and
   guardrails are tested; a real HTTP round-trip is not. Configure keys per `docs/providers.md`
   and the same code path goes live unmodified.
1. **The default path has no LLM.** Rankings, drafts and interview scores are deterministic.
   That is deliberate: reproducible, free, and the grounding validator can check its output
   precisely. With a key set, the planner becomes Claude-driven; tailoring and scoring stay
   deterministic and grounded.
2. **Job listings are seeded** (50 fictional companies) unless Adzuna keys are configured.
3. **"Sending" records, it does not email.** `send_application` writes an immutable outbox row and
   flips the application status. No SMTP, no third party. The approval gate is real; delivery is not.
4. **Interview scoring is rubric keyword coverage** (rule-based, no LLM). It is honest about this
   in the UI ("Score is rubric coverage, not fluency").
5. **Tailoring prose is templated**, not model-written, even when the LLM planner is enabled.
   Extending it means routing `draft_docs` through the model and letting `validate_grounding`
   gate the result — the validator is already the standard there.
6. **Hindi support is question text + keyword variants + browser TTS.** Not full localisation.
7. **Resume parsing handles single-column text PDFs.** Two-column layouts and scans are rejected
   (`parse_failed`) rather than half-parsed; facts can be added by hand.
8. **No auth.** One local student per browser id. Binding to `127.0.0.1` is the security boundary.
9. **Not reused from ProbeIQ:** its code. It has no license and is LLM-first. The session-store and
   per-topic-scoring *pattern* is credited; the schema here is an independent implementation.
10. **No deployment, no CI, no multi-worker serving.** SQLite + one uvicorn worker + one Next
    process is the intended shape for a local demo.

## Known environment constraints (this machine)

- `venv`'s `ensurepip` fails, and the `py` launcher points at a uv-managed interpreter that is not
  executable here. Deps were installed with `uv` against the explicit `Python313` interpreter.
- Node cannot spawn children with piped stdio under the restricted sandbox, which blocks every
  `next build`/`next dev`/Chromium launch. With full file access the build and Playwright work.
- AppData temp/caches are not writable under the restriction; `scripts/dev.ps1` redirects `TMP`,
  `TEMP`, npm, uv and Chrome profile paths into `.cache/` inside the repo.
- Chromium cannot launch at all under the restriction (its IPC needs named pipes), which is why
  the browser verification and the tutorial recording were run with full file access.

