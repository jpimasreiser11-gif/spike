import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";

type Preview = { token: string; parent: string; files: { path: string; diff: string; conflict: boolean; deleted: boolean; before: string | null; after: string | null; before_size: number; after_size: number }[] };

/** The approval button applies exactly the preview receipt. Any subsequent edit requires a fresh comparison. */
export function ProjectBranches({ projectId }: { projectId: string }) {
  const [name, setName] = useState("");
  const [branch, setBranch] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setPreview(null); setMessage(""); setError("");
    api.get<{ id: string }[]>("/api/project-branches").then((rows) => setBranch(rows.some((r) => r.id === projectId))).catch((e) => setError(e.message));
  }, [projectId]);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); setPreview(null); }
    finally { setBusy(false); }
  };
  return <details className="project-branches"><summary>{t.projectBranches}</summary>
    <div className="row"><input aria-label={t.branchName} placeholder={t.branchName} value={name} onChange={(e) => setName(e.target.value)} />
      <button className="btn" disabled={busy || !name.trim()} onClick={() => action(async () => {
        await api.post(`/api/projects/${projectId}/fork`, { name: name.trim() });
        setMessage(t.branchCreated); window.dispatchEvent(new Event("spike-projects-changed"));
      })}>{t.forkProject}</button>
      {branch && <button className="btn" disabled={busy} onClick={() => action(async () => setPreview(await api.get(`/api/projects/${projectId}/compare`)))}>{t.compareBranch}</button>}
    </div>
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
    {preview && <section aria-label={t.mergePreview}>
      <p>{t.mergeHint}</p>
      {preview.files.map((f) => <article key={f.path}><b>{f.path}</b> {f.conflict && <strong>{t.mergeConflict}</strong>}
        <p>{f.deleted ? t.deletedFile : `${f.before_size} → ${f.after_size} B`}</p>
        <pre>{f.diff || `${f.before ?? "∅"} → ${f.after ?? "∅"}`}</pre></article>)}
      <button className="btn primary" disabled={busy || preview.files.length === 0} onClick={() => action(async () => {
        await api.post(`/api/projects/${projectId}/merge`, { token: preview.token, approved: true });
        setPreview(null); setMessage(t.mergeDone);
      })}>{t.approveMerge}</button>
    </section>}
  </details>;
}
