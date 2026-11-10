// End-to-end smoke test of the real web app against tests/e2e/serve_scripted.py.
// Usage: node e2e/smoke.mjs [baseUrl] [screenshotDir]
import { dataAppFlow } from "./data-app.mjs";
import { workflowFlow } from "./workflow.mjs";
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const base = process.argv[2] || "http://127.0.0.1:8741";
const out = process.argv[3] || "e2e/screenshots";
fs.mkdirSync(out, { recursive: true });
// CHROMIUM_PATH, then a preinstalled Chromium, then the browser installed by `npx playwright-core install chromium`.
const executablePath = [process.env.CHROMIUM_PATH, "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"].find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile());
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const fail = (msg) => { console.error("FAIL:", msg); process.exitCode = 1; };
const ctx = await browser.newContext({ viewport: { width: 1360, height: 860 }, locale: "es-ES", colorScheme: "light" });
const page = await ctx.newPage();
// An SSE `done` event renders the answer before the transport reaches EOF. Wait for the real send control so
// the next Enter is not discarded while the previous request is still finishing. Keep keyboard submission covered.
const chatIdle = () => page.locator(".composer .send-btn:not(.stop)").waitFor({ timeout: 10000 });
const submitChat = async () => {
  await page.locator(".composer .send-btn:not(.stop):enabled").waitFor({ timeout: 10000 });
  await page.locator("#composer-input").press("Enter");
};
const errors = [];
const artifactLogs = []; // what the sandboxed artifact tried and the browser refused, kept apart from app errors
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && (m.location().url.startsWith("about:srcdoc") || m.text().includes("Content Security Policy") ? artifactLogs : errors).push(m.text()));
const frameRequests = [];
page.on("request", (r) => r.frame() !== page.mainFrame() && frameRequests.push(r.url()));

// Exercise the launcher wizard with local browser fixtures; never download weights in a smoke test.
let setupDownloads = 0;
let setupComplete = false;
await page.route(/\/api\/setup(?:\/|$)/, async (route) => {
  const request = route.request();
  if (request.method() === "POST" && request.url().endsWith("/download")) {
    setupDownloads++;
    if (JSON.stringify(request.postDataJSON()) !== JSON.stringify({ specialists: ["code"] })) fail("wizard selection lost");
    setupComplete = true;
    return route.fulfill({ json: { status: "done" } });
  }
  return route.fulfill({ json: { enabled: true, complete: setupComplete, can_download: true,
    disk_free: 20 * 1024 ** 3, ram_total: 16 * 1024 ** 3, ram_available: 10 * 1024 ** 3,
    required_disk: 6 * 1024 ** 3, required_ram: 8 * 1024 ** 3,
    job: { status: setupComplete ? "done" : "idle", file: "", done: 0, total: 0 },
    specialists: [{ id: "code", name: "Code", available: true }, { id: "law", name: "Law", available: false }] } });
});
await page.goto(base);
const wizard = page.getByRole("dialog", { name: "Preparar SPIKE" });
await wizard.waitFor();
if (setupDownloads) fail("wizard must never download on mount");
if (!await wizard.getByRole("checkbox").nth(1).isDisabled()) fail("unpublished adapter must be disabled");
await wizard.getByRole("checkbox").first().check();
await wizard.getByRole("button", { name: "Descargar todo", exact: true }).click();
await wizard.waitFor({ state: "hidden" });
if (setupDownloads !== 1) fail("wizard must submit exactly one download request");
await page.unroute(/\/api\/setup(?:\/|$)/);

await page.getByText("¿En qué te ayudo hoy?").waitFor();
await page.screenshot({ path: `${out}/01-welcome.png` });

// G28: every view and dialog in App.tsx opens, renders its content, makes zero provider POST calls on open and restores focus on close.
const g28Posts = [];
const onG28Request = (r) => { if (r.method() === "POST") g28Posts.push(r.url()); };
page.on("request", onG28Request);
const forgeLaunch = page.getByRole("button", { name: "Forge", exact: true });
await forgeLaunch.click();
const forgeView = page.getByRole("region", { name: "Forge", exact: true });
await forgeView.getByLabel("Tarea").waitFor();
if (g28Posts.length) fail("opening Forge must not make POST requests");
await forgeView.getByRole("button", { name: "Cerrar", exact: true }).click();
await forgeView.waitFor({ state: "hidden" });
if (!(await forgeLaunch.evaluate((el) => el === document.activeElement))) fail("Forge must restore keyboard focus on close");

const creatorLaunch = page.getByRole("button", { name: "Crear", exact: true });
await creatorLaunch.click();
const creatorView = page.getByRole("region", { name: "Crear", exact: true });
await creatorView.locator(".template-card", { hasText: "Dashboard" }).waitFor();
if (g28Posts.length) fail("opening Creator must not make POST requests");
await creatorView.getByRole("button", { name: "Cerrar", exact: true }).click();
await creatorView.waitFor({ state: "hidden" });
if (!(await creatorLaunch.evaluate((el) => el === document.activeElement))) fail("Creator must restore keyboard focus on close");

const workspaceLaunch = page.getByRole("button", { name: "Trabajos y conocimiento", exact: true });
await workspaceLaunch.click();
const workspaceDialog = page.getByRole("dialog", { name: "Trabajos y conocimiento", exact: true });
await workspaceDialog.getByLabel("Texto del conocimiento").waitFor();
if (g28Posts.length) fail("opening WorkspacePanel must not make POST requests");
await workspaceDialog.getByRole("button", { name: "Cerrar", exact: true }).click();
await workspaceDialog.waitFor({ state: "hidden" });
if (!(await workspaceLaunch.evaluate((el) => el === document.activeElement))) fail("WorkspacePanel must restore keyboard focus on close");

const newProjectLaunch = page.getByRole("button", { name: "Nuevo proyecto", exact: true });
await newProjectLaunch.click();
const newProjectDialog = page.getByRole("dialog", { name: "Nuevo proyecto", exact: true });
await newProjectDialog.getByLabel("Nombre", { exact: true }).waitFor();
if (g28Posts.length) fail("opening ProjectDialog must not make POST requests");
await page.keyboard.press("Escape");
await newProjectDialog.waitFor({ state: "hidden" });
if (!(await newProjectLaunch.evaluate((el) => el === document.activeElement))) fail("ProjectDialog must restore keyboard focus on close");

const settingsLaunch = page.getByRole("button", { name: "Ajustes", exact: true });
await settingsLaunch.click();
const settingsModal = page.getByRole("dialog", { name: "Ajustes", exact: true });
await settingsModal.getByLabel("Instrucciones personalizadas").waitFor();
if (g28Posts.length) fail("opening SettingsDialog must not make POST requests");
await page.keyboard.press("Escape");
await settingsModal.waitFor({ state: "hidden" });
if (!(await settingsLaunch.evaluate((el) => el === document.activeElement))) fail("SettingsDialog must restore keyboard focus on close");
page.off("request", onG28Request);

// A14: explicit local transcription, editing, downloads and keyboard/mobile layout.
const subtitlePosts = [];
page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/api/subtitles/")) subtitlePosts.push(r.url()); });
const subtitleLaunch = page.getByRole("button", { name: "Audio y subtítulos", exact: true });
await subtitleLaunch.click();
const subtitleDialog = page.getByRole("dialog", { name: "Audio y subtítulos", exact: true });
await subtitleDialog.getByRole("button", { name: "Transcribir localmente" }).waitFor();
if (subtitlePosts.length) fail("opening subtitles must not execute a command");
await page.keyboard.press("Escape");
await subtitleDialog.waitFor({ state: "hidden" });
if (!(await subtitleLaunch.evaluate((el) => el === document.activeElement))) fail("subtitles must restore keyboard focus");
await subtitleLaunch.click();
await subtitleDialog.locator('[name="media-path"]').fill("intro.mp4");
if (!(await subtitleDialog.getByTestId("subtitle-transcribe").isDisabled())) fail("transcription needs approval");
await subtitleDialog.locator('[name="approve-media"]').check();
const [subtitleResponse] = await Promise.all([
  page.waitForResponse((r) => r.url().endsWith("/api/subtitles/transcribe") && r.request().method() === "POST"),
  subtitleDialog.getByTestId("subtitle-transcribe").click(),
]);
if (!subtitleResponse.ok()) throw new Error("Subtitle transcription: " + await subtitleResponse.text());
await subtitleDialog.getByLabel("Texto 2", { exact: true }).waitFor();
await subtitleDialog.getByLabel("Texto 1", { exact: true }).fill("SPIKE conserva tu trabajo en local");
await subtitleDialog.getByRole("button", { name: "Dividir 1", exact: true }).click();
await subtitleDialog.getByLabel("Texto 3", { exact: true }).waitFor();
await subtitleDialog.getByRole("button", { name: "Unir con siguiente 1", exact: true }).click();
await subtitleDialog.getByLabel("Texto 3", { exact: true }).waitFor({ state: "hidden" });
await subtitleDialog.getByLabel("Desplazar todos (milisegundos)").fill("200");
await subtitleDialog.getByRole("button", { name: "Aplicar desplazamiento", exact: true }).click();
await page.waitForFunction(() => document.querySelector('[aria-label="Inicio (ms) 1"]')?.value === "200");
const [vttDownload] = await Promise.all([page.waitForEvent("download"), subtitleDialog.getByRole("button", { name: "Descargar VTT", exact: true }).click()]);
const vttPath = await vttDownload.path();
const vttText = fs.readFileSync(vttPath, "utf8");
if (!vttText.startsWith("WEBVTT") || !vttText.includes("00:00:00.200") || !vttText.includes("SPIKE")) fail("VTT export lost edited cues");
await subtitleDialog.locator('[name="subtitle-import"]').setInputFiles({ name: "roundtrip.vtt", mimeType: "text/vtt", buffer: Buffer.from(vttText) });
await subtitleDialog.getByRole("button", { name: "Descargar SRT", exact: true }).waitFor();
await page.screenshot({ path: `${out}/00-subtitles.png` });
await page.setViewportSize({ width: 390, height: 844 });
if (await subtitleDialog.evaluate((el) => el.scrollWidth > el.clientWidth)) fail("subtitle editor must fit mobile width");
await page.screenshot({ path: `${out}/00-subtitles-mobile.png` });
await page.setViewportSize({ width: 1360, height: 860 });
const renderButton = subtitleDialog.getByRole("button", { name: "Crear y descargar MP4", exact: true });
if (!(await renderButton.isDisabled())) fail("burn-in needs separate approval");
await subtitleDialog.locator('[name="approve-render"]').check();
const [renderDownload] = await Promise.all([page.waitForEvent("download"), renderButton.click()]);
if (!(fs.readFileSync(await renderDownload.path()).subarray(4, 8).toString() === "ftyp")) fail("render download missing");
await subtitleDialog.getByTestId("subtitle-close").click();
await subtitleDialog.getByText(/Hay cambios sin exportar/).waitFor();
await subtitleDialog.getByRole("button", { name: "Cerrar y descartar", exact: true }).click();
await subtitleDialog.waitFor({ state: "hidden" });

// A13: image preparation stays in the browser; speech settings never execute a command on opening.
const mediaPosts = [];
page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/api/media/")) mediaPosts.push(r.url()); });
await page.getByRole("button", { name: "Imagen y voz", exact: true }).click();
await page.getByLabel("Modelo whisper.cpp", { exact: true }).waitFor();
if (mediaPosts.length) fail("opening speech settings must not execute speech");
await page.getByRole("button", { name: "Imagen y voz", exact: true }).click();
const tinyPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC", "base64");
await page.locator('input[type="file"][accept="image/png,image/jpeg,image/webp"]').setInputFiles({ name: "pixel.png", mimeType: "image/png", buffer: tinyPng });
await page.getByRole("button", { name: "Quitar imagen 1", exact: true }).waitFor();
const preview = page.locator('.composer img');
if (!(await preview.getAttribute("src"))?.startsWith("data:image/jpeg;base64,")) fail("image must be decoded and resized locally");
await page.getByRole("button", { name: "Quitar imagen 1", exact: true }).click();
if (await preview.count()) fail("removed image must leave the composer");
// Research is inert on open. Local extraction precedes a single explicit model request; Forge only reviews.
const researchPosts = [];
page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/api/research/")) researchPosts.push(r.url()); });
await page.getByRole("button", { name: "Investigación", exact: true }).click();
const research = page.getByRole("region", { name: "Investigación", exact: true });
await research.getByText("Abre un chat para exportar su cuaderno.").waitFor();
if (researchPosts.length) fail("Research opening must not call a model or read files");
await research.getByLabel("Archivos relativos (uno por línea)").fill("research-paper.pdf");
await research.getByRole("button", { name: "Revisar texto y destino" }).click();
await research.getByRole("button", { name: "Enviar y analizar una vez" }).waitFor();
if (researchPosts.length !== 1 || !researchPosts[0].endsWith("/preview")) fail("Research preview must stay local");
await research.locator("summary").filter({ hasText: "research-paper.pdf" }).click();
await research.locator("pre").getByText(/Methods: compare two seeds/).waitFor();
await research.getByRole("button", { name: "Enviar y analizar una vez" }).click();
await research.locator("blockquote").getByText("compare two seeds", { exact: true }).waitFor();
await research.locator(".research-result").scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/00-research-paper.png` });
await research.getByRole("button", { name: "Revisar plan en Forge" }).click();
await page.getByRole("button", { name: "Aprobar y ejecutar", exact: true }).waitFor();
if (await page.locator(".conv").count()) fail("Paper Rebuilder must not silently run a plan");
await page.getByRole("button", { name: "Volver", exact: true }).click();
await research.getByLabel("Tipo de análisis").selectOption("contradictions");
await research.getByLabel("Archivos relativos (uno por línea)").fill("research-a.txt\nresearch-b.txt");
await research.getByRole("button", { name: "Revisar texto y destino" }).click();
await research.getByRole("button", { name: "Enviar y analizar una vez" }).click();
await research.locator("tbody tr").waitFor();
if (await research.locator("blockquote").allTextContents().then((q) => q.join("|")) !== "The result is positive.|The result is negative.") fail("Contradictions must retain both exact quotes");
if (researchPosts.filter((p) => p.endsWith("/analyze")).length !== 2) fail("Research must call once per explicit analysis");
await research.locator(".research-result").scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/00-research-contradictions.png` });
await research.getByRole("button", { name: "Volver al chat" }).click();
if (!(await page.getByRole("button", { name: "Investigación", exact: true }).evaluate((el) => el === document.activeElement))) fail("Research must restore keyboard focus on close");
// Search history: no model call, keyboard focus containment, project scope and exact message navigation.
const searchTraffic = [];
const historyTraffic = (r) => { if (r.method() === "POST") searchTraffic.push(r.url()); };
page.on("request", historyTraffic);
const historyButton = page.getByRole("button", { name: /Buscar conversaciones/ });
await historyButton.focus();
await page.keyboard.press("Control+k");
const history = page.getByRole("dialog", { name: "Buscar conversaciones" });
await history.getByLabel("Palabras o frase").waitFor();
if (searchTraffic.length) fail("opening history must make no POST requests");
await page.keyboard.press("Shift+Tab");
if (!(await history.evaluate((el) => el.contains(document.activeElement)))) fail("history must contain keyboard focus");
await page.keyboard.press("Escape");
await history.waitFor({ state: "hidden" });
if (!(await historyButton.evaluate((el) => el === document.activeElement))) fail("history must restore focus on Escape");
await historyButton.click();
await history.getByLabel("Palabras o frase").fill("SQLite memoria");
await history.getByRole("button", { name: "Buscar", exact: true }).click();
await history.getByRole("status").getByText(/Sin coincidencias/).waitFor();
await history.getByLabel("Dónde buscar").selectOption("all");
await history.getByRole("button", { name: "Buscar", exact: true }).click();
await history.locator(".history-hit").waitFor();
if (await history.locator(".history-hit").count() !== 1) fail("search must exclude temporary chats");
await page.screenshot({ path: `${out}/00-history.png` });
await page.setViewportSize({ width: 390, height: 844 });
if (await history.evaluate((el) => el.scrollWidth > el.clientWidth)) fail("history must fit mobile width");
await page.screenshot({ path: `${out}/00-history-mobile.png` });
await page.setViewportSize({ width: 1360, height: 860 });
await history.locator(".history-hit").click();
await history.waitFor({ state: "hidden" });
const targetMessage = page.locator(".history-message");
await targetMessage.getByText(/Elegimos SQLite/).waitFor();
if (!(await targetMessage.evaluate((el) => el === document.activeElement))) fail("search must focus the actual message");
await page.locator(".project-item.active").getByText("Archivo de decisiones").waitFor();
await page.screenshot({ path: `${out}/00-history-message.png` });
await historyButton.click();
const chosenScope = await history.getByLabel("Dónde buscar").inputValue();
if (!chosenScope.startsWith("project:")) fail("search defaults to the active project");
await page.keyboard.press("Escape");
if (!(await historyButton.evaluate((el) => el === document.activeElement))) fail("closing search must not jump back to the previous match");
if (searchTraffic.some((url) => !url.endsWith("/api/history/search"))) fail("history must not call a provider");
page.off("request", historyTraffic);
await ctx.request.delete(`${base}/api/projects/${chosenScope.slice(8)}`);
await page.reload();
await page.getByText("¿En qué te ayudo hoy?").waitFor();

