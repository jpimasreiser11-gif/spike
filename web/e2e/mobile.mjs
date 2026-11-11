// G41 mobile layout check of the real app (built web/dist served by tests/e2e/serve_scripted.py).
// Every view and dialog is opened at 375x812 and 768x1024 with hasTouch + isMobile and must (1) not scroll horizontally,
// (2) give every visible button/link/input at least 44x44 CSS px under `pointer: coarse`, and (3) keep the composer above
// the on-screen keyboard. Usage: node web/e2e/mobile.mjs <baseUrl> [screenshotDir]
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const base = (process.argv[2] || "http://127.0.0.1:8767").replace(/\/$/, "");
const out = process.argv[3] || "e2e/screenshots-mobile";
fs.mkdirSync(out, { recursive: true });
const executablePath = [process.env.CHROMIUM_PATH, "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"].find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile());
const browser = await chromium.launch(executablePath ? { executablePath } : {});
let failures = 0;
const fail = (msg) => { failures++; console.error("FAIL:", msg); process.exitCode = 1; };
const MIN = 44;
const SIZES = [{ name: "375", width: 375, height: 812 }, { name: "768", width: 768, height: 1024 }];

// Exceptions to the 44 px rule, each with its reason. A matching element is skipped and counted, never silently.
const EXCEPTIONS = [
  { why: "inline text link inside a sentence or markdown body (WCAG 2.5.8 inline exception; includes a link beside a field label)", css: "p a, li a, .markdown a, .muted a, .small a, label a" },
  { why: "native checkbox/radio: the wrapping label is measured instead", css: "input[type=checkbox], input[type=radio]" },
  { why: "file inputs are hidden behind a labelled button", css: "input[type=file]" },
  { why: "range slider: the input spans the row, the thumb is the target", css: "input[type=range]" },
];

async function newPage(ctx, { tourSeen = true, setup = false } = {}) {
  const page = await ctx.newPage();
  page.setDefaultTimeout(8000);
  await page.route(/\/api\/setup(?:\/|$)/, (route) => route.fulfill({ json: {
    enabled: setup, complete: !setup, can_download: true, disk_free: 20 * 1024 ** 3, ram_total: 16 * 1024 ** 3,
    ram_available: 10 * 1024 ** 3, required_disk: 6 * 1024 ** 3, required_ram: 8 * 1024 ** 3,
    job: { status: "idle", file: "", done: 0, total: 0 },
    specialists: [{ id: "code", name: "Code", available: true }, { id: "law", name: "Law", available: false }] } }));
  await ctx.request.put(`${base}/api/settings`, { data: { onboarding: { tour_seen: tourSeen } } });
  page.on("pageerror", (e) => fail(`page error: ${e}`));
  await page.goto(base);
  await page.locator(".app, .setup-wizard, [role=dialog]").first().waitFor();
  return page;
}

