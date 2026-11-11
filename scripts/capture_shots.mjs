/**
 * Capture the README's showcase screenshots from the running app.
 * Writes to docs/assets/shots/. Deterministic: seeds its own student each run.
 */
import { chromium } from "../apps/web/node_modules/playwright-core/index.mjs";
import { join } from "node:path";
import { existsSync, mkdirSync } from "node:fs";

const WEB = process.env.WEB ?? "http://127.0.0.1:3220";
const API = process.env.API ?? "http://127.0.0.1:8060";
const OUT = join(process.cwd(), "docs", "assets", "shots");
mkdirSync(OUT, { recursive: true });

const chrome = join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1248", "chrome-win64", "chrome.exe");
if (!existsSync(chrome)) throw new Error("chromium not found");

const browser = await chromium.launch({ executablePath: chrome, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
const page = await context.newPage();
await page.addInitScript(() => localStorage.setItem("placepilot.api", "http://127.0.0.1:8060"));

const shot = async (target, name) => {
  const t = target === null ? page : typeof target === "string" ? page.locator(target) : target;
  await t.screenshot({ path: join(OUT, `${name}.png`) });
  console.log("shot", name);
};

try {
  // landing
  await page.goto(WEB, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /asks before it applies/i }).waitFor();
  await shot(null, "01-landing");

  // onboard: sample resume -> facts
  await page.getByRole("link", { name: /upload a resume|open the desk/i }).first().click();
  await page.waitForURL(/onboarding/);
  await page.getByRole("button", { name: /load sample/i }).click();
  await page.getByRole("button", { name: /continue with \d+ facts/i }).waitFor({ timeout: 30000 });
  await shot(null, "02-verified-facts");

  // targets -> desk
  await page.getByRole("button", { name: /continue with/i }).click();
  await page.getByRole("button", { name: "AI / ML" }).click();
  await page.getByRole("button", { name: "Pune" }).click();
  await page.getByRole("button", { name: /open the desk/i }).click();
  await page.waitForURL(/desk/);

  // run + trace
  await page.getByLabel("Agent command").fill("Find 10 AI/ML internships in Pune");
  await page.getByRole("button", { name: /^run$/i }).click();
  await page.locator(".event").first().waitFor({ timeout: 30000 });
  await page.waitForFunction(() => !document.body.innerText.includes("Working…"), null, { timeout: 90000 });
  await page.waitForTimeout(800);
  await shot(null, "03-desk-trace");

  // tailor one -> review
  await page.getByRole("checkbox", { name: /tailor/i }).first().check();
  await page.getByRole("button", { name: /tailor 1 selected/i }).click();
  await page.waitForURL(/applications\//, { timeout: 60000 });
  await page.getByText(/resume diff/i).first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(600);
  await shot(null, "04-review-diff");

  // the gate
  await page.getByRole("button", { name: /try sending now/i }).click();
  await page.getByText(/approval_required/i).first().waitFor({ timeout: 20000 });
  await page.waitForTimeout(400);
  const gate = page.locator(".gate-blocked").first();
  await shot(gate, "05-blocked-422");
  await shot(null, "05-review-blocked");

  // grounding
  await page.getByRole("button", { name: /^grounding$/i }).click();
  await page.getByText(/every claim traced|unsupported claim/i).first().waitFor();
  await page.waitForTimeout(400);
  await shot(null, "06-grounding");

  console.log("done");
} catch (e) {
  console.error("FAILED:", e.message.split("\n")[0]);
  await page.screenshot({ path: join(OUT, "zz-failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
}
