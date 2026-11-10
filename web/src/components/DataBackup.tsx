import { useState } from "react";
import { api } from "../api";
import { lang, projectError, t } from "../i18n";

export interface BackupPreview {
  spike_version: string; created: number; include_models: boolean; total_bytes: number;
  add: number; replace: number; same: number; files: { path: string; size: number; action: "add" | "replace" | "same" }[];
}
interface RestoreResult { added: number; replaced: number; skipped: number; same: number }
interface DeleteResult { deleted: number; secrets_deleted: boolean; models_deleted: boolean }

const errorText = (e: unknown) => `${t.dataBackup.error} ${projectError(e instanceof Error ? e.message : String(e))}`;

/** Settings › Privacy: export everything (no secrets), restore with a preview, and delete all data (G34, G36). */
export function DataBackup() {
  const T = t.dataBackup;
  const [models, setModels] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [restored, setRestored] = useState<RestoreResult | null>(null);
  const [busy, setBusy] = useState<"" | "check" | "restore" | "delete">("");
  const [error, setError] = useState("");
  const [step, setStep] = useState<0 | 1 | 2>(0);  // delete: 0 idle, 1 first confirmation, 2 typing the word
  const [delModels, setDelModels] = useState(false);
  const [delSecrets, setDelSecrets] = useState(false);
  const [word, setWord] = useState("");
  const [typed, setTyped] = useState("");
  const [deleted, setDeleted] = useState<DeleteResult | null>(null);

  const pick = async (f: File | undefined) => {
    setPreview(null); setRestored(null); setError(""); setOverwrite(false); setFile(f ?? null);
    if (!f) return;
    setBusy("check");
    try { setPreview(await api.upload<BackupPreview>("POST", "/api/backup/preview", f)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };
  const restore = async () => {
    if (!file) return;
    setBusy("restore"); setError("");
    try {
      setRestored(await api.upload<RestoreResult>("POST", `/api/backup/restore?overwrite=${overwrite ? 1 : 0}`, file));
      setPreview(null);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };
  const askWord = async () => {
    setError(""); setTyped("");
    try { setWord((await api.get<{ word: string }>(`/api/privacy/delete-word?lang=${lang}`)).word); setStep(2); }
    catch (e) { setError(errorText(e)); }
  };
  const deleteAll = async () => {
    if (typed.trim() !== word) return;
    setBusy("delete"); setError("");
    try {
      setDeleted(await api.post<DeleteResult>("/api/privacy/delete",
        { word: typed.trim(), delete_models: delModels, delete_secrets: delSecrets }));
      setStep(0);
    } catch (e) { setError(errorText(e)); setStep(0); }
    finally { setBusy(""); setWord(""); setTyped(""); }
  };

  return (
    <div className="form" data-testid="data-backup">
      {error && <p className="small error" role="alert">{error}</p>}
      <div className="card">
        <div className="card-head"><b>{T.title}</b></div>
        <p className="small muted">{T.intro}</p>
        <label className="check small"><input type="checkbox" checked={models} onChange={(e) => setModels(e.target.checked)} />{T.includeModels}</label>
        <div className="row">
          <a className="btn small" href={`/api/backup/export?include_models=${models ? 1 : 0}`} download>{T.exportAll}</a>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><b>{T.restoreTitle}</b></div>
        <div className="row">
          <label className="btn small">
            {T.restorePick}
            <input type="file" accept=".zip,application/zip" hidden data-testid="backup-file"
              onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
        </div>
        {busy === "check" && <p className="small muted">{T.checking}</p>}
        {preview && (
          <div data-testid="backup-preview">
            <p className="small">
              {T.previewOf} {preview.spike_version}{preview.created ? ` · ${T.created} ${new Date(preview.created * 1000).toLocaleString()}` : ""}
              {" · "}{preview.files.length} {T.files}
            </p>
            <p className="small"><b>{preview.add}</b> {T.add} · <b>{preview.replace}</b> {T.replace} · <b>{preview.same}</b> {T.same}</p>
            <ul className="small muted">
              {preview.files.filter((f) => f.action !== "same").slice(0, 50).map((f) => (
                <li key={f.path}><code>{f.path}</code> — {f.action === "add" ? T.add : T.replace}</li>
              ))}
            </ul>
            {preview.replace > 0 && (
              <label className="check small">
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} data-testid="backup-overwrite" />
                {T.overwrite}
              </label>
            )}
            <small className="muted">{T.overwriteNote}</small>
            <div className="row">
              <button className="btn small" disabled={busy !== ""} onClick={() => void restore()}>{busy === "restore" ? T.restoring : T.restore}</button>
              <button className="btn small" onClick={() => { setPreview(null); setFile(null); }}>{T.cancel}</button>
            </div>
          </div>
        )}
        {restored && (
          <p className="small" data-testid="backup-restored">
            {T.restored} {restored.added} · {T.replaced} {restored.replaced} · {T.skipped} {restored.skipped}{" "}
            <button className="btn small" onClick={() => location.reload()}>{T.reload}</button>
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-head"><b>{T.deleteTitle}</b></div>
        <p className="small muted">{T.deleteIntro}</p>
        <label className="check small"><input type="checkbox" checked={delModels} onChange={(e) => setDelModels(e.target.checked)} data-testid="delete-models" />{T.deleteModels}</label>
        <label className="check small"><input type="checkbox" checked={delSecrets} onChange={(e) => setDelSecrets(e.target.checked)} data-testid="delete-secrets" />{T.deleteSecrets}</label>
        {step === 0 && (
          <div className="row"><button className="btn small danger" onClick={() => { setDeleted(null); setStep(1); }}>{T.deleteStart}</button></div>
        )}
        {step === 1 && (
          <div data-testid="delete-step1">
            <p className="small"><b>{T.deleteSure}</b></p>
            <div className="row">
              <button className="btn small danger" onClick={() => void askWord()}>{T.deleteContinue}</button>
              <button className="btn small" onClick={() => setStep(0)}>{T.cancel}</button>
            </div>
          </div>
        )}
        {step === 2 && (
          <div data-testid="delete-step2">
            <p className="small">{T.typeWord} <code data-testid="delete-word">{word}</code></p>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label={T.typeWord} data-testid="delete-input" autoComplete="off" />
            <div className="row">
              <button className="btn small danger" disabled={typed.trim() !== word || busy !== ""} onClick={() => void deleteAll()}>
                {busy === "delete" ? T.deleting : T.deleteNow}
              </button>
              <button className="btn small" onClick={() => { setStep(0); setWord(""); setTyped(""); }}>{T.cancel}</button>
            </div>
          </div>
        )}
        {deleted && (
          <p className="small" data-testid="delete-done">
            {T.deleted} {deleted.deleted}. {deleted.secrets_deleted ? "" : T.keptSecrets} {deleted.models_deleted ? "" : T.keptModels}{" "}
            <button className="btn small" onClick={() => location.reload()}>{T.reload}</button>
          </p>
        )}
      </div>
    </div>
  );
}