// Lab opens with local history only; both preview and explicit execution are exercised before chat.
const labPosts = [];
page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/api/lab/")) labPosts.push(r.url()); });
await page.getByRole("button", { name: "Lab", exact: true }).click();
const lab = page.getByRole("region", { name: "Lab", exact: true });
await lab.getByRole("heading", { name: "Ejecuciones guardadas" }).waitFor();
if (labPosts.length) fail("opening Lab must not issue a provider call");
await lab.getByLabel("Prompt", { exact: true }).fill("Hola, ¿quién eres?");
await lab.getByRole("button", { name: "Añadir comparación" }).click();
await lab.getByLabel("Especialista 2").selectOption("writing");
await lab.getByRole("button", { name: "Estimar comparación", exact: true }).click();
await lab.getByRole("button", { name: "Ejecutar ahora" }).waitFor();
if (labPosts.length !== 1 || !labPosts[0].endsWith("/preview")) fail("Lab preview must not execute");
await lab.getByRole("button", { name: "Ejecutar ahora" }).click();
await lab.locator("tbody tr").nth(1).waitFor();
if (await lab.locator("tbody tr").count() !== 2) fail("Lab must compare both targets");
const labExport = lab.getByRole("link", { name: "Exportar JSON" });
const exportedLab = await (await ctx.request.get(new URL(await labExport.getAttribute("href"), base).href)).json();
if (exportedLab.rows.length !== 2) fail("Lab JSON export must contain both results");
await lab.getByRole("button", { name: "Estimar prueba de proveedor", exact: true }).click();
await lab.getByRole("button", { name: "Ejecutar ahora" }).waitFor();
if (labPosts.filter((p) => p.endsWith("/execute")).length !== 1) fail("Lab probe preview must not execute");
await lab.getByRole("button", { name: "Ejecutar ahora" }).click();
await lab.getByText(/Sin probar/).first().waitFor();
if (await lab.locator("tbody tr").count() !== 5) fail("Lab must list all five capabilities");
await page.screenshot({ path: `${out}/00-lab.png` });
await lab.getByRole("button", { name: "Volver al chat" }).click();
if (!(await page.getByRole("button", { name: "Lab", exact: true }).evaluate((el) => el === document.activeElement))) fail("Lab must restore keyboard focus on close");
await page.getByRole("button", { name: "Lab", exact: true }).click();
await lab.getByRole("button", { name: /· Estimar comparación/ }).first().click(); // a saved run: wait for the history to load
await lab.locator("tbody tr").nth(1).waitFor();
await lab.getByRole("button", { name: "Volver al chat" }).click();

// 1. direct chat
await page.locator("#composer-input").fill("Hola, ¿quién eres?");
await submitChat();
await page.getByText("proveedor *de prueba*".replace(/\*/g, "")).first().waitFor({ timeout: 10000 }).catch(() => {});
await page.locator(".msg.assistant .markdown").first().waitFor();
await page.waitForFunction(() => document.querySelector(".msg-actions") !== null, null, { timeout: 10000 });
if (!(await page.locator(".conv").count())) fail("conversation not listed in sidebar");
await page.getByRole("button", { name: "Investigación", exact: true }).click();
const notebookLink = research.getByRole("link", { name: "Descargar cuaderno .ipynb" });
const exportedNotebook = await (await ctx.request.get(new URL(await notebookLink.getAttribute("href"), base).href)).json();
if (exportedNotebook.nbformat !== 4 || !exportedNotebook.cells.length) fail("Notebook export must be nbformat v4");
await research.getByRole("button", { name: "Volver al chat" }).click();

// 1b. retry on the same model, then edit the question: each replaces the turn instead of adding one
await chatIdle();
await page.locator(".msg.assistant").last().getByRole("button", { name: "Reintentar" }).click();
await page.getByRole("menuitem", { name: "El mismo modelo" }).click();
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length === 1 && document.querySelectorAll(".msg.user").length === 1, null, { timeout: 10000 })
  .catch(() => fail("retry should replace the answer"));
await page.locator(".msg.user").first().hover();
await chatIdle();
await page.locator(".msg.user").first().getByRole("button", { name: "Editar" }).click();
await page.getByLabel("Editar").fill("Hola de nuevo, ¿quién eres?");
await page.locator(".msg.user.editing").getByRole("button", { name: "Enviar", exact: true }).click();
await page.locator(".msg.user .bubble", { hasText: "Hola de nuevo" }).waitFor({ timeout: 10000 });
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length === 1 && document.querySelectorAll(".msg.user").length === 1, null, { timeout: 10000 })
  .catch(() => fail("edit should replace the turn"));

// 1c. an edit sent as a branch goes on in a copy; the original chat keeps its turn
await page.getByRole("button", { name: "Nuevo chat" }).click();
for (const [question, answers] of [["¿Qué sabes hacer?", 1], ["Dímelo en una lista", 2]]) {
  await page.locator("#composer-input").fill(question);
  await submitChat();
  await page.waitForFunction((n) => document.querySelectorAll(".msg-actions").length === n, answers, { timeout: 10000 });
}
await page.locator(".msg.user").last().hover();
await chatIdle();
await page.locator(".msg.user").last().getByRole("button", { name: "Editar" }).click();
await page.getByRole("textbox", { name: "Editar" }).fill("Dímelo en una tabla");
await page.locator(".msg.user.editing").getByRole("button", { name: "Enviar en una rama" }).click();
await page.locator(".conv-title", { hasText: "¿Qué sabes hacer? · rama" }).waitFor({ timeout: 10000 });
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length === 2, null, { timeout: 10000 });
const branchTexts = (await page.locator(".msg.user .bubble").allTextContents()).map((x) => x.trim()).join("|");
if (branchTexts !== "¿Qué sabes hacer?|Dímelo en una tabla") fail("branch thread: " + branchTexts);
await page.screenshot({ path: `${out}/01c-branch.png` });
await chatIdle();
await page.locator(".conv-title", { hasText: /^¿Qué sabes hacer\?$/ }).click();
await page.locator(".msg.user .bubble", { hasText: "Dímelo en una lista" }).waitFor({ timeout: 10000 });
await chatIdle();
await page.locator(".conv-title", { hasText: "Hola, ¿quién eres?" }).click();
await page.locator(".msg.user .bubble", { hasText: "Hola de nuevo" }).waitFor({ timeout: 10000 });

// 2. multi-specialist plan with synthesis
await page.locator("#composer-input").fill("Plan a marketing campaign for an ETF and estimate the ROI of the investment");
await submitChat();
await page.getByText("Plan de lanzamiento").waitFor({ timeout: 15000 });
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length >= 2, null, { timeout: 10000 });
const chips = await page.locator(".msg.assistant").nth(1).locator(".route .chip").allInnerTexts();
if (!chips.join(" ").includes("Marketing") || !chips.join(" ").includes("Finance")) fail("route chips missing: " + chips);
if ((await page.locator(".msg.assistant").nth(1).locator(".trace-item").count()) < 2) fail("subtask trace missing");
await page.locator(".msg.assistant").nth(1).locator(".trace-head").first().click();
await page.screenshot({ path: `${out}/02-multi-specialist.png` });

// 3. tool permission flow (write_file asks by default)
await page.locator("#composer-input").fill("Crea un archivo de notas");
await submitChat();
await page.getByRole("button", { name: "Permitir una vez" }).waitFor({ timeout: 10000 });
const card = await page.locator(".permission").boundingBox();
if (!card || card.y + card.height > 860) fail("permission card not scrolled into view");
await page.screenshot({ path: `${out}/03-permission.png` });
await page.getByRole("button", { name: "Permitir una vez" }).click();
await page.getByText("He creado el archivo").waitFor({ timeout: 10000 });

// 3b. undo that write, then replay the answer step by step
const lastAnswer = page.locator(".msg.assistant").last();
await lastAnswer.locator(".trace-head", { hasText: "write_file" }).click();
await lastAnswer.getByRole("button", { name: "Deshacer" }).click();
await lastAnswer.getByText("Deshecho: el archivo volvió a como estaba").waitFor({ timeout: 5000 });
const notes = await page.request.get(`${base}/api/workspace/files/notas.md`);
if (notes.status() !== 404) fail("undo should remove the file the answer created, got " + notes.status());
const replayPosts = [];
const onReplayRequest = (r) => { if (r.method() === "POST") replayPosts.push(r.url()); };
page.on("request", onReplayRequest);
const replayBtn = lastAnswer.getByRole("button", { name: "Ver paso a paso" });
await replayBtn.click();
const replay = page.getByRole("dialog", { name: "Paso a paso" });
await replay.waitFor();
if (replayPosts.length) fail("opening Replay must not make POST requests");
page.off("request", onReplayRequest);
await replay.locator(".replay-steps button").first().click();
if (await replay.locator(".replay-view .markdown").count()) fail("step 1 should show no answer text yet");
await replay.locator(".replay-steps button", { hasText: "Usa write_file" }).click();
await replay.locator(".replay-view .trace-item", { hasText: "write_file" }).waitFor();
await replay.locator(".replay-steps button").last().click();
await replay.locator(".replay-view", { hasText: "He creado el archivo" }).waitFor();
if (await replay.getByRole("button", { name: "Permitir una vez" }).count()) fail("the replay must not offer live permission buttons");
await page.screenshot({ path: `${out}/03b-replay.png` });
await page.keyboard.press("Escape");
await replay.waitFor({ state: "hidden" });
if (!(await replayBtn.evaluate((el) => el === document.activeElement))) fail("Replay must restore keyboard focus on close");

// 4. reload restores history
await chatIdle();
await page.reload();
await chatIdle();
await page.locator(".conv-title").first().click();
await page.getByText("Plan de lanzamiento").waitFor({ timeout: 5000 });

// 5. settings
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("dialog").waitFor();
await page.getByRole("tab", { name: "Proveedores" }).click();
await page.locator("select").filter({ hasText: "DeepSeek" }).selectOption("deepseek");
await page.getByRole("dialog").locator(".card.dashed input[type=password]").fill("sk-e2e-not-a-real-key");
await page.getByRole("dialog").getByRole("button", { name: "Añadir proveedor" }).click();
const dsCard = page.getByRole("dialog").locator(".card", { hasText: "api.deepseek.com" });
await dsCard.locator("label.check.warn input").click();
await dsCard.locator("label.check.warn input:checked").waitFor({ timeout: 5000 });
await dsCard.getByText("Topes mensuales").click();
await dsCard.getByLabel("Tokens al mes").fill("500000");
await dsCard.getByLabel("Tokens al mes").blur();
await page.screenshot({ path: `${out}/04-settings-providers.png` });
if (await dsCard.getByRole("checkbox", { name: /^Enviar el contenido de tus archivos a este proveedor/ }).isChecked()) fail("a new remote provider must not get file contents by default");
await page.getByRole("tab", { name: "Especialistas" }).click();
const medSpec = page.getByRole("dialog").locator('[data-specialist="medicine"]');
await medSpec.locator(".chip", { hasText: "Spike Medicine" }).waitFor();
await medSpec.getByText(/Evaluado y aceptado/).waitFor();
await medSpec.getByText(/\+35\.07 pts/).waitFor();
await medSpec.getByText(/-0\.62 pts/).waitFor();
await medSpec.getByText(/Perfil de instrucciones/).waitFor();
await medSpec.getByText("Instrucciones base").waitFor();
const codeSpec = page.getByRole("dialog").locator('[data-specialist="code"]');
await codeSpec.getByText(/Planificado/).waitFor();
if (await codeSpec.getByText(/Evaluado y aceptado/).count()) fail("planned specialist must not show evaluated and accepted");
await page.getByRole("tab", { name: "Skills" }).click();
await page.getByRole("dialog").locator('[data-skill="financial-ratio-analysis"]').waitFor();
for (const name of ["decision-simulator", "test-inventor", "migration-architect", "performance-profiler", "localization", "experiment-designer", "synthetic-data", "vector-designer", "system-diagnostic", "landing-page", "report-creator", "deck-creator", "dashboard-creator", "data-app-creator", "release-notes", "incident-review", "dataset-audit", "api-contract"]) {
  const card = page.getByRole("dialog").locator(`[data-skill="${name}"]`);
  await card.waitFor();
  if (!(await card.locator("input[type=checkbox]").isChecked())) fail(`bundled skill disabled: ${name}`);
}
await page.getByRole("dialog").locator('[data-skill="localization"]').getByText("Traduce textos con el glosario", { exact: false }).waitFor();
await page.getByRole("dialog").locator('[data-skill="landing-page"]').getByText("Crea una landing page", { exact: false }).waitFor();
await page.getByRole("tab", { name: "Herramientas" }).click();
const sandboxCard = page.getByRole("dialog").getByTestId("sandbox");
await sandboxCard.getByText("Aislamiento del código").waitFor();
const sandboxMode = sandboxCard.getByRole("combobox", { name: "Aislar el código que ejecuta SPIKE" });
if ((await sandboxMode.inputValue()) !== "auto") fail("the sandbox setting should start on auto");
await sandboxMode.selectOption("required");
await page.waitForFunction(async () => (await (await fetch("/api/settings")).json()).sandbox === "required", null, { timeout: 5000 })
  .catch(() => fail("the sandbox setting was not saved"));
