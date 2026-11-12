/**
 * Records the PlacePilot tutorial: real browser, real narration, real app.
 *
 *   node scripts/tutorial.mjs
 *
 * 1. Every scene says its line out loud (SAPI -> WAV) so we know its true duration.
 * 2. The browser then performs each scene while recording; the video is held
 *    exactly as long as that scene's audio.
 * 3. ffmpeg burns subtitles, muxes the narration and writes docs/tutorial.mp4.
 */
import { chromium } from "../apps/web/node_modules/playwright-core/index.mjs";
import { spawn, execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const WEB = process.env.WEB_URL ?? "http://127.0.0.1:3210";
const OUT = join(process.cwd(), "docs");
const TMP = join(process.cwd(), ".cache", "tutorial");
mkdirSync(OUT, { recursive: true });
mkdirSync(TMP, { recursive: true });

const W = 1280, H = 720, FPS = 30;

// ----------------------------------------------------------------- script
const SCENES = [
  {
    id: "intro",
    say: "PlacePilot is a placement agent that asks before it applies. It searches openings, tailors each application from facts you verified, and sends nothing without your yes.",
    act: async (p) => { await p.goto(WEB, { waitUntil: "networkidle" }); await p.waitForTimeout(600); },
  },
  {
    id: "resume",
    say: "We start by giving it something true to work with. Load the sample resume.",
    act: async (p) => {
      await p.getByRole("link", { name: /upload a resume|open the desk/i }).first().click();
      await p.waitForURL(/onboarding/);
      await p.waitForTimeout(800);
    },
  },
  {
    id: "facts",
    say: "It reads the PDF and splits it into individual facts. Thirteen here. Everything is checked, and only checked facts can enter a tailored resume. Uncheck one and it stops being usable.",
    act: async (p) => {
      await p.getByRole("button", { name: /load sample/i }).click();
      await p.getByRole("button", { name: /continue with \d+ facts/i }).waitFor({ timeout: 30000 });
      await p.waitForTimeout(1200);
      const box = p.locator('input[type="checkbox"]').nth(2);
      await box.uncheck();
      await p.waitForTimeout(900);
      await box.check();
      await p.waitForTimeout(600);
    },
  },
  {
    id: "targets",
    say: "Then the targets: which roles, and where you can actually work. This steers both the search and the interview mix.",
    act: async (p) => {
      await p.getByRole("button", { name: /continue with/i }).click();
      await p.waitForTimeout(700);
      await p.getByRole("button", { name: "AI / ML" }).click();
      await p.waitForTimeout(400);
      await p.getByRole("button", { name: "Pune" }).click();
      await p.waitForTimeout(900);
      await p.getByRole("button", { name: /open the desk/i }).click();
      await p.waitForURL(/desk/);
      await p.waitForTimeout(700);
    },
  },
  {
    id: "run",
    say: "Now ask for openings in plain language. Watch the trace on the right: it plans, calls a tool, observes the result, then revises its own plan when there are not enough matches.",
    act: async (p) => {
      await p.getByLabel("Agent command").fill("Find 10 AI/ML internships in Pune");
      await p.waitForTimeout(600);
      await p.getByRole("button", { name: /^run$/i }).click();
      await p.locator(".event").first().waitFor({ timeout: 30000 });
      await p.waitForFunction(() => !document.body.innerText.includes("Working…"), null, { timeout: 60000 });
      await p.waitForTimeout(2200);
    },
  },
  {
    id: "ranked",
    say: "Every opening gets a fit score you can audit: skills matched, location, how recent the post is, and how close the deadline. Missing skills are named as gaps, never quietly invented.",
    act: async (p) => {
      await p.mouse.wheel(0, 260);
      await p.waitForTimeout(1600);
      await p.mouse.wheel(0, -160);
      await p.waitForTimeout(700);
    },
  },
  {
    id: "tailor",
    say: "Select one and tailor it. Only your verified facts are eligible, so the agent selects and reorders. It does not add claims.",
    act: async (p) => {
      await p.getByRole("checkbox", { name: /tailor/i }).first().check();
      await p.waitForTimeout(600);
      await p.getByRole("button", { name: /tailor 1 selected/i }).click();
      await p.waitForURL(/applications\//, { timeout: 45000 });
      await p.getByText(/resume diff/i).first().waitFor();
      await p.waitForTimeout(2000);
    },
  },
  {
    id: "gaps",
    say: "This is the honest part. The posting wants Kubernetes, which is not in the facts. So it is listed as not claimed. It never appears in the document.",
    act: async (p) => {
      await p.mouse.wheel(0, 420);
      await p.waitForTimeout(2200);
      await p.mouse.wheel(0, -420);
      await p.waitForTimeout(700);
    },
  },
  {
    id: "gate",
    say: "Now the claim the whole product rests on. Try to send it. The endpoint refuses with four twenty two, approval required. That is not a disabled button, it is the server saying no.",
    act: async (p) => {
      await p.getByRole("button", { name: /try sending now/i }).click();
      await p.getByText(/approval_required/i).first().waitFor({ timeout: 20000 });
      await p.waitForTimeout(2600);
    },
  },
  {
    id: "grounding",
    say: "Before approving, open grounding. Every claim in the draft is mapped back to the fact it came from. Nothing here is unattributed.",
    act: async (p) => {
      await p.getByRole("button", { name: /^grounding$/i }).click();
      await p.getByText(/every claim traced|unsupported claim/i).first().waitFor();
      await p.waitForTimeout(2400);
    },
  },
  {
    id: "approve",
    say: "Confirm you reviewed it, and approve. The approval is tied to this exact bundle. Edit a fact later and that yes expires.",
    act: async (p) => {
      await p.getByRole("checkbox", { name: /reviewed every claim/i }).check();
      await p.waitForTimeout(700);
      await p.getByRole("button", { name: /approve bundle/i }).click();
      await p.getByText(/approved by you/i).first().waitFor({ timeout: 20000 });
      await p.waitForTimeout(1800);
      await p.getByRole("button", { name: /^send application$/i }).click();
      await p.getByText(/nothing left this machine/i).waitFor({ timeout: 20000 });
      await p.waitForTimeout(2200);
    },
  },
  {
    id: "tracker",
    say: "Sent. In this demo that means an immutable local record, no email leaves the machine. The tracker holds the deadline, and the calendar feed exports to dot ics.",
    act: async (p) => {
      await p.goto(`${WEB}/tracker`, { waitUntil: "networkidle" });
      await p.waitForTimeout(2400);
    },
  },
  {
    id: "interview",
    say: "Then practice. Six questions, scored against a rubric per topic. Answer badly on purpose here.",
    act: async (p) => {
      await p.goto(`${WEB}/interview`, { waitUntil: "networkidle" });
      await p.waitForTimeout(900);
      await p.getByRole("button", { name: /start 6-question mock/i }).click();
      await p.locator("h2").first().waitFor({ timeout: 30000 });
      await p.waitForTimeout(1600);
      await p.locator("textarea").fill("I am not sure about this topic.");
      await p.waitForTimeout(700);
      await p.getByRole("button", { name: /submit answer/i }).click();
      await p.getByText(/rubric score/i).waitFor({ timeout: 20000 });
      await p.waitForTimeout(1800);
    },
  },
  {
    id: "memory",
    say: "Finish it. Topics you scored badly on go into memory, with the score that put them there. Start another mock and those topics come back first, labelled with where they came from.",
    act: async (p) => {
      for (let i = 1; i < 6; i++) {
        await p.getByRole("button", { name: /next question/i }).click();
        await p.waitForTimeout(300);
        await p.locator("textarea").fill("I am not sure about this topic.");
        await p.getByRole("button", { name: /submit answer/i }).click();
        await p.getByText(/rubric score/i).waitFor({ timeout: 20000 });
        await p.waitForTimeout(320);
      }
      await p.getByRole("button", { name: /see scorecard/i }).click();
      await p.getByText(/session scorecard/i).waitFor({ timeout: 30000 });
      await p.waitForTimeout(2600);
      await p.getByRole("button", { name: /new mock/i }).click();
      await p.getByText(/carried over from your last session/i).waitFor({ timeout: 20000 });
      await p.waitForTimeout(2600);
    },
  },
  {
    id: "delete",
    say: "Finally, privacy. Memory shows everything stored. Delete all removes every row for this student: facts, drafts, approvals, outbox, interview scores. Zero remaining, and the app drops back to onboarding.",
    act: async (p) => {
      await p.goto(`${WEB}/memory`, { waitUntil: "networkidle" });
      await p.waitForTimeout(1800);
      await p.getByRole("button", { name: /^delete all$/i }).click();
      await p.waitForTimeout(900);
      await p.getByRole("button", { name: /yes, delete everything/i }).click();
      await p.getByText(/^Deleted\.$/).waitFor({ timeout: 20000 });
      await p.waitForTimeout(2800);
    },
  },
  {
    id: "outro",
    say: "That is PlacePilot. FastAPI and SQLite underneath, Next dot j s on top. No keys required, everything local. The gate you saw is enforced in the route, in the agent tool, and again by a database trigger.",
    act: async (p) => {
      await p.goto(WEB, { waitUntil: "networkidle" });
      await p.waitForTimeout(2000);
    },
  },
];

// ----------------------------------------------------------------- narration
// Windows PowerShell 5.1 is the only shell here, so narration runs from a script file.
const PS_FILE = join(TMP, "narrate.ps1");
writeFileSync(
  PS_FILE,
  [
    "param([string]$Text, [string]$Out)",
    "Add-Type -AssemblyName System.Speech",
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
    "$s.Rate = 0",
    "try { $s.SelectVoice('Microsoft Zira Desktop') } catch { }",
    "$s.SetOutputToWaveFile($Out)",
    "$s.Speak($Text)",
    "$s.Dispose()",
  ].join("\r\n"),
  "utf8",
);

const POWERSHELL = join(process.env.SystemRoot ?? "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");

function narrate(scene) {
  const wav = join(TMP, `say-${scene.id}.wav`);
  execFileSync(
    POWERSHELL,
    ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS_FILE, "-Text", scene.say, "-Out", wav],
    { stdio: "ignore" },
  );
  const dur = Number(
    execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav]).toString().trim(),
  );
  return { wav, dur };
}

