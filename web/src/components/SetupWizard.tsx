import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import "./SetupWizard.css";

type Status = {
  enabled: boolean; complete: boolean; can_download: boolean;
  low_disk?: boolean; low_ram?: boolean; has_local_model?: boolean; part_bytes?: number;
  disk_free: number; ram_total: number; ram_available: number; required_disk: number; required_ram: number;
  specialists: { id: string; name: string; available: boolean }[];
  job: { status: string; file: string; done: number; total: number; reason?: string; resumable?: boolean };
};
const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;

/** Only the launcher enables this wizard. Mount/status polling reads local state; a click authorizes transfers. */
export function SetupWizard({ onUseExternalApi }: { onUseExternalApi?: () => void } = {}) {
  const L = t.setup;
  const [status, setStatus] = useState<Status | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [importPath, setImportPath] = useState("");
  const [importSha, setImportSha] = useState("");
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.get<Status>("/api/setup");
        if (live) {
          setStatus(next);
          if (next.enabled) timer = setTimeout(poll, 1000);
        }
      } catch { if (live) setError(true); }
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, []);
  if (!status?.enabled) return null;
  const running = busy || status.job.status === "running";
  const download = async () => {
    setBusy(true); setError(false);
    try {
      await api.post("/api/setup/download", { specialists: selected });
      setStatus(await api.get<Status>("/api/setup"));
    } catch { setError(true); } finally { setBusy(false); }
  };
  const importLocal = async () => {
    if (!importPath.trim()) return;
    setBusy(true); setError(false);
    try {
      await api.post("/api/setup/import", {
        path: importPath.trim(),
        sha256: importSha.trim() ? importSha.trim() : null,
      });
      setStatus(await api.get<Status>("/api/setup"));
    } catch { setError(true); } finally { setBusy(false); }
  };
  const quit = async () => {
    try { await api.post("/api/setup/quit"); } catch { setError(true); }
  };
  const reason = status.job.reason || (status.low_disk ? "disk" : "");
  const isResumable = Boolean(status.job.resumable || reason === "interrupted" || (status.part_bytes && status.part_bytes > 0));
  const reasonText =
    reason === "offline" ? L.offline :
    reason === "interrupted" ? L.interrupted :
    reason === "checksum" ? L.checksum :
    reason === "disk" ? L.lowDisk : "";
  return <>
    <button className="btn launcher-quit" onClick={quit}>{L.quit}</button>
    {!dismissed && !status.complete && <div className="setup-backdrop">
      <section className="setup-wizard" role="dialog" aria-modal="true" aria-label={L.title}>
        <h1>{L.title}</h1><p>{L.intro}</p>
        <p role="status">{L.noModel}</p>
        <p>{L.disk}: {gb(status.disk_free)} · {L.required}: {gb(status.required_disk)}</p>
        <p>{L.ram}: {gb(status.ram_total)} · {L.available}: {gb(status.ram_available)} · {L.required}: {gb(status.required_ram)}</p>
        {!status.can_download && <p role="alert">{L.resources} {L.lowDisk}</p>}
        <fieldset disabled={running}><legend>{L.specialists}</legend>
          {status.specialists.map((s) => <label className="setup-option" key={s.id}>
            <input type="checkbox" disabled={!s.available} checked={selected.includes(s.id)} onChange={(e) =>
              setSelected(e.target.checked ? [...selected, s.id] : selected.filter((id) => id !== s.id))} />
            {s.name}{!s.available && ` · ${L.unavailable}`}
          </label>)}
        </fieldset>
        {running && <p role="status">{L.downloading} {status.job.file} · {gb(status.job.done)} / {gb(status.job.total)}</p>}
        {(error || status.job.status === "failed") && <p role="alert">{reasonText ? `${reasonText} (${L.failed})` : L.failed}</p>}
        <div className="row">
          <button className="btn primary" disabled={running || !status.can_download} onClick={download}>{L.download}</button>
          {(error || status.job.status === "failed" || isResumable) && (
            <button className="btn" disabled={running || !status.can_download} onClick={download}>
              {isResumable ? L.resume : L.retry}
            </button>
          )}
          <button className="btn" disabled={running} onClick={() => { setDismissed(true); onUseExternalApi?.(); }}>{L.useExternalApi}</button>
          <button className="btn" disabled={running} onClick={() => setShowImport((v) => !v)}>{L.importLocal}</button>
          <button className="btn" disabled={running} onClick={() => setDismissed(true)}>{L.later}</button>
        </div>
        {showImport && <div className="setup-import">
          <label>
            {L.importPathLabel}
            <input
              type="text"
              data-testid="setup-import-path"
              placeholder={L.importPathPlaceholder}
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
            />
          </label>
          <label>
            {L.importShaLabel}
            <input
              type="text"
              data-testid="setup-import-sha"
              placeholder={L.importShaPlaceholder}
              value={importSha}
              onChange={(e) => setImportSha(e.target.value)}
            />
          </label>
          <button className="btn primary" disabled={running || !importPath.trim()} onClick={importLocal}>{L.importConfirm}</button>
        </div>}
      </section>
    </div>}
    {error && dismissed && <p role="alert">{L.failed}</p>}
  </>;
}
