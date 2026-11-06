// A22 Visual Workflow Builder against tests/e2e/serve_scripted.py: no model, no network, no drag.
// Builds input -> specialist -> condition -> output on the canvas (nodes added and edited in the panel, connections made
// with the keyboard and with the "connect to" list), checks that an unfinished step is refused with a clear problem,
// saves, runs (the file write asks for permission as it does in the chat), then runs again and stops while it waits.
export async function workflowFlow(page, request, base, out, fail) {
  await page.getByRole("button", { name: "Crear", exact: true }).click();
  await page.getByRole("button", { name: "Flujos de trabajo", exact: true }).click();
  await page.getByRole("heading", { name: "Flujos de trabajo", exact: true }).waitFor({ timeout: 5000 });
  const node = (id) => page.locator(`[data-node="${id}"]`);
  const add = (name) => page.locator(".wf-add").getByRole("button", { name: `+ ${name}`, exact: true }).click();

  await add("Entrada");
  await page.getByLabel("Nombre de variable").fill("saludo");
  await page.getByLabel("Valor por defecto").fill("hola");
  await add("Especialista");
  await page.getByLabel("Nombre de variable").fill("respuesta");
  await page.getByLabel("Instrucción").fill("Responde a: {{input}}");
  await add("Condición");
  await page.getByLabel("Valor", { exact: true }).fill("SPIKE");
  await add("Salida");
  await page.getByLabel("Qué hace").selectOption("file");
  await page.getByLabel("Ruta del archivo").fill("flujos/saludo.md");
  if ((await page.locator("[data-node]").count()) !== 4) fail("workflow: expected 4 nodes on the canvas");
  for (const el of await page.locator("[data-node]").all()) {
    if ((await el.getAttribute("role")) !== "button" || (await el.getAttribute("tabindex")) !== "0") fail("workflow: a node is not reachable by keyboard");
  }

  // keyboard: n1 -> n2 with c and Enter (the first target is already chosen); n3 true -> n4 with t and Enter
  await node("n1").focus();
  await page.keyboard.press("c");
  await page.locator(".wf-live").getByText("Conectando: destino respuesta", { exact: false }).waitFor({ timeout: 3000 });
  await page.keyboard.press("Enter");
  await page.locator(".wf-live").getByText("Conectado.", { exact: true }).waitFor({ timeout: 3000 });
  // pointer-free alternative: the properties panel
  await node("n2").focus();
  await page.getByLabel("Conectar a").selectOption("n3");
  await page.getByRole("button", { name: "Conectar", exact: true }).click();
  await node("n3").focus();
  await page.keyboard.press("t");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelectorAll(".wf-edge").length === 3, null, { timeout: 3000 });
  // a cycle is refused with a sentence and no edge is added: n3 -> n2 would close one
  await node("n3").focus();
  await page.keyboard.press("c");
  await page.keyboard.press("Enter");
  if ((await page.locator(".wf-edge").count()) !== 3) fail("workflow: a connection that closes a cycle was drawn");
  await page.screenshot({ path: `${out}/22a-workflow-canvas.png`, fullPage: true });

  // an unfinished tool step is refused by the check, with the node named, and Delete takes it away
  await add("Herramienta");
  await page.getByRole("button", { name: "Comprobar", exact: true }).click();
  await page.locator(".wf-problems [data-code=tool_unknown]").waitFor({ timeout: 5000 });
  if (!(await node("n5").getAttribute("aria-label"))?.includes("1 problemas")) fail("workflow: the invalid node does not say so");
  await page.screenshot({ path: `${out}/22b-workflow-problem.png`, fullPage: true });
  await node("n5").focus();
  await page.keyboard.press("Delete");
  await page.getByRole("button", { name: "Comprobar", exact: true }).click();
  await page.locator(".wf-info", { hasText: "El flujo es válido." }).waitFor({ timeout: 5000 });
  if (await page.locator(".wf-problems").count()) fail("workflow: problems still shown for a valid workflow");

  // save, then run: the write asks first; allowing it lets the run finish with measured times
  await page.getByLabel("Nombre del flujo").fill("Saludo con SPIKE");
  await page.getByRole("button", { name: "Guardar", exact: true }).click();
  await page.locator(".wf-info", { hasText: "Guardado como versión 1." }).waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Ejecutar", exact: true }).click();
  await page.getByRole("button", { name: "Permitir una vez" }).click({ timeout: 20000 });
  await page.locator(".wf-history .wf-chip", { hasText: "completada" }).waitFor({ timeout: 20000 });
  for (const id of ["n1", "n2", "n3", "n4"]) {
    if (!(await node(id).getAttribute("class")).includes("st-ok")) fail(`workflow: node ${id} did not finish ok`);
  }
  await node("n4").focus();
  const written = page.locator(".wf-result a");
  await written.waitFor({ timeout: 5000 });
  const text = await (await request.get(base + (await written.getAttribute("href")))).text();
  if (!text.includes("SPIKE")) fail("workflow: the saved file does not hold the specialist's answer: " + text);
  if (!(await page.locator(".wf-log").getByText("medidos", { exact: false }).count())) fail("workflow: no measured time in the log");
  await page.screenshot({ path: `${out}/22c-workflow-run.png`, fullPage: true });

  // run again and stop while the write waits for a decision: the run ends as stopped and nothing is written twice
  await page.getByRole("button", { name: "Ejecutar", exact: true }).click();
  await page.getByRole("button", { name: "Permitir una vez" }).waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: "Detener", exact: true }).click();
  await page.locator(".wf-history .wf-chip", { hasText: "detenido" }).waitFor({ timeout: 20000 });
  if ((await page.locator(".wf-history li").count()) !== 2) fail("workflow: both runs should be in the history");
  await page.getByRole("button", { name: "Ejecutar", exact: true }).waitFor({ timeout: 5000 });

  await page.getByRole("button", { name: "Volver a Crear" }).click();
  await page.locator(".template-card").first().waitFor({ timeout: 5000 });

  // a phone: the saved workflow opens from the list, the canvas scrolls inside its frame and the page does not
  const phone = await page.context().browser().newContext({ viewport: { width: 390, height: 844 }, locale: "es-ES", isMobile: true, hasTouch: true });
  const mp = await phone.newPage();
  await mp.goto(base);
  await mp.getByText("¿En qué te ayudo hoy?").waitFor({ timeout: 15000 });
  if (await mp.getByRole("button", { name: /Abrir barra lateral|Open sidebar/ }).count()) await mp.getByRole("button", { name: /Abrir barra lateral|Open sidebar/ }).click();
  await mp.getByRole("button", { name: "Crear", exact: true }).click();
  await mp.getByRole("button", { name: "Flujos de trabajo", exact: true }).click();
  await mp.getByLabel("Flujos guardados").selectOption({ label: "Saludo con SPIKE · v1" });
  await mp.locator('[data-node="n4"]').waitFor({ timeout: 5000 });
  if ((await mp.locator("[data-node]").count()) !== 4) fail("workflow: the saved workflow did not open with its 4 nodes");
  if ((await mp.locator(".wf-history li").count()) !== 2) fail("workflow: the stored runs did not come back");
  if (await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) fail("workflow: the builder overflows a phone screen");
  await mp.screenshot({ path: `${out}/22d-workflow-mobile.png` });
  await phone.close();
  await page.getByRole("button", { name: "Nuevo chat" }).click(); // leave Create as the other flows expect
}
