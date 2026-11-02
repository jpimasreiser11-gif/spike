import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import "./SetupWizard.css";

type Status = {
  enabled: boolean; complete: boolean; can_download: boolean;
  disk_free: number; ram_total: number; ram_available: number; required_disk: number; required_ram: number;
  specialists: { id: string; name: string; available: boolean }[];
  job: { status: string; file: string; done: number; total: number };
};
const L = t.setup;
const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;

/** Only the launcher enables this wizard. Mount/status polling reads local state; a click authorizes transfers. */
export function SetupWizard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
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
  const quit = async () => {
    try { await api.post("/api/setup/quit"); } catch { setError(true); }
  };
  return <>
    <button className="btn launcher-quit" onClick={quit}>{L.quit}</button>
    {!dismissed && !status.complete && <div className="setup-backdrop">
      <section className="setup-wizard" role="dialog" aria-modal="true" aria-label={L.title}>
        <h1>{L.title}</h1><p>{L.intro}</p>
        <p>{L.disk}: {gb(status.disk_free)} · {L.required}: {gb(status.required_disk)}</p>
        <p>{L.ram}: {gb(status.ram_total)} · {L.available}: {gb(status.ram_available)} · {L.required}: {gb(status.required_ram)}</p>
        {!status.can_download && <p role="alert">{L.resources}</p>}
        <fieldset disabled={running}><legend>{L.specialists}</legend>
          {status.specialists.map((s) => <label className="setup-option" key={s.id}>
            <input type="checkbox" disabled={!s.available} checked={selected.includes(s.id)} onChange={(e) =>
              setSelected(e.target.checked ? [...selected, s.id] : selected.filter((id) => id !== s.id))} />
            {s.name}{!s.available && ` · ${L.unavailable}`}
          </label>)}
        </fieldset>
        {running && <p role="status">{L.downloading} {status.job.file} · {gb(status.job.done)} / {gb(status.job.total)}</p>}
        {(error || status.job.status === "failed") && <p role="alert">{L.failed}</p>}
        <div className="row"><button className="btn primary" disabled={running || !status.can_download} onClick={download}>{L.download}</button>
          <button className="btn" disabled={running} onClick={() => setDismissed(true)}>{L.later}</button></div>
      </section>
    </div>}
    {error && dismissed && <p role="alert">{L.failed}</p>}
  </>;
}
