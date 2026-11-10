import { useContext } from "react";
import { t } from "../i18n";
import type { DeviceLabProfile, DeviceLabUi } from "../types";
import { ArtifactContext, type ArtifactDoc } from "./Artifact";

const D = t.deviceLab;
const esc = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
export const PNG_URL = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;
const STYLE = "<style>:root{color-scheme:light dark}body{font-family:system-ui;padding:20px;line-height:1.5}table{border-collapse:collapse;width:100%}" +
  "th,td{text-align:left;padding:8px;border-bottom:1px solid #8884;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}" +
  "img{max-width:100%;height:auto;border:1px solid #8884}li{margin:6px 0}code{overflow-wrap:anywhere}.pass{color:#1a7f37}.fail{color:#b00020}.error{color:#9a6700}</style>";

export const profileName = (p: Pick<DeviceLabProfile, "id" | "name" | "builtin">) => (p.builtin && D.names[p.id]) || p.name;

/** The reasons of a profile's verdict in the user's language, one line each. */
export function reasonLines(p: DeviceLabProfile): string[] {
  const counts: Record<string, number> = { overflow: p.overflow.px, tap_targets: p.tap_targets.total, small_text: p.small_text.total,
    console_errors: p.console_errors.total, failed_requests: p.failed_requests.total };
  const lines = p.reasons.map(code => (D.reasons[code] ?? code).replace("{n}", String(counts[code] ?? "")) + (code === "navigation" && p.reason ? `: ${p.reason}` : ""));
  return lines.length ? lines : p.status === "pass" ? [D.reasons.clean] : [p.reason];
}

export const summaryText = (ui: DeviceLabUi) => D.summary.replace("{pass}", String(ui.summary.pass)).replace("{total}", String(ui.summary.profiles));

const ITEM: Record<string, (i: Record<string, unknown>) => string> = {
  overflow: i => `${i.selector} — ${i.kind === "content" ? "text" : "box"}, right edge ${i.right} px, width ${i.width} px`,
  tap_targets: i => `${i.selector} — ${i.width} × ${i.height} px${i.label ? ` “${i.label}”` : ""}`,
  small_text: i => `${i.selector} — ${i.font_size} px “${i.text}”`,
  console_errors: i => `${i.kind}: ${i.text}${i.source ? ` (${i.source})` : ""}`,
  failed_requests: i => `${i.status ?? i.failure} ${i.method} ${i.url}`,
  blocked_requests: i => String(i.url),
};
const SECTIONS = ["overflow", "tap_targets", "small_text", "console_errors", "failed_requests", "blocked_requests"] as const;

/** The readable report for the artifacts panel. Everything the page or the tool produced is escaped as text, and a
 * screenshot is used only when it is a PNG data URL, because the panel's page may load nothing else. */
export function deviceLabDocument(ui: DeviceLabUi): ArtifactDoc {
  const rows = ui.profiles.map(p => `<tr><td>${esc(profileName(p))}</td><td>${p.viewport.width} × ${p.viewport.height} @${p.scale}×${p.touch ? ` · ${esc(D.touch.toLowerCase())}` : ""}</td>` +
    `<td class="${esc(p.status)}">${esc(D.statuses[p.status] ?? p.status)}</td><td>${esc(reasonLines(p).join("; "))}</td></tr>`).join("");
  const detail = (p: DeviceLabProfile) => {
    const facts = [`${p.viewport.width} × ${p.viewport.height}`, `@${p.scale}×`, p.touch ? D.touch.toLowerCase() : "", p.mobile ? "mobile" : "", p.http_status ? `HTTP ${p.http_status}` : "",
      p.layout ? `${D.viewportWidth} ${p.layout.viewport_width} px · ${D.documentWidth} ${p.layout.document_width} px` : "", `${p.seconds} ${D.seconds}`].filter(Boolean).join(" · ");
    const sections = SECTIONS.filter(k => p[k].total).map(k => `<h3>${esc(D.sections[k])} (${p[k].total})</h3><ul>` +
      p[k].items.map(i => `<li><code>${esc(ITEM[k](i))}</code></li>`).join("") + (p[k].total > p[k].items.length ? `<li>…</li>` : "") + "</ul>").join("");
    return `<section><h2>${esc(profileName(p))} <span class="${esc(p.status)}">${esc(D.statuses[p.status] ?? p.status)}</span></h2><p>${esc(facts)}</p>` +
      `<p>${esc(reasonLines(p).join("; "))}</p>${p.notes.map(n => `<p>${esc(D.notes[n] ?? n)}</p>`).join("")}` +
      (PNG_URL.test(p.screenshot) ? `<img alt="${esc(D.screenshot)}: ${esc(profileName(p))}" src="${p.screenshot}">` : "") + sections + "</section>";
  };
  const phone = ui.android && ui.android.status === "ok" && PNG_URL.test(ui.android.screenshot)
    ? `<section><h2>${esc(D.androidTitle)}</h2><p>${esc(ui.android.model || ui.android.serial)} · ${esc(D.androidNote)}</p><img alt="${esc(D.androidImage)}" src="${ui.android.screenshot}"></section>`
    : ui.android ? `<section><h2>${esc(D.androidTitle)}</h2><p>${esc(D.androidStatuses[ui.android.status] ?? ui.android.status)}</p></section>` : "";
  const bare = { ...ui, profiles: ui.profiles.map(p => ({ ...p, screenshot: p.screenshot ? "(png)" : "" })), android: ui.android && { ...ui.android, screenshot: ui.android.screenshot ? "(png)" : "" } };
  return { title: D.report, filename: "device-lab-report.html",
    html: `${STYLE}<h1>${esc(D.report)}</h1><p><code>${esc(ui.url)}</code> · ${esc(ui.browser)} · ${esc(ui.started)}</p><p><b>${esc(summaryText(ui))}</b></p>` +
      `<p>${esc(D.emulated)}</p><p>${esc(D.limits)}</p><table><thead><tr><th>${esc(D.profile)}</th><th>${esc(D.screen)}</th><th>${esc(D.verdict)}</th><th>${esc(D.reason)}</th></tr></thead><tbody>${rows}</tbody></table>` +
      ui.profiles.map(detail).join("") + phone + `<h2>${esc(D.json)}</h2><pre>${esc(JSON.stringify(bare, null, 2))}</pre>` };
}

/** The tool's result in the chat: the verdict per profile and a button that opens the whole report. */
export function DeviceLabCard({ ui }: { ui: DeviceLabUi }) {
  const open = useContext(ArtifactContext);
  return <section className="data-card" aria-label={D.report}>
    <b>{D.title}</b> <code>{ui.url}</code>
    <p>{summaryText(ui)}</p>
    {ui.profiles.map(p => <p key={p.id} data-status={p.status}>{profileName(p)}: {D.statuses[p.status] ?? p.status}{p.status !== "pass" && ` — ${reasonLines(p).join("; ")}`}</p>)}
    <button type="button" className="btn small" disabled={!open} onClick={() => open?.(deviceLabDocument(ui))}>{D.view}</button>
  </section>;
}
