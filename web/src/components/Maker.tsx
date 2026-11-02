import { useContext, useState } from "react";
import { t } from "../i18n";
import type { BlenderUi, GodotUi, MakerUi } from "../types";
import { ArtifactContext, type ArtifactDoc } from "./Artifact";

const esc = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
const PNG_URL = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;
const STYLE = "<style>body{font-family:system-ui;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}img{max-width:100%;height:auto;border:1px solid #8884}li{margin:10px 0}.bad{color:#b00020}.ok{color:#1a7f37}</style>";

/** Download URL of a file a tool wrote: in the project's folder, or in the workspace. */
const fileUrl = (path: string, projectId?: string) =>
  `${projectId ? `/api/projects/${projectId}/files` : "/api/workspace/files"}/${path.split("/").map(encodeURIComponent).join("/")}`;

const baseName = (path: string) => path.split("/").pop() || path;

/** The render's page for the artifacts panel. Everything the tool or the script printed is escaped as text, and the
 * picture is only used when it is a PNG data URL, because the panel's page may load nothing else. */
export function blenderDocument(ui: BlenderUi, png: string, script: string): ArtifactDoc {
  const m = t.maker;
  const stem = baseName(ui.script).replace(/\.py$/i, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "scene";
  const facts = [`${ui.width}×${ui.height}`, ui.engine, `${ui.samples} ${m.samples}`, `${ui.seconds} ${m.seconds}`, ui.version && `Blender ${ui.version}`].filter(Boolean).join(" · ");
  return { title: m.blender, filename: `${stem}-preview.html`,
    html: `${STYLE}<h1>${esc(m.blender)}</h1>${PNG_URL.test(png) ? `<img alt="${esc(m.preview)}" src="${png}">` : ""}<p>${esc(facts)}</p><p>${esc(m.blenderNote)}</p>` +
      `<h2>${esc(m.script)} <code>${esc(ui.script)}</code></h2><pre>${esc(script)}</pre>` +
      (ui.log ? `<h2>${esc(m.blenderLog)}</h2><pre>${esc(ui.log)}</pre>` : "") };
}

/** The check's page: the verdict, then every check with the errors Godot printed for it (escaped text). */
export function godotDocument(ui: GodotUi): ArtifactDoc {
  const m = t.maker;
  const items = ui.checks.map(c => `<li><b class="${c.ok ? "ok" : "bad"}">${c.ok ? "✓" : "✕"}</b> ${esc(m[`${c.kind}_check`])} <code>${esc(c.name)}</code>` +
    (c.problems.length ? `<pre>${esc(c.problems.join("\n"))}</pre>` : "") + "</li>").join("");
  const facts = [`${m.project}: ${ui.project}`, `Godot ${ui.version}`, `${ui.seconds} ${m.seconds}`, ui.not_checked ? `${ui.not_checked} ${m.notChecked}` : ""].filter(Boolean).join(" · ");
  return { title: m.godot, filename: "godot-check.html",
    html: `${STYLE}<h1>${esc(m.godot)}</h1><h2 class="${ui.passed ? "ok" : "bad"}">${esc(ui.passed ? m.passed : m.failed)}</h2><p>${esc(facts)}</p><p>${esc(m.godotNote)}</p>` +
      `<h2>${esc(m.checks)}</h2><ul>${items}</ul>` };
}

const dataUrl = (blob: Blob) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result));
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(blob);
});

async function fetched(url: string): Promise<Response> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(String(r.status));
  return r;
}

/** The preview as a small picture in the chat and a button that opens it, with its script, in the artifacts panel. */
export function BlenderCard({ ui, projectId }: { ui: BlenderUi; projectId?: string }) {
  const open = useContext(ArtifactContext);
  const [failed, setFailed] = useState(false);
  const view = async () => {
    setFailed(false);
    try {
      const image = new Blob([await (await fetched(fileUrl(ui.preview, projectId))).arrayBuffer()], { type: "image/png" });
      const script = await (await fetched(fileUrl(ui.script, projectId))).text();
      open?.(blenderDocument(ui, await dataUrl(image), script));
    } catch {
      setFailed(true);
    }
  };
  return <section className="data-card maker-card" aria-label={t.maker.blender}>
    <b>{t.maker.blender}</b>
    <img src={fileUrl(ui.preview, projectId)} alt={t.maker.preview} width={ui.width} height={ui.height} style={{ maxWidth: "100%", height: "auto" }} />
    <p className="small muted">{ui.width}×{ui.height} · {ui.engine} · {ui.samples} {t.maker.samples} · {ui.seconds} {t.maker.seconds}{ui.version && ` · Blender ${ui.version}`}</p>
    <button type="button" className="btn small" disabled={!open} onClick={view}>{t.maker.viewBlender}</button>
    {failed && <p className="small bad" role="alert">{t.maker.loadError}</p>}
  </section>;
}

/** The verdict of a Godot check, the checks that failed, and a button that opens the whole result in the panel. */
export function GodotCard({ ui }: { ui: GodotUi }) {
  const open = useContext(ArtifactContext);
  const bad = ui.checks.filter(c => !c.ok);
  return <section className="data-card maker-card" aria-label={t.maker.godot}>
    <b>{t.maker.godot}</b>
    <p className={ui.passed ? "ok-text" : "bad"}>{ui.passed ? "✓" : "✕"} {ui.passed ? t.maker.passed : t.maker.failed} <span className="muted small">· {ui.project} · Godot {ui.version}</span></p>
    {bad.map(c => <p key={`${c.kind}-${c.name}`} className="small"><code>{c.name}</code>: {c.problems[0]}</p>)}
    <button type="button" className="btn small" disabled={!open} onClick={() => open?.(godotDocument(ui))}>{t.maker.viewGodot}</button>
  </section>;
}

export function MakerCard({ ui, projectId }: { ui: MakerUi; projectId?: string }) {
  return ui.kind === "blender_render" ? <BlenderCard ui={ui} projectId={projectId} /> : <GodotCard ui={ui} />;
}
