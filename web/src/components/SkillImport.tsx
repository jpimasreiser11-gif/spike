import { useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import "./SkillImport.css";

interface FileRow { path: string; size: number; binary: boolean; text?: string; truncated?: boolean }
export interface ImportPreview {
  preview_id: string; sha256: string; name: string; description: string; skill_md: string; can_install: boolean;
  license: { id: string; status: "allowed" | "blocked" | "missing"; source: string; can_enable: boolean };
  issues: { rule: string; location: string }[]; files: FileRow[];
  source: { owner: string; repo: string; ref: string; path: string };
}

/** Settings › Skills: paste a GitHub URL, review the license and every file, then install the skill disabled (O3).
 * SKILL.md and the files are shown as plain text: nothing from the repository is rendered or executed. */
export function SkillImport({ onInstalled }: { onInstalled: () => void }) {
  const T = t.skillImport;
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState<"" | "review" | "install">("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const fail = (e: unknown) => { const m = e instanceof Error ? e.message : String(e); setError(T.errors[m] ?? m); };

  const review = async () => {
    setError(""); setDone(""); setPreview(null); setBusy("review");
    try { setPreview(await api.post<ImportPreview>("/api/skills/import-github/preview", { url })); }
    catch (e) { fail(e); }
    finally { setBusy(""); }
  };
  const install = async () => {
    if (!preview) return;
    setError(""); setBusy("install");
    try {
      await api.post("/api/skills/import-github/install", { preview_id: preview.preview_id, sha256: preview.sha256 });
      setDone(`${preview.name}: ${T.installed}`); setPreview(null); setUrl(""); onInstalled();
    } catch (e) { fail(e); }
    finally { setBusy(""); }
  };
  const lic = preview?.license;
  const licText = !lic ? "" : lic.status === "allowed" ? T.licenseOk : lic.status === "missing" ? T.licenseMissing : T.licenseBlocked;

  return (
    <section className="skill-import" data-testid="skill-import-github">
      <h3>{T.title}</h3>
      <p className="small muted">{T.intro}</p>
      <div className="skill-import-row">
        <input type="text" inputMode="url" autoComplete="off" spellCheck={false} aria-label={T.urlLabel} placeholder={T.urlHelp}
          value={url} onChange={(e) => setUrl(e.target.value)} data-testid="skill-import-url" />
        <button className="btn" disabled={!url.trim() || busy !== ""} onClick={review} data-testid="skill-import-review">{busy === "review" ? T.reviewing : T.review}</button>
      </div>
      {error && <div className="error-box" role="alert" data-testid="skill-import-error">{error}</div>}
      {done && <div className="flash-box" data-testid="skill-import-done">{done}</div>}
      {preview && lic && (
        <div data-testid="skill-import-preview">
          <p><code>{preview.name || "—"}</code> · {T.source}: <code>{preview.source.owner}/{preview.source.repo}@{preview.source.ref}{preview.source.path && `/${preview.source.path}`}</code></p>
          <p className="skill-import-license" data-status={lic.status} data-testid="skill-import-license">
            {T.license}: <b>{lic.id || "—"}</b> ({lic.source || "—"}) · {licText}
          </p>
          {preview.issues.length > 0 && (
            <div className="error-box" data-testid="skill-import-issues">{T.issues}:
              <ul>{preview.issues.map((i, n) => <li key={n}>{T.rules[i.rule] ?? i.rule} (<code>{i.location}</code>)</li>)}</ul>
            </div>
          )}
          <details open><summary>{T.skillMd}</summary><pre data-testid="skill-import-md">{preview.skill_md}</pre></details>
          <h3>{T.files} ({preview.files.length})</h3>
          <ul className="skill-import-files">
            {preview.files.map((f) => (
              <li key={f.path}>
                <details><summary><code>{f.path}</code> · {f.size} {T.bytes}{f.binary && ` · ${T.binary}`}{f.truncated && ` · ${T.truncated}`}</summary>
                  {!f.binary && f.text !== undefined && <pre>{f.text}</pre>}
                </details>
              </li>
            ))}
          </ul>
          <p className="small muted">{T.sha}: <code>{preview.sha256}</code></p>
          <div className="skill-import-row">
            <button className="btn primary" disabled={!preview.can_install || busy !== ""} onClick={install} data-testid="skill-import-install">
              {busy === "install" ? T.installing : T.install}
            </button>
            <button className="btn" onClick={() => setPreview(null)}>{T.cancel}</button>
          </div>
        </div>
      )}
    </section>
  );
}
