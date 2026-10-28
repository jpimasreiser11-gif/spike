import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { Project } from "../types";
import "./HistorySearch.css";

export type HistoryHit = {
  id: number; conversation_id: string; message_id: string | null; title: string;
  project_id: string | null; project_name: string | null; role: "title" | "user" | "assistant";
  created: number; segments: { text: string; matched: boolean }[];
};
type SearchPage = { results: HistoryHit[]; has_more: boolean; next_offset: number | null };
const H = t.history;

/** Explicit local searches only. The native modal contains focus; request generations discard stale responses. */
export function HistorySearch({ projects, projectId, onClose, onSelect }: {
  projects: Project[]; projectId?: string; onClose: () => void; onSelect: (hit: HistoryHit) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState(projectId ? `project:${projectId}` : "workspace");
  const [match, setMatch] = useState("words");
  const [role, setRole] = useState("all");
  const [days, setDays] = useState("0");
  const [page, setPage] = useState<SearchPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const after = useRef(0);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const el = dialog.current!;
    el.showModal(); input.current?.focus();
    return () => { generation.current++; el.close(); if (previous?.isConnected) previous.focus(); };
  }, []);

  function reset() { generation.current++; setPage(null); setError(""); setBusy(false); }
  async function search(offset = 0) {
    if (!query.trim() || opening) return;
    const current = ++generation.current;
    setBusy(true); setError("");
    if (!offset) { setPage(null); after.current = days === "0" ? 0 : Date.now() / 1000 - Number(days) * 86400; }
    try {
      const found = await api.post<SearchPage>("/api/history/search", { query, match, role, after: after.current, offset,
        scope: scope.startsWith("project:") ? "project" : scope,
        project_id: scope.startsWith("project:") ? scope.slice(8) : null });
      if (generation.current === current) setPage((prev) => ({ ...found, results: offset ? [...(prev?.results ?? []), ...found.results] : found.results }));
    } catch { if (generation.current === current) setError(H.error); }
    finally { if (generation.current === current) setBusy(false); }
  }
  async function select(hit: HistoryHit) {
    setOpening(true); setError("");
    try { await onSelect(hit); } catch { setError(H.openError); setOpening(false); }
  }
  return (
    <dialog className="history-dialog" ref={dialog} aria-labelledby="history-heading" aria-describedby="history-note"
      onCancel={(e) => { e.preventDefault(); if (!opening) onClose(); }}>
      <header className="history-header"><h2 id="history-heading">{H.title}</h2>
        <button className="btn" onClick={onClose} disabled={opening}>{H.close}</button></header>
      <p id="history-note" className="history-note">{H.note}</p>
      <form onSubmit={(e) => { e.preventDefault(); search(); }}>
        <label htmlFor="history-query">{H.query}</label>
        <div className="history-query"><input ref={input} id="history-query" type="search" value={query} maxLength={200}
          placeholder={H.placeholder} disabled={opening} onChange={(e) => { reset(); setQuery(e.target.value); }} />
          <button type="submit" className="btn primary" disabled={busy || opening || !query.trim()}>{H.search}</button></div>
        <div className="history-filters">
          <label>{H.scope}<select name="scope" value={scope} disabled={opening} onChange={(e) => { reset(); setScope(e.target.value); }}>
            <option value="workspace">{H.workspace}</option><option value="all">{H.everywhere}</option>
            {projects.map((p) => <option key={p.id} value={`project:${p.id}`}>{p.name}</option>)}
          </select></label>
          <label>{H.match}<select name="match" value={match} disabled={opening} onChange={(e) => { reset(); setMatch(e.target.value); }}>
            <option value="words">{H.words}</option><option value="phrase">{H.phrase}</option>
          </select></label>
          <label>{H.sender}<select name="role" value={role} disabled={opening} onChange={(e) => { reset(); setRole(e.target.value); }}>
            <option value="all">{H.allContent}</option><option value="user">{H.user}</option><option value="assistant">SPIKE</option>
          </select></label>
          <label>{H.date}<select name="days" value={days} disabled={opening} onChange={(e) => { reset(); setDays(e.target.value); }}>
            <option value="0">{H.anyDate}</option><option value="7">{H.days7}</option><option value="30">{H.days30}</option><option value="90">{H.days90}</option>
          </select></label>
        </div>
      </form>
      <p className="history-status" role="status" aria-live="polite">{busy ? H.searching : page ?
        (page.results.length ? `${page.results.length} ${page.results.length === 1 ? H.result : H.results}${page.has_more ? ` · ${H.moreAvailable}` : ""}` : H.empty) : H.ready}</p>
      {error && <p className="notice error" role="alert">{error}</p>}
      <ul className="history-results" aria-label={H.results} aria-busy={busy}>
        {page?.results.map((hit) => <li key={hit.id}><button className="history-hit" disabled={opening || busy} onClick={() => select(hit)}>
          <span className="history-hit-title">{hit.title}</span>
          <span className="history-hit-meta">{hit.project_name ?? H.workspace} · {hit.role === "title" ? H.chatTitle : hit.role === "user" ? H.user : "SPIKE"} · {new Date(hit.created * 1000).toLocaleDateString()}</span>
          <span className="history-excerpt">{hit.segments.map((s, i) => s.matched ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>)}</span>
        </button></li>)}
      </ul>
      {page?.has_more && <button className="btn history-more" disabled={busy || opening} onClick={() => search(page.next_offset!)}>{H.more}</button>}
    </dialog>
  );
}
