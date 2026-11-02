// G6 browser check of light, OS-dark, explicit-dark, narrow touch and reduced-motion accessibility.
// Evaluates SPIKE's own deterministic spike/dev/visual_checks.js in real Chromium: no SPIKE server, no model, no network.
// Usage (from web/): node e2e/a11y.mjs [screenshotDir]
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = process.argv[2] || "e2e/screenshots";
fs.mkdirSync(out, { recursive: true });
const visualChecksSource = fs.readFileSync(path.resolve(root, "../spike/dev/visual_checks.js"), "utf-8");
const fail = (msg) => { console.error("FAIL:", msg); process.exitCode = 1; };

const ENTRY = "/__g6_harness.tsx";
const HARNESS = `
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import { createRoot } from "react-dom/client";
import "/src/styles.css";

const theme = new URLSearchParams(location.search).get("theme");
if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;

createRoot(document.getElementById("root")!).render(
  <div className="app with-sidebar" style={{ height: "auto", minHeight: "100vh", flexDirection: "column" }}>
    <aside className="sidebar" style={{ position: "static", marginLeft: 0, width: "100%", maxWidth: 320 }}>
      <div className="conv-group">Today</div>
      <div className="conv-list">
        <div className="conv active">
          <button type="button" className="conv-title">Quarterly margin review</button>
          <button type="button" className="icon-btn conv-del" aria-label="Delete chat">×</button>
        </div>
      </div>
      <div className="sidebar-bottom">
        <div className="engine-status"><span className="status-dot on" />Local engine ready</div>
      </div>
    </aside>

    <main className="main" style={{ padding: 16, gap: 14 }}>
      <div className="welcome-mark" style={{ width: 28, height: 28, background: "var(--accent)", borderRadius: 8 }} />
      <div className="flash">Saved default provider</div>

      <form className="composer" onSubmit={(e) => e.preventDefault()}>
        <label className="sr-only" htmlFor="composer-input">Write a message or question for SPIKE</label>
        <textarea id="composer-input" rows={2} defaultValue="Audit contrast across dark surfaces" />
        <div className="composer-bar">
          <button type="button" className="btn small minds-toggle on">Parallel minds · ×3</button>
          <span className="spacer" />
          <button type="submit" className="send-btn" aria-label="Send">→</button>
        </div>
      </form>

      <div className="msg user">
        <button type="button" className="icon-btn edit-btn" aria-label="Edit message">✎</button>
        <div className="bubble"><div className="markdown"><p>Check verified badges and code blocks.</p></div></div>
      </div>

      <section className="card" aria-label="Status badges and links">
        <div className="row" style={{ alignItems: "center" }}>
          <span className="badge ok">2/2 criteria met</span>
          <span className="badge status-trained">trained</span>
          <span className="badge status-evaluated">evaluated</span>
          <span className="badge status-placed">placed</span>
          <span className="badge status-planned">planned</span>
          <span className="badge warn">needs review</span>
          <span className="chip skill-chip">✦ dashboard-creator</span>
          <span className="chip trust-chip ok">1 verified</span>
          <span className="badge claim-badge verified">verified</span>
          <span className="role role-execute">execute</span>
          <span className="role role-verify">verify</span>
        </div>
        <div className="flash-box" role="status">Workspace indexed locally without errors.</div>
        <div className="warn-box">External search sends your query text to the configured provider.</div>
        <div className="error-box">Connection refused on port 8740.</div>
        <div className="permission">
          <div className="permission-title">
            <span>dependency_doctor</span>
            <span className="risk risk-execute">execute</span>
            <span className="risk risk-network">network</span>
          </div>
          <p className="permission-reason">Audits contact package registries.</p>
        </div>
        <div className="markdown">
          <p>
            Read the <a href="#report">isolated verification report</a> or{" "}
            <button type="button" className="link-btn" style={{ minHeight: 24, padding: "2px 4px" }}>show checks</button>{" "}
            and <button type="button" className="link" style={{ minHeight: 24, padding: "2px 4px" }}>make default</button>.
          </p>
        </div>
        <div className="forge-report">
          <div className="ok-text">All deliverables verified</div>
          <ul className="criteria">
            <li className="ok"><span>✓</span> <span>Dark mode meets 4.5:1 text contrast</span></li>
          </ul>
        </div>
        <ul className="tune-rows"><li className="best">Checkpoint 400 · 0.84</li></ul>
        <ul className="evo-checks"><li className="ok"><b>PASS</b> Regression suite</li></ul>
        <div><span className="side side-buy">BUY</span> <span className="muted">10 units · simulated</span></div>
        <button type="button" className="template-card">
          <span className="template-icon" aria-hidden="true">★</span>
          <b>Verified Dashboard</b>
          <span className="muted small">Local HTML artifact</span>
        </button>
      </section>

      <div className="code-block">
        <div className="code-head">
          <span>example.ts</span>
          <button type="button" className="code-copy" style={{ minHeight: 24, padding: "2px 6px" }}>Copy</button>
        </div>
        <pre><code>
          <span className="hljs-keyword">export</span>{" "}
          <span className="hljs-function">verify</span>{" "}
          <span className="hljs-type">ThemeTokens</span><br />
          <span className="hljs-class">Contrast</span>{" "}
          <span className="hljs-title">check</span>{" "}
          <span className="hljs-built_in">Math</span><br />
          <span className="hljs-selector-tag">button</span>{" "}
          <span className="hljs-attr">ratio</span>=
          <span className="hljs-string">"4.5:1"</span><br />
          <span className="hljs-number">4.5</span>{" "}
          <span className="hljs-literal">true</span>{" "}
          <span className="hljs-comment">// WCAG 2.1 AA</span>
        </code></pre>
      </div>

      <div className="trace">
        <div className="trace-item live">
          <button type="button" className="trace-head"><span className="trace-title">Running local check</span></button>
        </div>
      </div>
      <div className="typing" aria-label="Assistant typing">
        <span className="dot" /><span className="dot" /><span className="dot" />
        <span className="muted">Checking...</span>
      </div>
    </main>
  </div>,
);
`;