/** Measures the page: horizontal overflow and every visible interactive element smaller than MIN under pointer: coarse. */
async function measure(page) {
  return page.evaluate(({ MIN, EXCEPTIONS }) => {
    const se = document.scrollingElement;
    const res = { coarse: matchMedia("(pointer: coarse)").matches, overflow: se.scrollWidth - se.clientWidth, small: [], clipped: [], skipped: {} };
    const sel = "button, a[href], input, select, textarea, summary, [role=button], [role=tab], [role=option], [role=menuitem]";
    const vw = innerWidth;
    const visible = (el) => {
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") return false;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      if (r.right <= 0 || r.left >= vw) return false; // off-canvas (closed drawer)
      for (let p = el.parentElement; p; p = p.parentElement) {
        if (p.hasAttribute("inert") || getComputedStyle(p).display === "none") return false;
      }
      return true;
    };
    const name = (el) => {
      const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      const label = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.getAttribute("name") || "").trim().replace(/\s+/g, " ").slice(0, 28);
      return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""}[${label}]`;
    };
    for (const el of document.querySelectorAll(sel)) {
      if (!visible(el)) continue;
      if (el.tagName === "INPUT" && el.type === "hidden") continue;
      { const r0 = el.getBoundingClientRect(); const scroller = Boolean(el.closest('[role=tablist], .composer-bar')); /* intentional scroll strips */ if (!scroller && (r0.right > vw + 1 || r0.left < -1)) res.clipped.push(`${name(el)} spans ${Math.round(r0.left)}..${Math.round(r0.right)} of ${vw}px`); }
      const ex = EXCEPTIONS.find((e) => el.matches(e.css));
      let box = el.getBoundingClientRect();
      if (ex) {
        const lab = el.closest("label");
        if (lab && /checkbox|radio/.test(el.type || "")) {
          const lr = lab.getBoundingClientRect();
          if (lr.height >= MIN - 0.5 && lr.width >= MIN - 0.5) { res.skipped[ex.why] = (res.skipped[ex.why] || 0) + 1; continue; }
          box = lr;
        } else { res.skipped[ex.why] = (res.skipped[ex.why] || 0) + 1; continue; }
      }
      if (box.width < MIN - 0.5 || box.height < MIN - 0.5) res.small.push(`${name(el)} ${Math.round(box.width)}x${Math.round(box.height)}`);
    }
    return res;
  }, { MIN, EXCEPTIONS });
}

const seenSkips = {};
async function audit(page, label, size, shot) {
  await page.waitForTimeout(150);
  const m = await measure(page);
  if (!m.coarse) fail(`${label}: emulation does not match (pointer: coarse)`);
  if (m.overflow > 0) fail(`${label}: horizontal scroll, scrollWidth exceeds clientWidth by ${m.overflow}px`);
  for (const c of [...new Set(m.clipped)].slice(0, 20)) fail(`${label}: control extends beyond the ${size.width}px viewport (clipped, not scrollable): ${c}`);
  const uniq = [...new Set(m.small)];
  for (const s of uniq.slice(0, 40)) fail(`${label}: touch target below ${MIN}px: ${s}`);
  if (uniq.length > 40) fail(`${label}: ... and ${uniq.length - 40} more small targets`);
  for (const [k, v] of Object.entries(m.skipped)) seenSkips[k] = (seenSkips[k] || 0) + v;
  if (shot && size.name === "375") await page.screenshot({ path: `${out}/g41-${shot}.png` });
}

const openSidebar = async (page) => {
  if (!(await page.locator(".app.with-sidebar").count())) await page.getByRole("button", { name: /Abrir barra lateral|Open sidebar/ }).click();
  await page.waitForTimeout(300);
};
const side = async (page, name) => { await openSidebar(page); await page.locator(".sidebar > .side-btn, .sidebar-bottom > .side-btn").filter({ hasText: name }).first().click(); }; // never a conversation titled alike

/** A Dev session on a fresh folder of this computer (the scripted server runs here too). */
async function openDevSession(page) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "spike-mobile-dev-"));
  fs.writeFileSync(path.join(folder, "calc.py"), "x = 1\n", "utf-8");
  await side(page, /Sesiones Dev/);
  await page.locator("dialog.dev-sessions").waitFor();
  await page.locator('[name="dev-folder"]').fill(folder);
  await page.getByTestId("dev-open").click();
  await page.getByTestId("dev-send").waitFor();
}
async function endDevSessions(page, ctx) {
  const r = await ctx.request.get(`${base}/api/dev/sessions`);
  for (const s of (await r.json()).active) await ctx.request.delete(`${base}/api/dev/sessions/${s.id}`);
}

const scenes = [
  { id: "chat-welcome", run: async () => {} },
  { id: "sidebar-drawer", run: async (page) => { await openSidebar(page); } },
  { id: "palette", run: async (page) => { await page.keyboard.press("Control+k"); await page.locator(".palette [role=option]").first().waitFor(); } },
  { id: "tour", tourSeen: false, run: async (page) => { await page.getByRole("dialog", { name: /Primeros pasos/ }).waitFor(); } },
  { id: "setup-wizard", setup: true, run: async (page) => { await page.locator(".setup-wizard").waitFor(); } },
  { id: "chat-thread", run: async (page) => {
    await page.locator("#composer-input").fill("Hola, ¿quién eres?");
    await page.locator("#composer-input").press("Enter");
    await page.locator(".msg.assistant").first().waitFor();
    await page.locator(".composer .send-btn:not(.stop)").waitFor();
  } },
  { id: "artifact-panel", run: async (page) => {
    await page.locator("#composer-input").fill("Dame una página");
    await page.locator("#composer-input").press("Enter");
    const btn = page.getByRole("button", { name: "Vista previa" }).first();
    await btn.waitFor({ timeout: 15000 });
    await btn.click();
    await page.locator(".artifact-frame").first().waitFor();
  } },
  { id: "history-search", run: async (page) => { await side(page, /Buscar conversaciones/); await page.locator(".history-dialog").first().waitFor(); } },
  { id: "workspace-panel", run: async (page) => { await side(page, /Trabajos y conocimiento/); await page.getByRole("dialog", { name: "Trabajos y conocimiento" }).waitFor(); } },
  { id: "subtitles", run: async (page) => { await side(page, /Audio y subt/); await page.getByRole("dialog", { name: /Audio y subt/ }).waitFor(); } },
  { id: "device-lab", run: async (page) => { await side(page, /Device Lab/); await page.locator("dialog.device-lab").waitFor(); } },
  { id: "dev-sessions", run: async (page) => { await side(page, /Sesiones Dev/); await page.locator("dialog.dev-sessions").waitFor(); } },
  // O1: a Dev session (history, plan/act, changes, files) and, below, its permission card waiting for an answer.
  { id: "dev-session", cleanup: endDevSessions, run: async (page) => { await openDevSession(page); await page.getByTestId("dev-act").waitFor(); } },
  { id: "dev-permission", cleanup: endDevSessions, run: async (page) => {
    await openDevSession(page);
    await page.locator('[name="dev-input"]').fill("dev-e2e edit: cambia x a 2");
    await page.getByTestId("dev-send").click();
    await page.locator("dialog.dev-sessions .permission", { hasText: "edit_file" }).waitFor({ timeout: 15000 });
  } },
  { id: "forge", run: async (page) => { await side(page, /Forge/); await page.locator(".forge").first().waitFor(); } },
  { id: "creator", run: async (page) => { await side(page, /Crear/); await page.locator(".template-card").first().waitFor(); } },
  { id: "creator-template", run: async (page) => { await side(page, /Crear/); await page.locator(".template-card").first().click(); } },
  { id: "research", run: async (page) => { await page.getByRole("button", { name: "Investigación", exact: true }).click(); await page.locator(".research-panel").waitFor(); } },
  { id: "lab", run: async (page) => { await page.getByRole("button", { name: "Lab", exact: true }).click(); await page.getByRole("region", { name: "Lab", exact: true }).waitFor(); } },
  { id: "project-new", run: async (page) => { await openSidebar(page); await page.getByRole("button", { name: "Nuevo proyecto" }).click(); await page.getByRole("dialog", { name: "Nuevo proyecto" }).waitFor(); } },
  { id: "sample-projects", run: async (page) => { await openSidebar(page); await page.getByTestId("sample-projects-open").click(); await page.locator("dialog, [role=dialog]").first().waitFor(); } },
  { id: "project-panel", run: async (page, ctx) => {
    const name = `Mobile ${Date.now()}`;
    const r = await ctx.request.post(`${base}/api/projects`, { data: { name, description: "d", instructions: "i" } });
    if (!r.ok()) throw new Error("project create failed " + (await r.text()));
    page.__project = (await r.json()).id;
    await page.reload();
    await openSidebar(page);
    await page.locator(".project-item", { hasText: name }).click();
    await page.locator(".project-panel").waitFor();
  }, cleanup: async (page, ctx) => { if (page.__project) await ctx.request.delete(`${base}/api/projects/${page.__project}`); } },
  { id: "settings", settings: true, run: async (page) => { await side(page, "Ajustes"); await page.getByRole("dialog", { name: "Ajustes", exact: true }).waitFor(); } },
];

// Settings: one audit per tab (the tab strip scrolls inside the dialog, never the page).
async function settingsTabs(page, size) {
  const tabs = page.locator(".tabs[role=tablist] > button[role=tab]");
  const n = await tabs.count();
  for (let i = 0; i < n; i++) {
    await tabs.nth(i).scrollIntoViewIfNeeded();
    await tabs.nth(i).click();
    const label = ((await tabs.nth(i).textContent()) || `tab${i}`).trim();
    await audit(page, `${size.name}/settings:${label}`, size, `settings-${i}`);
    const memSub = page.locator(".memory-sub[role=tablist] > button[role=tab]");
    const m = await memSub.count();
    for (let j = 1; j < m; j++) {
      await memSub.nth(j).click();
      await audit(page, `${size.name}/settings:${label}:${j}`, size, null);
    }
  }
}

/** The composer must stay above the on-screen keyboard. A real keyboard cannot be opened in headless Chromium, so the
 * VisualViewport is faked at 420 px high inside the 812 px layout viewport (the iOS case, where the layout viewport does
 * not shrink) and, for the Android `interactive-widget=resizes-content` case, the layout viewport itself is resized. */
async function keyboardChecks() {
  for (const state of ["welcome", "thread"]) for (const mode of ["visual-viewport", "resizes-content"]) {
    const ctx = await browser.newContext({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true, locale: "es-ES" });
    if (mode === "visual-viewport") {
      await ctx.addInitScript(() => {
        const vv = new EventTarget();
        Object.assign(vv, { width: 375, height: 812, offsetTop: 0, offsetLeft: 0, pageTop: 0, pageLeft: 0, scale: 1 });
        Object.defineProperty(window, "visualViewport", { value: vv, configurable: true });
        window.__vv = vv;
      });
    }
    const page = await newPage(ctx);
    if (state === "thread") {
      await page.locator("#composer-input").fill("Hola, ¿quién eres?");
      await page.locator("#composer-input").press("Enter");
      await page.locator(".msg.assistant").first().waitFor();
      await page.locator(".composer .send-btn:not(.stop)").waitFor();
    }
    await page.locator("#composer-input").focus();
    if (mode === "visual-viewport") await page.evaluate(() => { window.__vv.height = 420; window.__vv.dispatchEvent(new Event("resize")); });
    else await page.setViewportSize({ width: 375, height: 420 });
    await page.waitForTimeout(300);
    const r = await page.evaluate(() => {
      const c = document.querySelector(".composer").getBoundingClientRect();
      return { bottom: Math.round(c.bottom), top: Math.round(c.top), vvh: window.__vv ? window.__vv.height : innerHeight };
    });
    const tag = `keyboard/${state}/${mode}`;
    if (r.bottom > r.vvh + 1 || r.top < 0) fail(`${tag}: composer (${r.top}..${r.bottom}) is outside the visible ${r.vvh}px`);
    else console.log(`${tag}: composer ${r.top}..${r.bottom} within ${r.vvh}px`);
    await page.screenshot({ path: `${out}/g41-keyboard-${state}-${mode}.png` });
    await ctx.close();
  }
}

try {
  for (const size of SIZES) {
    for (const sc of scenes) {
      const ctx = await browser.newContext({ viewport: { width: size.width, height: size.height }, hasTouch: true, isMobile: true, locale: "es-ES", colorScheme: "light" });
      try {
        const page = await newPage(ctx, sc);
        try {
          await sc.run(page, ctx);
          if (sc.settings) await settingsTabs(page, size);
          else await audit(page, `${size.name}/${sc.id}`, size, sc.id);
          if (sc.id === "sidebar-drawer") {
            const nav = await page.evaluate(() => [...document.querySelectorAll(".sidebar .side-btn, .sidebar .new-chat")]
              .filter((b) => !b.closest(".sidebar-bottom") && !b.classList.contains("back")).map((b) => {
                const cs = getComputedStyle(b); const r = b.getBoundingClientRect();
                return { t: b.textContent.trim().slice(0, 20), left: Math.round(r.left), icon: !!b.querySelector("svg"), pl: cs.paddingLeft };
              }));
            if (new Set(nav.map((n) => n.left)).size > 1 || new Set(nav.map((n) => n.pl)).size > 1 || nav.some((n) => !n.icon)) {
              fail(`${size.name}/sidebar entries inconsistent: ${JSON.stringify(nav)}`);
            }
          }
        } catch (e) {
          fail(`${size.name}/${sc.id}: could not open view: ${String(e).split("\n")[0]}`);
          await page.screenshot({ path: `${out}/g41-error-${size.name}-${sc.id}.png` }).catch(() => {});
        }
        if (sc.cleanup) await sc.cleanup(page, ctx).catch(() => {});
      } catch (e) {
        fail(`${size.name}/${sc.id}: setup failed: ${String(e).split("\n")[0]}`);
      }
      await ctx.close();
    }
  }
  await keyboardChecks();
} finally {
  await browser.close();
}
console.log("Exceptions applied (reason: elements skipped):", JSON.stringify(seenSkips, null, 1));
console.log(failures ? `MOBILE FAIL (${failures})` : "MOBILE OK");
