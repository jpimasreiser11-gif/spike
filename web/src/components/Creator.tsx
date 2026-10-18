import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { Blueprint, DesignSystemInfo, ProviderInfo, Specialist } from "../types";
import { Forge } from "./Forge";

const C = lang === "es"
  ? { title: "Crear", intro: "Elige qué quieres crear y responde unas preguntas. SPIKE prepara el plan de Forge con los pasos, los archivos y los criterios; lo revisas y el equipo lo hace y lo comprueba.",
      close: "Cerrar", back: "Volver", plan: "Preparar el plan", preparing: "Preparando…", design: "Sistema de diseño", noDesign: "Ninguno",
      files: "Archivos de datos encontrados", noFiles: "No hay archivos de datos en esta carpeta: súbelos al proyecto o ponlos en el espacio de trabajo.",
      makes: "Crea", skills: "Sigue la skill", reviewIntro: "Este plan sale de la plantilla con tus respuestas. Revísalo o cámbialo y apruébalo." }
  : { title: "Create", intro: "Pick what you want to create and answer a few questions. SPIKE prepares the Forge plan with steps, files and criteria; you review it and the team does it and checks it.",
      close: "Close", back: "Back", plan: "Prepare the plan", preparing: "Preparing…", design: "Design system", noDesign: "None",
      files: "Data files found", noFiles: "There are no data files in this folder: upload them to the project or put them in the workspace.",
      makes: "Makes", skills: "Follows the skill", reviewIntro: "This plan comes from the template and your answers. Review or change it and approve it." };

export type TemplateField = { id: string; label: string; kind: "text" | "textarea" | "number" | "file"; required: boolean; placeholder: string; default: string };
export type Template = { id: string; icon: string; name: string; description: string; fields: TemplateField[]; skills: string[]; design: boolean; deliverables: string[] };
type Built = { task: string; blueprint: Blueprint; skills: string[]; design: boolean; template: string };
export type CreatorExtra = { skills: string[]; design_system?: string };

const ICONS: Record<string, string> = {
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm-9 9h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3Z",
  app: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm-1 4h16M8 12h8M8 16h5",
  chart: "M4 20V4m0 16h16M8 16v-4m4 4V8m4 8v-6",
  table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  slides: "M3 5h18v11H3zM12 16v4m-4 0h8M7 9h6M7 12h4",
  bolt: "M13 3 5 14h6l-1 7 8-11h-6z",
};

function TemplateIcon({ name }: { name: string }) {
  return (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name] ?? ICONS.doc} />
    </svg>
  );
}