// ----------------------------------------------------------------- helpers
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function srtTime(t) {
  const ms = Math.round(t * 1000);
  const h = String(Math.floor(ms / 3600000)).padStart(2, "0");
  const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
  const s = String(Math.floor((ms % 60000) / 1000)).padStart(2, "0");
  return `${h}:${m}:${s},${String(ms % 1000).padStart(3, "0")}`;
}

const wrap = (text, max = 46) => {
  const words = text.split(" ");
  const lines = [];
  let line = "";
  for (const w of words) {
    if ((line + " " + w).trim().length > max) { lines.push(line.trim()); line = w; }
    else line += " " + w;
  }
  if (line.trim()) lines.push(line.trim());
  return lines;
};

// ----------------------------------------------------------------- run
const REUSE = process.env.REUSE_RECORDING === "1" && existsSync(join(TMP, "voice.wav")) &&
  existsSync(join(TMP, "tutorial.srt")) && existsSync(join(TMP, "take.webm"));

console.log("1/3 narrating scenes…");
const timings = [];
let cursor = 0;
if (REUSE && existsSync(join(TMP, "timings.json"))) {
  const saved = JSON.parse(readFileSync(join(TMP, "timings.json"), "utf8"));
  for (const s of saved.scenes) timings.push({ ...SCENES.find((x) => x.id === s.id), wav: s.wav, dur: s.dur, start: s.start });
  cursor = saved.total;
  console.log(`   reused ${timings.length} scenes, ${cursor.toFixed(1)}s`);
} else if (REUSE) {
  // narration WAVs already on disk: measure them instead of speaking again
  for (const scene of SCENES) {
    const wav = join(TMP, `say-${scene.id}.wav`);
    if (!existsSync(wav)) throw new Error(`missing narration ${wav}; run without REUSE_RECORDING`);
    const dur = Number(
      execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav]).toString().trim(),
    );
    timings.push({ ...scene, wav, dur, start: cursor });
    cursor += dur;
    console.log(`   ${scene.id.padEnd(11)} ${dur.toFixed(2)}s (existing)`);
  }
} else {
  for (const scene of SCENES) {
    const { wav, dur } = narrate(scene);
    timings.push({ ...scene, wav, dur, start: cursor });
    cursor += dur;
    console.log(`   ${scene.id.padEnd(11)} ${dur.toFixed(2)}s`);
  }
}
const total = cursor;
console.log(`   total ${total.toFixed(1)}s`);

