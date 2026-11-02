import { lang, t } from "./i18n";
import type { ArchitectureUi, GeoUi } from "./types";
import type { ArtifactDoc } from "./components/Artifact";

/** Escapes text for HTML (the artifact pages below are strings, so every value goes through this). */
export const esc = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

export const num = (value: number | null | undefined, digits = 3) =>
  value === null || value === undefined ? "" : value.toLocaleString(lang, { maximumFractionDigits: digits });

/** `fill("{n} of {m}", { n: 3, m: 5 })`: the texts of i18n.ts keep their numbers in braces. */
export const fill = (text: string, values: Record<string, string | number>) => text.replace(/\{(\w+)\}/g, (all, key) => String(values[key] ?? all));

export const slug = (value: string) => value.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "spike";

/**
 * The drawing the server made, or null when it is not what the server makes. The server escapes every name it draws, so
 * this is a second wall, not the first: no script, foreign content, event handler, link or reference outside the picture.
 */
export function safeSvg(svg: unknown): string | null {
  if (typeof svg !== "string" || svg.length > 8_000_000 || !/^<svg[\s>]/.test(svg) || !svg.trimEnd().endsWith("</svg>")) return null;
  if (/<\s*(script|foreignObject|iframe|object|embed|link|image|use|a|style[^>]*\ssrc)\b|<[^<>]*\son[a-z]+\s*=|javascript:|data:text|@import|url\(\s*['"]?\s*(https?:|\/\/)/i.test(svg)) return null;
  return svg;
}

/** An image of the drawing for the chat: an SVG shown as an image can run no script and load nothing. */
export const svgImage = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

const PAGE_STYLE = "body{font-family:system-ui,sans-serif;margin:0;padding:16px;color:#1b1f23;background:#fff}" +
  "@media(prefers-color-scheme:dark){body{background:#14181d;color:#e8ebee}}svg{max-width:100%;height:auto}h1{font-size:18px}h2{font-size:15px}" +
  "table{border-collapse:collapse;font-size:13px;margin:8px 0}th,td{border:1px solid #8b95a366;padding:4px 8px;text-align:left;vertical-align:top}" +
  "td.num{text-align:right}p{font-size:13px;max-width:70ch}code{font-size:12px}";

const table = (head: string[], rows: string[][]) =>
  `<table><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.join("")}</tr>`).join("")}</tbody></table>`;
const cell = (value: string, numeric = false) => `<td${numeric ? ' class="num"' : ""}>${esc(value)}</td>`;

export const geoCaption = (ui: GeoUi) => {
  const e = t.explorer;
  return `${num(ui.stats.features, 0)} ${e.features} · ${num(ui.stats.points, 0)} ${e.points} · ${num(ui.stats.lines, 0)} ${e.lines} · ${num(ui.stats.polygons, 0)} ${e.polygons}`;
};
export const geoAccuracy = (ui: GeoUi) => fill(t.explorer.accuracy, { r: num(ui.radius_km, 4) });

/** What was left out of the map or of the table, in the user's language (the card and the page in the panel say the same). */
export function geoNotes(ui: GeoUi): string[] {
  const e = t.explorer;
  const cut = Object.entries(ui.truncated ?? {}).filter(([key]) => e.cut[key]).map(([key, n]) => fill(e.cut[key], { n: num(n, 0) }));
  return [...ui.skipped.slice(0, 5).map((s) => `${e.notRead}: ${s}`), ...cut];
}

/** The map and the measures of each feature as an isolated page for the artifacts panel; null when the drawing is not safe. */
export function geoDocument(ui: GeoUi): ArtifactDoc | null {
  const svg = safeSvg(ui.svg);
  if (!svg) return null;
  const e = t.explorer;
  const title = ui.title || e.map;
  const head = [e.name, e.pointsCol, e.length, e.perimeter, e.area, ...(ui.value ? [`${e.value}: ${ui.value}`] : [])];
  const rows = ui.rows.map(r => [cell(r.name), cell(num(r.points, 0), true), cell(num(r.length_km), true), cell(num(r.perimeter_km), true),
    cell(num(r.area_km2), true), ...(ui.value ? [cell(num(r.value), true)] : [])]);
  const notes = [...(ui.rows_truncated ? [e.firstRows] : []), ...geoNotes(ui)];
  const body = `<h1>${esc(title)}</h1><p>${esc(ui.source)} · ${esc(geoCaption(ui))}</p>${svg}<p>${esc(geoAccuracy(ui))}</p>` +
    `<h2>${esc(e.table)}</h2>${table(head, rows)}${notes.map(n => `<p>${esc(n)}</p>`).join("")}`;
  return { title, filename: `${slug(title)}.html`, html: `<style>${PAGE_STYLE}</style>${body}` };
}

export const graphCaption = (ui: ArchitectureUi) => {
  const e = t.explorer, s = ui.stats;
  return `${num(s.modules, 0)} ${e.modules} (Python ${num(s.python, 0)}, JS/TS ${num(s.javascript, 0)}) · ${num(s.edges, 0)} ${e.imports}`;
};

/** What was left out of the reading or the picture, in the user's language. */
export function graphNotes(ui: ArchitectureUi): string[] {
  const e = t.explorer, s = ui.stats;
  const notes = [ui.lazy ? e.lazyOn : e.lazyOff];
  if (s.shown < s.modules) notes.push(fill(e.showing, { n: s.shown, m: s.modules }));
  if (s.external || s.unresolved) notes.push(fill(e.outside, { e: num(s.external, 0), u: num(s.unresolved, 0) }));
  for (const [key, value] of Object.entries(ui.truncated ?? {})) if (e.left[key]) notes.push(fill(e.left[key], { n: value }));
  if (ui.errors?.length) notes.push(`${e.errors}: ${ui.errors.slice(0, 5).join("; ")}`);
  return notes;
}

export const cycleRow = (c: ArchitectureUi["cycles"][number]) => `${c.path.join(" → ")}${c.more ? ` (+${c.more} ${t.explorer.more})` : ""}`;

/** The diagram and the table of cycles as an isolated page for the artifacts panel; null when the drawing is not safe. */
export function architectureDocument(ui: ArchitectureUi): ArtifactDoc | null {
  const svg = safeSvg(ui.svg);
  if (!svg) return null;
  const e = t.explorer;
  const title = ui.title || e.graph;
  const cycles = ui.cycles.length
    ? `<h2>${esc(e.cyclesTitle)}</h2><p>${esc(fill(e.cyclesLine, { n: ui.stats.cycles, k: ui.stats.in_cycles }))}</p>` +
      table(["#", e.size, e.path], ui.cycles.map((c, i) => [cell(String(i + 1), true), cell(String(c.size), true), `<td><code>${esc(cycleRow(c))}</code></td>`]))
    : `<h2>${esc(e.cyclesTitle)}</h2><p>${esc(e.noCycles)}</p>`;
  const body = `<h1>${esc(title)}</h1><p>${esc(graphCaption(ui))}</p>${svg}${cycles}${graphNotes(ui).map(n => `<p>${esc(n)}</p>`).join("")}`;
  return { title: `${e.graph}: ${title}`, filename: `${slug(title)}-architecture.html`, html: `<style>${PAGE_STYLE}</style>${body}` };
}
