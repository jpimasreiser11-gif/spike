import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { MemoryItem, MemoryStatus, Project, Settings } from "../types";
import { Glossary } from "./Glossary";
import { IconTrash, IconUpload } from "./Icons";
import { MemoryFolders } from "./MemoryFolders";
import { MemoryGraph } from "./MemoryGraph";
import { Tutor } from "./Tutor";

export const M = lang === "es"
  ? {
      intro: "SPIKE recuerda lo importante de tus chats y de los archivos de tus proyectos, y lo usa cuando viene al caso. Todo se guarda en tu ordenador; puedes verlo, corregirlo, exportarlo y borrarlo aquí.",
      enabled: "Usar la memoria en los chats", learn: "Guardar lo que le pides recordar («recuerda que…», «a partir de ahora…») y proponer reglas cuando lo corriges", summaries: "Resumir los chats en la memoria (solo con el modelo local, sin coste)",
      search: "Búsqueda", semanticOn: "por palabras y por significado", wordsOnly: "por palabras", installHint: "Para buscar también por significado, instala el modelo de memoria:",
      semanticOff: "Buscar solo por palabras", failed: "El modelo de memoria no arrancó; se busca por palabras",
      memories: "recuerdos", add: "Añadir", addPlaceholder: "Algo que SPIKE debe recordar…", filter: "Buscar en la memoria…",
      all: "Todo", global: "Global", project: "Proyecto", allKinds: "Todos los tipos",
      kinds: { fact: "Dato", decision: "Decisión", preference: "Preferencia", rule: "Regla", summary: "Resumen de chat", document: "Archivo" } as Record<string, string>,
      ruleHint: "Las reglas se aplican siempre; el resto se usa cuando es relevante.",
      edit: "Editar", save: "Guardar", cancel: "Cancelar", remove: "Eliminar", exportAll: "Exportar (.json)", importFile: "Importar",
      clear: "Borrar toda la memoria", confirmClear: "Sí, borrarla", imported: "Importados", empty: "Todavía no hay recuerdos.",
      byWords: "palabras", byMeaning: "significado",
      glossary: "Glosario", sub: { notes: "Recuerdos", folders: "Carpetas", glossary: "Glosario", tutor: "Tutor", graph: "Grafo" },
    }
  : {
      intro: "SPIKE remembers what matters from your chats and your project files, and uses it when relevant. Everything stays on your computer; see, correct, export and delete it here.",
      enabled: "Use memory in chats", learn: "Save what you ask it to remember (\"remember that…\", \"from now on…\") and suggest rules when you correct it", summaries: "Summarise chats into memory (local model only, no cost)",
      search: "Search", semanticOn: "by words and by meaning", wordsOnly: "by words", installHint: "To also search by meaning, install the memory model:",
      semanticOff: "Search by words only", failed: "The memory model did not start; searching by words",
      memories: "memories", add: "Add", addPlaceholder: "Something SPIKE should remember…", filter: "Search memory…",
      all: "All", global: "Global", project: "Project", allKinds: "All kinds",
      kinds: { fact: "Fact", decision: "Decision", preference: "Preference", rule: "Rule", summary: "Chat summary", document: "File" } as Record<string, string>,
      ruleHint: "Rules always apply; everything else is used when relevant.",
      edit: "Edit", save: "Save", cancel: "Cancel", remove: "Delete", exportAll: "Export (.json)", importFile: "Import",
      clear: "Delete all memory", confirmClear: "Yes, delete it", imported: "Imported", empty: "No memories yet.",
      byWords: "words", byMeaning: "meaning",
      glossary: "Glossary", sub: { notes: "Memories", folders: "Folders", glossary: "Glossary", tutor: "Tutor", graph: "Graph" },
    };

const ADDABLE = ["fact", "decision", "preference", "rule"] as const;

const SUBS = ["notes", "folders", "glossary", "tutor", "graph"] as const;
type Sub = (typeof SUBS)[number];