// subtitles
let srt = "";
timings.forEach((t, i) => {
  const lines = wrap(t.say);
  srt += `${i + 1}\n${srtTime(t.start)} --> ${srtTime(t.start + t.dur - 0.05)}\n${lines.join("\n")}\n\n`;
});
writeFileSync(join(TMP, "sub.srt"), srt, "utf8");
writeFileSync(join(TMP, "tutorial.srt"), srt, "utf8");
writeFileSync(
  join(TMP, "timings.json"),
  JSON.stringify({ total, scenes: timings.map((t) => ({ id: t.id, wav: t.wav, dur: t.dur, start: t.start })) }),
  "utf8",
);

console.log("2/3 recording…");
let raw;
if (REUSE) {
  raw = join(TMP, "take.webm");
  console.log("   reusing existing recording");
} else {
  const browser = await chromium.launch({
    executablePath: join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1248", "chrome-win64", "chrome.exe"),
    args: ["--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1"],
  });
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    recordVideo: { dir: TMP, size: { width: W, height: H } },
  });
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of 422/.test(m.text())) console.log("   ! console:", m.text().slice(0, 120));
  });

  const started = Date.now();
  const spans = [];
  for (const scene of timings) {
    process.stdout.write(`   ${scene.id}\n`);
    const w0 = (Date.now() - started) / 1000;
    const t0 = Date.now();
    try {
      await scene.act(page);
    } catch (e) {
      console.log(`   ! ${scene.id} action failed: ${e.message.split("\n")[0]}`);
    }
    const used = (Date.now() - t0) / 1000;
    await sleep(Math.max(0.3, scene.dur - used) * 1000 + 250);
    const w1 = (Date.now() - started) / 1000;
    spans.push({ id: scene.id, w0, w1, dur: scene.dur });
  }
  const wall = (Date.now() - started) / 1000;
  const video = page.video();
  await context.close();
  await browser.close();
  raw = await video.path();
  writeFileSync(join(TMP, "wall.txt"), String(wall), "utf8");
  writeFileSync(join(TMP, "spans.json"), JSON.stringify(spans), "utf8");
  console.log(`   recorded ${wall.toFixed(1)}s of wall time, target ${total.toFixed(1)}s`);
}

