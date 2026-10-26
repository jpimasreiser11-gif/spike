import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { Specialist } from "../types";

type Job = { id: string; kind: string; status: string };
type Queue = { limit: number; ram_floor: number; jobs: Job[] };
type Note = { id: string; text: string; kind: string };

export function WorkspacePanel({ specialists, onClose }: { specialists: Specialist[]; onClose: () => void }) {
  const [queue, setQueue] = useState<Queue | null>(null);
  const [scope, setScope] = useState("code");
  const [notes, setNotes] = useState<Note[]>([]);
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState("fact");
  const [error, setError] = useState("");
  const load = () => api.get<Note[]>(`/api/memory?scope=specialist:${scope}`).then(setNotes).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [scope]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let live = true;
    const refresh = () => api.get<Queue>("/api/jobs").then((q) => { if (live) setQueue(q); }).catch((e) => { if (live) setError(e.message); });
    refresh(); const timer = setInterval(refresh, 1000);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => { live = false; clearInterval(timer); window.removeEventListener("keydown", key); };
  }, [onClose]);
  const save = async () => {
    try { await api.post("/api/memory", { scope: `specialist:${scope}`, kind, text: draft }); setDraft(""); load(); }
    catch (e) { setError((e as Error).message); }
  };
  const states: Record<string, string> = { queued: t.jobQueued, running: t.running, completed: t.jobCompleted, cancelling: t.jobCancelling, cancelled: t.stopped, failed: t.error };
  const kinds: Record<string, string> = { render: t.jobRender, eval: t.jobEval, indexing: t.jobIndexing, training: t.jobTraining };
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label={t.workspaceJobs}>
    <div className="modal-head"><h2>{t.workspaceJobs}</h2><button className="btn" onClick={onClose}>{t.close}</button></div>
    <div className="form padded">
      {error && <p role="alert">{error}</p>}
      <section aria-label={t.jobs}><h3>{t.jobs}</h3>
        {queue && <p>{t.jobLimits}: {queue.limit} · {t.ramFloor}: {(queue.ram_floor / 1024 ** 3).toFixed(1)} GiB</p>}
        {!queue?.jobs.length && <p>{t.noJobs}</p>}
        {queue?.jobs.map((j) => <div className="row" key={j.id}><span>{kinds[j.kind]} · {states[j.status]}</span>
          {["queued", "running"].includes(j.status) && <button className="btn" onClick={() => api.post(`/api/jobs/${j.id}/cancel`).catch((e) => setError(e.message))}>{t.cancel}</button>}</div>)}
      </section>
      <section aria-label={t.specialistKnowledge}><h3>{t.specialistKnowledge}</h3><p>{t.knowledgeHint}</p>
        <label className="field">{t.specialistSelect}<select value={scope} onChange={(e) => setScope(e.target.value)}>{specialists.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label className="field">{t.knowledgeKind}<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="fact">{t.knowledgeNote}</option><option value="document">{t.knowledgeDocument}</option><option value="rule">{t.knowledgeRule}</option></select></label>
        <label className="field">{t.knowledgeText}<textarea value={draft} onChange={(e) => setDraft(e.target.value)} /></label>
        <button className="btn primary" disabled={!draft.trim()} onClick={save}>{t.saveKnowledge}</button>
        <label className="field">{t.knowledgeUpload}<input type="file" accept=".txt,.md,.csv" onChange={async (e) => {
          const file = e.target.files?.[0]; if (!file) return;
          try { if (file.size > 2_000_000) throw new Error(t.knowledgeText);
            await api.post("/api/specialist-documents", { specialist: scope, filename: file.name, text: await file.text() }); load(); }
          catch (err) { setError((err as Error).message); }
          e.target.value = "";
        }} /></label>
        {notes.map((n) => <article key={n.id}><p>{n.text}</p><button className="btn" onClick={() => api.del(`/api/memory/${n.id}`).then(load).catch((e) => setError(e.message))}>{t.removeKnowledge}</button></article>)}
      </section>
    </div>
  </section></div>;
}