const sandboxStatus = await (await fetch(`${base}/api/sandbox`)).json();
if (sandboxStatus.mode !== "required" || typeof sandboxStatus.available !== "boolean") fail("the sandbox status is wrong: " + JSON.stringify(sandboxStatus));
if (!sandboxStatus.available) await sandboxCard.getByText("no ejecutará python ni run_command", { exact: false }).waitFor({ timeout: 5000 }).catch(() => fail("no warning for required without a sandbox"));
await page.screenshot({ path: `${out}/05a-settings-sandbox.png` });
await sandboxMode.selectOption("auto");
await page.waitForFunction(async () => (await (await fetch("/api/settings")).json()).sandbox === "auto", null, { timeout: 5000 })
  .catch(() => fail("the sandbox setting was not put back"));
await page.getByRole("tab", { name: "Conectores" }).click();
const fsCard = page.getByRole("dialog").locator('[data-connector="filesystem"]');
await fsCard.getByRole("button", { name: "Activar" }).click();
await fsCard.locator("code.cmd", { hasText: "@modelcontextprotocol/server-filesystem@1.0.0" }).waitFor();
await page.screenshot({ path: `${out}/05b-settings-connectors.png` });
await fsCard.getByRole("button", { name: "Cancelar" }).click();
if (await fsCard.locator("code.cmd").count()) fail("connector confirmation did not close");
await page.getByRole("tab", { name: "Motor local" }).click();
await page.getByRole("dialog").getByText("Hardware").waitFor();
await page.getByRole("button", { name: "Optimizar mi equipo" }).click();
await page.locator(".tune-rows li.best", { hasText: "4 hilos · KV q8_0" }).waitFor({ timeout: 10000 });
await page.getByTestId("tune").getByText("Guardado").waitFor();
await page.screenshot({ path: `${out}/05-settings-engine.png` });
await page.keyboard.press("Escape");

// 6. projects: deleting requires two clicks, then removes both the project and its uploaded files.
await page.getByRole("button", { name: "Nuevo proyecto" }).click();
const disposable = page.getByRole("dialog", { name: "Nuevo proyecto" });
await disposable.getByLabel("Nombre").fill("Proyecto para borrar");
await disposable.getByRole("button", { name: "Crear" }).click();
await page.locator(".project-panel h2", { hasText: "Proyecto para borrar" }).waitFor();
await page.getByTestId("project-upload").setInputFiles({ name: "nota.txt", mimeType: "text/plain", buffer: Buffer.from("solo este proyecto") });
await page.locator(".file-list a", { hasText: "nota.txt" }).waitFor();
const disposableId = (await (await ctx.request.get(`${base}/api/projects`)).json()).find((p) => p.name === "Proyecto para borrar").id;
await page.locator(".project-panel").getByRole("button", { name: "Editar", exact: true }).click();
const deletingProject = page.getByRole("dialog", { name: "Editar proyecto" });
await deletingProject.getByRole("button", { name: "Eliminar proyecto", exact: true }).click();
if (!(await ctx.request.get(`${base}/api/projects/${disposableId}`)).ok()) fail("first click deleted the project before confirmation");
await deletingProject.getByRole("button", { name: "Pulsa otra vez para borrar el proyecto, sus chats y sus archivos", exact: true }).click();
await deletingProject.waitFor({ state: "hidden" });
if ((await ctx.request.get(`${base}/api/projects/${disposableId}`)).status() !== 404) fail("confirmed project deletion did not finish");
if ((await ctx.request.get(`${base}/api/projects/${disposableId}/files/nota.txt`)).status() !== 404) fail("deleted project file remains accessible");

// Create, upload a file, export, chat with the project's instructions; the chat stays in its project.
await page.getByRole("button", { name: "Nuevo proyecto" }).click();
const dlg = page.getByRole("dialog", { name: "Nuevo proyecto" });
await dlg.getByLabel("Nombre").fill("Tesis");
await dlg.getByLabel("Instrucciones del proyecto").fill("Responde citando fuentes.");
await dlg.getByLabel("Especialista por defecto").selectOption("medicine");
await dlg.getByRole("button", { name: "Crear" }).click();
await page.locator(".project-panel h2", { hasText: "Tesis" }).waitFor();
await page.getByTestId("project-upload").setInputFiles({ name: "datos.csv", mimeType: "text/csv", buffer: Buffer.from("producto,ventas\nNorte,120\nSur,95\n") });
await page.locator(".file-list a", { hasText: "datos.csv" }).waitFor();
// Project notes travel in the existing ZIP, without needing another project UI or archive format.
const projects = await (await ctx.request.get(`${base}/api/projects`)).json();
const thesis = projects.find((p) => p.name === "Tesis");
const note = await (await ctx.request.post(`${base}/api/memory`, {
  data: { scope: `project:${thesis.id}`, kind: "decision", text: "Conservar las fuentes del proyecto." },
})).json();
await page.screenshot({ path: `${out}/06-project.png` });
const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Exportar (.zip)" }).click()]);
if (!download.suggestedFilename().endsWith(".spike-project.zip")) fail("export filename: " + download.suggestedFilename());
const archive = fs.readFileSync(await download.path());
const importedResponse = await ctx.request.post(`${base}/api/projects/import`, {
  data: archive, headers: { "Content-Type": "application/octet-stream" },
});
if (!importedResponse.ok()) throw new Error("project import failed: " + await importedResponse.text());
const importedProject = await importedResponse.json();
const importedNotes = await (await ctx.request.get(`${base}/api/memory`, {
  params: { scope: `project:${importedProject.id}` },
})).json();
if (!importedNotes.some((m) => m.kind === "decision" && m.text === note.text)) fail("project note lost in export/import");
await ctx.request.delete(`${base}/api/projects/${importedProject.id}`);
await ctx.request.delete(`${base}/api/memory/${note.id}`);
// G39: a bundled sample project imports in one request and its CSV is there
const sampleResponse = await ctx.request.post(`${base}/api/samples/expenses/import?lang=es`);
if (!sampleResponse.ok()) throw new Error("sample import failed: " + await sampleResponse.text());
const sampleProject = await sampleResponse.json();
const sampleFiles = await (await ctx.request.get(`${base}/api/projects/${sampleProject.id}/files`)).json();
if (!sampleFiles.some((f) => f.path === "gastos.csv")) fail("sample project lost its CSV");
await ctx.request.delete(`${base}/api/projects/${sampleProject.id}`);
await page.locator("#composer-input").fill("Resume las ventas por producto");
await submitChat();
await page.getByText("Respuesta del proyecto").waitFor({ timeout: 10000 });
// the same turn on DeepSeek: the file passage memory found is withheld, and the answer says so
await chatIdle();
await page.locator(".msg.assistant").last().getByRole("button", { name: "Reintentar" }).click();
await page.getByRole("menuitem", { name: "DeepSeek" }).click();
await page.locator(".privacy-chip", { hasText: "Archivos protegidos" }).waitFor({ timeout: 10000 });
await page.waitForFunction(() => document.querySelectorAll(".conv").length === 1, null, { timeout: 5000 }).catch(() => fail("project chat list should hold only the project's chat"));
await page.screenshot({ path: `${out}/07-project-chat.png` });
await chatIdle();
await page.getByRole("button", { name: "Todos los chats" }).click();
await page.locator(".conv-title", { hasText: "Hola, ¿quién eres?" }).waitFor();
if (await page.locator(".conv-title", { hasText: "Resume las ventas" }).count()) fail("project chat leaked into the main list");

// A9: fork the actual project, review and approve its diff, and preserve the parent chat snapshot.
await page.getByRole("button", { name: "Tesis", exact: true }).click();
await page.locator(".project-branches summary").click();
await page.getByLabel("Nombre de la rama").fill("Tesis alternativa");
await page.getByRole("button", { name: "Crear rama", exact: true }).click();
await page.getByText("Rama creada; disponible en Proyectos.").waitFor();
await page.getByRole("button", { name: "Tesis alternativa", exact: true }).click();
await page.locator(".project-branches summary").click();
const allProjects = await (await fetch(`${base}/api/projects`)).json();
const forked = allProjects.find((p) => p.name === "Tesis alternativa");
const parentProject = allProjects.find((p) => p.name === "Tesis");
await fetch(`${base}/api/projects/${forked.id}/files/branch.txt`, { method: "PUT", body: "approved change\n" });
await page.getByRole("button", { name: "Comparar con el origen" }).click();
await page.getByRole("region", { name: "Vista previa de fusión" }).getByText("+approved change", { exact: false }).waitFor();
await page.getByRole("button", { name: "Aprobar este diff y fusionar" }).click();
await page.getByText("Archivos fusionados.").waitFor();
if (await (await fetch(`${base}/api/projects/${parentProject.id}/files/branch.txt`)).text() !== "approved change\n") fail("approved merge did not update parent");
await page.screenshot({ path: `${out}/07-a9-branches.png` });
await page.getByRole("button", { name: "Todos los chats" }).click();

// A9: specialist knowledge and a fake heavy job; cancellation exercises the real session queue without models.
await fetch(`${base}/_test/queue-job`, { method: "POST" });
await page.getByRole("button", { name: "Trabajos y conocimiento" }).click();
const jobsDialog = page.getByRole("dialog", { name: "Trabajos y conocimiento" });
await jobsDialog.getByLabel("Texto del conocimiento").fill("quartz: usar tipos explícitos");
await jobsDialog.getByRole("button", { name: "Guardar conocimiento", exact: true }).click();
await jobsDialog.getByText("quartz: usar tipos explícitos", { exact: true }).waitFor();
await jobsDialog.getByLabel("Especialista", { exact: true }).selectOption("medicine");
await jobsDialog.locator("article").filter({ hasText: "quartz: usar tipos explícitos" }).waitFor({ state: "detached" });
await jobsDialog.getByRole("region", { name: "Trabajos", exact: true }).getByRole("button", { name: "Cancelar" }).click();
await jobsDialog.getByText("Entrenamiento · Detenido", { exact: true }).waitFor({ timeout: 5000 });
await page.screenshot({ path: `${out}/07-a9-jobs-knowledge.png` });
await jobsDialog.getByRole("button", { name: "Cerrar", exact: true }).click();

// privacy: the call log shows the DeepSeek call with the file passage withheld
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Privacidad" }).click();
await page.locator("table.calls tr", { hasText: "DeepSeek" }).filter({ hasText: "protegidos" }).first().waitFor({ timeout: 5000 });
await page.getByTestId("usage-deepseek").filter({ hasText: "500.000 tope" }).waitFor({ timeout: 5000 });
await page.screenshot({ path: `${out}/07f-privacy.png` });
// G34/G36: export link and the two-step delete confirmation (cancelled: nothing is deleted)
const dataBackup = page.getByTestId("data-backup");
await dataBackup.locator('a[href="/api/backup/export?include_models=0"]').waitFor({ timeout: 5000 });
await dataBackup.getByRole("button", { name: "Borrar todo…" }).click();
await dataBackup.getByRole("button", { name: "Continuar" }).click();
await dataBackup.getByTestId("delete-word").filter({ hasText: /^BORRAR-\d{4}$/ }).waitFor({ timeout: 5000 });
if (!(await dataBackup.getByRole("button", { name: "Borrar definitivamente" }).isDisabled())) {
  throw new Error("delete is enabled before the confirmation word is typed");
}
await page.screenshot({ path: `${out}/07g-delete-confirm.png` });
await dataBackup.getByRole("button", { name: "Cancelar" }).click();
await page.keyboard.press("Escape");

// skills: a finance question gets the ratio-analysis skill, shown on the answer
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Finance" }).click();
await page.locator("#composer-input").fill("Calcula el margen EBITDA y el ROE");
await submitChat();
await page.locator(".skill-chip", { hasText: "financial-ratio-analysis" }).waitFor({ timeout: 10000 });
await page.screenshot({ path: `${out}/07b-skill.png` });

// memory: a note added in Settings is recalled in a later chat and shown on the answer
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Memoria" }).click();
await page.getByLabel("Algo que SPIKE debe recordar…").fill("El cliente Norte paga a 60 días");
await page.getByRole("dialog").getByRole("button", { name: "Añadir" }).click();
await page.locator('.memory-item[data-memory="fact"]', { hasText: "El cliente Norte paga a 60 días" }).waitFor();
await page.getByLabel("Buscar en la memoria…").fill("cliente norte");
await page.locator('.memory-item[data-memory="fact"]', { hasText: "palabras" }).waitFor();
await page.screenshot({ path: `${out}/07e-memory-settings.png` });
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("¿A cuántos días paga el cliente Norte?");
await submitChat();
await page.locator(".memory-chip", { hasText: "Memoria · 1" }).waitFor({ timeout: 10000 });

