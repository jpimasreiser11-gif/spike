import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { GlossaryEntry, Project } from "../types";
import { IconTrash, IconUpload } from "./Icons";

const S = lang === "es"
  ? {
      intro: "Tu vocabulario fijo: cuando un término aparece en la conversación, SPIKE lo recibe como regla y usa exactamente tu traducción o definición. Hay un glosario global y uno por proyecto; el del proyecto manda sobre el global. Se guarda en tu ordenador.",
      scope: "Glosario de", global: "Global", search: "Buscar un término…", term: "Término", translation: "Traducción o definición", lang: "Idioma", langHint: "es, en…",
      note: "Nota (opcional)", langTitle: "Código del idioma de la traducción; vacío si es una definición", add: "Añadir", save: "Guardar", cancel: "Cancelar", edit: "Editar", remove: "Eliminar", empty: "Este glosario está vacío.",
      exportCsv: "Exportar (.csv)", importCsv: "Importar (.csv)", imported: "Importados", updated: "actualizados", skipped: "omitidos", line: "línea",
      csvHint: "Columnas del CSV: término, traducción, idioma, nota. Se admiten , ; o tabulador como separador.", count: "entradas",
    }
  : {
      intro: "Your fixed vocabulary: when a term appears in the conversation, SPIKE gets it as a rule and uses exactly your translation or definition. There is a global glossary and one per project; the project's wins over the global one. It is stored on your computer.",
      scope: "Glossary of", global: "Global", search: "Find a term…", term: "Term", translation: "Translation or definition", lang: "Language", langHint: "en, es…",
      note: "Note (optional)", langTitle: "Language code of the translation; empty for a definition", add: "Add", save: "Save", cancel: "Cancel", edit: "Edit", remove: "Delete", empty: "This glossary is empty.",
      exportCsv: "Export (.csv)", importCsv: "Import (.csv)", imported: "Imported", updated: "updated", skipped: "skipped", line: "line",
      csvHint: "CSV columns: term, translation, language, note. Comma, semicolon or tab separators work.", count: "entries",
    };

type Draft = { term: string; translation: string; lang: string; note: string };
const blank: Draft = { term: "", translation: "", lang: "", note: "" };
type ImportResult = { added: number; updated: number; skipped: number; errors: { line: number; error: string }[] };

function Fields({ draft, set }: { draft: Draft; set: (d: Draft) => void }) {
  return (
    <div className="row glossary-fields">
      <label className="field"><span>{S.term}</span><input aria-label={S.term} value={draft.term} maxLength={200} onChange={(e) => set({ ...draft, term: e.target.value })} /></label>
      <label className="field"><span>{S.translation}</span><input aria-label={S.translation} value={draft.translation} maxLength={1000} onChange={(e) => set({ ...draft, translation: e.target.value })} /></label>
      <label className="field narrow"><span>{S.lang}</span><input aria-label={S.lang} placeholder={S.langHint} title={S.langTitle} value={draft.lang} maxLength={20} onChange={(e) => set({ ...draft, lang: e.target.value })} /></label>
      <label className="field"><span>{S.note}</span><input aria-label={S.note} value={draft.note} maxLength={500} onChange={(e) => set({ ...draft, note: e.target.value })} /></label>
    </div>
  );
}

export function Glossary() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [scope, setScope] = useState("global");
  const [q, setQ] = useState("");
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [draft, setDraft] = useState<Draft>(blank);
  const [editing, setEditing] = useState<{ id: string } & Draft | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const importRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    const params = new URLSearchParams({ scope });
    if (q.trim()) params.set("q", q.trim());
    try { setEntries(await api.get<GlossaryEntry[]>(`/api/glossary?${params}`)); } catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { api.get<Project[]>("/api/projects").then(setProjects).catch(() => {}); }, []);
  useEffect(() => { const id = setTimeout(load, q ? 250 : 0); return () => clearTimeout(id); }, [scope, q]);

  const run = async (fn: () => Promise<unknown>) => {
    setErr(""); setMsg("");
    try { await fn(); } catch (e) { setErr((e as Error).message); }
    load();
  };

  return (
    <div className="form" data-testid="glossary">
      <p className="small muted">{S.intro}</p>
      <div className="row end">
        <label className="field inline"><span>{S.scope}</span>
          <select aria-label={S.scope} value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="global">{S.global}</option>
            {projects.map((p) => <option key={p.id} value={`project:${p.id}`}>{p.name}</option>)}
          </select>
        </label>
        <input type="search" className="grow" aria-label={S.search} placeholder={S.search} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div className="memory-add">
        <Fields draft={draft} set={setDraft} />
        <div className="row">
          <button className="btn primary" disabled={!draft.term.trim() || !draft.translation.trim()}
            onClick={() => run(async () => { await api.post("/api/glossary", { ...draft, scope }); setDraft(blank); })}>{S.add}</button>
        </div>
      </div>
      {msg && <div className="flash-box">{msg}</div>}
      {err && <div className="error-box" role="alert">{err}</div>}

      {entries.length === 0 && <p className="small muted">{S.empty}</p>}
      {entries.map((e) => (
        <div key={e.id} className="card glossary-item" data-testid="glossary-entry">
          {editing?.id === e.id ? (
            <>
              <Fields draft={editing} set={(d) => setEditing({ ...d, id: e.id })} />
              <div className="row">
                <button className="btn primary" disabled={!editing.term.trim() || !editing.translation.trim()}
                  onClick={() => run(async () => { await api.put(`/api/glossary/${e.id}`, { term: editing.term, translation: editing.translation, lang: editing.lang, note: editing.note }); setEditing(null); })}>{S.save}</button>
                <button className="btn" onClick={() => setEditing(null)}>{S.cancel}</button>
              </div>
            </>
          ) : (
            <div className="card-head">
              <b>{e.term}</b><span aria-hidden="true">→</span><span className="glossary-translation">{e.translation}</span>
              {e.lang && <span className="badge">{e.lang}</span>}
              {e.note && <span className="small muted">{e.note}</span>}
              <div className="spacer" />
              <button className="btn small" onClick={() => setEditing({ id: e.id, term: e.term, translation: e.translation, lang: e.lang, note: e.note })}>{S.edit}</button>
              <button className="icon-btn" aria-label={`${S.remove}: ${e.term}`} onClick={() => run(() => api.del(`/api/glossary/${e.id}`))}><IconTrash size={14} /></button>
            </div>
          )}
        </div>
      ))}

      <div className="row">
        <a className="btn" href={`/api/glossary-export?scope=${encodeURIComponent(scope)}`} download>{S.exportCsv}</a>
        <button className="btn" onClick={() => importRef.current?.click()}><IconUpload size={14} /> {S.importCsv}</button>
        <input ref={importRef} type="file" accept=".csv,text/csv,text/plain" hidden data-testid="glossary-import" onChange={(ev) => {
          const file = ev.target.files?.[0];
          if (file) run(async () => {
            const r = await api.upload<ImportResult>("POST", `/api/glossary-import?scope=${encodeURIComponent(scope)}`, file);
            const first = r.errors[0];
            setMsg(`${S.imported}: ${r.added} · ${S.updated}: ${r.updated} · ${S.skipped}: ${r.skipped}${first ? ` (${S.line} ${first.line}: ${first.error})` : ""}`);
          });
          ev.target.value = "";
        }} />
        <small className="muted">{S.csvHint}</small>
      </div>
    </div>
  );
}
