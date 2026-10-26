// End-to-end smoke test of the real web app against tests/e2e/serve_scripted.py.
// Usage: node e2e/smoke.mjs [baseUrl] [screenshotDir]
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
const errors = [];
const artifactLogs = []; // what the sandboxed artifact tried and the browser refused, kept apart from app errors
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && (m.location().url.startsWith("about:srcdoc") || m.text().includes("Content Security Policy") ? artifactLogs : errors).push(m.text()));
const frameRequests = [];
page.on("request", (r) => r.frame() !== page.mainFrame() && frameRequests.push(r.url()));

await page.goto(base);
await page.getByText("¿En qué te ayudo hoy?").waitFor();
await page.screenshot({ path: `${out}/01-welcome.png` });

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
const exportedLab = await (await ctx.request.get(await labExport.getAttribute("href"))).json();
if (exportedLab.rows.length !== 2) fail("Lab JSON export must contain both results");
await lab.getByRole("button", { name: "Estimar prueba de proveedor", exact: true }).click();
await lab.getByRole("button", { name: "Ejecutar ahora" }).waitFor();
if (labPosts.filter((p) => p.endsWith("/execute")).length !== 1) fail("Lab probe preview must not execute");
await lab.getByRole("button", { name: "Ejecutar ahora" }).click();
await lab.getByText("Sin probar", { exact: true }).first().waitFor();
if (await lab.locator("tbody tr").count() !== 5) fail("Lab must list all five capabilities");
await page.screenshot({ path: `${out}/00-lab.png` });
await lab.getByRole("button", { name: "Volver al chat" }).click();
await page.getByRole("button", { name: "Lab", exact: true }).click();
await lab.getByRole("button", { name: /Estimar comparación/ }).last().click();
await lab.locator("tbody tr").nth(1).waitFor();
await lab.getByRole("button", { name: "Volver al chat" }).click();

// 1. direct chat
await page.locator("#composer-input").fill("Hola, ¿quién eres?");
await page.keyboard.press("Enter");
await page.getByText("proveedor *de prueba*".replace(/\*/g, "")).first().waitFor({ timeout: 10000 }).catch(() => {});
await page.locator(".msg.assistant .markdown").first().waitFor();
await page.waitForFunction(() => document.querySelector(".msg-actions") !== null, null, { timeout: 10000 });
if (!(await page.locator(".conv").count())) fail("conversation not listed in sidebar");

// 1b. retry on the same model, then edit the question: each replaces the turn instead of adding one
await page.locator(".msg.assistant").last().getByRole("button", { name: "Reintentar" }).click();
await page.getByRole("menuitem", { name: "El mismo modelo" }).click();
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length === 1 && document.querySelectorAll(".msg.user").length === 1, null, { timeout: 10000 })
  .catch(() => fail("retry should replace the answer"));
await page.locator(".msg.user").first().hover();
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
  await page.keyboard.press("Enter");
  await page.waitForFunction((n) => document.querySelectorAll(".msg-actions").length === n, answers, { timeout: 10000 });
}
await page.locator(".msg.user").last().hover();
await page.locator(".msg.user").last().getByRole("button", { name: "Editar" }).click();
await page.getByRole("textbox", { name: "Editar" }).fill("Dímelo en una tabla");
await page.locator(".msg.user.editing").getByRole("button", { name: "Enviar en una rama" }).click();
await page.locator(".conv-title", { hasText: "¿Qué sabes hacer? · rama" }).waitFor({ timeout: 10000 });
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length === 2, null, { timeout: 10000 });
const branchTexts = (await page.locator(".msg.user .bubble").allTextContents()).map((x) => x.trim()).join("|");
if (branchTexts !== "¿Qué sabes hacer?|Dímelo en una tabla") fail("branch thread: " + branchTexts);
await page.screenshot({ path: `${out}/01c-branch.png` });
await page.locator(".conv-title", { hasText: /^¿Qué sabes hacer\?$/ }).click();
await page.locator(".msg.user .bubble", { hasText: "Dímelo en una lista" }).waitFor({ timeout: 10000 });
await page.locator(".conv-title", { hasText: "Hola, ¿quién eres?" }).click();
await page.locator(".msg.user .bubble", { hasText: "Hola de nuevo" }).waitFor({ timeout: 10000 });

