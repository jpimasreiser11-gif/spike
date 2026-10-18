// Records the README demo: the real app answering a real question with the real local model, in real time.
// Usage: node web/e2e/demo.mjs <url> <out-dir> [--question "..."] [--lang es|en] [--timeout seconds]
// Run it against `spike serve` with the local engine started and the model loaded. Never against
// tests/e2e/serve_scripted.py: its fake model only proves that this script works, and such a video is not a demo.
// Nothing is scripted, sped up or cut: the video is what Chromium showed and the times are measured in the page.
import { chromium } from "playwright-core";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const die = (msg) => { console.error(msg); process.exit(1); };
const flag = (name, fallback) => { // --name value, taken out of args so that the positionals are what remains
  const i = args.indexOf(`--${name}`);
  if (i < 0) return fallback;
  const value = args.splice(i, 2)[1];
  return value ?? die(`--${name} needs a value`);
};
// A short question that the router sends to one specialist (Finance) with high confidence, and that needs no tool
// (a tool permission would stop the recording); asking for two sentences keeps the answer near 80 tokens.
const QUESTIONS = {
  es: "¿Qué es un ETF y en qué se diferencia de un fondo de inversión? Responde en dos frases.",
  en: "What is an ETF and how does it differ from an investment fund? Answer in two sentences.",
};
const lang = flag("lang", "es");
if (!QUESTIONS[lang]) die(`--lang must be es or en, not ${lang}`);
const question = flag("question", QUESTIONS[lang]);
const timeoutS = Number(flag("timeout", "300")); // a small model on a slow machine may need minutes
const [base, out] = args;
if (!base || !out || !(timeoutS > 0)) {
  die('Usage: node web/e2e/demo.mjs <url> <out-dir> [--question "..."] [--lang es|en] [--timeout seconds]');
}
fs.mkdirSync(out, { recursive: true });
const webm = path.join(out, "demo.webm");

// SPIKE_CHROMIUM / CHROMIUM_PATH, then a preinstalled Chromium, then the browser installed by
// `npx playwright-core install chromium` (which also installs the ffmpeg that Playwright records video with).
const executablePath = [process.env.SPIKE_CHROMIUM, process.env.CHROMIUM_PATH,
  "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"].find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile());
const browser = await chromium.launch(executablePath ? { executablePath } : {}).catch((e) => die(
  `No Chromium: ${e.message.split("\n")[0]}\nRun npx playwright-core install chromium or set SPIKE_CHROMIUM`));

const tmp = fs.mkdtempSync(path.join(out, ".rec-")); // Playwright names the video itself; it becomes demo.webm below
const size = { width: 1280, height: 720 };
const ctx = await browser.newContext({ viewport: size, locale: lang === "es" ? "es-ES" : "en-US", colorScheme: "light",
  recordVideo: { dir: tmp, size } });
// Timestamps taken inside the page, by watching what the viewer sees (not the network): the Enter key in the composer,
// the specialist chip, the first answer text and the finished answer (the answer's action row, and no stop button).
await ctx.addInitScript(() => {
  const m = (window.__demo = { sent: null, route: null, reasoning: null, first: null, done: null });
  const mark = (key) => { if (m[key] == null) m[key] = performance.now(); };
  addEventListener("keydown", (e) => { // capture phase: before the app handles the key
    if (e.key === "Enter" && !e.shiftKey && e.target?.id === "composer-input" && e.target.value.trim()) mark("sent");
  }, true);
  new MutationObserver(() => {
    const msg = m.sent != null && document.querySelector(".msg.assistant");
    if (!msg) return;
    if (msg.querySelector(".route .chip")) mark("route");
    if (msg.querySelector(".reasoning")) mark("reasoning");
    if (msg.querySelector(".markdown")?.textContent.trim()) mark("first");
    if (msg.querySelector(".msg-actions") && !document.querySelector(".send-btn.stop")) mark("done");
  }).observe(document, { childList: true, subtree: true, characterData: true });
});
const page = await ctx.newPage();
let ok = false;
let result;
try {
  await page.goto(base);
  await page.locator(".welcome h1").waitFor(); // the main chat screen
  await page.locator(".spec-chips .chip").first().waitFor(); // and the specialists it lists
  await page.waitForTimeout(1500); // let the viewer take in the empty chat before anyone types
  await page.locator("#composer-input").click();
  for (const [i, ch] of [...question].entries()) { // human speed: about 70 ms a key, never the same twice in a row
    await page.keyboard.type(ch);
    await page.waitForTimeout(45 + ((i * 37) % 60));
  }
  await page.waitForTimeout(700); // a beat to re-read the question before sending it
  await page.keyboard.press("Enter");
  const asking = ".permission:not(.done), .question:not(.done)"; // a tool permission or question waits for a person
  await page.waitForFunction((sel) => window.__demo.done != null || document.querySelector(sel), asking,
    { timeout: timeoutS * 1000, polling: 100 });
  if (await page.locator(asking).count()) {
    throw new Error("the model asked for a tool or put a question: pick a question that needs no tool (--question)");
  }
  result = await page.evaluate(() => {
    const msg = document.querySelector(".msg.assistant");
    const at = window.__demo;
    const secs = (k) => (at[k] == null ? null : Math.round(at[k] - at.sent) / 1000);
    return {
      route_s: secs("route"), reasoning_s: secs("reasoning"), first_token_s: secs("first"), done_s: secs("done"),
      answer: msg.querySelector(".markdown")?.textContent.trim() ?? "",
      error: msg.querySelector(".error-box")?.textContent.trim() ?? null,
      chips: [...msg.querySelectorAll(".route .chip")].map((c) => ({
        name: c.textContent.replace(c.querySelector(".chip-note")?.textContent ?? "", "").trim(), title: c.title })),
      app_elapsed: [...msg.querySelectorAll(".msg-actions .small")].map((x) => x.textContent.trim())
        .find((x) => /^[\d.,]+ s$/.test(x)),
    };
  });
  if (result.error) throw new Error(`the answer failed: ${result.error}`);
  if (!result.answer || result.first_token_s == null) throw new Error("no answer text appeared");
  await page.waitForTimeout(2000); // hold the finished answer
  ok = true;
} catch (e) {
  console.error("FAIL:", e.message.split("\n")[0]);
  process.exitCode = 1;
  await page.screenshot({ path: path.join(out, "demo-failed.png") }).catch(() => {});
} finally {
  await ctx.close(); // writes the video
  await page.video().saveAs(ok ? webm : path.join(out, "demo-failed.webm")).catch(() => {}); // a failed run is no demo
  fs.rmSync(tmp, { recursive: true, force: true });
  await browser.close();
}
if (!ok) process.exit(1);

