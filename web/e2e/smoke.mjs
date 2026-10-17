// End-to-end smoke test of the real web app against tests/e2e/serve_scripted.py.
// Usage: node e2e/smoke.mjs [baseUrl] [screenshotDir]
import { chromium } from "playwright-core";
import fs from "node:fs";

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
await page.screenshot({ path: `${out}/06-project.png` });
const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Exportar (.zip)" }).click()]);
if (!download.suggestedFilename().endsWith(".spike-project.zip")) fail("export filename: " + download.suggestedFilename());
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

// 7. dark mode + mobile
const dark = await browser.newContext({ viewport: { width: 1360, height: 860 }, locale: "en-US", colorScheme: "dark" });
const dp = await dark.newPage();
await dp.goto(base);
await dp.getByText("How can I help you today?").waitFor();
await dp.screenshot({ path: `${out}/08-welcome-dark-en.png` });
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