// memory folders: a folder added in Settings is indexed in the background and cited by a chat; what is hidden or
// outside it is never read; forgetting the folder removes its files from memory
const notesDir = fs.mkdtempSync(path.join(os.tmpdir(), "spike-folder-"));
const outsideDir = fs.mkdtempSync(path.join(os.tmpdir(), "spike-outside-"));
fs.writeFileSync(path.join(notesDir, "acuerdo.md"), "# Acuerdo\nEl proveedor Zafiro entrega los pedidos en 12 días laborables.\n");
fs.mkdirSync(path.join(notesDir, ".privado"));
fs.writeFileSync(path.join(notesDir, ".privado", "secreto.txt"), "clave quimeraoculta");
fs.writeFileSync(path.join(outsideDir, "ajeno.txt"), "documento quimeraajena");
try { fs.symlinkSync(path.join(outsideDir, "ajeno.txt"), path.join(notesDir, "enlace.txt")); } catch { /* no symlinks here */ }
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Memoria" }).click();
await page.getByRole("tab", { name: "Carpetas" }).click();
await page.getByLabel("Ruta absoluta de la carpeta").fill(notesDir);
await page.getByRole("button", { name: "Añadir carpeta e indexar" }).click();
await page.locator('[data-testid="folder-job"][data-state="done"]').waitFor({ timeout: 20000 });
if ((await page.getByTestId("folder-files").innerText()) !== "1") fail("folder indexing should read only acuerdo.md");
await page.getByRole("button", { name: "Archivos", exact: true }).click();
await page.locator(".folder-files code", { hasText: "acuerdo.md" }).waitFor();
if (await page.locator(".folder-files code", { hasText: /secreto|enlace/ }).count()) fail("hidden or linked files were indexed");
await page.screenshot({ path: `${out}/07g-memory-folders.png` });
for (const word of ["quimeraoculta", "quimeraajena"]) {
  const hits = await (await page.request.get(`${base}/api/memory?q=${word}`)).json();
  if (hits.length) fail(`${word} was found in memory: a hidden file or one outside the folder was read`);
}
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("¿Cuándo entrega Zafiro los pedidos?");
await submitChat();
const folderChip = page.locator(".memory-chip").last();
await folderChip.waitFor({ timeout: 10000 });
if (!(await folderChip.getAttribute("title"))?.includes(path.join(notesDir, "acuerdo.md").split(path.sep).join("/"))) fail("the answer should cite the file's path");
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Memoria" }).click();
await page.getByRole("tab", { name: "Carpetas" }).click();
await page.getByRole("button", { name: `Olvidar carpeta: ${notesDir}` }).click();
await page.getByRole("button", { name: "Sí, olvidarla" }).click();
await page.getByTestId("memory-folder").waitFor({ state: "detached" });
const afterForget = await (await page.request.get(`${base}/api/memory?q=Zafiro`)).json();
if (afterForget.length) fail("forgetting a folder should remove its files from memory");

// glossary: a term of the conversation reaches the answer as a rule; tutor: a review moves the next date
await page.getByRole("tab", { name: "Glosario" }).click();
await page.getByLabel("Término", { exact: true }).fill("factura");
await page.getByLabel("Traducción o definición").fill("invoice");
await page.getByLabel("Idioma").fill("en");
await page.getByRole("dialog").getByRole("button", { name: "Añadir", exact: true }).click();
await page.locator('[data-testid="glossary-entry"]', { hasText: "invoice" }).waitFor();
await page.screenshot({ path: `${out}/07h-glossary.png` });
await page.getByRole("tab", { name: "Tutor" }).click();
await page.getByLabel("Tema que estudias").fill("Álgebra lineal");
await page.getByRole("button", { name: "Añadir tema" }).click();
const topic = page.locator('[data-testid="tutor-topic"]', { hasText: "Álgebra lineal" });
await topic.waitFor();
if ((await topic.getAttribute("data-due")) !== "true") fail("a new topic should be due at once");
await topic.locator('button[data-grade="4"]').click();
await page.locator('[data-testid="tutor-topic"][data-due="false"]', { hasText: "en 1 día" }).waitFor();
await page.screenshot({ path: `${out}/07i-tutor.png` });
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Revisa la factura del cliente Norte");
await submitChat();
await page.locator(".memory-chip").last().waitFor({ timeout: 10000 });
if (!(await page.locator(".memory-chip").last().getAttribute("title"))?.includes("Glosario: factura")) fail("the glossary term should show on the answer");

// knowledge graph: entities from the notes, drawn as an SVG and opened in the artifacts panel
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Memoria" }).click();
await page.getByRole("tab", { name: "Grafo" }).click();
await page.getByTestId("graph-stats").waitFor();
await page.waitForFunction(() => { const i = document.querySelector('[data-testid="graph-image"]'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 10000 })
  .catch(() => fail("the memory graph picture did not load"));
await page.screenshot({ path: `${out}/07j-graph.png` });
await page.getByRole("button", { name: "Abrir en el panel" }).click();
await page.locator(".artifact-panel").waitFor();
await page.frameLocator(".artifact-frame").locator("svg").first().waitFor();
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();
// clean up what this block added, through the UI
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Memoria" }).click();
await page.getByRole("tab", { name: "Glosario" }).click();
await page.getByRole("button", { name: "Eliminar: factura" }).click();
await page.getByRole("tab", { name: "Tutor" }).click();
await page.getByRole("button", { name: "Eliminar: Álgebra lineal" }).click();
await page.getByTestId("tutor-topic").waitFor({ state: "detached" });
await page.keyboard.press("Escape");
fs.rmSync(notesDir, { recursive: true, force: true });
fs.rmSync(outsideDir, { recursive: true, force: true });

// learning: "recuerda que…" is saved at once (with undo); a correction proposes a rule the user edits and saves
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Recuerda que nunca uses emojis. ¿Qué es el IVA?");
await submitChat();
const learnedRule = page.locator('.learned-line[data-learned="rule"]', { hasText: "Nunca uses emojis." });
await learnedRule.waitFor({ timeout: 10000 });
await page.locator("#composer-input").fill("No, el IVA general en España es del 21 %, no del 18 %.");
await submitChat();
const learnCard = page.locator(".learn-card");
await learnCard.waitFor({ timeout: 10000 });
if ((await learnCard.getByRole("textbox").inputValue()) !== "El IVA general en España es del 21 %, no del 18 %.") fail("proposed rule text");
await learnCard.getByRole("textbox").fill("El IVA general en España es del 21 %.");
await page.screenshot({ path: `${out}/07f-correction.png` });
await learnCard.getByRole("button", { name: "Guardar regla" }).click();
await page.locator('.learned-line[data-learned="correction"]', { hasText: "Regla guardada" }).waitFor();
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Memoria" }).click();
await page.getByLabel("Buscar en la memoria…").fill("");
await page.locator('.memory-item[data-memory="rule"]', { hasText: "El IVA general en España es del 21 %." }).waitFor();
await page.locator('.memory-item[data-memory="rule"]', { hasText: "Nunca uses emojis." }).waitFor();
await page.keyboard.press("Escape");
await learnedRule.getByRole("button", { name: "Deshacer" }).click();
await page.locator(".learned-line", { hasText: "Quitado de la memoria" }).waitFor();

// human handoff: the specialist asks, the run waits, the answer goes back and the run finishes
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("¿Qué IVA pongo en la factura?");
await submitChat();
const question = page.getByRole("alertdialog", { name: "SPIKE necesita que le digas algo para seguir" });
await question.getByText("¿Para qué país es la factura?").waitFor({ timeout: 10000 });
await page.screenshot({ path: `${out}/07h-question.png` });
await question.getByRole("button", { name: "España" }).click();
await page.getByText("el IVA general es del").waitFor({ timeout: 10000 });
await page.locator(".question.done", { hasText: "Tu respuesta: España" }).waitFor();
await page.getByLabel("Elegir evidencia", { exact: true }).click();
await page.getByLabel("Chat y eventos", { exact: true }).check();
if (!await page.getByRole("link", { name: "Descargar paquete de prueba" }).getAttribute("href").then(href => href.includes("chat%2Cenvironment"))) fail("proof selection missing");
const [proofDl] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Descargar paquete de prueba" }).click()]);
if (!/^spike-proof-.*\.zip$/.test(proofDl.suggestedFilename())) fail("proof package name: " + proofDl.suggestedFilename());
if (fs.readFileSync(await proofDl.path()).subarray(0, 2).toString() !== "PK") fail("proof package is not a zip");

// answer contracts: JSON is checked; a schema the answer breaks is reported after a second attempt
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByLabel("Formato", { exact: true }).selectOption("json");
await page.locator("#composer-input").fill("Dame el IVA de España");
await submitChat();
await page.locator(".contract.ok", { hasText: "Cumple el esquema" }).waitFor({ timeout: 10000 });
if (!(await page.locator("pre.json-answer").innerText()).includes('"iva": 21')) fail("contract JSON answer");
await page.getByLabel("Formato", { exact: true }).selectOption("schema");
await page.getByLabel("JSON con esquema").fill('{"type": "object", "required": ["total"]}');
await page.locator("#composer-input").fill("Y el total");
await submitChat();
await page.locator(".contract.bad", { hasText: "'total' is a required property" }).waitFor({ timeout: 10000 });
await page.screenshot({ path: `${out}/07i-contract.png` });
await page.getByLabel("Formato", { exact: true }).selectOption("text");

// temporary chat: not listed in the sidebar, no memory used
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByRole("button", { name: "Chat temporal" }).click();
await page.getByRole("heading", { name: "Chat temporal" }).waitFor();
await page.locator("#composer-input").fill("Pregunta temporal sobre el cliente Norte");
await submitChat();
await page.locator(".temp-notice").waitFor();
await page.locator(".msg.assistant .msg-actions").last().waitFor({ timeout: 10000 });
if (await page.locator(".conv-title", { hasText: "Pregunta temporal" }).count()) fail("temporary chat listed in the sidebar");
if (await page.locator(".memory-chip").count()) fail("temporary chat used memory");
await page.screenshot({ path: `${out}/07g-temporary.png` });

// evolution: retrying with another specialist teaches the router behind its check; Settings → Evolución shows it
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByLabel("Especialista", { exact: true }).selectOption("auto");
await page.locator("#composer-input").fill("Mi perro lleva dos días sin comer nada y está muy decaído, ¿qué le doy?");
await submitChat();
await page.locator(".msg.assistant .route .chip.spec-core").waitFor({ timeout: 10000 });
await page.locator(".msg.assistant .msg-actions").last().waitFor({ timeout: 10000 });
await chatIdle();
await page.locator(".msg.assistant").last().getByRole("button", { name: "Reintentar" }).click();
await page.getByLabel("Con otro especialista").selectOption("medicine");
await page.locator(".msg.assistant .route .chip.spec-medicine").waitFor({ timeout: 10000 });
await page.locator(".msg.assistant .msg-actions").last().waitFor({ timeout: 10000 });
if ((await page.locator(".msg.assistant").count()) !== 1) fail("retry with a specialist should replace the answer");
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Mi perro sigue sin comer y está decaído");
await submitChat();
await page.locator(".msg.assistant .route .chip.spec-medicine").waitFor({ timeout: 10000 })
  .catch(() => fail("the learned router should send the same kind of question to Medicine"));
await page.locator(".msg.assistant .msg-actions").last().waitFor({ timeout: 10000 });
// EV8: a candidate prompt version proposed through the API shows up in Settings → Evolución, not in use
await page.evaluate(() => fetch("/api/evolution/prompts/finance/candidate", { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ instructions: ["Cita siempre la norma"] }) }).then((r) => r.ok || Promise.reject(new Error(String(r.status)))));
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Evolución" }).click();
await page.getByTestId("evo-route").filter({ hasText: "medicine" }).waitFor();
await page.getByTestId("evo-router").getByText(/Aprendido v\d+/).waitFor();
await page.screenshot({ path: `${out}/07j-evolution.png` });
await page.getByRole("button", { name: "Comprobar ahora" }).click();
await page.getByTestId("evo-checks").locator("li.ok", { hasText: "Enrutador" }).waitFor({ timeout: 10000 });
if (await page.getByTestId("evo-checks").locator("li.fail").count()) fail("the evolution check failed");
await page.screenshot({ path: `${out}/07k-evolution-check.png` });
await page.getByRole("button", { name: "Volver a la anterior" }).first().click();
await page.getByTestId("evo-router").getByText(/Aprendido v/).waitFor({ state: "detached" });
// Evolution level 3: with consent, the saved IVA correction becomes a training example the user approves
await page.getByText("Usar mis correcciones para reentrenar").click();
await page.getByRole("button", { name: "Buscar ejemplos nuevos" }).click();
const example = page.getByTestId("evo-example").filter({ hasText: "Tienes razón" });
await example.waitFor({ timeout: 10000 });
await page.screenshot({ path: `${out}/07x-evolution-examples.png` });
await example.getByRole("button", { name: "Aprobar" }).click();
await page.getByRole("link", { name: "Descargar ejemplos (.jsonl)" }).waitFor();
const examples = await page.evaluate(() => fetch("/api/evolution/training.jsonl").then((r) => r.text()));
if (!examples.includes("Tienes razón") || !examples.includes('"source": "spike-correction"')) fail("exported training examples");
// EV3: the tool strategy table lists what was recorded from the chats above, and can be reset after a confirmation
await page.getByRole("heading", { name: "Estrategia de herramientas" }).scrollIntoViewIfNeeded();
await page.getByTestId("evo-strategy-row").first().waitFor({ timeout: 10000 })
  .catch(() => fail("the tool strategy table should list the tools used in the chats above"));
