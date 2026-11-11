/**
 * Render the README SVGs to PNG so their layout can be checked (not just XML validity).
 * Uses the installed Playwright Chromium, same as the other scripts.
 */
import { chromium } from "../apps/web/node_modules/playwright-core/index.mjs";
import { join } from "node:path";
import { existsSync, mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";

const root = process.cwd();
const assets = join(root, "docs", "assets");
const out = join(root, ".cache", "svgrender");
mkdirSync(out, { recursive: true });

const chrome = join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1248", "chrome-win64", "chrome.exe");
if (!existsSync(chrome)) throw new Error("chromium not found");

const browser = await chromium.launch({ executablePath: chrome, args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1240, height: 400 }, deviceScaleFactor: 2 });

for (const [file, height] of [["banner.svg", 260], ["pipeline.svg", 300], ["terminal.svg", 420]]) {
  const src = join(assets, file);
  if (!existsSync(src)) continue;
  await page.setViewportSize({ width: 1240, height });
  await page.goto(pathToFileURL(src).href, { waitUntil: "load" });
  await page.waitForTimeout(1600); // let the SVG animations settle at their final state
  const png = join(out, file.replace(".svg", ".png"));
  // screenshot the SVG element itself, not the page around it
  await page.locator("svg").screenshot({ path: png });
  console.log("rendered", png);
}

await browser.close();
