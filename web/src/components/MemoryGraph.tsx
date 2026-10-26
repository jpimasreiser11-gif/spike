import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { GraphNode, GraphRelation, MemoryGraph as GraphData, Project } from "../types";
import { ArtifactContext } from "./Artifact";
import { IconTrash } from "./Icons";

const S = lang === "es"
  ? {
      intro: "Un mapa de lo que SPIKE sabe: personas, empresas, correos, fechas, cantidades y enlaces que aparecen en tus recuerdos y archivos, unidos por las notas que comparten. Se calcula en tu ordenador con patrones, sin modelo. Las relaciones que propone el modelo local solo cuentan cuando tú las confirmas.",
      scope: "Alcance", all: "Todo", global: "Global", find: "Buscar una entidad…", overview: "Vista general", focusOn: "Centrado en",
      stats: (g: GraphData["stats"]) => `${g.entities} entidades · ${g.relations} relaciones confirmadas · ${g.proposed} por revisar`,
      depth: "Distancia", notes: "Mostrar notas", proposals: "Mostrar propuestas", openPanel: "Abrir en el panel", opening: "Abriendo…",
      title: "Grafo de la memoria", empty: "Todavía no hay entidades: añade recuerdos o indexa carpetas.", alt: "Grafo de la memoria",
      neighbours: "En el grafo", entity: "Entidad", note: "Nota", askModel: "Proponer relaciones (modelo local)", asking: "Preguntando…",
      none: "El modelo no propuso relaciones nuevas para esta nota.", proposedHead: "Relaciones propuestas por revisar", confirmedHead: "Relaciones confirmadas",
      confirm: "Confirmar", reject: "Rechazar", remove: "Eliminar", relFrom: "Entidad", relLabel: "Relación", relTo: "Entidad", addRel: "Añadir relación",
      addHead: "Añadir una relación a mano", kinds: { name: "nombre", email: "correo", date: "fecha", quantity: "cantidad", link: "enlace" } as Record<string, string>,
    }
  : {
      intro: "A map of what SPIKE knows: people, companies, e-mails, dates, amounts and links that appear in your memories and files, joined by the notes they share. It is computed on your computer with patterns, no model. Relations the local model proposes only count once you confirm them.",
      scope: "Scope", all: "Everything", global: "Global", find: "Find an entity…", overview: "Overview", focusOn: "Focused on",
      stats: (g: GraphData["stats"]) => `${g.entities} entities · ${g.relations} confirmed relations · ${g.proposed} to review`,
      depth: "Distance", notes: "Show notes", proposals: "Show proposals", openPanel: "Open in the panel", opening: "Opening…",
      title: "Memory graph", empty: "There are no entities yet: add memories or index folders.", alt: "Memory graph",
      neighbours: "In the graph", entity: "Entity", note: "Note", askModel: "Propose relations (local model)", asking: "Asking…",
      none: "The model proposed no new relations for this note.", proposedHead: "Proposed relations to review", confirmedHead: "Confirmed relations",
      confirm: "Confirm", reject: "Reject", remove: "Delete", relFrom: "Entity", relLabel: "Relation", relTo: "Entity", addRel: "Add relation",
      addHead: "Add a relation by hand", kinds: { name: "name", email: "e-mail", date: "date", quantity: "amount", link: "link" } as Record<string, string>,
    };

