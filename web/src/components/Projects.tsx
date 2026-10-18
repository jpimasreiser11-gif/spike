import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { DesignSystemInfo, Project, ProjectFile, Specialist } from "../types";
import { IconClose, IconTrash, IconUpload } from "./Icons";

export const PL = lang === "es"
  ? {
      projects: "Proyectos", newProject: "Nuevo proyecto", importProject: "Importar proyecto", editProject: "Editar proyecto",
      name: "Nombre", instructions: "Instrucciones del proyecto", instructionsHint: "Se añaden a cada chat de este proyecto, igual que tus instrucciones personalizadas.",
      mode: "Especialista por defecto", auto: "Auto (el orquestador elige)", save: "Guardar", create: "Crear", remove: "Eliminar proyecto",
      confirmRemove: "Pulsa otra vez para borrar el proyecto, sus chats y sus archivos", files: "Archivos", filesHint: "Las herramientas de archivos de los chats de este proyecto trabajan en esta carpeta.",
      upload: "Subir archivos", removeFile: "Eliminar archivo", noFiles: "Todavía no hay archivos.", export: "Exportar (.zip)", edit: "Editar", back: "Todos los chats", chats: "Chats del proyecto",
      design: "Sistema de diseño", designNone: "Ninguno", designHint: "Las páginas, presentaciones y documentos de este proyecto lo siguen (tu marca, por ejemplo). Importa el tuyo en Ajustes › Diseño.",
    }
  : {
      projects: "Projects", newProject: "New project", importProject: "Import project", editProject: "Edit project",
      name: "Name", instructions: "Project instructions", instructionsHint: "Added to every chat in this project, like your custom instructions.",
      mode: "Default specialist", auto: "Auto (the orchestrator picks)", save: "Save", create: "Create", remove: "Delete project",
      confirmRemove: "Click again to delete the project, its chats and its files", files: "Files", filesHint: "File tools in this project's chats work in this folder.",
      upload: "Upload files", removeFile: "Delete file", noFiles: "No files yet.", export: "Export (.zip)", edit: "Edit", back: "All chats", chats: "Project chats",
      design: "Design system", designNone: "None", designHint: "Pages, slides and documents in this project follow it (your brand, for example). Import yours in Settings › Design.",
    };

const size = (n: number) => (n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`);
const fileUrl = (pid: string, path: string) => `/api/projects/${pid}/files/${path.split("/").map(encodeURIComponent).join("/")}`;

export function ProjectDialog({ project, specialists, designs = [], onClose, onSaved, onDeleted }: {
  project: Project | null;
  specialists: Specialist[];
  designs?: DesignSystemInfo[];
  onClose: () => void;
  onSaved: (p: Project) => void;
  onDeleted: (id: string) => void;
}) {
  const [name, setName] = useState(project?.name ?? "");
  const [instructions, setInstructions] = useState(project?.instructions ?? "");
  const [mode, setMode] = useState(project?.mode ?? "auto");
  const [design, setDesign] = useState(project?.design ?? "");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const body = { name: name.trim(), instructions, mode, design };
      onSaved(project ? await api.patch<Project>(`/api/projects/${project.id}`, body) : await api.post<Project>("/api/projects", body));
    } catch (err) {
      setError(String((err as Error).message));
    }
  };

  const remove = async () => {
    if (!project) return;
    if (!confirm) return setConfirm(true);
    await api.del(`/api/projects/${project.id}`);
    onDeleted(project.id);
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal small" role="dialog" aria-modal="true" aria-label={project ? PL.editProject : PL.newProject} onSubmit={submit}>
        <div className="modal-head">
          <h2>{project ? PL.editProject : PL.newProject}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><IconClose /></button>
        </div>
        <div className="form padded">
          <label className="field"><span>{PL.name}</span>
            <input autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field"><span>{PL.instructions}</span>
            <textarea rows={6} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
            <small>{PL.instructionsHint}</small>
          </label>
          <label className="field"><span>{PL.mode}</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="auto">{PL.auto}</option>
              {specialists.filter((s) => s.id !== "core").map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          {designs.length > 0 && (
            <label className="field"><span>{PL.design}</span>
              <select value={design} onChange={(e) => setDesign(e.target.value)}>
                <option value="">{PL.designNone}</option>
                {designs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
              <small>{PL.designHint}</small>
            </label>
          )}
          {error && <div className="error-box" role="alert">{error}</div>}
          <div className="row end">
            {project && <button type="button" className="btn danger" onClick={remove}>{confirm ? PL.confirmRemove : PL.remove}</button>}
            <div className="spacer" />
            <button className="btn primary" type="submit" disabled={!name.trim()}>{project ? PL.save : PL.create}</button>
          </div>
        </div>
      </form>
    </div>
  );
}

export function ProjectPanel({ project, specialists, designs = [], onEdit }: { project: Project; specialists: Specialist[]; designs?: DesignSystemInfo[]; onEdit: () => void }) {
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const load = () => api.get<ProjectFile[]>(`/api/projects/${project.id}/files`).then(setFiles).catch((e) => setError(String(e.message)));

  useEffect(() => {
    load();
  }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async (list: FileList | null) => {
    setError("");
    try {
      for (const file of Array.from(list ?? [])) await api.upload("PUT", fileUrl(project.id, file.name), file);
    } catch (e) {
      setError(String((e as Error).message));
    }
    if (input.current) input.current.value = "";
    load();
  };

  const spec = specialists.find((s) => s.id === project.mode);
  return (
    <section className="project-panel" aria-label={project.name}>
      <div className="project-head">
        <h2>{project.name}</h2>
        <span className="chip">{spec ? spec.name : PL.auto}</span>
        {designs.find((d) => d.id === project.design) && <span className="chip design-chip">{PL.design}: {designs.find((d) => d.id === project.design)?.name}</span>}
        <div className="spacer" />
        <button className="btn" onClick={onEdit}>{PL.edit}</button>
        <a className="btn" href={`/api/projects/${project.id}/export`} download>{PL.export}</a>
      </div>
      {project.instructions && <p className="project-instructions">{project.instructions}</p>}
      <div className="project-files">
        <div className="project-files-head">
          <strong>{PL.files}</strong>
          <small className="muted">{PL.filesHint}</small>
          <div className="spacer" />
          <button className="btn" onClick={() => input.current?.click()}><IconUpload size={15} /> {PL.upload}</button>
          <input ref={input} type="file" multiple hidden data-testid="project-upload" onChange={(e) => upload(e.target.files)} />
        </div>
        {error && <div className="error-box" role="alert">{error}</div>}
        {files.length === 0 ? <p className="muted small">{PL.noFiles}</p> : (
          <ul className="file-list">
            {files.map((f) => (
              <li key={f.path}>
                <a href={fileUrl(project.id, f.path)} download>{f.path}</a>
                <span className="muted">{size(f.size)}</span>
                <button className="icon-btn" aria-label={`${PL.removeFile}: ${f.path}`} onClick={() => api.del(fileUrl(project.id, f.path)).then(load)}><IconTrash size={14} /></button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
