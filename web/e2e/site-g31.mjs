// Browser check of the static landing page (G31): no horizontal scroll at 375 px, no third-party requests, screenshots.
// Usage (from web/): node e2e/site-g31.mjs <baseUrl of the site/ folder> <screenshotDir>
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const base = (process.argv[2] || "http://127.0.0.1:8766").replace(/\/$/, "");
const out = process.argv[3] || "e2e/screenshots";
fs.mkdirSync(out, { recursive: true });
const executablePath = [process.env.CHROMIUM_PATH, "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"].find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile());
const browser = await chromium.launch(executablePath ? { executablePath } : {});
let failed = false;
for (const [lang, url] of [["en", `${base}/index.html`], ["es", `${base}/es/index.html`]]) {
  for (const width of [375, 1280]) {
    const page = await (await browser.newContext({ viewport: { width, height: 800 }, colorScheme: "light" })).newPage();
    const external = [];
    page.on("request", (r) => { if (!r.url().startsWith(base)) external.push(r.url()); });
    const bad = [];
    page.on("response", (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url()}`); });
    await page.goto(url, { waitUntil: "networkidle" });
    const m = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth,
      interLoaded: document.fonts.check("16px Inter"),
      wide: [...document.querySelectorAll("body *")]
        .filter((e) => !e.closest(".table-wrap") && e.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
        .map((e) => e.tagName + "." + e.className).slice(0, 5),
    }));
    const ok = m.scrollWidth <= m.clientWidth && !external.length && !bad.length && !m.wide.length;
    if (!ok) failed = true;
    console.log(JSON.stringify({ lang, width, ...m, external, bad, ok }));
    const file = path.join(out, `site-${lang}-${width}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(file, fs.statSync(file).size, "bytes");
  }
}
await browser.close();
if (failed) process.exit(1);
