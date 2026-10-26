import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { FolderFile, FolderJob, MemoryFolder, MemoryFolders as FoldersData, Project } from "../types";
import { IconTrash } from "./Icons";

const S = lang === "es"
  ? {
      intro: "Carpetas de este ordenador que SPIKE lee y guarda en su memoria para citarlas en las respuestas. No se indexa nada hasta que añadas una carpeta aquí. Solo se leen archivos que están dentro de la carpeta: los enlaces que salen de ella se ignoran. Todo se queda en tu ordenador.",
      pathLabel: "Ruta absoluta de la carpeta", pathPlaceholder: "/home/ana/notas   o   C:\\Users\\Ana\\Notas", scope: "Para", global: "Global",
      add: "Añadir carpeta e indexar", rules: "Reglas", hideRules: "Ocultar reglas", include: "Incluir (uno por línea)", exclude: "Excluir (uno por línea)",
      rulesHint: "Un patrón sin «/» se compara con el nombre del archivo; con «/», con la ruta dentro de la carpeta. Se ignoran siempre las carpetas ocultas, node_modules, .git y los entornos virtuales.",
      maxMb: "Tamaño máximo por archivo (MB)", maxFiles: "Máximo de archivos", saveRules: "Guardar reglas y reindexar", cancel: "Cancelar",
      empty: "No hay carpetas indexadas.", files: "archivos", chunks: "fragmentos", never: "sin indexar todavía", lastIndexed: "Indexada",
      reindex: "Reindexar", reindexAll: "Reindexar todo", showFiles: "Archivos", hideFiles: "Ocultar archivos", forget: "Olvidar carpeta",
      confirmForget: "Sí, olvidarla", forgetHint: "Borra de la memoria todo lo indexado de esta carpeta: texto, índice de palabras y vectores. No toca tus archivos.",
      editRules: "Editar reglas", defaultRules: "Valores por defecto",
      state: { queued: "En cola", scanning: "Buscando archivos…", indexing: "Indexando", embedding: "Calculando significados", done: "Al día", error: "Error", cancelled: "Cancelada" } as Record<string, string>,
      stats: (j: FolderJob) => `${j.indexed} nuevos o cambiados · ${j.unchanged} sin cambios · ${j.removed} retirados`,
      skippedWhy: { venv: "entorno virtual", link: "enlace", outside: "fuera de la carpeta", denied: "excluido por reglas", empty: "vacío", too_big: "demasiado grande", limit: "más del máximo", binary: "binario", unreadable: "ilegible" } as Record<string, string>,
      skipped: "Omitidos", filesOf: "Archivos indexados", noFiles: "Todavía no hay archivos indexados.", status: { binary: "binario", unreadable: "ilegible" } as Record<string, string>,
    }
  : {
      intro: "Folders on this computer that SPIKE reads and keeps in its memory so answers can cite them. Nothing is indexed until you add a folder here. Only files that are inside the folder are read: links that point out of it are ignored. Everything stays on your computer.",
      pathLabel: "Absolute path of the folder", pathPlaceholder: "/home/ana/notes   or   C:\\Users\\Ana\\Notes", scope: "For", global: "Global",
      add: "Add folder and index it", rules: "Rules", hideRules: "Hide rules", include: "Include (one per line)", exclude: "Exclude (one per line)",
      rulesHint: "A pattern without \"/\" is matched against the file name; with \"/\", against the path inside the folder. Hidden folders, node_modules, .git and virtual environments are always skipped.",
      maxMb: "Largest file (MB)", maxFiles: "Most files", saveRules: "Save rules and reindex", cancel: "Cancel",
      empty: "No folders are indexed.", files: "files", chunks: "chunks", never: "not indexed yet", lastIndexed: "Indexed",
      reindex: "Reindex", reindexAll: "Reindex everything", showFiles: "Files", hideFiles: "Hide files", forget: "Forget folder",
      confirmForget: "Yes, forget it", forgetHint: "Deletes everything indexed from this folder from memory: text, word index and vectors. Your files are not touched.",
      editRules: "Edit rules", defaultRules: "Defaults",
      state: { queued: "Queued", scanning: "Looking for files…", indexing: "Indexing", embedding: "Computing meanings", done: "Up to date", error: "Error", cancelled: "Cancelled" } as Record<string, string>,
      stats: (j: FolderJob) => `${j.indexed} new or changed · ${j.unchanged} unchanged · ${j.removed} removed`,
      skippedWhy: { venv: "virtual environment", link: "link", outside: "outside the folder", denied: "excluded by rules", empty: "empty", too_big: "too big", limit: "over the limit", binary: "binary", unreadable: "unreadable" } as Record<string, string>,
      skipped: "Skipped", filesOf: "Indexed files", noFiles: "No files are indexed yet.", status: { binary: "binary", unreadable: "unreadable" } as Record<string, string>,
    };