// What the app itself says about the model and machine, only what its API offers (the model path is cut to its file
// name, and the CPU flags are left out).
const get = (p) => fetch(new URL(p, base)).then((r) => (r.ok ? r.json() : null)).catch(() => null);
const [health, providers, settings, runtime, system] = await Promise.all(
  ["/api/health", "/api/providers", "/api/settings", "/api/runtime", "/api/system"].map(get));
const provider = (providers ?? []).find((p) => p.id === settings?.default_provider);
const { cpu_flags: _flags, ...hardware } = system?.hardware ?? {};
const info = {
  question, lang, date: new Date().toISOString(), url: base,
  seconds_from_send: { specialist_chip: result.route_s, reasoning: result.reasoning_s,
    first_token: result.first_token_s, done: result.done_s },
  app_reported_elapsed: result.app_elapsed ?? null,
  answer: result.answer, route: result.chips,
  app: { version: health?.version ?? null,
    default_provider: provider && { id: provider.id, name: provider.name, kind: provider.kind, model: provider.model,
      local: provider.local },
    local_engine: runtime && { running: runtime.running, context: runtime.context ?? null,
      model_file: runtime.model ? path.basename(runtime.model) : null, load_seconds: runtime.load_seconds ?? null },
    hardware },
};
fs.writeFileSync(path.join(out, "demo.json"), JSON.stringify(info, null, 2) + "\n");
console.log(`question: ${question}`);
console.log(`answer (${result.answer.length} chars): ${result.answer.slice(0, 200)}`);
if (result.route_s != null) {
  const names = result.chips.map((c) => c.name).join(", ");
  console.log(`send -> specialist chip: ${result.route_s.toFixed(2)} s (${names})`);
}
console.log(`send -> first token: ${result.first_token_s.toFixed(2)} s`);
console.log(`send -> done:        ${result.done_s.toFixed(2)} s`);
if (!runtime?.running) console.error("WARNING: the local engine is not running: this is not a local-model recording.");
console.log(`saved ${webm} and ${path.join(out, "demo.json")}`);

// GIF (about 12 fps, 960 px wide, one palette for the whole clip) and MP4 (H.264, yuv420p) from the recording.
const q = (s) => (/^[\w@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`);
const gifFilter = "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];" +
  "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle";
const conversions = [
  [path.join(out, "demo.gif"), ["-vf", gifFilter, "-loop", "0"]],
  [path.join(out, "demo.mp4"), ["-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "25",
    "-movflags", "+faststart"]],
].map(([file, opts]) => ({ file, argv: ["-y", "-i", webm, ...opts, file] }));
if (spawnSync("ffmpeg", ["-version"], { stdio: "ignore" }).error) {
  console.log("ffmpeg is not on PATH. Install it (brew install ffmpeg) and run:");
  for (const { argv } of conversions) console.log(`ffmpeg ${argv.map(q).join(" ")}`);
} else {
  for (const { file, argv } of conversions) {
    const r = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", ...argv], { stdio: "inherit" });
    if (r.status === 0) console.log(`saved ${file}`);
    else {
      console.error(`FAIL: ffmpeg did not write ${file}; command: ffmpeg ${argv.map(q).join(" ")}`);
      process.exitCode = 1;
    }
  }
}