// 2. multi-specialist plan with synthesis
await page.locator("#composer-input").fill("Plan a marketing campaign for an ETF and estimate the ROI of the investment");
await page.keyboard.press("Enter");
await page.getByText("Plan de lanzamiento").waitFor({ timeout: 15000 });
await page.waitForFunction(() => document.querySelectorAll(".msg-actions").length >= 2, null, { timeout: 10000 });
const chips = await page.locator(".msg.assistant").nth(1).locator(".route .chip").allInnerTexts();
if (!chips.join(" ").includes("Marketing") || !chips.join(" ").includes("Finance")) fail("route chips missing: " + chips);
if ((await page.locator(".msg.assistant").nth(1).locator(".trace-item").count()) < 2) fail("subtask trace missing");
await page.locator(".msg.assistant").nth(1).locator(".trace-head").first().click();
await page.screenshot({ path: `${out}/02-multi-specialist.png` });

// 3. tool permission flow (write_file asks by default)
await page.locator("#composer-input").fill("Crea un archivo de notas");
await page.keyboard.press("Enter");
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
await lastAnswer.getByRole("button", { name: "Ver paso a paso" }).click();
const replay = page.getByRole("dialog", { name: "Paso a paso" });
await replay.waitFor();
await replay.locator(".replay-steps button").first().click();
if (await replay.locator(".replay-view .markdown").count()) fail("step 1 should show no answer text yet");
await replay.locator(".replay-steps button", { hasText: "Usa write_file" }).click();
await replay.locator(".replay-view .trace-item", { hasText: "write_file" }).waitFor();
await replay.locator(".replay-steps button").last().click();
await replay.locator(".replay-view", { hasText: "He creado el archivo" }).waitFor();
if (await replay.getByRole("button", { name: "Permitir una vez" }).count()) fail("the replay must not offer live permission buttons");
await page.screenshot({ path: `${out}/03b-replay.png` });
await page.keyboard.press("Escape");

// 4. reload restores history
await page.reload();
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
if (await dsCard.locator("label.check input").nth(1).isChecked()) fail("a new remote provider must not get file contents by default");
await page.getByRole("tab", { name: "Especialistas" }).click();
await page.getByRole("dialog").locator(".chip", { hasText: "Spike Medicine" }).waitFor();
await page.getByRole("tab", { name: "Skills" }).click();
await page.getByRole("dialog").locator('[data-skill="financial-ratio-analysis"]').waitFor();
for (const name of ["decision-simulator", "test-inventor", "migration-architect", "performance-profiler", "localization", "experiment-designer", "synthetic-data", "vector-designer", "system-diagnostic"]) {
  const card = page.getByRole("dialog").locator(`[data-skill="${name}"]`);
  await card.waitFor();
  if (!(await card.locator("input[type=checkbox]").isChecked())) fail(`bundled skill disabled: ${name}`);
}
await page.getByRole("dialog").locator('[data-skill="localization"]').getByText("Traduce textos con el glosario", { exact: false }).waitFor();
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

// 6. projects: create, upload a file, export, chat with the project's instructions; the chat stays in its project
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
await page.locator("#composer-input").fill("Resume las ventas por producto");
await page.keyboard.press("Enter");
await page.getByText("Respuesta del proyecto").waitFor({ timeout: 10000 });
// the same turn on DeepSeek: the file passage memory found is withheld, and the answer says so
await page.locator(".msg.assistant").last().getByRole("button", { name: "Reintentar" }).click();
await page.getByRole("menuitem", { name: "DeepSeek" }).click();
await page.locator(".privacy-chip", { hasText: "Archivos protegidos" }).waitFor({ timeout: 10000 });
await page.waitForFunction(() => document.querySelectorAll(".conv").length === 1, null, { timeout: 5000 }).catch(() => fail("project chat list should hold only the project's chat"));
await page.screenshot({ path: `${out}/07-project-chat.png` });
await page.getByRole("button", { name: "Todos los chats" }).click();
await page.locator(".conv-title", { hasText: "Hola, ¿quién eres?" }).waitFor();
if (await page.locator(".conv-title", { hasText: "Resume las ventas" }).count()) fail("project chat leaked into the main list");

// privacy: the call log shows the DeepSeek call with the file passage withheld
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Privacidad" }).click();
await page.locator("table.calls tr", { hasText: "DeepSeek" }).filter({ hasText: "protegidos" }).first().waitFor({ timeout: 5000 });
await page.getByTestId("usage-deepseek").filter({ hasText: "500.000 tope" }).waitFor({ timeout: 5000 });
await page.screenshot({ path: `${out}/07f-privacy.png` });
await page.keyboard.press("Escape");