await page.getByTestId("evo-strategy").scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/07y-evolution-strategy.png` });
await page.getByRole("button", { name: "Olvidar los usos anotados" }).click();
await page.getByRole("alertdialog").getByRole("button", { name: "Sí, olvidar" }).click();
await page.getByTestId("evo-strategy").getByText("Aún no hay usos anotados").waitFor({ timeout: 10000 });
// EV8: the candidate is listed with its state; the check can compare prompt versions, and with too few eval questions it says so
const candidate = page.getByTestId("evo-candidate-finance");
await candidate.scrollIntoViewIfNeeded();
await candidate.getByText(/Candidata v\d+/).waitFor();
await candidate.getByText("sin comparar").waitFor();
await candidate.getByText("add: Cita siempre la norma").waitFor();
await page.screenshot({ path: `${out}/07z-evolution-candidate.png` });
await page.getByText("Comparar también las versiones de instrucciones").click();
await page.getByRole("button", { name: "Comprobar ahora" }).click();
await page.getByTestId("evo-checks").locator("li.fail", { hasText: "Instrucciones" }).waitFor({ timeout: 10000 });
await page.getByTestId("evo-checks").getByText("acepta al menos 3 para poder comparar").waitFor();
await page.getByTestId("evo-checks").locator("li.ok", { hasText: "Desempate" }).waitFor();
// EV6: the personal adapter is off by default; on, it shows what would be used and lets the user mark a chat
if (await page.getByTestId("evo-personal").count()) fail("the personal adapter should be off by default");
await page.getByText("Activar el adaptador personal").click();
await page.getByTestId("evo-personal").waitFor();
if (process.platform !== "darwin") await page.getByTestId("evo-personal-unavailable").getByText("No disponible en este ordenador").waitFor();
await page.getByTestId("evo-personal-counts").getByText(/se necesitan al menos 30/).waitFor();
await page.getByLabel("Elige un chat para marcarlo").selectOption({ index: 1 });
await page.getByRole("button", { name: "Marcar este chat" }).click();
await page.getByTestId("evo-personal-marked").waitFor();
await page.screenshot({ path: `${out}/07w-evolution-personal.png` });
await page.getByTestId("evo-personal-marked").getByRole("button", { name: "Quitar" }).click();
await page.getByTestId("evo-personal-marked").waitFor({ state: "detached" });
await page.getByText("Activar el adaptador personal").click();
await page.getByTestId("evo-personal").waitFor({ state: "detached" });
await page.keyboard.press("Escape");

// A5: explicit approval, then the full local diagnostic opens as an isolated artifact.
// The scripted workspace has no supported audit manifests: no registry requests or installed auditors run.
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Code" }).click();
await page.locator("#composer-input").fill("Ejecuta Dependency Doctor");
await submitChat();
const diagnosticPermission = page.locator(".permission", { hasText: "dependency_doctor" });
await diagnosticPermission.getByRole("button", { name: "Permitir una vez" }).click();
await page.getByRole("button", { name: "Ver informe de diagnóstico" }).click();
await page.frameLocator(".artifact-frame").getByRole("heading", { name: "Dependency Doctor" }).waitFor();
await page.frameLocator(".artifact-frame").getByText("Sin manifiesto compatible").first().waitFor();
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

// A21: Device Lab opens a page on this computer (the app itself) in phone and desktop profiles. The agent's run asks first
// and its report opens as an isolated artifact; the window never starts anything before its approval. Needs a Chromium
// for the server, which CI installs for Spike Motion.
const labRequests = [];
page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/api/device-lab/")) labRequests.push(r.url()); });
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Code" }).click();
await page.locator("#composer-input").fill("Ejecuta Device Lab");
await submitChat();
const labPermission = page.locator(".permission", { hasText: "device_lab" });
await labPermission.getByText("Abrirá esta página local en un navegador sin ventana").waitFor();
await labPermission.getByRole("button", { name: "Permitir una vez" }).click();
const labCard = page.getByRole("region", { name: "Informe de Device Lab" });
await labCard.getByText(/de 2 perfiles sin problemas/).waitFor({ timeout: 60000 });
const labReportBtn = labCard.getByRole("button", { name: "Ver informe de Device Lab" });
await labReportBtn.click();
const labFrame = page.frameLocator(".artifact-frame");
await labFrame.getByRole("heading", { name: "Informe de Device Lab" }).waitFor();
if (await labFrame.locator("tbody tr").count() !== 2) fail("the Device Lab report must list both profiles");
await labFrame.locator("img").first().waitFor();
if (await labFrame.locator("img").evaluateAll((imgs) => imgs.some((i) => i.naturalWidth === 0))) fail("a Device Lab screenshot did not decode");
await page.screenshot({ path: `${out}/07v-device-lab-report.png` });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();
if (!(await labReportBtn.evaluate((el) => el === document.activeElement))) fail("ArtifactPanel must restore keyboard focus on close");

await page.getByTestId("device-lab-open-btn").click();
const labDialog = page.getByRole("dialog", { name: "Device Lab" });
await labDialog.waitFor();
await labDialog.getByTestId("device-lab-run").waitFor();
if (labRequests.length) fail("opening Device Lab must not start anything: " + labRequests.join(", "));
if (!await labDialog.getByTestId("device-lab-run").isDisabled()) fail("Device Lab must wait for the approval");
await labDialog.getByTestId("device-lab-close").click();
await labDialog.waitFor({ state: "hidden" });
if (!(await page.getByTestId("device-lab-open-btn").evaluate((el) => el === document.activeElement))) fail("DeviceLab must restore keyboard focus on close");
await page.getByTestId("device-lab-open-btn").click();
await labDialog.waitFor();
await labDialog.locator('[name="device-lab-url"]').fill(`${base}/`);
for (const id of ["small-phone", "large-phone", "tablet-portrait", "tablet-landscape"]) await labDialog.locator(`[name="profile-${id}"]`).uncheck();
await labDialog.locator('[name="custom-name"]').fill("Quiosco");
await labDialog.getByTestId("device-lab-add").click();
await labDialog.locator('[name="device-lab-approve"]').check();
await labDialog.getByTestId("device-lab-run").click();
const labResults = labDialog.getByTestId("device-lab-results");
await labResults.waitFor({ timeout: 60000 });
if (await labResults.locator("tbody tr").count() !== 3) fail("Device Lab must report the two chosen profiles and the custom one");
await labResults.getByText("Quiosco").waitFor();
if (labRequests.length !== 1 || !labRequests[0].endsWith("/api/device-lab/run")) fail("one approved run, nothing else: " + labRequests.join(", "));
await page.screenshot({ path: `${out}/07v-device-lab-window.png` });
await labDialog.getByTestId("device-lab-open").click();
await page.frameLocator(".artifact-frame").getByRole("heading", { name: "Informe de Device Lab" }).waitFor();
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

// A18: Blender renders a preview and Godot checks a game, both with fake programs on the server's PATH (the real ones
// are the user's own). Every run is approved first; the preview and the check open in the artifacts panel.
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Code" }).click();
await page.locator("#composer-input").fill("Renderiza una escena en Blender");
await page.keyboard.press("Enter");
const blenderPermission = page.locator(".permission", { hasText: "blender_render" });
await blenderPermission.getByText("Ejecutará Blender con este script en tu ordenador").waitFor();
await blenderPermission.getByRole("button", { name: "Permitir una vez" }).click();
const blenderCard = page.getByRole("region", { name: "Vista previa de Blender" });
await blenderCard.waitFor();
await page.waitForFunction(() => { const i = document.querySelector(".maker-card img"); return i && i.complete && i.naturalWidth > 0; });
await blenderCard.getByRole("button", { name: "Ver vista previa 3D" }).click();
const blenderFrame = page.frameLocator(".artifact-frame");
await blenderFrame.getByRole("heading", { name: "Vista previa de Blender" }).waitFor();
const previewSrc = await blenderFrame.locator("img").getAttribute("src");
if (!previewSrc?.startsWith("data:image/png;base64,")) fail("the Blender preview is not an inline PNG: " + previewSrc?.slice(0, 40));
if (await blenderFrame.locator("img").evaluate((i) => i.naturalWidth) !== 64) fail("the Blender preview did not decode");
await blenderFrame.locator("pre", { hasText: "SUN_STRENGTH = 6.0" }).waitFor();
await page.screenshot({ path: `${out}/07x-blender-preview.png` });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Code" }).click();
await page.locator("#composer-input").fill("Crea un juego en Godot");
await page.keyboard.press("Enter");
await page.locator(".permission", { hasText: "godot_scaffold" }).getByRole("button", { name: "Permitir una vez" }).click();
const godotPermission = page.locator(".permission", { hasText: "godot_check" });
await godotPermission.getByText("Ejecutará Godot sin ventana").waitFor();
await godotPermission.getByRole("button", { name: "Permitir una vez" }).click();
const godotCard = page.getByRole("region", { name: "Comprobación de Godot" });
await godotCard.getByText("Con errores").waitFor();
await godotCard.getByText("jugador.gd").waitFor();
await godotCard.getByRole("button", { name: "Ver resultado de Godot" }).click();
const godotFrame = page.frameLocator(".artifact-frame");
await godotFrame.getByRole("heading", { name: "Comprobación de Godot" }).waitFor();
await godotFrame.getByText("Parse Error").first().waitFor();
await page.screenshot({ path: `${out}/07y-godot-check.png` });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

// artifacts: an HTML answer opens in the sandboxed panel and can reach neither SPIKE's storage nor its API
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Code" }).click();
await page.locator("#composer-input").fill("Hazme una página de prueba");
await submitChat();
await page.locator(".code-preview").first().click({ timeout: 10000 });
await page.locator(".artifact-panel").getByText("Prueba de aislamiento").waitFor();
const probe = page.frameLocator(".artifact-frame").locator("#out");
await probe.filter({ hasText: "api:" }).waitFor({ timeout: 5000 });
const verdict = await probe.innerText();
if (verdict !== "storage:blocked parent:blocked api:blocked") fail("artifact sandbox: " + verdict);
if (frameRequests.length) fail("the artifact sent requests: " + frameRequests.join(", "));
if (!artifactLogs.some((l) => l.includes("connect-src"))) fail("expected the CSP to refuse the artifact's fetch");
await page.screenshot({ path: `${out}/07c-artifact.png` });
const [page_dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Descargar" }).click()]);
if (page_dl.suggestedFilename() !== "prueba-de-aislamiento.html") fail("artifact download name: " + page_dl.suggestedFilename());
await page.locator(".artifact-panel").getByRole("tab", { name: "Comentarios", exact: true }).click();
await page.getByLabel("Comentario", { exact: true }).fill("Revisar la línea inicial");
await page.getByRole("button", { name: "Guardar comentario" }).click();
await page.getByText("Revisar la línea inicial", { exact: true }).waitFor();
await page.getByRole("button", { name: "Responder al hilo" }).click();
await page.getByLabel("Comentario", { exact: true }).fill("Confirmado");
await page.getByRole("button", { name: "Guardar comentario" }).click();
await page.getByText("Confirmado", { exact: true }).waitFor();
await page.getByRole("button", { name: "Usar hilo en el próximo mensaje" }).click();
await page.getByText("Hilo seleccionado para el próximo mensaje.").waitFor();
await page.screenshot({ path: `${out}/07-a9-comments.png` });
await page.getByRole("button", { name: "Hilos seleccionados:", exact: false }).click();
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

// Spike Design: Settings lists the design systems with a sample page; a chat with one gets a page in its tokens
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Diseño" }).click();
const minimalCard = page.locator('[data-design="minimal"]');
await minimalCard.getByRole("button", { name: "Vista previa" }).click();
await page.frameLocator('[data-design="minimal"] .design-frame').locator("h1", { hasText: "Minimal" }).waitFor({ timeout: 5000 });
if ((await page.locator("[data-design]").count()) !== 21) fail("expected 21 design systems");
await page.screenshot({ path: `${out}/07l-design-settings.png` });
// Reverse Studio (A20): a page on this computer becomes editable HTML; nothing runs until ownership is confirmed
const reverse = page.getByTestId("reverse-studio");
await reverse.scrollIntoViewIfNeeded();
const reverseButton = reverse.getByTestId("reverse-generate");
if (!(await reverseButton.isDisabled())) fail("Reverse Studio must wait for the ownership confirmation");
await reverse.locator('[name="reverse-url"]').fill(base + "/");
if (!(await reverseButton.isDisabled())) fail("Reverse Studio enabled without the ownership confirmation");
await reverse.locator('[name="reverse-authorized"]').check();
await reverseButton.click();
await reverse.getByTestId("reverse-result").waitFor({ timeout: 90000 });
const reverseScore = (await reverse.getByTestId("reverse-score").textContent()) ?? "";
if (!/\d\.\d{4}/.test(reverseScore)) fail("Reverse Studio shows no measured similarity: " + reverseScore);
await page.screenshot({ path: `${out}/07n-reverse-studio.png` });
await reverse.getByRole("button", { name: "Abrir en el panel de artefactos" }).click();
await page.frameLocator(".artifact-frame").locator("h1", { hasText: "Lorem ipsum dolor" }).waitFor({ timeout: 10000 });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Diseño" }).click();
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByLabel("Diseño", { exact: true }).selectOption("spike");
await page.locator("#composer-input").fill("Hazme una landing para mi app");
await submitChat();
await page.locator(".design-chip", { hasText: "SPIKE" }).waitFor({ timeout: 10000 });
await page.locator(".code-preview").first().click({ timeout: 10000 });
const cta = page.frameLocator(".artifact-frame").locator("button.cta");
await cta.waitFor({ timeout: 5000 });
const ctaColour = await cta.evaluate((el) => getComputedStyle(el).backgroundColor);
if (ctaColour !== "rgb(136, 212, 69)") fail("the page does not use the SPIKE tokens: " + ctaColour);
await page.screenshot({ path: `${out}/07m-design-artifact.png` });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();
await page.getByLabel("Diseño", { exact: true }).selectOption("");

// Spike Finance: a paper trade, then a real order that is off until set up and only sent on the user's click
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByLabel("Especialista", { exact: true }).selectOption("finance");
await page.locator("#composer-input").fill("Compra 0,01 BTC en paper");
await submitChat();
await page.getByText("en la cuenta simulada").waitFor({ timeout: 10000 });
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Finanzas" }).click();
await page.locator(".chip", { hasText: "BTC 0,01" }).waitFor({ timeout: 5000 });
const liveCard = page.locator(".live-settings");
await liveCard.getByText("Las órdenes reales están apagadas").waitFor();
await liveCard.getByLabel("Permitir proponer órdenes reales").check();
await liveCard.getByLabel("Exchange", { exact: true }).selectOption("binance");
await liveCard.getByLabel("Confirmo que la clave NO puede retirar fondos", { exact: false }).check();
await liveCard.getByLabel("Mercados permitidos", { exact: false }).fill("BTC/USDT");
await liveCard.getByRole("button", { name: "Guardar", exact: true }).click();
await liveCard.locator(".flash-box", { hasText: "Guardado" }).waitFor({ timeout: 5000 });
await page.locator(".live-settings").getByLabel("API key").fill("e2e-key");
await page.locator(".live-settings").getByLabel("Secreto").fill("e2e-secret");
await page.locator(".live-settings").getByRole("button", { name: "Guardar clave" }).click();
await page.locator(".live-settings").getByText("Listo: cada orden necesitará tu clic", { exact: false }).waitFor({ timeout: 5000 });
const settingsText = await (await fetch(`${base}/api/settings`)).text();
if (settingsText.includes("e2e-secret")) fail("the exchange secret is in the settings");
await page.screenshot({ path: `${out}/07n-finance-settings.png`, fullPage: true });
await page.keyboard.press("Escape");
await page.locator("#composer-input").fill("Haz una orden real: compra 0,001 BTC");
await submitChat();
const order = page.locator(".live-order");
await order.getByText("esperando tu confirmación").waitFor({ timeout: 10000 });
let placed = await (await fetch(`${base}/api/finance/live/orders`)).json();
if (placed[0].status !== "proposed") fail("the proposal was sent before the click: " + placed[0].status);
await order.getByRole("button", { name: "Confirmar" }).click();
await order.getByRole("button", { name: "Sí, enviar" }).click();
await order.getByText("enviada", { exact: true }).waitFor({ timeout: 5000 });
placed = await (await fetch(`${base}/api/finance/live/orders`)).json();
if (placed[0].status !== "placed" || !placed[0].result.includes("E2E-1")) fail("the confirmed order was not placed");
await page.screenshot({ path: `${out}/07o-live-order.png` });
await page.getByLabel("Especialista", { exact: true }).selectOption("auto");

// MCP Apps: a connector's view shows the tool's result in an isolated frame; its calls need the user
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Muéstrame el precio con la app");
await submitChat();
const view = page.frameLocator(".mcp-app-frame");
await view.locator("#price", { hasText: "50000" }).waitFor({ timeout: 10000 });
if ((await view.locator("#input").textContent()) !== "BTC") fail("the view did not get the tool's input");
await view.locator("#probe", { hasText: "api:blocked" }).waitFor({ timeout: 5000 });
if (!(await view.locator("#probe").textContent()).includes("parent:blocked")) fail("the view reached the parent page");
if ((await view.locator("#out").textContent()) !== "SPIKE") fail("the view did not initialize");
await view.getByRole("button", { name: "Actualizar" }).click();
await page.locator(".mcp-app .permission", { hasText: "refresh_price" }).waitFor({ timeout: 5000 });
await page.locator(".mcp-app .permission").getByRole("button", { name: "Permitir" }).click();
await view.locator("#price", { hasText: "50100" }).waitFor({ timeout: 5000 });
await view.getByRole("button", { name: "Enlace" }).click();
await page.locator(".mcp-app .permission", { hasText: "https://example.com/" }).waitFor({ timeout: 5000 });
await page.screenshot({ path: `${out}/07p-mcp-app.png` });
await page.locator(".mcp-app .permission").getByRole("button", { name: "Cancelar" }).click();
await view.locator("#out", { hasText: "denied" }).waitFor({ timeout: 5000 });
await view.getByRole("button", { name: "Contexto" }).click();
await page.getByText("La app añadirá lo que muestra a tu próximo mensaje").waitFor({ timeout: 5000 });
await page.locator("#composer-input").fill("¿Qué ves en la app?");
await submitChat();
await page.getByText("En la vista veo: BTC a 50100 USD").waitFor({ timeout: 10000 });
const audit = await (await fetch(`${base}/api/connectors-audit`)).json();
if (!audit.some((e) => e.event === "tools/call" && e.decision === "approved")) fail("the approved view call is not in the audit log");
if (!audit.some((e) => e.event === "model-context")) fail("the context update is not in the audit log");

// Spike Data: a chart computed by SQL from a CSV, its data and query in the card, the report as a page, Word and PDF
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Data" }).click();
await page.locator("#composer-input").fill("Haz un gráfico de ventas por región con ventas.csv");
await submitChat();
const chartCard = page.locator(".chart-card");
await chartCard.locator(".chart svg").waitFor({ timeout: 15000 });
const bars = await chartCard.locator('.chart svg path[aria-roledescription="bar"]').count();
if (bars !== 2) fail(`the chart has ${bars} bars, expected 2`);
await page.getByText("El norte ingresa 90 €").waitFor({ timeout: 10000 });
await chartCard.getByRole("button", { name: "Datos" }).click();
const cells = (await chartCard.locator(".data-grid td").allTextContents()).join("|");
if (cells !== "norte|90|sur|70") fail("the chart's data is " + cells);
await chartCard.locator(".data-sql summary").click();
await chartCard.locator(".data-sql").getByText("GROUP BY region").first().waitFor();
await chartCard.getByText("Evidencias del análisis", { exact: true }).click();
await chartCard.getByText("Vista previa SQL de solo lectura", { exact: true }).waitFor();
await chartCard.getByText("Linaje", { exact: true }).waitFor();
await chartCard.locator(".analytics-evidence pre").first().filter({ hasText: "LIMIT 5001" }).waitFor();
await page.screenshot({ path: `${out}/07q-data-chart.png` });
await page.getByRole("button", { name: "Ver informe" }).click();
const reportFrame = page.frameLocator(".artifact-frame");
await reportFrame.locator('svg path[aria-roledescription="bar"]').first().waitFor({ timeout: 10000 });
await reportFrame.getByText("Haz un gráfico de ventas por región con ventas.csv", { exact: true }).waitFor();
await reportFrame.getByText("no del modelo").waitFor();
await page.screenshot({ path: `${out}/07r-data-report.png` });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();
const [wordDl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Word", exact: true }).click()]);
if (!wordDl.suggestedFilename().endsWith(".docx")) fail("the Word report is named " + wordDl.suggestedFilename());
if (fs.readFileSync(await wordDl.path()).subarray(0, 2).toString() !== "PK") fail("the Word report is not a .docx");
const [pdfDl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "PDF", exact: true }).click()]);
if (fs.readFileSync(await pdfDl.path()).subarray(0, 4).toString() !== "%PDF") fail("the PDF report is not a PDF");
await page.getByLabel("Especialista", { exact: true }).selectOption("auto");

// documents: the Word tool asks first, then its file is offered as a download
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Writing" }).click();
await page.locator("#composer-input").fill("Redacta el informe en Word");
await submitChat();
await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 10000 });
const docLink = page.locator(".artifact-files a", { hasText: "informe.docx" });
await docLink.waitFor({ timeout: 10000 });
const [doc_dl] = await Promise.all([page.waitForEvent("download"), docLink.click()]);
const docBytes = fs.readFileSync(await doc_dl.path());
if (docBytes.subarray(0, 2).toString() !== "PK") fail("downloaded .docx is not a zip package");
await page.screenshot({ path: `${out}/07d-document.png` });

// Recorder (A16): start recording what Spike View does as a local script. The scripted server stands in for the browser,
// so these steps check the panel and the guard (what is asked, what is kept); tests/test_recorder.py records and replays
// against a real Chromium.
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Conectores" }).click();
const recorder = () => page.getByRole("dialog").locator('[data-connector="playwright"] .view-recorder');
await recorder().getByLabel("Nombre del guion").fill("Pedido BOE");
await recorder().getByRole("button", { name: "Grabar", exact: true }).click();
await recorder().getByText("Grabando", { exact: true }).waitFor({ timeout: 5000 });
await page.keyboard.press("Escape");
// a specialist chip toggles, and the choice stays across chats: click one only when it is not the one chosen
const pick = async (name) => {
  const chip = page.locator(".spec-chips .chip", { hasText: name });
  if (!(await chip.evaluate((el) => el.classList.contains("selected")))) await chip.click();
};

// browser (Spike View): a new site asks with its domain; "always" saves the domain, which Settings lists and removes
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Law" }).click();
await page.locator("#composer-input").fill("Busca en el BOE la ley del IVA");
await submitChat();
const browserCard = page.locator(".permission").filter({ hasText: "Abrirá boe.es." });
await browserCard.waitFor({ timeout: 10000 });
if (await browserCard.getByRole("button", { name: "Permitir en esta sesión" }).count()) fail("a page must offer its domain, not the whole tool");
await browserCard.getByRole("button", { name: "Bloquear boe.es" }).waitFor();
await page.screenshot({ path: `${out}/07e-browser-permission.png` });
await browserCard.getByRole("button", { name: "Permitir siempre boe.es" }).click();
await page.locator(".permission.done").filter({ hasText: "Permitido" }).waitFor({ timeout: 10000 });
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Conectores" }).click();
const domains = page.getByRole("dialog").locator('[data-connector="playwright"] .browser-domains');
await domains.locator("li", { hasText: "boe.es" }).getByText("permitido").waitFor({ timeout: 5000 });
await domains.scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/07f-browser-domains.png` });
await domains.getByRole("button", { name: "Eliminar boe.es" }).click();
await domains.getByText("Aún no hay dominios con regla.").waitFor();
await page.keyboard.press("Escape");

