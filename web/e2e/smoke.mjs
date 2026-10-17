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
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

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

// 4. reload restores history
await page.reload();
await page.locator(".conv-title").first().click();
await page.getByText("Plan de lanzamiento").waitFor({ timeout: 5000 });

// 5. settings
await page.getByRole("button", { name: "Ajustes" }).click();
await page.getByRole("dialog").waitFor();
await page.getByRole("tab", { name: "Proveedores" }).click();
await page.locator("select").filter({ hasText: "DeepSeek" }).selectOption("deepseek");
await page.screenshot({ path: `${out}/04-settings-providers.png` });
await page.getByRole("tab", { name: "Especialistas" }).click();
await page.getByRole("dialog").locator(".chip", { hasText: "Spike Medicine" }).waitFor();
await page.getByRole("tab", { name: "Conectores" }).click();
const fsCard = page.getByRole("dialog").locator('[data-connector="filesystem"]');
await fsCard.getByRole("button", { name: "Activar" }).click();
await fsCard.locator("code.cmd", { hasText: "@modelcontextprotocol/server-filesystem@1.0.0" }).waitFor();
await page.screenshot({ path: `${out}/05b-settings-connectors.png` });
await fsCard.getByRole("button", { name: "Cancelar" }).click();
if (await fsCard.locator("code.cmd").count()) fail("connector confirmation did not close");
await page.getByRole("tab", { name: "Motor local" }).click();
await page.getByRole("dialog").getByText("Hardware").waitFor();
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
await page.getByTestId("project-upload").setInputFiles({ name: "datos.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") });
await page.locator(".file-list a", { hasText: "datos.csv" }).waitFor();
await page.screenshot({ path: `${out}/06-project.png` });
const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Exportar (.zip)" }).click()]);
if (!download.suggestedFilename().endsWith(".spike-project.zip")) fail("export filename: " + download.suggestedFilename());
await page.locator("#composer-input").fill("Resume los datos");
await page.keyboard.press("Enter");
await page.getByText("Respuesta del proyecto").waitFor({ timeout: 10000 });
await page.waitForFunction(() => document.querySelectorAll(".conv").length === 1, null, { timeout: 5000 }).catch(() => fail("project chat list should hold only the project's chat"));
await page.screenshot({ path: `${out}/07-project-chat.png` });
await page.getByRole("button", { name: "Todos los chats" }).click();
await page.locator(".conv-title", { hasText: "Hola, ¿quién eres?" }).waitFor();
if (await page.locator(".conv-title", { hasText: "Resume los datos" }).count()) fail("project chat leaked into the main list");

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