/** Settings › Memory: the notes SPIKE keeps, plus the folders it indexes, the glossary, study progress and the graph. */
export function Memory({ settings, save, onClose }: { settings: Settings; save: (p: Partial<Settings>) => void; onClose: () => void }) {
  const [sub, setSub] = useState<Sub>("notes");
  return (
    <div className="form">
      <div className="seg memory-sub" role="tablist" aria-label="Memory">
        {SUBS.map((k) => (
          <button key={k} role="tab" aria-selected={sub === k} className={sub === k ? "on" : ""} data-sub={k} onClick={() => setSub(k)}>{M.sub[k]}</button>
        ))}
      </div>
      {sub === "notes" ? <Notes settings={settings} save={save} />
        : sub === "folders" ? <MemoryFolders />
        : sub === "glossary" ? <Glossary />
        : sub === "tutor" ? <Tutor />
        : <MemoryGraph onClose={onClose} />}
    </div>
  );
}

function Notes({ settings, save }: { settings: Settings; save: (p: Partial<Settings>) => void }) {
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [q, setQ] = useState("");
  const [scope, setScope] = useState("");
  const [kind, setKind] = useState("");
  const [draft, setDraft] = useState({ text: "", kind: "fact", scope: "global" });
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const importRef = useRef<HTMLInputElement>(null);
  const mem = settings.memory;

  const load = async () => {
    const params = new URLSearchParams({ limit: "200" });
    if (q.trim()) params.set("q", q.trim());
    if (scope) params.set("scope", scope);
    if (kind) params.set("kind", kind);
    try {
      setItems(await api.get<MemoryItem[]>(`/api/memory?${params}`));
      setStatus(await api.get<MemoryStatus>("/api/memory-status"));
    } catch (e) { setErr(String((e as Error).message)); }
  };
  useEffect(() => { api.get<Project[]>("/api/projects").then(setProjects).catch(() => {}); }, []);
  useEffect(() => { const id = setTimeout(load, q ? 250 : 0); return () => clearTimeout(id); }, [q, scope, kind]);

  const scopeName = (s: string) => s === "global" ? M.global : projects.find((p) => `project:${p.id}` === s)?.name ?? M.project;
  const run = async (fn: () => Promise<unknown>) => {
    setErr(""); setMsg("");
    try { await fn(); } catch (e) { setErr(String((e as Error).message)); }
    load();
  };

  return (
    <div className="form">
      <p className="small muted">{M.intro}</p>
      <label className="check"><input type="checkbox" checked={mem.enabled} onChange={(e) => save({ memory: { ...mem, enabled: e.target.checked } })} />{M.enabled}</label>
      <label className="check"><input type="checkbox" checked={mem.learn !== false} onChange={(e) => save({ memory: { ...mem, learn: e.target.checked } })} />{M.learn}</label>
      <label className="check"><input type="checkbox" checked={mem.auto_summary} onChange={(e) => save({ memory: { ...mem, auto_summary: e.target.checked } })} />{M.summaries}</label>
      <label className="check"><input type="checkbox" checked={mem.embeddings === "off"} onChange={(e) => save({ memory: { ...mem, embeddings: e.target.checked ? "off" : "auto" } })} />{M.semanticOff}</label>
      {status && (
        <div className="small" data-testid="memory-status">
          <b>{status.stats.memories}</b> {M.memories} · {M.search}: {status.semantic.installed && mem.embeddings !== "off" && !status.semantic.error ? `${M.semanticOn} (${status.semantic.model})` : M.wordsOnly}
          {status.semantic.error && <div className="muted">{M.failed}</div>}
          {!status.semantic.installed && mem.embeddings !== "off" && <div className="muted">{M.installHint} <code>{status.semantic.install}</code></div>}
        </div>
      )}

      <div className="memory-add">
        <textarea rows={2} aria-label={M.addPlaceholder} placeholder={M.addPlaceholder} value={draft.text} onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
        <div className="row">
          <select aria-label="kind" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
            {ADDABLE.map((k) => <option key={k} value={k}>{M.kinds[k]}</option>)}
          </select>
          <select aria-label="scope" value={draft.scope} onChange={(e) => setDraft({ ...draft, scope: e.target.value })}>
            <option value="global">{M.global}</option>
            {projects.map((p) => <option key={p.id} value={`project:${p.id}`}>{p.name}</option>)}
          </select>
          <button className="btn primary" disabled={!draft.text.trim()} onClick={() => run(async () => {
            await api.post("/api/memory", draft);
            setDraft({ ...draft, text: "" });
          })}>{M.add}</button>
        </div>
        <small className="muted">{M.ruleHint}</small>
      </div>

      <div className="row">
        <input type="search" className="grow" aria-label={M.filter} placeholder={M.filter} value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label={M.project} value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">{M.all}</option>
          <option value="global">{M.global}</option>
          {projects.map((p) => <option key={p.id} value={`project:${p.id}`}>{p.name}</option>)}
        </select>
        <select aria-label={M.allKinds} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">{M.allKinds}</option>
          {Object.entries(M.kinds).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
      </div>
      {msg && <div className="flash-box">{msg}</div>}
      {err && <div className="error-box" role="alert">{err}</div>}

      {items.length === 0 && <p className="small muted">{M.empty}</p>}
      {items.map((m) => (
        <div key={m.id} className="card memory-item" data-memory={m.kind}>
          <div className="card-head">
            <span className={`badge kind-${m.kind}`}>{M.kinds[m.kind] ?? m.kind}</span>
            <span className="badge">{scopeName(m.scope)}</span>
            {m.source.startsWith("file:") && <code className="small">{m.source.slice(5)}</code>}
            <span className="small muted">{new Date(m.updated * 1000).toLocaleDateString()}</span>
            {m.by && <span className="small muted">· {m.by.map((b) => b === "words" ? M.byWords : M.byMeaning).join(" + ")}</span>}
            <div className="spacer" />
            {m.kind !== "document" && editing?.id !== m.id && <button className="btn small" onClick={() => setEditing({ id: m.id, text: m.text })}>{M.edit}</button>}
            <button className="icon-btn" aria-label={`${M.remove}: ${m.text.slice(0, 40)}`} onClick={() => run(() => api.del(`/api/memory/${m.id}`))}><IconTrash size={14} /></button>
          </div>
          {editing?.id === m.id ? (
            <div className="memory-edit">
              <textarea rows={3} value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
              <div className="row">
                <button className="btn primary" onClick={() => run(async () => { await api.put(`/api/memory/${m.id}`, { text: editing.text }); setEditing(null); })}>{M.save}</button>
                <button className="btn" onClick={() => setEditing(null)}>{M.cancel}</button>
              </div>
            </div>
          ) : (
            <p className="small memory-text">{m.match && m.kind === "document" ? m.match : m.text.length > 600 ? `${m.text.slice(0, 600)}…` : m.text}</p>
          )}
        </div>
      ))}

      <div className="row">
        <a className="btn" href="/api/memory-export" download>{M.exportAll}</a>
        <button className="btn" onClick={() => importRef.current?.click()}><IconUpload size={14} /> {M.importFile}</button>
        <input ref={importRef} type="file" accept=".json,application/json" hidden data-testid="memory-import" onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) run(async () => {
            const r = await api.upload<{ imported: number }>("POST", "/api/memory-import", file);
            setMsg(`${M.imported}: ${r.imported}`);
          });
          e.target.value = "";
        }} />
        <div className="spacer" />
        {confirm
          ? <><button className="btn danger" onClick={() => run(async () => { await api.del("/api/memory?scope=all"); setConfirm(false); })}>{M.confirmClear}</button>
              <button className="btn" onClick={() => setConfirm(false)}>{M.cancel}</button></>
          : <button className="btn danger" onClick={() => setConfirm(true)}>{M.clear}</button>}
      </div>
    </div>
  );
}
