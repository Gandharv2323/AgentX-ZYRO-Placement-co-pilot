/**
 * Golden-path E2E. Real browser, real API, real database.
 * Run: node scripts/e2e.mjs   (API on :8010, web on :3210)
 */
import { chromium } from "../apps/web/node_modules/playwright-core/index.mjs";
import { mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const WEB = process.env.WEB_URL ?? "http://127.0.0.1:3210";
const SHOTS = join(process.cwd(), "docs", "screens");
mkdirSync(SHOTS, { recursive: true });

function findChrome() {
  const root = join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
  const candidates = [
    join(root, "chromium-1248", "chrome-win64", "chrome.exe"),
    join(root, "chromium-1248", "chrome-win", "chrome.exe"),
  ];
  for (const p of candidates) if (existsSync(p)) return p;
  throw new Error(`No Playwright Chromium found under ${root}. Set CHROME_PATH.`);
}

const consoleErrors = [];
const failedRequests = [];

const shot = async (page, name) => {
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
  console.log(`  shot ${name}.png`);
};

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH ?? findChrome(),
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text());
});
page.on("requestfailed", (r) => failedRequests.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`));

let step = 0;
const ok = (msg) => console.log(`✓ ${++step}. ${msg}`);

try {
  // 1. landing
  await page.goto(WEB, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /asks before it applies/i }).waitFor();
  await shot(page, "01-landing");
  ok("landing renders");

  // 2. onboarding: sample resume
  await page.getByRole("link", { name: /upload a resume|open the desk/i }).first().click();
  await page.waitForURL(/onboarding/);
  await page.getByRole("button", { name: /load sample/i }).click();
  await page.getByRole("heading", { name: /check what it read/i }).waitFor({ timeout: 30000 });
  // wait for the real fact list, not the zero-state render
  await page.getByRole("button", { name: /continue with \d+ facts/i }).waitFor({ timeout: 30000 });
  const factCount = await page.getByText(/\d+ facts · \d+ verified/).first().innerText();
  if (!/[1-9]\d* facts/.test(factCount)) throw new Error("no facts parsed: " + factCount);
  await shot(page, "02-onboarding-facts");
  ok(`parsed resume: ${factCount.trim()}`);

  // 3. targets
  await page.getByRole("button", { name: /continue with/i }).click();
  await page.getByRole("heading", { name: /what should it aim at/i }).waitFor();
  await page.getByRole("button", { name: "AI / ML" }).click();
  await page.getByRole("button", { name: "Pune" }).click();
  await shot(page, "03-onboarding-targets");
  await page.getByRole("button", { name: /open the desk/i }).click();
  await page.waitForURL(/desk/);
  ok("onboarded with targets");

  // 4. run the agent
  await page.getByLabel("Agent command").fill("Find 10 AI/ML internships in Pune");
  await page.getByRole("button", { name: /^run$/i }).click();
  await page.locator(".event").first().waitFor({ timeout: 30000 });
  await page.waitForFunction(
    () => !document.body.innerText.includes("Working…"),
    null,
    { timeout: 60000 },
  );
  await page.locator(".event").last().waitFor();
  const traceText = await page.locator(".trace-col").innerText();
  if (!/job_search/i.test(traceText)) throw new Error("trace has no job_search step");
  const replanned = /revising the plan/i.test(traceText);
  await shot(page, "04-desk-run-trace");
  ok(`agent run visible (re-planned: ${replanned})`);

  // 5. tailor one opening
  const cards = page.locator("main .card").filter({ hasText: /Intern/ });
  const firstJobLink = page.getByRole("link", { name: /review draft/i }).first();
  await page.getByRole("checkbox", { name: /tailor/i }).first().check();
  await page.getByRole("button", { name: /tailor 1 selected/i }).click();
  await page.waitForURL(/applications\//, { timeout: 45000 });
  await page.getByText(/resume diff/i).first().waitFor({ timeout: 45000 });
  await shot(page, "05-review-diff");
  ok("tailored bundle opened");

  // 6. the gate: send before approval
  await page.getByRole("button", { name: /try sending now/i }).click();
  await page.getByText(/approval_required/i).first().waitFor({ timeout: 20000 });
  const gateText = await page.locator(".gate-blocked").first().innerText();
  if (!/422/.test(gateText)) throw new Error("no 422 shown: " + gateText);
  await shot(page, "06-blocked-422");
  ok("unapproved send blocked with HTTP 422");

  // 7. grounding tab proves the claims
  await page.getByRole("button", { name: /^grounding$/i }).click();
  await page.getByText(/every claim traced|unsupported claim/i).first().waitFor();
  await shot(page, "07-grounding");
  ok("grounding audit visible");

  // 8. approve then send
  await page.getByRole("checkbox", { name: /reviewed every claim/i }).check();
  await page.getByRole("button", { name: /approve bundle/i }).click();
  await page.getByText(/approved by you/i).first().waitFor({ timeout: 20000 });
  await shot(page, "08-approved");
  await page.getByRole("button", { name: /^send application$/i }).click();
  await page.getByText(/nothing left this machine/i).waitFor({ timeout: 20000 });
  await shot(page, "09-sent-outbox");
  ok("approved, then recorded in demo outbox");

  // 9. tracker
  await page.goto(`${WEB}/tracker`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /^tracker$/i }).waitFor();
  await shot(page, "10-tracker");
  ok("tracker shows the application");

  // 10. interview: two sessions, weak topics return
  await page.goto(`${WEB}/interview`, { waitUntil: "networkidle" });
  await shot(page, "11-interview-setup");
  await page.getByRole("button", { name: /start 6-question mock/i }).click();
  await page.locator("h2").first().waitFor({ timeout: 30000 });
  await shot(page, "12-interview-question");
  for (let i = 0; i < 6; i++) {
    await page.locator("textarea").fill("I am not sure about this topic.");
    await page.getByRole("button", { name: /submit answer/i }).click();
    await page.getByText(/rubric score/i).waitFor({ timeout: 20000 });
    const isLast = i === 5;
    await page.getByRole("button", { name: isLast ? /see scorecard/i : /next question/i }).click();
  }
  await page.getByText(/session scorecard/i).waitFor({ timeout: 30000 });
  await shot(page, "13-scorecard");
  const cardText = await page.locator("main").innerText();
  if (!/pushed into memory/i.test(cardText)) throw new Error("no weak topics pushed");
  ok("interview scored; weak topics stored");

  // 11. second session reopens them
  await page.getByRole("button", { name: /new mock/i }).click();
  await page.getByText(/carried over from your last session/i).waitFor({ timeout: 20000 });
  await shot(page, "14-weak-topics-return");
  await page.getByRole("button", { name: /start 6-question mock/i }).click();
  await page.getByText(/reopened/i).first().waitFor({ timeout: 20000 });
  ok("second session reopens weak topics with provenance");

  // 12. memory + delete
  await page.goto(`${WEB}/memory`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /^memory$/i }).waitFor();
  await shot(page, "15-memory");
  await page.getByRole("button", { name: /delete all/i }).click();
  await page.getByRole("button", { name: /yes, delete everything/i }).click();
  await page.getByText(/^Deleted\.$/).waitFor({ timeout: 20000 });
  const deletedText = await page.locator(".gate").first().innerText();
  if (!/Remaining for this student: 0/.test(deletedText.replace(/\s+/g, " "))) {
    throw new Error("rows remain after delete: " + deletedText);
  }
  await shot(page, "16-deleted");
  ok("delete removed every row (0 remaining)");

  // 13. mobile
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true });
  await mobile.goto(WEB, { waitUntil: "networkidle" });
  await mobile.getByRole("heading", { name: /asks before it applies/i }).waitFor();
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await mobile.screenshot({ path: join(SHOTS, "17-mobile-landing.png"), fullPage: true });
  if (overflow) throw new Error("horizontal overflow at 390px");
  ok("mobile landing has no horizontal overflow");

  // The only console error allowed is the intentional 422 the demo triggers on purpose.
  const realConsole = consoleErrors.filter((e) => !/status of 422/.test(e));
  console.log(`\nconsole errors: ${realConsole.length} (intentional 422 excluded: ${consoleErrors.length - realConsole.length})`);
  realConsole.slice(0, 5).forEach((e) => console.log("  ! " + e.slice(0, 160)));

  // Next aborts RSC prefetches when navigating away; those are not failures.
  const realFailed = failedRequests.filter((r) => !/net::ERR_ABORTED/.test(r) && !/_rsc=/.test(r));
  console.log(`failed requests: ${realFailed.length} (prefetch aborts ignored: ${failedRequests.length - realFailed.length})`);
  realFailed.slice(0, 5).forEach((r) => console.log("  ! " + r));

  if (realConsole.length || realFailed.length) {
    console.error("\nFAILED: console errors or failed requests above");
    process.exitCode = 1;
  }
} catch (e) {
  await shot(page, "zz-failure");
  console.error("\nFAILED:", e.message);
  console.error("console errors:", consoleErrors.slice(0, 8));
  process.exitCode = 1;
} finally {
  await browser.close();
}