// Recorder: typing into a password field and clicking a button that submits are recorded too
await page.getByRole("button", { name: "Nuevo chat" }).click();
await pick("Law");
await page.locator("#composer-input").fill("Escribe la clave en el formulario");
await page.keyboard.press("Enter");
await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 10000 });
await page.getByText("Hecho en el navegador.").first().waitFor({ timeout: 10000 });
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Pulsa enviar el pedido");
await page.keyboard.press("Enter");
await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 10000 }); // a click that submits asks every time
await page.getByText("Hecho en el navegador.").first().waitFor({ timeout: 10000 });
const browserCalls = async () => (await (await page.request.get(`${base}/__e2e/browser`)).json()).calls;
const named = (calls, name) => calls.filter((c) => c[0] === name).length;
let calls = await browserCalls();
if (named(calls, "browser_navigate") !== 1 || named(calls, "browser_type") !== 1 || named(calls, "browser_click") !== 1) fail("the chats should have made one call each: " + JSON.stringify(calls));

await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Conectores" }).click();
await recorder().getByText("Grabando", { exact: true }).waitFor({ timeout: 5000 });
const recorded = recorder().locator(".view-recording .view-steps li");
await recorded.nth(2).waitFor({ timeout: 5000 });
if (await recorded.count() !== 3) fail("the recorder should hold 3 steps, it holds " + await recorded.count());
await recorded.filter({ hasText: "Abrir https://www.boe.es/buscar" }).waitFor();
await recorded.filter({ hasText: "«Clave»" }).getByText("secreto", { exact: true }).waitFor(); // a password field: its text is not kept
await recorded.filter({ hasText: "«Enviar pedido»" }).getByText("envía", { exact: true }).waitFor();
if ((await recorder().textContent()).includes("clave-e2e-secreta")) fail("the recorder panel shows what was typed into the password field");
await recorder().scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/a16-1-recorder-recording.png` });
await recorder().getByRole("button", { name: "Terminar y guardar" }).click();
await recorder().getByText("Guion guardado: 3 pasos").waitFor({ timeout: 5000 });
const stored = await page.request.get(`${base}/api/browser/scripts/pedido-boe`);
const storedText = await stored.text();
if (storedText.includes("clave-e2e-secreta")) fail("the saved script holds what was typed into the password field");
const script = JSON.parse(storedText);
if (script.steps.length !== 3 || script.steps[1].secret !== true || "text" in script.steps[1]) fail("the password step should be a secret without text: " + storedText);

// Replay: the scripted browser has no rule for boe.es now, so the replay asks about the domain, asks for the secret
// text (which it never kept), and asks before the click that submits
const row = recorder().locator(".view-scripts li").filter({ hasText: "Pedido BOE" });
await row.getByRole("button", { name: "Reproducir", exact: true }).click();
const viewReplay = recorder().locator(".view-replay");
await viewReplay.getByText("Va a abrir boe.es, un dominio que no tienes permitido.").waitFor({ timeout: 10000 });
await viewReplay.getByRole("button", { name: "Permitir solo esta vez" }).click();
await viewReplay.getByText("Este campo es secreto: escribe su texto. No se guarda.").waitFor({ timeout: 10000 });
await viewReplay.getByLabel("Texto del campo (no se guarda)").fill("otra-clave-e2e");
await viewReplay.getByRole("button", { name: "Usar este texto" }).click();
await viewReplay.getByText("Va a hacer clic en algo que puede enviar un formulario.").waitFor({ timeout: 10000 });
calls = await browserCalls();
if (named(calls, "browser_click") !== 1) fail("the replay clicked a button that submits before asking");
await page.screenshot({ path: `${out}/a16-2-recorder-replay-asks.png` });
await viewReplay.getByRole("button", { name: "Omitir este paso" }).click();
await viewReplay.getByText("Terminada", { exact: true }).waitFor({ timeout: 10000 });
calls = await browserCalls();
if (named(calls, "browser_navigate") !== 2 || named(calls, "browser_type") !== 2 || named(calls, "browser_click") !== 1) fail("after the replay: " + JSON.stringify(calls));
if (JSON.stringify(calls).includes("otra-clave-e2e")) fail("the secret text reached a place that logs calls");
if ((await page.request.get(`${base}/api/browser/scripts/pedido-boe`).then((r) => r.text())).includes("otra-clave-e2e")) fail("the replay saved the secret text");

// step by step: it asks before each step, and Stop ends it at once
await row.getByRole("button", { name: "Paso a paso" }).click();
await viewReplay.getByText("¿Ejecutar el siguiente paso?").waitFor({ timeout: 10000 });
await viewReplay.getByRole("button", { name: "Ejecutar el paso" }).click();
await viewReplay.getByText("Va a abrir boe.es, un dominio que no tienes permitido.").waitFor({ timeout: 10000 });
await viewReplay.getByRole("button", { name: "Permitir solo esta vez" }).click();
await viewReplay.getByText("¿Ejecutar el siguiente paso?").waitFor({ timeout: 10000 });
await viewReplay.getByRole("button", { name: "Parar", exact: true }).click();
await viewReplay.getByText("Detenida", { exact: true }).waitFor({ timeout: 10000 });
calls = await browserCalls();
if (named(calls, "browser_navigate") !== 3 || named(calls, "browser_type") !== 2 || named(calls, "browser_click") !== 1) fail("after stopping step by step: " + JSON.stringify(calls));
await page.screenshot({ path: `${out}/a16-3-recorder-stopped.png` });
await row.getByRole("button", { name: "Borrar" }).click();
await recorder().getByText("No hay guiones guardados.").waitFor({ timeout: 5000 });
await page.keyboard.press("Escape");

// Spike Geo (A16): a map of regions coloured by a number, drawn without any tile server, with its measures and legend
await page.getByRole("button", { name: "Nuevo chat" }).click();
await pick("Data");
await page.locator("#composer-input").fill("Dibuja el mapa de las regiones");
await page.keyboard.press("Enter");
const geoCard = page.getByRole("region", { name: "Regiones por habitantes" });
await geoCard.locator("img.explorer-svg").waitFor({ timeout: 15000 });
if (!(await geoCard.locator("img.explorer-svg").evaluate((img) => img.complete && img.naturalWidth > 0))) fail("the map did not load as an image");
if (await geoCard.locator("svg").count()) fail("the map must be an image, not inline markup");
await geoCard.getByText("Proyección equirrectangular").waitFor();
await geoCard.getByText("Medidas por elemento").click();
const geoRows = geoCard.locator("tbody tr");
if (await geoRows.count() !== 3) fail("the map should list 3 regions, it lists " + await geoRows.count());
await geoRows.filter({ hasText: "Centro" }).getByText("540").waitFor();
await page.screenshot({ path: `${out}/a16-4-geo-map.png` });
await geoCard.getByRole("button", { name: "Abrir en el panel" }).click();
const geoFrame = page.frameLocator(".artifact-frame");
await geoFrame.locator("svg").first().waitFor({ timeout: 10000 });
if (await geoFrame.locator("table tbody tr").count() !== 3) fail("the map's page should hold the table of 3 regions");
await page.screenshot({ path: `${out}/a16-5-geo-panel.png` });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Dibuja el mapa de las ciudades");
await page.keyboard.press("Enter");
const cityCard = page.getByRole("region", { name: "Ciudades" });
await cityCard.locator("img.explorer-svg").waitFor({ timeout: 15000 });
await cityCard.getByText("3 elementos").first().waitFor();

// Architecture Explorer (A16): the modules of a project, import loops highlighted and listed
await page.getByRole("button", { name: "Nuevo chat" }).click();
await pick("Code");
await page.locator("#composer-input").fill("Dame la arquitectura del proyecto");
await page.keyboard.press("Enter");
const archCard = page.getByRole("region", { name: "Arquitectura del proyecto: proyecto" });
await archCard.locator("img.explorer-svg").waitFor({ timeout: 15000 });
if (!(await archCard.locator("img.explorer-svg").evaluate((img) => img.complete && img.naturalWidth > 0))) fail("the diagram did not load as an image");
const cycleRows = archCard.locator(".explorer-cycles tbody tr");
if (await cycleRows.count() !== 2) fail("the project has 2 import loops, the card lists " + await cycleRows.count());
await cycleRows.filter({ hasText: "app/models.py → app/util.py → app/models.py" }).waitFor();
await cycleRows.filter({ hasText: "web/a.js → web/b.js → web/a.js" }).waitFor();
await page.screenshot({ path: `${out}/a16-6-architecture.png` });
await archCard.getByRole("button", { name: "Abrir en el panel" }).click();
await page.frameLocator(".artifact-frame").locator("table tbody tr").nth(1).waitFor({ timeout: 10000 });
await page.screenshot({ path: `${out}/a16-7-architecture-panel.png` });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();
await page.getByRole("button", { name: "Nuevo chat" }).click();
await pick("Law"); // the choice before this block, which the sections below were written with

// Forge: the task becomes a blueprint the user edits and approves; the team runs it, the checker sends the writer
// back once, and the report lists the criteria and the saved file
await page.getByRole("button", { name: "Forge", exact: true }).click();
await page.getByLabel("Tarea").fill("Calcula el IVA de 120 € y escribe un informe");
await page.locator(".forge-skills summary").click();
await page.locator('[data-forge-skill="writing-plans"]').check();
await page.screenshot({ path: `${out}/07g-forge.png` });
// Parallel Prototypes is opt-in: the "two approaches" box starts unticked and only changes the button when ticked
// (building two git branches is covered by tests/test_prototypes.py against real git repositories)
const protoToggle = page.locator("[data-proto-toggle]");
if (await protoToggle.isChecked()) fail("Parallel Prototypes must be off by default");
await protoToggle.check();
await page.getByRole("button", { name: "Preparar los dos planes" }).waitFor({ timeout: 5000 });
await page.getByText("×2 tiempo y tokens", { exact: false }).waitFor({ timeout: 5000 });
await protoToggle.uncheck();
await page.getByRole("button", { name: "Preparar el plan" }).click();
const step2 = page.locator('[data-step="t2"]');
await step2.getByLabel("Archivos que guarda (separados por comas)").waitFor({ timeout: 10000 });
if (await step2.getByLabel("Archivos que guarda (separados por comas)").inputValue() !== "informe.md") fail("blueprint deliverable not shown");
if (await page.locator('[data-step="t1"]').getByLabel("Papel").inputValue() !== "research") fail("blueprint role not shown");
const criteriaBox = page.getByLabel("Criterios de aceptación (uno por línea)");
if (!await page.locator('[data-forge-skill="writing-plans"]').isChecked()) fail("Forge lost the selected skill on drafting");
await criteriaBox.fill((await criteriaBox.inputValue()) + "\nMenciona el IVA del 21 %");
await page.screenshot({ path: `${out}/07h-blueprint.png`, fullPage: true });
await page.getByRole("button", { name: "Aprobar y ejecutar" }).click();
for (let i = 0; i < 2; i++) { // the writer saves informe.md, is sent back once, and saves it again
  await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 10000 });
  await page.locator(".permission.done").nth(i).waitFor({ timeout: 5000 });
}
const report = page.locator(".forge-report");
await report.getByText("2/2 criterios cumplidos").waitFor({ timeout: 10000 });
await report.getByRole("link", { name: "informe.md" }).waitFor();
await page.locator(".skill-chip", { hasText: "writing-plans" }).waitFor({ timeout: 5000 });
// Read the checked output directly in the report; Markdown remains literal text.
await report.getByRole("button", { name: "Vista previa: informe.md", exact: true }).click();
await report.getByRole("region", { name: "Archivos creados" }).locator("pre").waitFor();
const savedReport = await (await page.request.get(`${base}/api/workspace/files/informe.md`)).text();
if ((await report.locator("pre").textContent()) !== savedReport || !savedReport.includes("145,20")) fail("Forge text preview did not match the saved report");
await page.screenshot({ path: `${out}/07i-forge-text-preview.png`, fullPage: true });
await report.getByRole("button", { name: "Cerrar", exact: true }).click();
if (!(await page.locator(".trace").getByText("ronda 2").count())) fail("the sent-back step is not shown");
if ((await page.locator(".trace .role-verify").count()) < 2) fail("expected two checker passes in the trace");
await page.screenshot({ path: `${out}/07i-forge-report.png`, fullPage: true });

// Creator: a template and a few answers become a Forge plan; the run follows the template's skill and design system
await page.getByRole("button", { name: "Crear", exact: true }).click();
await page.locator(".template-card", { hasText: "Dashboard" }).waitFor({ timeout: 5000 });
if ((await page.locator(".template-card").count()) !== 8) fail("expected 8 Creator templates");
await page.screenshot({ path: `${out}/07s-creator.png` });
await page.locator(".template-card", { hasText: "Dashboard" }).click();
await page.locator(".file-picks").getByRole("button", { name: "ventas.csv" }).click();
if (await page.getByLabel("Archivo de datos").inputValue() !== "ventas.csv") fail("the data file chip did not fill the field");
await page.getByLabel("¿Qué quieres ver? (opcional)").fill("ingresos por región");
await page.getByLabel("Sistema de diseño").selectOption("spike");
await page.screenshot({ path: `${out}/07t-creator-form.png` });
await page.getByRole("button", { name: "Preparar el plan" }).click();
const dashStep = page.locator('[data-step="t2"]');
await dashStep.getByLabel("Archivos que guarda (separados por comas)").waitFor({ timeout: 5000 });
if (await dashStep.getByLabel("Archivos que guarda (separados por comas)").inputValue() !== "dashboard.html") fail("template deliverable not shown");
if (await page.locator('[data-step="t1"]').getByLabel("Papel").inputValue() !== "research") fail("template research step not shown");
await page.screenshot({ path: `${out}/07u-creator-plan.png`, fullPage: true });
await page.getByRole("button", { name: "Aprobar y ejecutar" }).click();
await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 10000 });
const dashReport = page.locator(".forge-report");
await dashReport.getByText("2/2 criterios cumplidos").waitFor({ timeout: 10000 });
await dashReport.getByRole("link", { name: "dashboard.html" }).waitFor();
await dashReport.getByRole("button", { name: "Vista previa: dashboard.html", exact: true }).click();
const bar = page.frameLocator(".artifact-frame").locator("rect").first();
await bar.waitFor({ timeout: 5000 });
const barColour = await bar.evaluate((el) => getComputedStyle(el).fill);
if (barColour !== "rgb(136, 212, 69)") fail("the dashboard does not use the SPIKE tokens: " + barColour);
await page.screenshot({ path: `${out}/07v-creator-result.png`, fullPage: true });
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

// Spike Motion: Code writes an HTML scene and renders it to a video that plays in the chat
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByLabel("Especialista", { exact: true }).selectOption("code");
await page.locator("#composer-input").fill("Hazme un vídeo animado de 2 segundos con el título SPIKE");
await submitChat();
for (let i = 0; i < 2; i++) { // write the scene, then render it
  await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 10000 });
  await page.locator(".permission.done").nth(i).waitFor({ timeout: 30000 });
}
const player = page.locator(".video-card video");
await player.waitFor({ timeout: 30000 });
const length = await player.evaluate((v) => new Promise((ok) => (v.readyState >= 1 ? ok(v.duration)
  : v.addEventListener("loadedmetadata", () => ok(v.duration), { once: true }))));
if (Math.abs(length - 2) > 0.1) fail("the rendered video does not last 2 s: " + length);
await player.evaluate((v) => new Promise((ok) => { v.addEventListener("seeked", () => ok(), { once: true }); v.currentTime = 1.9; }));
await page.locator(".video-card figcaption").getByText("1280×720", { exact: false }).waitFor();
await player.evaluate((v) => new Promise((ok) => (v.readyState >= 2 ? ok() : v.addEventListener("loadeddata", () => ok(), { once: true }))));
await page.waitForTimeout(400); // the player's own loading spinner fades out
await page.screenshot({ path: `${out}/07w-motion-video.png` });
await page.getByLabel("Especialista", { exact: true }).selectOption("auto");

// Code isolation: the card of a python call says whether it will run isolated, and the call runs
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Haz un cálculo en python");
await submitChat();
const pyCard = page.locator(".permission", { hasText: "python" });
await pyCard.waitFor({ timeout: 10000 });
const isolation = pyCard.locator("[data-isolated]");
await isolation.waitFor({ timeout: 5000 });
const isolated = (await isolation.getAttribute("data-isolated")) === "true";
const isolationLine = (await isolation.textContent()) ?? "";
if (!(isolated ? isolationLine.startsWith("aislado (") : isolationLine.startsWith("sin aislamiento: "))) fail("the python card does not say whether it is isolated: " + isolationLine);
await page.screenshot({ path: `${out}/07x-python-isolation.png` });
await pyCard.getByRole("button", { name: "Permitir una vez" }).click();
await page.getByText("Resultado de python: 42", { exact: false }).waitFor({ timeout: 15000 });

// Trustworthy answers: the summary chip under the answer, a badge per claim behind "ver comprobación", a fabricated
// citation caught, and a second opinion that is offered but sent only after the click (DeepSeek, added above, is
// served by the scripted provider here; the call log shows when it was really called)
const remoteCalls = async () => (await (await fetch(`${base}/api/calls?remote=true`)).json()).filter((c) => c.provider_id === "deepseek").length;
const callsBefore = await remoteCalls();
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Haz una comprobación de fuentes con contrato.md");
await submitChat();
const trustBox = page.locator(".msg.assistant").last().locator("[data-trust]");
await trustBox.locator("[data-trust-summary]").waitFor({ timeout: 15000 });
const trustSummary = ((await trustBox.locator("[data-trust-summary]").textContent()) ?? "").trim();
if (trustSummary !== "1 verificada · 3 sin comprobar") fail("the summary chip says: " + trustSummary);
if (await trustBox.locator("[data-claim-label]").count()) fail("the claims should be hidden until 'ver comprobación' is pressed");
await trustBox.getByRole("button", { name: "ver comprobación" }).click();
const badges = await trustBox.locator("[data-claim-label]").evaluateAll((els) => els.map((e) => e.getAttribute("data-claim-label")));
if (badges.join(",") !== "verified,unchecked,unchecked,unchecked") fail("the claim badges are " + badges.join(","));
const failedCitation = trustBox.locator('[data-citation="unsupported"]');
await failedCitation.waitFor({ timeout: 5000 });
if (!(await failedCitation.textContent())?.includes("falta en la fuente: 90")) fail("the changed number is not shown: " + (await failedCitation.textContent()));
await trustBox.locator('[data-claim-label="verified"] .claim-badge').getByText("verificada").waitFor();
const offer = trustBox.locator('[data-offer="deepseek"]');
await offer.getByRole("button", { name: "Preguntar a DeepSeek" }).waitFor({ timeout: 5000 });
if (!(await offer.textContent())?.includes("no se enviará")) fail("the offer does not say the user's files stay out: " + (await offer.textContent()));
if ((await remoteCalls()) !== callsBefore) fail("a provider was called before the user pressed the button");
await page.screenshot({ path: `${out}/07y-trust.png` });
await offer.getByRole("button", { name: "Preguntar a DeepSeek" }).click();
await trustBox.locator("[data-second-opinion]").getByText("Soy SPIKE", { exact: false }).waitFor({ timeout: 10000 });
if ((await remoteCalls()) !== callsBefore + 1) fail(`pressing the button should make exactly one call, got ${(await remoteCalls()) - callsBefore}`);
await trustBox.locator("[data-second-opinion]").getByText("Segunda opinión de DeepSeek", { exact: false }).waitFor();
await chatIdle();
await page.reload();
await chatIdle();
await page.locator(".conv-title", { hasText: "comprobación de fuentes" }).first().click();
const storedBox = page.locator(".msg.assistant").last().locator("[data-trust]");
await storedBox.locator("[data-trust-summary]").getByText("1 verificada · 3 sin comprobar").waitFor({ timeout: 10000 });
await storedBox.locator("[data-second-opinion]").waitFor({ timeout: 5000 }); // the second opinion is kept with the answer
if (await storedBox.locator("[data-offer]").count()) fail("an answered offer must not offer to ask again");

// Parallel Minds: off by default and per message; the toggle shows "×3 tiempo y tokens" and the cost estimate before
// anything runs; three answers come back, the one with the best claim labels is the answer and the others stay collapsed
// with their labels (the scripted provider answers by temperature: 0.7 only restates the question, the others invent)
const MINDS_QUESTION = "Dime algo del modelo Zorvak: el modelo Zorvak tiene 12 capas.";
await page.getByRole("button", { name: "Nuevo chat" }).click();
if (await page.locator("[data-minds-box]").count()) fail("Parallel Minds must be off by default");
const mindsToggle = page.locator("[data-minds-toggle]");
if ((await mindsToggle.getAttribute("aria-pressed")) !== "false") fail("the Parallel Minds toggle should start off");
await page.locator("#composer-input").fill(MINDS_QUESTION);
await mindsToggle.click();
const mindsBox = page.locator("[data-minds-box]");
await mindsBox.waitFor({ timeout: 5000 });
if (((await mindsBox.locator("[data-minds-multiplier]").textContent()) ?? "").trim() !== "×3 tiempo y tokens") fail("the multiplier is not shown before sending");
await mindsBox.locator("[data-minds-estimate]").getByText("modelo local", { exact: false }).waitFor({ timeout: 5000 }); // local: no API cost
await page.screenshot({ path: `${out}/07z-minds-composer.png` });
await mindsBox.getByLabel("Mentes").selectOption("4");
await mindsBox.locator("[data-minds-multiplier]").getByText("×4 tiempo y tokens").waitFor({ timeout: 5000 });
await mindsBox.getByLabel("Mentes").selectOption("3");
await page.getByLabel("Proveedor", { exact: true }).selectOption("deepseek"); // an API provider without prices: no cost can be estimated
await mindsBox.locator("[data-minds-estimate]").getByText("Sin precio configurado para DeepSeek", { exact: false }).waitFor({ timeout: 5000 });
if (!((await mindsBox.locator("[data-minds-estimate]").textContent()) ?? "").includes("3 llamadas")) fail("the estimate should count 3 calls");
await page.getByLabel("Proveedor", { exact: true }).selectOption("");
await mindsBox.locator("[data-minds-estimate]").getByText("modelo local", { exact: false }).waitFor({ timeout: 5000 });
const callsBeforeMinds = (await (await fetch(`${base}/api/calls?remote=true`)).json()).length;
await submitChat(); // the provider select had the focus
const mindsAnswer = page.locator(".msg.assistant").last();
await mindsAnswer.locator("[data-minds]").waitFor({ timeout: 15000 });
await mindsAnswer.locator("[data-mind-chosen]").waitFor({ timeout: 15000 });
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length >= 1 && !document.querySelector(".typing"), null, { timeout: 15000 });
if (((await mindsAnswer.locator(".markdown").first().textContent()) ?? "").trim() !== "El modelo Zorvak tiene 12 capas.") fail("the answer should be the mind with the best labels");
if ((await mindsToggle.getAttribute("aria-pressed")) !== "false") fail("Parallel Minds should turn off after the message is sent");
if (!((await mindsAnswer.locator("[data-minds-multiplier]").textContent()) ?? "").includes("×3 tiempo y tokens")) fail("the answer does not say it took 3 minds");
const chosenMind = mindsAnswer.locator("[data-mind-chosen]").locator("xpath=ancestor::li[@data-mind]");
if ((await chosenMind.getAttribute("data-mind")) !== "2") fail("mind 2 should be chosen, got " + (await chosenMind.getAttribute("data-mind")));
const mindLabels = await mindsAnswer.locator("[data-mind]").evaluateAll((els) => els.map((e) => (e.querySelector("[data-mind-labels]")?.textContent ?? "").trim()));
if (mindLabels.join("|") !== "1 verificada · 2 sin comprobar|1 verificada|2 sin comprobar") fail("labels of the minds: " + mindLabels.join("|"));
if (!((await mindsAnswer.locator("[data-minds-why]").textContent()) ?? "").includes("Se eligió la mente 2")) fail("the answer does not say why mind 2 was chosen");
if (await mindsAnswer.locator('[data-mind="3"] .trace-body').count()) fail("the minds that were not chosen should be collapsed");
await mindsAnswer.locator('[data-mind="3"] .trace-head').click();
await mindsAnswer.locator('[data-mind="3"] .trace-body').getByText("Fue entrenado en 2019 con 40 GPUs", { exact: false }).waitFor({ timeout: 5000 });
await page.screenshot({ path: `${out}/07z-minds-answer.png` });
if ((await (await fetch(`${base}/api/calls?remote=true`)).json()).length !== callsBeforeMinds) fail("local minds should not log remote calls");
await chatIdle();
await page.reload(); // the minds are kept with the answer
await chatIdle();
await page.locator(".conv-title", { hasText: "Dime algo del modelo Zorvak" }).first().click();
const storedMinds = page.locator(".msg.assistant").last().locator("[data-minds]");
await storedMinds.waitFor({ timeout: 10000 });
await storedMinds.locator('[data-mind="2"] [data-mind-chosen]').waitFor({ timeout: 5000 });
await storedMinds.locator('[data-mind="1"] [data-mind-labels]').getByText("1 verificada · 2 sin comprobar").waitFor({ timeout: 5000 });
// an ordinary message right after it makes one answer and shows no minds
await page.locator("#composer-input").fill("Hola, ¿quién eres?");
await submitChat();
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length === 2, null, { timeout: 15000 });
if (await page.locator(".msg.assistant").last().locator("[data-minds]").count()) fail("a message sent without the toggle must not run minds");
// 6e. desktop actions (A19): off until the user turns them on; each action waits for an approval card; Stop is always there
const desktopCalls = async () => (await (await fetch(`${base}/__e2e/desktop`)).json()).calls;
const anthropic = await page.request.post(`${base}/api/providers`, { data: {
  preset: "anthropic", api_key: "sk-e2e-not-a-real-key", model: "claude-sonnet-5-5", allow_paid: true, share_files: true } });
if (!anthropic.ok()) fail("could not add the provider with computer use: " + (await anthropic.text()));
await chatIdle();
await page.reload();
await page.getByText("¿En qué te ayudo hoy?").waitFor();
if (await page.getByTestId("desktop-open").count()) fail("the desktop button must not show while the setting is off");
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Escritorio" }).click();
const desktopSetting = page.getByLabel("Control del escritorio (solo con un proveedor con computer use)");
await desktopSetting.waitFor();
if (await desktopSetting.isChecked()) fail("desktop control must be off by default");
if (!(await page.getByTestId("desktop-start").isDisabled())) fail("a desktop task must not start while the setting is off");
await page.getByTestId("desktop-provider").locator("option", { hasText: "nunca controla el escritorio" }).waitFor({ state: "attached" });
const refusedProviders = await page.getByTestId("desktop-provider").locator("option[disabled]").allTextContents();
if (!refusedProviders.some((o) => o.includes("nunca controla el escritorio"))) fail("a local model must be refused: " + refusedProviders.join(" | "));
await desktopSetting.click();
await page.locator('[data-testid="desktop-enabled"]:checked').waitFor({ timeout: 5000 });
await page.getByTestId("desktop-provider").selectOption("anthropic");
await page.waitForFunction(() => document.querySelector('[data-testid="desktop-start"]')?.disabled === false, null, { timeout: 5000 });
await page.getByTestId("desktop-driver").getByText("scripted").waitFor({ timeout: 5000 });
await page.screenshot({ path: `${out}/07z-desktop-settings.png` });
await page.getByTestId("desktop-start").click();
const task = page.getByTestId("desktop-task");
await task.getByTestId("desktop-estimate").getByText("Hasta 21 peticiones a Anthropic", { exact: false }).waitFor({ timeout: 10000 });
await task.getByTestId("desktop-goal").fill("Pulsa el botón de la calculadora");
await task.getByTestId("desktop-begin").click();
const deskCard = task.getByTestId("desktop-card");
await deskCard.waitFor({ timeout: 10000 });
if ((await desktopCalls()).length) fail("an action ran before the user approved it");
await task.getByTestId("desktop-stop").waitFor();
if (!(await deskCard.getByTestId("desktop-action").textContent())?.includes("Clic en (300, 200)")) fail("the card does not say what it will do");
if (await deskCard.getByTestId("desktop-sensitive").count()) fail("a plain click must not be marked sensitive");
const cropUrl = ((await deskCard.getByTestId("desktop-crop").evaluate((el) => el.style.backgroundImage)).match(/\/api\/desktop\/shots\/[\w/]+/) ?? [])[0];
const cropShot = cropUrl ? await page.request.get(base + cropUrl) : null;
if (!cropShot?.ok() || cropShot.headers()["content-type"] !== "image/png" || cropShot.headers()["cache-control"] !== "no-store") fail("the card's screenshot is not served privately: " + cropUrl);
await page.screenshot({ path: `${out}/07z-desktop-card.png` });
await deskCard.getByTestId("desktop-approve").click();
await task.getByTestId("desktop-done").getByText("Tarea de escritorio: 1 paso, terminó.").waitFor({ timeout: 10000 });
if (JSON.stringify(await desktopCalls()) !== JSON.stringify([["click", 300, 200, "left", 1, []]])) fail("the approved click did not reach the screen: " + JSON.stringify(await desktopCalls()));
await task.getByRole("button", { name: "Abrir el chat" }).click();
await page.getByTestId("desktop-record").getByText("Clic en (300, 200) — aprobada", { exact: false }).waitFor({ timeout: 10000 });
await page.screenshot({ path: `${out}/07z-desktop-record.png` });
// a task the model marks as sensitive offers no "approve the next"; Stop ends it and nothing is done
const desktopOpenBtn = page.getByTestId("desktop-open");
await desktopOpenBtn.click();
await page.getByTestId("desktop-estimate").getByText("Hasta 21 peticiones", { exact: false }).waitFor({ timeout: 10000 });
if ((await desktopCalls()).length !== 1) fail("opening DesktopTask must not run an action");
await page.keyboard.press("Escape");
await page.getByTestId("desktop-task").waitFor({ state: "hidden" });
if (!(await desktopOpenBtn.evaluate((el) => el === document.activeElement))) fail("DesktopTask must restore keyboard focus on close");
await desktopOpenBtn.click();
await page.getByTestId("desktop-estimate").getByText("Hasta 21 peticiones", { exact: false }).waitFor({ timeout: 10000 });
await page.getByTestId("desktop-goal").fill("Pulsa Enviar en el correo");
await page.getByTestId("desktop-begin").click();
const sensitiveCard = page.getByTestId("desktop-card");
await sensitiveCard.getByTestId("desktop-sensitive").getByText("envío o publicación").waitFor({ timeout: 10000 });
if (await sensitiveCard.getByTestId("desktop-approve-next").count()) fail("a sensitive action must not offer to approve the next ones");
await page.getByTestId("desktop-stop").click();
await page.getByTestId("desktop-done").getByText("detenida por ti", { exact: false }).waitFor({ timeout: 10000 });
if ((await desktopCalls()).length !== 1) fail("stopping must leave the screen untouched: " + JSON.stringify(await desktopCalls()));
await page.getByTestId("desktop-done").getByRole("button", { name: "Cerrar" }).click();

// 7. dark mode + mobile
const dark =await browser.newContext({ viewport: { width: 1360, height: 860 }, locale: "en-US", colorScheme: "dark" });
const dp = await dark.newPage();
await dp.goto(base);
await dp.getByText("How can I help you today?").waitFor();
await dp.screenshot({ path: `${out}/08-welcome-dark-en.png` });
await dp.locator(".conv-title", { hasText: "Calcula el IVA de 120" }).click(); // a stored Forge answer, rebuilt
await dp.locator(".forge-report").getByText("2/2 criteria met").waitFor({ timeout: 5000 });
if ((await dp.locator(".trace .role-verify").count()) < 2) fail("stored Forge answer lost its checker passes");
await dp.screenshot({ path: `${out}/08b-forge-dark-en.png` });
await dp.locator(".conv-title", { hasText: "comprobación de fuentes" }).first().click(); // a stored trust report, in English
const enTrust = dp.locator(".msg.assistant").last().locator("[data-trust]");
await enTrust.locator("[data-trust-summary]").getByText("1 verified · 3 unchecked").waitFor({ timeout: 5000 });
await enTrust.getByRole("button", { name: "show checks" }).click();
await enTrust.locator('[data-claim-label="unchecked"] .claim-badge').first().getByText("unchecked").waitFor({ timeout: 5000 });
await enTrust.getByText("Second opinion from DeepSeek", { exact: false }).waitFor({ timeout: 5000 });
await dp.screenshot({ path: `${out}/08c-trust-dark-en.png` });
await dp.locator(".conv-title", { hasText: "Dime algo del modelo Zorvak" }).first().click(); // the stored Parallel Minds answer, in English
const enMinds = dp.locator("[data-minds]"); // the answer after it (the ordinary message) shows no minds
await enMinds.getByText("Parallel minds", { exact: true }).waitFor({ timeout: 5000 });
await enMinds.locator("[data-minds-multiplier]").getByText("×3 time and tokens").waitFor({ timeout: 5000 });
await enMinds.locator("[data-minds-why]").getByText("Mind 2 was chosen by its labels", { exact: false }).waitFor({ timeout: 5000 });
await enMinds.locator('[data-mind="1"] [data-mind-labels]').getByText("1 verified · 2 unchecked").waitFor({ timeout: 5000 });
await dp.screenshot({ path: `${out}/08d-minds-dark-en.png` });
// the stored map and diagram cards come back rebuilt, in English and the dark theme (the drawings read in both)
await dp.locator(".conv-title", { hasText: "Dame la arquitectura del proyecto" }).first().click();
const darkGraph = dp.getByRole("region", { name: "Project architecture: proyecto" });
await darkGraph.locator("img.explorer-svg").waitFor({ timeout: 10000 });
await darkGraph.getByText("Import cycles", { exact: true }).waitFor();
await darkGraph.locator(".explorer-cycles tbody tr").nth(1).waitFor();
await dp.screenshot({ path: `${out}/a16-8-architecture-dark-en.png` });
await dp.locator(".conv-title", { hasText: "Dibuja el mapa de las regiones" }).first().click();
const darkMap = dp.getByRole("region", { name: "Regiones por habitantes" });
await darkMap.locator("img.explorer-svg").waitFor({ timeout: 10000 });
await darkMap.getByText("Measures per feature").click();
await darkMap.locator("tbody tr").nth(2).waitFor();
await dp.screenshot({ path: `${out}/a16-9-geo-dark-en.png` });
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "es-ES", isMobile: true, hasTouch: true });
const mp = await mobile.newPage();
await mp.goto(base);
await mp.getByText("¿En qué te ayudo hoy?").waitFor();
const overflow = await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
if (overflow) fail("horizontal overflow on mobile");
const send = await mp.locator(".send-btn").boundingBox();
if (!send || send.x + send.width > 390) fail("send button outside the mobile viewport");
await mp.screenshot({ path: `${out}/09-mobile.png` });
await mp.getByRole("button", { name: "Investigación", exact: true }).click();
await mp.getByRole("heading", { name: "Investigación", exact: true }).waitFor();
if (await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) fail("Research overflows mobile");
await mp.screenshot({ path: `${out}/09-research-mobile.png` });
// the diagram card on a phone: the picture shrinks to the screen and the table of cycles scrolls inside its card
const openSidebar = mp.getByRole("button", { name: /Abrir barra lateral|Open sidebar/ });
if (await openSidebar.count()) await openSidebar.click();
await mp.locator(".conv-title", { hasText: "Dame la arquitectura del proyecto" }).first().click();
await mp.locator("img.explorer-svg").waitFor({ timeout: 10000 });
if (await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) fail("horizontal overflow on mobile with the diagram card");
await mp.waitForTimeout(500); // the sidebar slides away first
await mp.screenshot({ path: `${out}/a16-10-architecture-mobile.png` });

await workflowFlow(page, ctx.request, base, out, fail);
await dataAppFlow(page, ctx.request, base);

if (errors.length) fail("browser errors: " + errors.join(" | "));
await browser.close();
console.log(process.exitCode ? "E2E FAILED" : "E2E OK");
