// Offline generated-report smoke. No app server, provider, network or model is involved.
// Generate the HTML with scripts/release/readiness.py, then pass its path and an optional screenshot path.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { chromium } from 'playwright-core';

const file = process.argv[2];
if (!file) throw new Error('Pass a generated release report HTML path');
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/*', route => { requests.push(route.request().url()); return route.abort(); });
  await page.setContent(fs.readFileSync(file, 'utf8'));
  await page.getByRole('heading', { name: 'Preparación del lanzamiento', exact: true }).waitFor();
  const total = await page.locator('tbody tr').count();
  assert.ok(total >= 60, 'the complete source catalog must be shown');
  assert.equal(await page.getByRole('status').textContent(), `${total} / ${total} funciones`);
  await page.getByLabel('Buscar función, módulo o responsable').fill('Forge');
  const filtered = await page.locator('tbody tr:visible').count();
  assert.ok(filtered > 0 && filtered < total);
  await page.getByLabel('Buscar función, módulo o responsable').fill('<img src=x onerror=alert(1)>');
  assert.equal(await page.locator('tbody tr:visible').count(), 0);
  assert.equal(await page.locator('img').count(), 0);
  await page.getByLabel('Buscar función, módulo o responsable').fill('');
  await page.getByLabel('Mostrar').selectOption('true');
  assert.equal(await page.locator('tbody tr:visible').count(), 0, 'initial evidence is intentionally empty');
  await page.getByLabel('Mostrar').selectOption('all');
  if (process.argv[3]) await page.screenshot({ path: process.argv[3] });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.locator('.scroll').evaluate(el => el.scrollWidth > el.clientWidth));
  await page.getByLabel('Buscar función, módulo o responsable').focus();
  await page.keyboard.type('memoria');
  assert.ok(await page.locator('tbody tr:visible').count() > 0);
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, [], 'report must remain offline');
  console.log(`RELEASE REPORT E2E OK: ${total} rows, filters, keyboard, mobile scroll, no external requests`);
} finally {
  await browser.close();
}