const ACTIVE = new Set(["queued", "scanning", "indexing", "embedding"]);
const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

type Rules = { include: string; exclude: string; mb: string; files: string };

function RulesEditor({ rules, set }: { rules: Rules; set: (r: Rules) => void }) {
  return (
    <div className="form folder-rules">
      <div className="row">
        <label className="field"><span>{S.include}</span><textarea rows={5} value={rules.include} onChange={(e) => set({ ...rules, include: e.target.value })} /></label>
        <label className="field"><span>{S.exclude}</span><textarea rows={5} value={rules.exclude} onChange={(e) => set({ ...rules, exclude: e.target.value })} /></label>
      </div>
      <small className="muted">{S.rulesHint}</small>
      <div className="row">
        <label className="field"><span>{S.maxMb}</span><input type="number" min={1} value={rules.mb} onChange={(e) => set({ ...rules, mb: e.target.value })} /></label>
        <label className="field"><span>{S.maxFiles}</span><input type="number" min={1} value={rules.files} onChange={(e) => set({ ...rules, files: e.target.value })} /></label>
      </div>
    </div>
  );
}

const toRules = (r: { include: string[]; exclude: string[]; max_file_bytes: number; max_files: number }): Rules => ({
  include: r.include.join("\n"), exclude: r.exclude.join("\n"), mb: String(Math.max(1, Math.round(r.max_file_bytes / 1024 ** 2))), files: String(r.max_files),
});
const fromRules = (r: Rules) => ({
  include: lines(r.include), exclude: lines(r.exclude),
  max_file_bytes: Math.max(1, Number(r.mb) || 1) * 1024 ** 2, max_files: Math.max(1, Number(r.files) || 1),
});

function Progress({ job }: { job: FolderJob }) {
  const active = ACTIVE.has(job.state);
  return (
    <div className="folder-job small" data-testid="folder-job" data-state={job.state}>
      <div className="row end">
        <b>{S.state[job.state] ?? job.state}</b>
        {active && job.total > 0 && <progress value={job.done} max={job.total} aria-label={S.state[job.state]} />}
        {job.total > 0 && <span className="muted">{job.done} / {job.total}</span>}
      </div>
      {active && job.current && <div className="muted folder-current"><code>{job.current}</code></div>}
      {job.state === "done" && <div className="muted">{S.stats(job)}</div>}
      {job.warning && <div className="muted">{job.warning}</div>}
      {job.error && <div className="error-box" role="alert">{job.error}</div>}
    </div>
  );
}

