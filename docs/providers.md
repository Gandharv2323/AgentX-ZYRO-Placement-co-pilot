# Optional providers: Adzuna and Claude

Both integrations are **real code with fake-transport tests, and neither is on the demo path.**
Nothing here runs unless you configure it, and the app behaves identically without it.

Honest status: **no live call has ever been made from this machine — no keys were available.**
The contracts below are proven; live behaviour is not. See `docs/limitations.md`.

## Turn on live job listings (Adzuna)

```powershell
$env:ADZUNA_APP_ID  = "your-app-id"
$env:ADZUNA_APP_KEY = "your-app-key"
$env:ADZUNA_COUNTRY = "in"          # optional, default in
$env:PLACEPILOT_JOBS = "adzuna"     # optional: auto (default) | mock | adzuna
```

What happens: `Toolkit.search_jobs` calls `providers.merge_jobs`, which fetches live listings,
maps them into the internal job shape, persists them (so applications can reference them), and
ranks the combined set. The trace shows `source adzuna+mock` and the UI badge shows the split.

Failure is designed to be boring: a timeout, 429, or malformed payload degrades to the seeded
listings and records `fallback: adzuna_unavailable: <reason>` as an `observe` event. The run
never fails because a third party is down. `test_adzuna_http_failure_degrades_to_seed_set` pins this.

## Turn on the Claude planner

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:PLACEPILOT_LLM    = "anthropic"   # auto (default) | off | anthropic
$env:PLACEPILOT_MODEL  = "claude-sonnet-4-5"
```

What happens: `run_search` uses `run_search_llm`, a real tool-use loop over the same registry the
deterministic planner uses (`/api/agent/tools`). Each turn the model picks a tool, we execute it
through the audited executor, and feed the result back. Then `_finish_search` scores, ranks, and
records applications exactly as before.

Guardrails that survive the LLM:

- **Unknown tools are rejected** and the run continues deterministically (`test_llm_cannot_invent_a_tool`).
- **`send_application` is exposed but always guard-blocked** — the approval gate is in the executor
  and a SQLite trigger, not in the prompt (`test_llm_send_attempt_still_blocked_by_approval`).
- **Malformed output falls back mid-run** with a visible `planner_fallback` event, not a dead run.
- **Grounding still validates tailoring** — an LLM draft that invents a claim fails
  `validate_grounding` and cannot be approved.

## Why no keys were used

There were none in the environment, and shipping an untested network path as the demo would have
made the submission dishonest. So the adapters were written to a seam (`providers.http_json`),
and the whole contract is tested through fakes. When you add a key, the same code path runs live
with no edits.

## Verify without keys

```powershell
cd apps\api
.\.venv\Scripts\python.exe -m pytest tests\test_providers.py -v
```

16 tests: mode selection, request construction (keys and query actually sent), response mapping,
fallback on HTTP failure, malformed-plan rejection, LLM-driven run, LLM failure fallback,
unknown-tool rejection, and the send gate holding under an LLM.
