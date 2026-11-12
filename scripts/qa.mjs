/**
 * Visual/DOM quality checks that don't need eyes: overflow, contrast, clipping,
 * tap targets, heading order. Runs against the live app.
 * Run: node scripts/qa.mjs
 */
import { chromium } from "../apps/web/node_modules/playwright-core/index.mjs";
import { join } from "node:path";
import { existsSync } from "node:fs";

const WEB = process.env.WEB_URL ?? "http://127.0.0.1:3210";
const chrome = join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1248", "chrome-win64", "chrome.exe");
if (!existsSync(chrome)) throw new Error("chromium missing");

const browser = await chromium.launch({ executablePath: chrome, args: ["--no-sandbox"] });
const problems = [];

function report(kind, detail) {
  problems.push(`${kind}: ${detail}`);
  console.log(`  ✗ ${kind}: ${detail}`);
}

/** WCAG relative luminance contrast for the given fg/bg. */
const CONTRAST_FN = `(fg, bg) => {
  const lum = (c) => {
    const [r, g, b] = c.map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = lum(fg), c = lum(bg);
  return (Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05);
}`;

const PAGES = ["/", "/onboarding", "/desk", "/tracker", "/interview", "/memory"];

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1280, height: 800 },
  { name: "mobile", width: 390, height: 844 },
]) {
  console.log(`\n[${viewport.name} ${viewport.width}px]`);
  const page = await browser.newPage({ viewport, isMobile: viewport.width < 500 });
  // seed a profile so data screens have content
  await page.goto(WEB, { waitUntil: "domcontentloaded" });

  for (const path of PAGES) {
    await page.goto(WEB + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(350);

    const res = await page.evaluate((contrastSrc) => {
      const contrast = eval(contrastSrc);
      const parse = (c) => (c.match(/[\d.]+/g) ?? []).slice(0, 4).map(Number);
      const out = { overflow: [], contrast: [], tap: [], clipped: [], headings: [], small: [] };

      // horizontal overflow of the document
      if (document.documentElement.scrollWidth > window.innerWidth + 1) {
        out.overflow.push(`document ${document.documentElement.scrollWidth}px > ${window.innerWidth}px`);
      }
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.right > window.innerWidth + 2 && getComputedStyle(el).position !== "fixed") {
          out.overflow.push(`${el.tagName.toLowerCase()}.${(el.className || "").toString().slice(0, 24)} right=${Math.round(r.right)}`);
          if (out.overflow.length > 6) break;
        }
      }

      // text contrast against the nearest opaque ancestor background
      const bgOf = (el) => {
        let n = el;
        while (n && n !== document.documentElement) {
          const c = getComputedStyle(n).backgroundColor;
          const p = parse(c);
          if (p.length >= 3 && (p[3] === undefined || p[3] > 0.7)) return p.slice(0, 3);
          n = n.parentElement;
        }
        return [7, 7, 8];
      };
      const seen = new Set();
      for (const el of document.querySelectorAll("p,span,a,button,td,th,li,label,h1,h2,h3,h4,strong,b")) {
        const txt = (el.textContent ?? "").trim();
        if (!txt || el.children.length > 0) continue;
        const st = getComputedStyle(el);
        if (st.visibility === "hidden" || st.display === "none" || Number(st.opacity) < 0.3) continue;
        const key = txt.slice(0, 30) + st.color;
        if (seen.has(key)) continue;
        seen.add(key);
        const fg = parse(st.color).slice(0, 3);
        const ratio = contrast(fg, bgOf(el));
        const size = parseFloat(st.fontSize);
        const large = size >= 18.66 || (size >= 14 && Number(st.fontWeight) >= 700);
        const min = large ? 3 : 4.5;
        if (ratio < min) out.contrast.push(`"${txt.slice(0, 28)}" ${ratio.toFixed(2)}:1 (needs ${min}) ${size}px`);
      }

      // interactive targets
      for (const el of document.querySelectorAll("button, a, input[type=checkbox]")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.height < 24) out.tap.push(`${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 20)}" h=${Math.round(r.height)}`);
      }

      // text clipped without ellipsis (content wider than its box)
      for (const el of document.querySelectorAll("p,span,td,th,h1,h2,h3,h4,strong")) {
        if (el.children.length) continue;
        const st = getComputedStyle(el);
        if (st.overflow === "visible" && st.whiteSpace !== "nowrap") continue;
        if (el.scrollWidth > el.clientWidth + 2 && st.textOverflow !== "ellipsis" && el.clientWidth > 0) {
          out.clipped.push(`"${(el.textContent ?? "").trim().slice(0, 26)}" ${el.scrollWidth}>${el.clientWidth}`);
        }
      }

      // heading order
      const lv = [...document.querySelectorAll("h1,h2,h3,h4")].map((h) => Number(h.tagName[1]));
      out.headings = lv;
      return out;
    }, CONTRAST_FN);

    const name = path === "/" ? "landing" : path.slice(1);
    if (res.overflow.length) report("overflow", `${name}(${viewport.name}) ${res.overflow.join(" | ")}`);
    for (const c of res.contrast.slice(0, 4)) report("contrast", `${name}(${viewport.name}) ${c}`);
    for (const t of res.tap.slice(0, 3)) report("tap-target", `${name}(${viewport.name}) ${t}`);
    for (const c of res.clipped.slice(0, 3)) report("clipped", `${name}(${viewport.name}) ${c}`);
    if (res.headings.length && res.headings[0] !== 1) report("heading", `${name}(${viewport.name}) first heading h${res.headings[0]}`);
    if (res.headings.some((l, i, a) => i > 0 && l - a[i - 1] > 1)) report("heading-order", `${name}(${viewport.name}) ${res.headings.join(",")}`);

    console.log(`  ${name}: overflow=${res.overflow.length} contrast=${res.contrast.length} tap=${res.tap.length} clipped=${res.clipped.length}`);
  }
  await page.close();
}

await browser.close();
console.log(`\n${problems.length} issue(s)`);
if (problems.length) process.exitCode = 1;
