# Limitations, stated plainly

1. **No LLM in the shipped path.** Every ranking, draft and interview score is deterministic.
   That is deliberate: it is reproducible, free, and the grounding validator can check its output
   precisely. The cost is prose quality — the cover note is templated, not written.
2. **No live job API.** 50 seeded listings with fictional companies. Swapping in Adzuna means
   implementing `Toolkit.search_jobs` against its response shape and caching; the tool contract and
   run trace would not change.
3. **"Sending" records, it does not email.** `send_application` writes an immutable outbox row and
   flips the application status. No SMTP, no third party. The approval gate is real; the delivery is not.
4. **Interview scoring is rubric keyword coverage.** An answer can score without being good. It is
   honest about this in the UI ("Score is rubric coverage, not fluency"). An LLM judge would score
   better and cost money, keys and determinism.
5. **Hindi support is question text + keyword variants + browser TTS.** Not a full localisation,
   and the scorer does not do morphology.
6. **Resume parsing handles single-column text PDFs.** Two-column layouts and scans are rejected
   (`parse_failed`) rather than half-parsed; you can add facts by hand.
7. **No auth.** One local student per browser id. Binding to `127.0.0.1` is the security boundary.
8. **Not reused from ProbeIQ:** its code. It has no license and is LLM-first. The session-store and
   per-topic-scoring *pattern* is credited, and the interview schema here is an independent implementation.
9. **`dedupe` and cache TTL for a real jobs API, multi-worker serving, and deployment are not built.**
   SQLite + one uvicorn worker + one Next process is the intended shape for a local demo.

## Known environment constraints (this machine)

- `venv`'s `ensurepip` fails, and the `py` launcher points at a uv-managed interpreter that is not
  executable here. Deps were installed with `uv` against the explicit `Python313` interpreter.
- Node cannot spawn children with piped stdio under the restricted sandbox, which blocks every
  `next build`/`next dev`/Chromium launch. With full file access the build and the Playwright run work.
- AppData temp/caches are not writable under the restriction; `scripts/dev.ps1` redirects `TMP`,
  `TEMP`, npm, uv and Chrome profile paths into `.cache/` inside the repo.