/** Creator: templates that become a Forge plan; Forge runs and checks it with the template's skills and design. */
export function Creator({ specialists, providers, projectId, designs, projectDesign, onRun, onClose }: {
  specialists: Specialist[];
  providers: ProviderInfo[];
  projectId?: string;
  designs: DesignSystemInfo[];
  projectDesign?: string;
  onRun: (task: string, blueprint: Blueprint, providerId: string | null, extra: CreatorExtra) => void;
  onClose: () => void;
}) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [chosen, setChosen] = useState<Template | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [design, setDesign] = useState(projectDesign ?? "");
  const [files, setFiles] = useState<{ path: string; bytes: number }[] | null>(null);
  const [built, setBuilt] = useState<Built | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Template[]>(`/api/creator/templates?lang=${lang}`).then(setTemplates).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!chosen?.fields.some((f) => f.kind === "file")) return;
    api.get<{ path: string; bytes: number }[]>(`/api/creator/data-files${projectId ? `?project_id=${projectId}` : ""}`)
      .then(setFiles).catch(() => setFiles([]));
  }, [chosen, projectId]);

  const choose = (tpl: Template) => {
    setChosen(tpl);
    setAnswers(Object.fromEntries(tpl.fields.map((f) => [f.id, f.default])));
    setError("");
  };

  const prepare = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chosen) return;
    setBusy(true);
    setError("");
    try {
      setBuilt(await api.post<Built>("/api/creator/blueprint", { template: chosen.id, fields: answers, lang }));
    } catch (e2) {
      setError((e2 as Error).message);
    }
    setBusy(false);
  };

  if (built && chosen) {
    return (
      <Forge specialists={specialists} providers={providers} projectId={projectId} initialTask={built.task} initialBlueprint={built.blueprint}
        title={`${C.title} · ${chosen.name}`} intro={C.reviewIntro} onBack={() => setBuilt(null)} onClose={onClose}
        onRun={(task, bp, providerId) => onRun(task, bp, providerId, { skills: built.skills, ...(chosen.design && design ? { design_system: design } : {}) })} />
    );
  }

  return (
    <section className="forge creator" aria-label={C.title}>
      <div className="forge-head">
        <h1>{chosen ? `${C.title} · ${chosen.name}` : C.title}</h1>
        <div className="spacer" />
        <button className="btn" onClick={onClose}>{C.close}</button>
      </div>
      {!chosen ? (
        <>
          <p className="muted">{C.intro}</p>
          <div className="template-grid">
            {templates.map((tpl) => (
              <button key={tpl.id} className="template-card" onClick={() => choose(tpl)}>
                <span className="template-icon"><TemplateIcon name={tpl.icon} /></span>
                <b>{tpl.name}</b>
                <span className="muted small">{tpl.description}</span>
              </button>
            ))}
          </div>
          {error && <div className="error-box" role="alert">{error}</div>}
        </>
      ) : (
        <form className="form" onSubmit={prepare}>
          <p className="muted">{chosen.description}</p>
          {chosen.fields.map((f) => (
            <div key={f.id} className="field-group">
              <label className="field"><span>{f.label}</span>
                {f.kind === "textarea" ? (
                  <textarea rows={3} required={f.required} value={answers[f.id] ?? ""} placeholder={f.placeholder}
                    onChange={(e) => setAnswers({ ...answers, [f.id]: e.target.value })} />
                ) : (
                  <input type={f.kind === "number" ? "number" : "text"} min={f.kind === "number" ? 1 : undefined} max={f.kind === "number" ? 40 : undefined}
                    required={f.required} value={answers[f.id] ?? ""} placeholder={f.placeholder} list={f.kind === "file" ? `files-${f.id}` : undefined}
                    onChange={(e) => setAnswers({ ...answers, [f.id]: e.target.value })} />
                )}
                {f.kind === "file" && <datalist id={`files-${f.id}`}>{(files ?? []).map((x) => <option key={x.path} value={x.path} />)}</datalist>}
              </label>
              {f.kind === "file" && files && (files.length ? (
                <div className="file-picks">
                  <span className="muted small">{C.files}:</span>
                  {files.slice(0, 8).map((x) => (
                    <button type="button" key={x.path} className={`chip ${answers[f.id] === x.path ? "selected" : ""}`}
                      aria-pressed={answers[f.id] === x.path} onClick={() => setAnswers({ ...answers, [f.id]: x.path })}>{x.path}</button>
                  ))}
                </div>
              ) : <p className="muted small">{C.noFiles}</p>)}
            </div>
          ))}
          {chosen.design && (
            <label className="field inline"><span>{C.design}</span>
              <select value={design} onChange={(e) => setDesign(e.target.value)} aria-label={C.design}>
                <option value="">{C.noDesign}</option>
                {designs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </label>
          )}
          <p className="small muted">
            {C.makes} {chosen.deliverables.map((d) => <code key={d}>{d}</code>).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, ", ", el] : [el]), [])}
            {chosen.skills.length > 0 && <> · {C.skills} <code>{chosen.skills.join(", ")}</code></>}
          </p>
          {error && <div className="error-box" role="alert">{error}</div>}
          <div className="row end"><div className="spacer" />
            <button className="btn" type="button" onClick={() => setChosen(null)}>{C.back}</button>
            <button className="btn primary" type="submit" disabled={busy}>{busy ? C.preparing : C.plan}</button>
          </div>
        </form>
      )}
    </section>
  );
}