const virtualHarness = {
  name: "g6-a11y-harness",
  resolveId: (id) => (id === ENTRY ? ENTRY : null),
  load: (id) => (id === ENTRY ? HARNESS : null),
  configureServer(srv) {
    srv.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/__g6.html")) return next();
      const html = await srv.transformIndexHtml(
        req.url,
        `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
          `<title>G6 accessibility harness</title></head><body><div id="root"></div>` +
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
  server: { host: "127.0.0.1", port: 5198, strictPort: false },
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
  { name: "wide-light", viewport: { width: 1360, height: 860 }, colorScheme: "light", query: "?theme=light" },
  { name: "wide-dark-system", viewport: { width: 1360, height: 860 }, colorScheme: "dark", query: "" },
  { name: "wide-dark-explicit", viewport: { width: 1360, height: 860 }, colorScheme: "light", query: "?theme=dark" },
  {
    name: "narrow-dark-reduced-touch",
    viewport: { width: 375, height: 760 },
    colorScheme: "dark",
    reducedMotion: "reduce",
    hasTouch: true,
    isMobile: true,
    query: "",
  },
];

try {
  for (const run of runs) {
    const ctx = await browser.newContext({
      viewport: run.viewport,
      colorScheme: run.colorScheme,
      reducedMotion: run.reducedMotion || "no-preference",
      hasTouch: Boolean(run.hasTouch),
      isMobile: Boolean(run.isMobile),
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${base}__g6.html${run.query}`);
    await page.getByText("2/2 criteria met").waitFor();

    const report = await page.evaluate((src) => window.eval(`(${src})`)(), visualChecksSource);
    const blocking = report.issues.filter((i) => ["contrast", "alt", "label", "overflow"].includes(i.code));
    if (blocking.length) {
      fail(`${run.name}: visual_checks found blocking issues: ${JSON.stringify(blocking)}`);
    }

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 0) fail(`${run.name}: horizontal overflow ${overflow}px`);

    if (run.hasTouch) {
      const touchOpacity = await page.locator(".conv-del").evaluate((el) => getComputedStyle(el).opacity);
      if (touchOpacity !== "1") fail(`${run.name}: .conv-del must be visible on touch devices, got opacity=${touchOpacity}`);
    } else {
      await page.locator(".conv-title").focus();
      const withinOpacity = await page.locator(".conv-del").evaluate((el) => getComputedStyle(el).opacity);
      if (withinOpacity !== "1") fail(`${run.name}: .conv:focus-within must reveal .conv-del, got opacity=${withinOpacity}`);
      await page.keyboard.press("Tab");
      const delState = await page.locator(".conv-del").evaluate((el) => {
        const s = getComputedStyle(el);
        return { active: el === document.activeElement, opacity: s.opacity, outlineStyle: s.outlineStyle, outlineWidth: s.outlineWidth };
      });
      if (!delState.active || delState.opacity !== "1" || delState.outlineStyle !== "solid") {
        fail(`${run.name}: Tab to .conv-del failed focus-visible state: ${JSON.stringify(delState)}`);
      }
    }

    if (run.reducedMotion === "reduce") {
      const motion = await page.evaluate(() => {
        const mark = getComputedStyle(document.querySelector(".welcome-mark"));
        const dot = getComputedStyle(document.querySelector(".typing .dot"));
        const sidebar = getComputedStyle(document.querySelector(".sidebar"));
        const composer = getComputedStyle(document.querySelector(".composer"));
        return {
          markAnim: mark.animationName,
          dotAnim: dot.animationName,
          dotOpacity: Number(dot.opacity),
          sidebarTrans: sidebar.transitionDuration,
          composerTrans: composer.transitionDuration,
        };
      });
      if (
        motion.markAnim !== "none" ||
        motion.dotAnim !== "none" ||
        motion.dotOpacity < 0.7 ||
        motion.sidebarTrans !== "0s" ||
        motion.composerTrans !== "0s"
      ) {
        fail(`${run.name}: prefers-reduced-motion not respected: ${JSON.stringify(motion)}`);
      }
    }

    await page.screenshot({ path: `${out}/g6-${run.name}.png`, fullPage: !run.isMobile });
    if (errors.length) fail(`${run.name}: page errors: ${errors.join(" | ")}`);
    console.log(`${run.name}: ok (visual_checks blocking=0)`);
    await ctx.close();
  }
} finally {
  await browser.close();
  await server.close();
}