export function MemoryGraph({ onClose }: { onClose: () => void }) {
  const openArtifact = useContext(ArtifactContext);
  const [projects, setProjects] = useState<Project[]>([]);
  const [scope, setScope] = useState("");
  const [q, setQ] = useState("");
  const [found, setFound] = useState<GraphNode[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [depth, setDepth] = useState(1);
  const [withNotes, setWithNotes] = useState(true);
  const [withProposals, setWithProposals] = useState(true);
  const [data, setData] = useState<GraphData | null>(null);
  const [relations, setRelations] = useState<GraphRelation[]>([]);
  const [rev, setRev] = useState(0);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [rel, setRel] = useState({ source: "", label: "", target: "" });

  const query = (extra: Record<string, string> = {}) => {
    const p = new URLSearchParams({ depth: String(depth), limit: "30", notes: String(withNotes), proposed: String(withProposals), ...extra });
    if (scope) p.set("scope", scope);
    if (focus) p.set("node", focus);
    return p;
  };
  const load = async () => {
    try {
      setData(await api.get<GraphData>(`/api/memory-graph?${query()}`));
      setRelations(await api.get<GraphRelation[]>(`/api/memory-graph/relations${scope ? `?scope=${encodeURIComponent(scope)}` : ""}`));
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
      if (focus) setFocus(null); // the focused node is gone (a note was deleted): back to the overview
    }
  };
  useEffect(() => { api.get<Project[]>("/api/projects").then(setProjects).catch(() => {}); }, []);
  useEffect(() => { load(); }, [scope, focus, depth, withNotes, withProposals, rev]);
  useEffect(() => {
    if (!q.trim()) { setFound([]); return; }
    const id = setTimeout(() => {
      const p = new URLSearchParams({ q: q.trim(), limit: "12" });
      if (scope) p.set("scope", scope);
      api.get<GraphNode[]>(`/api/memory-graph/entities?${p}`)
        .then(setFound)
        .catch(() => setFound([]));
    }, 250);
    return () => clearTimeout(id);
  }, [q, scope]);

  const act = async (fn: () => Promise<unknown>) => {
    setErr(""); setMsg("");
    try { await fn(); } catch (e) { setErr((e as Error).message); }
    setRev((n) => n + 1);
  };
  const svgUrl = `/api/memory-graph/svg?${query({ lang })}&v=${rev}`;
  const openInPanel = async () => {
    setBusy("open"); setErr("");
    try {
      const res = await fetch(svgUrl);
      if (!res.ok) throw new Error(res.statusText);
      const label = data?.nodes.find((n) => n.id === focus)?.label;
      openArtifact?.({ title: label ? `${S.title}: ${label}` : S.title, html: await res.text(), filename: "memory-graph.svg" });
      onClose(); // the settings dialog would cover the panel
    } catch (e) { setErr((e as Error).message); }
    setBusy("");
  };
  const propose = (memoryId: string) => act(async () => {
    setBusy(memoryId);
    try {
      const r = await api.post<{ proposed: GraphRelation[] }>("/api/memory-graph/propose", { memory_id: memoryId });
      setMsg(r.proposed.length ? "" : S.none);
    } finally { setBusy(""); }
  });
  const proposed = relations.filter((r) => r.status === "proposed");
  const confirmed = relations.filter((r) => r.status === "confirmed");
  const focusLabel = data?.nodes.find((n) => n.id === focus)?.label;
  const empty = data !== null && data.nodes.length === 0;

  return (
    <div className="form" data-testid="memory-graph">
      <p className="small muted">{S.intro}</p>
      <div className="row end">
        <label className="field inline"><span>{S.scope}</span>
          <select aria-label={S.scope} value={scope} onChange={(e) => { setScope(e.target.value); setFocus(null); }}>
            <option value="">{S.all}</option>
            <option value="global">{S.global}</option>
            {projects.map((p) => <option key={p.id} value={`project:${p.id}`}>{p.name}</option>)}
          </select>
        </label>
        <input type="search" className="grow" aria-label={S.find} placeholder={S.find} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {found.length > 0 && (
        <div className="row graph-found">
          {found.map((n) => (
            <button key={n.id} className="chip" onClick={() => { setFocus(n.id); setQ(""); }} title={S.kinds[n.kind] ?? n.kind}>{n.label} · {n.weight}</button>
          ))}
        </div>
      )}
      {data && <div className="small" data-testid="graph-stats">{S.stats(data.stats)}{focusLabel ? ` · ${S.focusOn}: ` : ""}{focusLabel && <b>{focusLabel}</b>}</div>}
      <div className="row end">
        <label className="field inline"><span>{S.depth}</span>
          <select aria-label={S.depth} value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
            {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={withNotes} onChange={(e) => setWithNotes(e.target.checked)} />{S.notes}</label>
        <label className="check"><input type="checkbox" checked={withProposals} onChange={(e) => setWithProposals(e.target.checked)} />{S.proposals}</label>
        <div className="spacer" />
        {focus && <button className="btn" onClick={() => setFocus(null)}>{S.overview}</button>}
        <button className="btn primary" disabled={empty || busy === "open"} onClick={openInPanel}>{busy === "open" ? S.opening : S.openPanel}</button>
      </div>
      {msg && <div className="flash-box">{msg}</div>}
      {err && <div className="error-box" role="alert">{err}</div>}

      {empty ? <p className="small muted">{S.empty}</p> : (
        <>
          <img className="graph-img" src={svgUrl} alt={S.alt} data-testid="graph-image" />
          <div className="graph-nodes" data-testid="graph-nodes">
            <b className="small">{S.neighbours}</b>
            <ul>
              {data?.nodes.map((n) => (
                <li key={n.id} className={n.id === focus ? "focus" : ""}>
                  <button className="link-btn" onClick={() => setFocus(n.id)}>{n.label}</button>{" "}
                  <span className="badge">{n.type === "note" ? S.note : S.kinds[n.kind] ?? S.entity}</span>
                  {n.type === "note" && (
                    <button className="btn small" disabled={Boolean(busy)} onClick={() => propose(n.id.slice(2))}>{busy === n.id.slice(2) ? S.asking : S.askModel}</button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </>
      )}

      {proposed.length > 0 && (
        <div data-testid="graph-proposed">
          <b className="small">{S.proposedHead}</b>
          {proposed.map((r) => (
            <div key={r.id} className="card graph-relation">
              <div className="card-head">
                <span><b>{r.from}</b> — {r.label} → <b>{r.to}</b></span>
                <div className="spacer" />
                <button className="btn small primary" onClick={() => act(() => api.patch(`/api/memory-graph/relations/${r.id}`, { status: "confirmed" }))}>{S.confirm}</button>
                <button className="btn small" onClick={() => act(() => api.patch(`/api/memory-graph/relations/${r.id}`, { status: "rejected" }))}>{S.reject}</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {confirmed.length > 0 && (
        <div>
          <b className="small">{S.confirmedHead}</b>
          {confirmed.map((r) => (
            <div key={r.id} className="card graph-relation">
              <div className="card-head">
                <span><b>{r.from}</b> — {r.label} → <b>{r.to}</b></span>
                <div className="spacer" />
                <button className="icon-btn" aria-label={`${S.remove}: ${r.label}`} onClick={() => act(() => api.del(`/api/memory-graph/relations/${r.id}`))}><IconTrash size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="memory-add">
        <b className="small">{S.addHead}</b>
        <div className="row">
          <label className="field"><span>{S.relFrom}</span><input aria-label={S.relFrom} value={rel.source} onChange={(e) => setRel({ ...rel, source: e.target.value })} /></label>
          <label className="field"><span>{S.relLabel}</span><input aria-label={S.relLabel} value={rel.label} onChange={(e) => setRel({ ...rel, label: e.target.value })} /></label>
          <label className="field"><span>{S.relTo}</span><input aria-label={S.relTo} value={rel.target} onChange={(e) => setRel({ ...rel, target: e.target.value })} /></label>
        </div>
        <div className="row">
          <button className="btn" disabled={!rel.source.trim() || !rel.label.trim() || !rel.target.trim()}
            onClick={() => act(async () => { await api.post("/api/memory-graph/relations", { ...rel, scope: scope || "global" }); setRel({ source: "", label: "", target: "" }); })}>{S.addRel}</button>
        </div>
      </div>
    </div>
  );
}