// skills: a finance question gets the ratio-analysis skill, shown on the answer
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Finance" }).click();
await page.locator("#composer-input").fill("Calcula el margen EBITDA y el ROE");
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
const learnedRule = page.locator('.learned-line[data-learned="rule"]', { hasText: "Nunca uses emojis." });
await learnedRule.waitFor({ timeout: 10000 });
await page.locator("#composer-input").fill("No, el IVA general en España es del 21 %, no del 18 %.");
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
await page.locator(".contract.ok", { hasText: "Cumple el esquema" }).waitFor({ timeout: 10000 });
if (!(await page.locator("pre.json-answer").innerText()).includes('"iva": 21')) fail("contract JSON answer");
await page.getByLabel("Formato", { exact: true }).selectOption("schema");
await page.getByLabel("JSON con esquema").fill('{"type": "object", "required": ["total"]}');
await page.locator("#composer-input").fill("Y el total");
await page.keyboard.press("Enter");
await page.locator(".contract.bad", { hasText: "'total' is a required property" }).waitFor({ timeout: 10000 });
await page.screenshot({ path: `${out}/07i-contract.png` });
await page.getByLabel("Formato", { exact: true }).selectOption("text");

// temporary chat: not listed in the sidebar, no memory used
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByRole("button", { name: "Chat temporal" }).click();
await page.getByRole("heading", { name: "Chat temporal" }).waitFor();
await page.locator("#composer-input").fill("Pregunta temporal sobre el cliente Norte");
await page.keyboard.press("Enter");
await page.locator(".temp-notice").waitFor();
await page.locator(".msg.assistant .msg-actions").last().waitFor({ timeout: 10000 });
if (await page.locator(".conv-title", { hasText: "Pregunta temporal" }).count()) fail("temporary chat listed in the sidebar");
if (await page.locator(".memory-chip").count()) fail("temporary chat used memory");
await page.screenshot({ path: `${out}/07g-temporary.png` });

// evolution: retrying with another specialist teaches the router behind its check; Settings → Evolución shows it
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByLabel("Especialista", { exact: true }).selectOption("auto");
await page.locator("#composer-input").fill("Mi perro tiene diarrea desde ayer, ¿qué le doy?");
await page.keyboard.press("Enter");
await page.locator(".msg.assistant .route .chip.spec-core").waitFor({ timeout: 10000 });
await page.locator(".msg.assistant .msg-actions").last().waitFor({ timeout: 10000 });
await page.locator(".msg.assistant").last().getByRole("button", { name: "Reintentar" }).click();
await page.getByLabel("Con otro especialista").selectOption("medicine");
await page.locator(".msg.assistant .route .chip.spec-medicine").waitFor({ timeout: 10000 });
await page.locator(".msg.assistant .msg-actions").last().waitFor({ timeout: 10000 });
if ((await page.locator(".msg.assistant").count()) !== 1) fail("retry with a specialist should replace the answer");
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator("#composer-input").fill("Mi perro tiene diarrea otra vez");
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
const diagnosticPermission = page.locator(".permission", { hasText: "dependency_doctor" });
await diagnosticPermission.getByRole("button", { name: "Permitir una vez" }).click();
await page.getByRole("button", { name: "Ver informe de diagnóstico" }).click();
await page.frameLocator(".artifact-frame").getByRole("heading", { name: "Dependency Doctor" }).waitFor();
await page.frameLocator(".artifact-frame").getByText("Sin manifiesto compatible").first().waitFor();
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

// artifacts: an HTML answer opens in the sandboxed panel and can reach neither SPIKE's storage nor its API
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Code" }).click();
await page.locator("#composer-input").fill("Hazme una página de prueba");
await page.keyboard.press("Enter");
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
await page.locator(".artifact-panel").getByRole("button", { name: "Cerrar" }).click();

// Spike Design: Settings lists the design systems with a sample page; a chat with one gets a page in its tokens
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("tab", { name: "Diseño" }).click();
const minimalCard = page.locator('[data-design="minimal"]');
await minimalCard.getByRole("button", { name: "Vista previa" }).click();
await page.frameLocator('[data-design="minimal"] .design-frame').locator("h1", { hasText: "Minimal" }).waitFor({ timeout: 5000 });
if ((await page.locator("[data-design]").count()) !== 21) fail("expected 21 design systems");
await page.screenshot({ path: `${out}/07l-design-settings.png` });
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.getByLabel("Diseño", { exact: true }).selectOption("spike");
await page.locator("#composer-input").fill("Hazme una landing para mi app");
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
await page.getByText("En la vista veo: BTC a 50100 USD").waitFor({ timeout: 10000 });
const audit = await (await fetch(`${base}/api/connectors-audit`)).json();
if (!audit.some((e) => e.event === "tools/call" && e.decision === "approved")) fail("the approved view call is not in the audit log");
if (!audit.some((e) => e.event === "model-context")) fail("the context update is not in the audit log");

