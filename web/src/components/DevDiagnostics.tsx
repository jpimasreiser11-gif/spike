import { useContext } from "react";
import { t } from "../i18n";
import type { DiagnosticUi } from "../types";
import { ArtifactContext, type ArtifactDoc } from "./Artifact";

const esc = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
const title = (ui: DiagnosticUi) => t.diagnostics[ui.report];
const status = (value: string) => t.diagnostics.statuses[value] ?? value;

/** Inline-only artifact: all page selectors, package metadata and auditor output are escaped as text. */
export function diagnosticDocument(ui: DiagnosticUi): ArtifactDoc {
  const d = t.diagnostics;
  const png = ui.screenshot?.match(/^data:image\/png;base64,[A-Za-z0-9+/=]+$/) ? ui.screenshot : "";
  const body = ui.report === "visual"
    ? `<p>${esc(d.limits)}</p><p>${esc(ui.url)}</p>${png ? `<img style="max-width:100%" alt="${esc(d.screenshot)}" src="${png}">` : ""}` +
      `<h2>${esc(d.issues)}</h2><ul>${(ui.issues ?? []).map(i => `<li>${esc(d.checks[i.code] ?? i.code)} <code>${esc(i.selector)}</code><pre>${esc(JSON.stringify(i, null, 2))}</pre></li>`).join("")}</ul>`
    : `<p>${esc(d.metadata)}</p><h2>${esc(d.audits)}</h2>${(ui.audits ?? []).map(a => `<h3>${esc(a.tool)}: ${esc(status(a.status))}</h3><pre>${esc(JSON.stringify(a.result ?? {}, null, 2))}</pre>`).join("")}` +
      `<h2>${esc(d.licenses)}</h2><ul>${(ui.licenses ?? []).map(l => `<li>${esc(l.package)}: ${esc(l.license)} — ${esc(status(l.status))}</li>`).join("")}</ul>`;
  return { title: title(ui), filename: `${ui.report}-diagnostic.html`,
    html: `<style>body{font-family:system-ui;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}li{margin:12px 0}</style><h1>${esc(title(ui))}</h1>${body}` };
}

export function DiagnosticCard({ ui }: { ui: DiagnosticUi }) {
  const open = useContext(ArtifactContext);
  return <section className="data-card" aria-label={title(ui)}>
    <b>{title(ui)}</b>
    {(ui.audits ?? []).map(a => <p key={a.tool}>{a.tool}: {status(a.status)}</p>)}
    {ui.report === "visual" && <p>{t.diagnostics.issues}: {ui.issues?.length ?? 0}</p>}
    <button type="button" className="btn small" disabled={!open} onClick={() => open?.(diagnosticDocument(ui))}>{t.diagnostics.view}</button>
  </section>;
}