function Folder({ folder, projects, reload, defaults }: { folder: MemoryFolder; projects: Project[]; reload: () => void; defaults: FoldersData["defaults"] }) {
  const [showFiles, setShowFiles] = useState(false);
  const [files, setFiles] = useState<FolderFile[] | null>(null);
  const [editing, setEditing] = useState<Rules | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState("");
  const job = folder.job;
  const scopeName = folder.scope === "global" ? S.global : projects.find((p) => `project:${p.id}` === folder.scope)?.name ?? folder.scope;
  const act = async (fn: () => Promise<unknown>) => {
    setErr("");
    try { await fn(); } catch (e) { setErr((e as Error).message); }
    reload();
  };
  useEffect(() => {
    if (!showFiles) return;
    api.get<FolderFile[]>(`/api/memory-folders/${folder.id}/files?limit=500`).then(setFiles).catch((e) => setErr(String(e.message)));
  }, [showFiles, folder.indexed, folder.files, folder.id]);
  const skipped = Object.entries(job?.state === "done" || !job ? folder.skipped : job.skipped).filter(([, n]) => n > 0);
  const busy = job ? ACTIVE.has(job.state) : false;
  return (
    <div className="card memory-folder" data-testid="memory-folder">
      <div className="card-head">
        <code className="folder-path">{folder.path}</code>
        <span className="badge">{scopeName}</span>
        <div className="spacer" />
        <button className="icon-btn" aria-label={`${S.forget}: ${folder.path}`} title={S.forget} onClick={() => setConfirm(true)}><IconTrash size={14} /></button>
      </div>
      <div className="small muted">
        <b data-testid="folder-files">{folder.files}</b> {S.files} · {folder.chunks} {S.chunks} · {folder.indexed ? `${S.lastIndexed} ${new Date(folder.indexed * 1000).toLocaleString()}` : S.never}
      </div>
      {job && <Progress job={job} />}
      {skipped.length > 0 && (
        <div className="small muted">{S.skipped}: {skipped.map(([why, n]) => `${n} ${S.skippedWhy[why] ?? why}`).join(" · ")}</div>
      )}
      {err && <div className="error-box" role="alert">{err}</div>}
      {confirm ? (
        <div className="form">
          <small className="muted">{S.forgetHint}</small>
          <div className="row">
            <button className="btn danger" onClick={() => act(async () => { await api.del(`/api/memory-folders/${folder.id}`); setConfirm(false); })}>{S.confirmForget}</button>
            <button className="btn" onClick={() => setConfirm(false)}>{S.cancel}</button>
          </div>
        </div>
      ) : (
        <div className="row">
          <button className="btn small" disabled={busy} onClick={() => act(() => api.post(`/api/memory-folders/${folder.id}/reindex`, { force: false }))}>{S.reindex}</button>
          <button className="btn small" disabled={busy} onClick={() => act(() => api.post(`/api/memory-folders/${folder.id}/reindex`, { force: true }))}>{S.reindexAll}</button>
          <button className="btn small" onClick={() => setEditing(editing ? null : toRules(folder))}>{S.editRules}</button>
          <button className="btn small" aria-expanded={showFiles} onClick={() => setShowFiles(!showFiles)}>{showFiles ? S.hideFiles : S.showFiles}</button>
        </div>
      )}
      {editing && (
        <div className="form">
          <RulesEditor rules={editing} set={setEditing} />
          <div className="row">
            <button className="btn primary" onClick={() => act(async () => { await api.patch(`/api/memory-folders/${folder.id}`, fromRules(editing)); setEditing(null); })}>{S.saveRules}</button>
            <button className="btn" onClick={() => setEditing(null)}>{S.cancel}</button>
            <button className="btn" onClick={() => setEditing(toRules(defaults))}>{S.defaultRules}</button>
          </div>
        </div>
      )}
      {showFiles && (
        <div className="folder-files small">
          <b>{S.filesOf}</b>
          {files && files.length === 0 && <p className="muted">{S.noFiles}</p>}
          <ul>
            {(files ?? []).map((f) => (
              <li key={f.path}><code>{f.path}</code> <span className="muted">{(f.size / 1024).toFixed(f.size < 10240 ? 1 : 0)} KB{f.status !== "indexed" ? ` · ${S.status[f.status] ?? f.status}` : ""}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function MemoryFolders() {
  const [data, setData] = useState<FoldersData | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [path, setPath] = useState("");
  const [scope, setScope] = useState("global");
  const [rules, setRules] = useState<Rules | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try { setData(await api.get<FoldersData>("/api/memory-folders")); } catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { load(); api.get<Project[]>("/api/projects").then(setProjects).catch(() => {}); }, []);
  // while a folder is being indexed, ask again every second so the progress moves
  const active = data?.folders.some((f) => f.job && ACTIVE.has(f.job.state)) ?? false;
  useEffect(() => {
    if (!active) return;
    const id = setTimeout(load, 700);
    return () => clearTimeout(id);
  }, [data, active]);

  const add = async () => {
    setErr(""); setBusy(true);
    try {
      await api.post("/api/memory-folders", { path: path.trim(), scope, ...(rules ? fromRules(rules) : {}) });
      setPath(""); setRules(null);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
    load();
  };

  return (
    <div className="form" data-testid="memory-folders">
      <p className="small muted">{S.intro}</p>
      <div className="memory-add">
        <label className="field"><span>{S.pathLabel}</span>
          <input type="text" aria-label={S.pathLabel} placeholder={S.pathPlaceholder} value={path} onChange={(e) => setPath(e.target.value)} spellCheck={false} />
        </label>
        <div className="row end">
          <label className="field inline"><span>{S.scope}</span>
            <select aria-label={S.scope} value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="global">{S.global}</option>
              {projects.map((p) => <option key={p.id} value={`project:${p.id}`}>{p.name}</option>)}
            </select>
          </label>
          <button className="btn" disabled={!data} onClick={() => setRules(rules ? null : toRules(data!.defaults))}>{rules ? S.hideRules : S.rules}</button>
          <button className="btn primary" disabled={!path.trim() || busy} onClick={add}>{S.add}</button>
        </div>
        {rules && <RulesEditor rules={rules} set={setRules} />}
      </div>
      {err && <div className="error-box" role="alert">{err}</div>}
      {data && data.folders.length === 0 && <p className="small muted">{S.empty}</p>}
      {data?.folders.map((f) => <Folder key={f.id} folder={f} projects={projects} reload={load} defaults={data.defaults} />)}
    </div>
  );
}