console.log("3/3 assembling video…");
// audio track: concatenate the narration WAVs
const list = join(TMP, "audio.txt");
writeFileSync(list, timings.map((t) => `file '${t.wav.replace(/\\/g, "/")}'`).join("\n"), "utf8");
const voice = join(TMP, "voice.wav");
execFileSync("ffmpeg", ["-y", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", voice], { stdio: "ignore" });

// The recording is longer than the narration (setup time between scenes). A single global
// rescale would drift; instead each scene's recorded span is retimed to its exact narration
// length and the pieces are concatenated, so captions land on the right frames.
const wall = existsSync(join(TMP, "wall.txt"))
  ? Number(readFileSync(join(TMP, "wall.txt"), "utf8"))
  : Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", raw]).toString().trim());

const spansFile = join(TMP, "spans.json");
const segments = [];
if (existsSync(spansFile)) {
  const spans = JSON.parse(readFileSync(spansFile, "utf8"));
  spans.forEach((s, i) => {
    const from = s.w0;
    const len = s.w1 - s.w0;
    const target = i === spans.length - 1 ? total - s.dur * i : s.dur;
    segments.push({ from, len, target, id: s.id });
  });
  // trim the tail of the last scene to land exactly on the audio length
  const sumBefore = segments.slice(0, -1).reduce((a, s) => a + s.target, 0);
  segments[segments.length - 1].target = Math.max(0.5, total - sumBefore);
} else {
  const retime = wall / total;
  segments.push({ from: 0, len: wall, target: total, id: "whole", speed: retime });
}

const trims = segments
  .map((s, i) => {
    const speed = s.len / s.target;
    return `[0:v]trim=start=${s.from.toFixed(3)}:end=${(s.from + s.len).toFixed(3)},setpts=(PTS-STARTPTS)/${speed.toFixed(6)}[v${i}]`;
  })
  .join(";");
const concat = segments.map((_, i) => `[v${i}]`).join("") + `concat=n=${segments.length}:v=1:a=0[cat]`;

const style =
  "FontName=Segoe UI,FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3," +
  "Outline=1.6,Shadow=0,BackColour=&H99000000,MarginV=26";

const srtName = "sub.srt";
const post = [
  `scale=${W}:${H}:flags=lanczos`,
  `subtitles=${srtName}:force_style='${style}'`,
  "format=yuv420p",
].join(",");

execFileSync(
  "ffmpeg",
  ["-y", "-i", raw, "-i", voice,
   "-filter_complex", `${trims};${concat};[cat]${post}[v]`,
   "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
   "-r", String(FPS), "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
   join(OUT, "tutorial.mp4")],
  { stdio: ["ignore", "ignore", "pipe"], cwd: TMP },
);

const mb = (readFileSync(join(OUT, "tutorial.mp4")).length / 1048576).toFixed(1);
console.log(`\ndone: ${outFile} (${mb} MB, ${total.toFixed(0)}s)`);
console.log(`subtitles: ${join(TMP, "sub.srt")}`);