// Spike Data: a chart computed by SQL from a CSV, its data and query in the card, the report as a page, Word and PDF
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Data" }).click();
await page.locator("#composer-input").fill("Haz un gráfico de ventas por región con ventas.csv");
await page.keyboard.press("Enter");
const chartCard = page.locator(".chart-card");
await chartCard.locator(".chart svg").waitFor({ timeout: 15000 });
const bars = await chartCard.locator('.chart svg path[aria-roledescription="bar"]').count();
if (bars !== 2) fail(`the chart has ${bars} bars, expected 2`);
await page.getByText("El norte ingresa 90 €").waitFor({ timeout: 10000 });
await chartCard.getByRole("button", { name: "Datos" }).click();
const cells = (await chartCard.locator(".data-grid td").allTextContents()).join("|");
if (cells !== "norte|90|sur|70") fail("the chart's data is " + cells);
await chartCard.locator(".data-sql summary").click();
await chartCard.getByText("GROUP BY region").waitFor();
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
await page.keyboard.press("Enter");
await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 10000 });
const docLink = page.locator(".file-chip a", { hasText: "informe.docx" });
await docLink.waitFor({ timeout: 10000 });
const [doc_dl] = await Promise.all([page.waitForEvent("download"), docLink.click()]);
const docBytes = fs.readFileSync(await doc_dl.path());
if (docBytes.subarray(0, 2).toString() !== "PK") fail("downloaded .docx is not a zip package");
await page.screenshot({ path: `${out}/07d-document.png` });

// browser (Spike View): a new site asks with its domain; "always" saves the domain, which Settings lists and removes
await page.getByRole("button", { name: "Nuevo chat" }).click();
await page.locator(".spec-chips .chip", { hasText: "Law" }).click();
await page.locator("#composer-input").fill("Busca en el BOE la ley del IVA");
await page.keyboard.press("Enter");
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

// Forge: the task becomes a blueprint the user edits and approves; the team runs it, the checker sends the writer
// back once, and the report lists the criteria and the saved file
await page.getByRole("button", { name: "Forge", exact: true }).click();
await page.getByLabel("Tarea").fill("Calcula el IVA de 120 € y escribe un informe");
await page.screenshot({ path: `${out}/07g-forge.png` });
await page.getByRole("button", { name: "Preparar el plan" }).click();
const step2 = page.locator('[data-step="t2"]');
await step2.getByLabel("Archivos que guarda (separados por comas)").waitFor({ timeout: 10000 });
if (await step2.getByLabel("Archivos que guarda (separados por comas)").inputValue() !== "informe.md") fail("blueprint deliverable not shown");
if (await page.locator('[data-step="t1"]').getByLabel("Papel").inputValue() !== "research") fail("blueprint role not shown");
const criteriaBox = page.getByLabel("Criterios de aceptación (uno por línea)");
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
await page.locator(".file-chip", { hasText: "dashboard.html" }).getByRole("button", { name: "Vista previa" }).click();
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.keyboard.press("Enter");
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
await page.reload();
await page.locator(".conv-title", { hasText: "comprobación de fuentes" }).first().click();
const storedBox = page.locator(".msg.assistant").last().locator("[data-trust]");
await storedBox.locator("[data-trust-summary]").getByText("1 verificada · 3 sin comprobar").waitFor({ timeout: 10000 });
await storedBox.locator("[data-second-opinion]").waitFor({ timeout: 5000 }); // the second opinion is kept with the answer
if (await storedBox.locator("[data-offer]").count()) fail("an answered offer must not offer to ask again");

// 7. dark mode + mobile
const dark = await browser.newContext({ viewport: { width: 1360, height: 860 }, locale: "en-US", colorScheme: "dark" });
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
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "es-ES", isMobile: true, hasTouch: true });
const mp = await mobile.newPage();
await mp.goto(base);
await mp.getByText("¿En qué te ayudo hoy?").waitFor();
const overflow = await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
if (overflow) fail("horizontal overflow on mobile");
const send = await mp.locator(".send-btn").boundingBox();
if (!send || send.x + send.width > 390) fail("send button outside the mobile viewport");
await mp.screenshot({ path: `${out}/09-mobile.png` });

if (errors.length) fail("browser errors: " + errors.join(" | "));
await browser.close();
console.log(process.exitCode ? "E2E FAILED" : "E2E OK");
