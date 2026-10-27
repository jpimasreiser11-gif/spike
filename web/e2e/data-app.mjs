// Real workbook -> Creator -> sandboxed editor -> review -> approved write. No model or network provider.
import fs from "node:fs";

export async function dataAppFlow(page, request, base) {
  const fixture = fs.readFileSync(new URL("../../tests/fixtures/stock.xlsx", import.meta.url));
  const file = "a12-stock.xlsx";
  await page.getByRole("button", { name: "Nuevo proyecto", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Nuevo proyecto" });
  await dialog.getByLabel("Nombre", { exact: true }).fill("A12 Stock");
  await dialog.getByRole("button", { name: "Crear", exact: true }).click();
  await page.getByTestId("project-upload").setInputFiles({ name: file, mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: fixture });
  await page.locator(".file-list a", { hasText: file }).waitFor();
  const projects = await (await request.get(`${base}/api/projects`)).json();
  const project = projects.find(p => p.name === "A12 Stock");
  const sourceUrl = `${base}/api/projects/${project.id}/files/${file}`;
  await page.getByRole("button", { name: "Crear", exact: true }).click();
  await page.locator(".template-card", { hasText: "De datos a aplicación" }).click();
  await page.getByLabel("Archivo de datos").fill(file);
  await page.getByLabel("¿Para qué es la aplicación?").fill("Consultar y editar stock");
  await page.getByRole("button", { name: "Crear app local (escribe app.html)", exact: true }).click();
  const editor = page.frameLocator(".artifact-frame");
  await editor.getByLabel("Buscar", { exact: true }).fill("ausente");
  if (await editor.locator("tbody tr").count()) throw new Error("A12 search did not filter");
  await editor.getByLabel("Buscar", { exact: true }).fill("café");
  await editor.getByLabel("Stock 1", { exact: true }).fill("12");
  await editor.getByRole("button", { name: "Proponer cambios" }).click();
  const panel = page.locator(".artifact-panel");
  await panel.getByText("Fila 1, Columna 2: 5 → 12", { exact: true }).waitFor();
  const before = await (await request.get(sourceUrl)).body();
  if (!before.equals(fixture)) throw new Error("A12 source changed before approval");
  await panel.getByRole("button", { name: "Aprobar escritura", exact: true }).click();
  await panel.getByText("Archivo original actualizado.", { exact: false }).waitFor();
  const after = await (await request.get(sourceUrl)).body();
  if (after.equals(fixture)) throw new Error("A12 approved write did not update source");
  await panel.getByRole("button", { name: "Cerrar", exact: true }).click();
  // Regenerate from disk: this proves the approved workbook actually contains the new cell.
  await page.getByRole("button", { name: "Crear app local (escribe app.html)", exact: true }).click();
  await editor.getByLabel("Stock 1", { exact: true }).waitFor();
  if (await editor.getByLabel("Stock 1", { exact: true }).inputValue() !== "12") throw new Error("A12 workbook roundtrip failed");
  await panel.getByRole("button", { name: "Cerrar", exact: true }).click();
  await page.locator(".creator").getByRole("button", { name: "Cerrar", exact: true }).click();
}
