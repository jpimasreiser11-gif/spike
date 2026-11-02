// G8 focused browser check for Replay modal keyboard/slider/focus-trap accessibility and ProofDownload Escape/outside dismissal.
// Runs against in-memory Vite + real Chromium with simulated ChatEvents: no SPIKE server, no model, no network.
// Usage (from web/): node e2e/replay.mjs [screenshotDir]
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = process.argv[2] || "e2e/screenshots";
fs.mkdirSync(out, { recursive: true });
const fail = (msg) => { console.error("FAIL:", msg); process.exitCode = 1; };

const ENTRY = "/__g8_harness.tsx";
const HARNESS = `
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import "/src/styles.css";
import { ProofDownload } from "/src/components/ProofDownload";
import { Replay } from "/src/components/Replay";
import type { ChatEvent, Specialist } from "/src/types";

const SPECIALISTS: Specialist[] = [
  {
    id: "core",
    name: "Spike Core",
    domain: "General",
    description: "Generalist",
    adapter: null,
    adapter_status: "none",
    sensitive: false,
    tools: [],
  },
];

const EVENTS: ChatEvent[] = [
  { type: "status", message: "starting", t: 0.0 },
  { type: "route", mode: "single", method: "rule", confidence: 1, specialists: [{ id: "core", name: "Spike Core" }], t: 0.1 },
  { type: "tool_call", id: "c1", name: "read_file", arguments: { path: "README.md" }, t: 0.3 },
  { type: "tool_result", id: "c1", name: "read_file", ok: true, content: "# SPIKE", t: 0.5 },
  { type: "delta", text: "Resumen verificado sin desbordamiento.", t: 0.8 },
];

function Harness() {
  const [open, setOpen] = useState(false);
  const [emptyMode, setEmptyMode] = useState(false);
  return (
    <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="row" style={{ alignItems: "center", gap: 12 }}>
        <button id="open-replay" className="btn primary" onClick={() => { setEmptyMode(false); setOpen(true); }}>
          Open replay
        </button>
        <button id="open-empty-replay" className="btn" onClick={() => { setEmptyMode(true); setOpen(true); }}>
          Open empty replay
        </button>
        <ProofDownload conversationId="conv-g8" />
      </div>
      {open && (
        <Replay
          events={emptyMode ? [{ type: "status", message: "stopped" }] : EVENTS}
          specialists={SPECIALISTS}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Harness />);
`;

const virtualHarness = {
  name: "g8-replay-harness",
  resolveId: (id) => (id === ENTRY ? ENTRY : null),
  load: (id) => (id === ENTRY ? HARNESS : null),
  configureServer(srv) {
    srv.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/__g8.html")) return next();
      const html = await srv.transformIndexHtml(
        req.url,
        `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
          `<title>G8 Replay & ProofDownload harness</title></head><body><div id="root"></div>` +
          `<script type="module" src="${ENTRY}"></script></body></html>`,
      );
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(html);
    });
  },
};

const server = await createServer({
  root,
  logLevel: "error",
  plugins: [virtualHarness],
  server: { host: "127.0.0.1", port: 5199, strictPort: false },
});
await server.listen();
const base = server.resolvedUrls.local[0];
const executablePath = [
  process.env.CHROMIUM_PATH,
  "/Users/jpima/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell",
  "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
].find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile());
const browser = await chromium.launch(executablePath ? { executablePath } : {});

const runs = [
  { name: "wide-light", viewport: { width: 1360, height: 860 }, colorScheme: "light" },
  { name: "narrow-dark", viewport: { width: 375, height: 760 }, colorScheme: "dark" },
];

try {
  for (const run of runs) {
    const ctx = await browser.newContext({ viewport: run.viewport, colorScheme: run.colorScheme });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${base}__g8.html`);

    // 1. ProofDownload Escape + outside click
    await page.locator("details.proof-download > summary").click();
    if (!(await page.locator("details.proof-download").evaluate((el) => el.open))) {
      fail(`${run.name}: ProofDownload did not open`);
    }
    await page.locator('details.proof-download input[value="chat"]').focus();
    await page.keyboard.press("Escape");
    const afterEsc = await page.evaluate(() => ({
      open: document.querySelector("details.proof-download").open,
      focusedSummary: document.activeElement === document.querySelector("details.proof-download > summary"),
    }));
    if (afterEsc.open || !afterEsc.focusedSummary) {
      fail(`${run.name}: ProofDownload Escape failed: ${JSON.stringify(afterEsc)}`);
    }

    await page.locator("details.proof-download > summary").click();
    await page.mouse.click(10, run.viewport.height - 10);
    if (await page.locator("details.proof-download").evaluate((el) => el.open)) {
      fail(`${run.name}: ProofDownload outside click did not close details`);
    }

    // 2. Replay modal focus move, single-step range ArrowRight, Tab wrap, and Escape focus restore
    await page.locator("#open-replay").focus();
    await page.keyboard.press("Enter");
    await page.locator('[role="dialog"]').waitFor();

    const initialInside = await page.evaluate(() =>
      document.querySelector('[role="dialog"]').contains(document.activeElement),
    );
    if (!initialInside) fail(`${run.name}: initial focus did not move inside Replay dialog`);

    // Focus range slider and press real browser ArrowRight: must advance 1 / 4 -> 2 / 4, NOT 3 / 4!
    const slider = page.locator('[role="dialog"] input[type="range"]');
    await slider.focus();
    await page.keyboard.press("ArrowRight");
    const stepText = await page.locator(".modal-head .muted").textContent();
    if (!stepText?.includes("2 / 4")) {
      fail(`${run.name}: range ArrowRight expected '2 / 4', got '${stepText}'`);
    }

    // Tab 20 times: focus must never escape [role="dialog"]
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() =>
        document.querySelector('[role="dialog"]').contains(document.activeElement),
      );
      if (!inside) fail(`${run.name}: Tab escaped Replay modal at iteration ${i}`);
    }

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 0) fail(`${run.name}: horizontal overflow ${overflow}px`);

    await page.screenshot({ path: `${out}/g8-${run.name}.png` });

    await page.keyboard.press("Escape");
    await page.locator('[role="dialog"]').waitFor({ state: "detached" });
    const restored = await page.evaluate(() => document.activeElement?.id);
    if (restored !== "open-replay") {
      fail(`${run.name}: focus not restored to #open-replay on Escape, got '${restored}'`);
    }

    // 3. Empty replay displays 0 / 0 cleanly
    await page.locator("#open-empty-replay").click();
    const emptyText = await page.locator(".modal-head .muted").textContent();
    if (!emptyText?.includes("0 / 0")) {
      fail(`${run.name}: empty replay expected '0 / 0', got '${emptyText}'`);
    }
    await page.keyboard.press("Escape");

    if (errors.length) fail(`${run.name}: page errors: ${errors.join(" | ")}`);
    console.log(`${run.name}: ok`);
    await ctx.close();
  }
} finally {
  await browser.close();
  await server.close();
}
