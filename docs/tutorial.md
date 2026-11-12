# PlacePilot — video walkthrough

**File:** `docs/tutorial.mp4` · 3 min 6 s · 1280×720 · narrated with burned-in captions.
Recorded against the real app (no mockups) by `scripts/tutorial.mjs`.

## Chapters

| Time | Scene | What to watch for |
|---|---|---|
| 0:00 | Landing | The one-line pitch and the three deck stats with their source |
| 0:12 | Resume intake | "Give the agent something true to work with" |
| 0:17 | **Verified facts** | 13 facts; unchecking one makes it unusable for tailoring |
| 0:31 | Targets | Roles + locations steer search *and* interview mix |
| 0:39 | **The run** | Trace shows plan → tool call → observe → **re-plan** → verify |
| 0:52 | Ranked list | Fit breakdown, matched skills, named gaps |
| 1:05 | Tailor | Diff against the base resume |
| 1:15 | **Not claimed** | Kubernetes listed as a gap, never written into the document |
| 1:26 | **The gate** | `HTTP 422 approval_required` from the endpoint itself |
| 1:40 | Grounding | Every claim mapped to the fact it came from |
| 1:50 | Approve → Send | Bundle-hash bound; lands in the local demo outbox |
| 1:59 | Tracker | Deadline, status, `.ics` export |
| 2:11 | Interview | Rubric-scored question |
| 2:20 | **Memory** | Weak topics stored with the score that put them there |
| 2:32 | Delete all | Every row gone, zero FK violations |
| 2:49 | Outro | Architecture in one line: FastAPI + SQLite, Next on top |

## How the video was made

`scripts/tutorial.mjs` is a single pipeline:

1. Each scene's narration is synthesized to WAV (Windows SAPI, "Zira") and measured with `ffprobe`,
   so the script knows the exact duration of every line before filming.
2. Playwright drives the real app while recording; each scene holds for its narration length.
3. Because acting time varies, one global speed-up would drift the captions. Instead the script
   records per-scene wall-clock spans, then **retimes each segment to its own narration length**
   and concatenates them. Captions are generated from the same timings, so they cannot drift.
4. ffmpeg burns the captions in, muxes the narration, and writes a faststart H.264/AAC MP4.

Re-record (needs both servers up):

```powershell
node scripts\tutorial.mjs
```

Re-encode without re-filming (reuses the take and narration in `.cache\tutorial`):

```powershell
$env:REUSE_RECORDING='1'; node scripts\tutorial.mjs
```

Editing narration only: change the `say:` strings in `scripts/tutorial.mjs` and re-record. Changing
what a scene *does* means editing its `act:` block — keep the actions shorter than the spoken line,
or the scene will end before the narration finishes.

## Verification done on the output

- `ffprobe`: 186.2 s, video 1280×720 @ 30 fps, audio AAC present and equal in length
- audio levels: mean −20.8 dB, peak −2.2 dB (not silent)
- captions: bright text pixels present in the bottom band of frames sampled at 8/42/96/150 s
- sync: frames sampled mid-scene match the expected screen — no sidebar during landing/onboarding,
  sidebar during desk/review/tracker/memory, and the lime-tinted gate card at 1:32
