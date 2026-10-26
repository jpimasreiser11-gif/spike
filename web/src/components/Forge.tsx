import { useEffect, useState } from "react";
import { api } from "../api";
import { lang, t } from "../i18n";
import type { Blueprint, BlueprintStep, ProtoRun, ProviderInfo, Specialist } from "../types";
import { IconPlus, IconTrash } from "./Icons";
import { Prototypes } from "./Prototypes";

const F = lang === "es"
  ? {
      title: "Forge", intro: "Describe una tarea. SPIKE prepara un plan con pasos, archivos y criterios de aceptación; lo revisas, lo cambias si quieres y solo entonces el equipo lo ejecuta y un verificador lo comprueba.",
      task: "Tarea", taskPlaceholder: "Ej.: Calcula el IVA de mis tres facturas, guárdalo en facturas.csv y resume el total en informe.md",
      executor: "Quién ejecuta", defaultProvider: "Predeterminado (ajustes)", draft: "Preparar el plan", drafting: "Preparando el plan…",
      goal: "Objetivo", requirements: "Requisitos (uno por línea)", steps: "Pasos", criteria: "Criterios de aceptación (uno por línea)",
      specialist: "Especialista", role: "Papel", research: "Investigador", execute: "Ejecutor", instruction: "Instrucción",
      files: "Archivos que guarda (separados por comas)", dependsOn: "Usa el resultado de", addStep: "Añadir paso", removeStep: "Quitar paso",
      back: "Volver", run: "Aprobar y ejecutar", fallback: "El planificador no dio un plan válido: revisa este borrador antes de aprobarlo.",
      close: "Cerrar", paid: "de pago", local: "local", noCriteria: "Sin criterios, el verificador solo revisa cada paso contra su instrucción.",
    }
  : {
      title: "Forge", intro: "Describe a task. SPIKE drafts a plan with steps, files and acceptance criteria; you review it, change it if you like, and only then the team runs it and a checker verifies it.",
      task: "Task", taskPlaceholder: "E.g.: Work out the VAT of my three invoices, save it to invoices.csv and summarise the total in report.md",
      executor: "Who runs it", defaultProvider: "Default (settings)", draft: "Draft the plan", drafting: "Drafting the plan…",
      goal: "Goal", requirements: "Requirements (one per line)", steps: "Steps", criteria: "Acceptance criteria (one per line)",
      specialist: "Specialist", role: "Role", research: "Researcher", execute: "Executor", instruction: "Instruction",
      files: "Files it saves (comma-separated)", dependsOn: "Uses the result of", addStep: "Add step", removeStep: "Remove step",
      back: "Back", run: "Approve and run", fallback: "The planner did not give a valid plan: review this draft before approving it.",
      close: "Close", paid: "paid", local: "local", noCriteria: "Without criteria, the checker only reviews each step against its instruction.",
    };

export const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);
const nextId = (steps: BlueprintStep[]) => {
  let n = steps.length + 1;
  while (steps.some((s) => s.id === `t${n}`)) n += 1;
  return `t${n}`;
};

/** The review form of a blueprint: goal, requirements, steps (specialist, role, instruction, files, dependencies) and
 * criteria. Forge uses it for one plan, Parallel Prototypes for each of its two. */
export function BlueprintEditor({ bp, onChange, requirements, setRequirements, criteria, setCriteria, specialists }: {
  bp: Blueprint;
  onChange: (bp: Blueprint) => void;
  requirements: string;
  setRequirements: (text: string) => void;
  criteria: string;
  setCriteria: (text: string) => void;
  specialists: Specialist[];
}) {
  const setStep = (i: number, patch: Partial<BlueprintStep>) =>
    onChange({ ...bp, steps: bp.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const removeStep = (i: number) => {
    const gone = bp.steps[i].id;
    onChange({ ...bp, steps: bp.steps.filter((_, j) => j !== i).map((s) => ({ ...s, depends_on: s.depends_on.filter((d) => d !== gone) })) });
  };
  const addStep = () =>
    onChange({ ...bp, steps: [...bp.steps, { id: nextId(bp.steps), specialist: "core", role: "execute", instruction: "", depends_on: [], deliverables: [] }] });

  return (
    <>
      <label className="field"><span>{F.goal}</span><input value={bp.goal} onChange={(e) => onChange({ ...bp, goal: e.target.value })} /></label>
      <label className="field"><span>{F.requirements}</span><textarea rows={3} value={requirements} onChange={(e) => setRequirements(e.target.value)} /></label>
      <div className="field"><span>{F.steps}</span></div>
      {bp.steps.map((s, i) => (
        <div key={s.id} className="card step" data-step={s.id}>
          <div className="card-head">
            <b>{s.id}</b>
            <div className="spacer" />
            {bp.steps.length > 1 && <button className="btn small" onClick={() => removeStep(i)} aria-label={`${F.removeStep} ${s.id}`} title={F.removeStep}><IconTrash size={14} /></button>}
          </div>
          <div className="row">
            <label className="field"><span>{F.specialist}</span>
              <select value={s.specialist} onChange={(e) => setStep(i, { specialist: e.target.value })}>
                {specialists.map((sp) => <option key={sp.id} value={sp.id}>{sp.name}</option>)}
              </select>
            </label>
            <label className="field"><span>{F.role}</span>
              <select value={s.role} onChange={(e) => setStep(i, { role: e.target.value as BlueprintStep["role"] })}>
                <option value="research">{F.research}</option><option value="execute">{F.execute}</option>
              </select>
            </label>
          </div>
          <label className="field"><span>{F.instruction}</span>
            <textarea rows={2} value={s.instruction} onChange={(e) => setStep(i, { instruction: e.target.value })} />
          </label>
          <label className="field"><span>{F.files}</span>
            <input value={s.deliverables.join(", ")} placeholder="informe.md"
              onChange={(e) => setStep(i, { deliverables: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
          </label>
          {i > 0 && (
            <div className="field"><span>{F.dependsOn}</span>
              <div className="deps">
                {bp.steps.slice(0, i).map((prev) => (
                  <label key={prev.id} className="check">
                    <input type="checkbox" checked={s.depends_on.includes(prev.id)}
                      onChange={(e) => setStep(i, { depends_on: e.target.checked ? [...s.depends_on, prev.id] : s.depends_on.filter((d) => d !== prev.id) })} /> {prev.id}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
      <div><button className="btn" onClick={addStep}><IconPlus size={14} /> {F.addStep}</button></div>
      <label className="field"><span>{F.criteria}</span><textarea rows={3} value={criteria} onChange={(e) => setCriteria(e.target.value)} /></label>
      {lines(criteria).length === 0 && <p className="small muted">{F.noCriteria}</p>}
    </>
  );
}

/** Forge: a task becomes a blueprint the user approves, then runs as a chat with the team's trace and a report. */
export function Forge({ specialists, providers, projectId, initialTask = "", initialBlueprint, title, intro, onBack, onRun, onClose }: {
  specialists: Specialist[];
  providers: ProviderInfo[];
  projectId?: string;
  initialTask?: string;
  initialBlueprint?: Blueprint; // a plan made elsewhere (a Creator template): Forge opens on its review
  title?: string;
  intro?: string;
  onBack?: () => void; // "Back" from the review, when the plan was not drafted here
  onRun: (task: string, blueprint: Blueprint, providerId: string | null) => void;
  onClose: () => void;
}) {
  const [task, setTask] = useState(initialTask);
  const [providerId, setProviderId] = useState<string | null>(null);
  const [bp, setBp] = useState<Blueprint | null>(initialBlueprint ?? null);
  const [requirements, setRequirements] = useState(initialBlueprint?.requirements.join("\n") ?? "");
  const [criteria, setCriteria] = useState(initialBlueprint?.criteria.join("\n") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [two, setTwo] = useState(false); // Parallel Prototypes: off unless the user ticks it
  const [protoOpen, setProtoOpen] = useState<"new" | "list" | null>(null);
  const [pending, setPending] = useState(0); // earlier prototype runs still waiting for the user's choice

  useEffect(() => {
    if (initialBlueprint) return;
    api.get<{ runs: ProtoRun[] }>(`/api/forge/prototypes${projectId ? `?project_id=${projectId}` : ""}`)
      .then((r) => setPending(r.runs.filter((x) => x.status === "built" || x.status === "interrupted").length))
      .catch(() => setPending(0)); // the list is a convenience
  }, [initialBlueprint, projectId, protoOpen]);

  const draft = async (e: React.FormEvent) => {
    e.preventDefault();
    if (two) { setProtoOpen("new"); return; }
    setBusy(true); setError("");
    try {
      const drafted = await api.post<Blueprint>("/api/forge/blueprint", { task, provider_id: providerId, project_id: projectId ?? null });
      setBp(drafted);
      setRequirements(drafted.requirements.join("\n"));
      setCriteria(drafted.criteria.join("\n"));
    } catch (e2) { setError(String((e2 as Error).message)); }
    setBusy(false);
  };

  const approve = () => {
    if (!bp) return;
    onRun(task, { ...bp, requirements: lines(requirements), criteria: lines(criteria) }, providerId);
  };

  const executor = (
    <label className="field inline"><span>{F.executor}</span>
      <select value={providerId ?? ""} onChange={(e) => setProviderId(e.target.value || null)} aria-label={F.executor}>
        <option value="">{F.defaultProvider}</option>
        {providers.map((p) => <option key={p.id} value={p.id}>{p.name}{p.local ? ` · ${F.local}` : ""}{p.paid ? ` · ${F.paid}` : ""}</option>)}
      </select>
    </label>
  );

  if (protoOpen) {
    return <Prototypes specialists={specialists} projectId={projectId} initialTask={protoOpen === "new" ? task : ""}
      initialProvider={providerId} onBack={() => setProtoOpen(null)} onClose={onClose} />;
  }

  return (
    <section className="forge" aria-label={title ?? F.title}>
      <div className="forge-head">
        <h1>{title ?? F.title}</h1>
        <div className="spacer" />
        <button className="btn" onClick={onClose}>{F.close}</button>
      </div>
      <p className="muted">{intro ?? F.intro}</p>
      {!bp ? (
        <form className="form" onSubmit={draft}>
          <label className="field"><span>{F.task}</span>
            <textarea rows={4} required value={task} onChange={(e) => setTask(e.target.value)} placeholder={F.taskPlaceholder} />
          </label>
          {executor}
          <div className="field-group">
            <label className="check" title={t.proto.toggleHint}>
              <input type="checkbox" checked={two} onChange={(e) => setTwo(e.target.checked)} data-proto-toggle /> {t.proto.toggle}
            </label>
            {two && <p className="small muted">{t.proto.toggleHint} {t.proto.multiplier}.</p>}
          </div>
          {error && <div className="error-box" role="alert">{error}</div>}
          <div className="row end">
            {pending > 0 && <button type="button" className="btn" onClick={() => setProtoOpen("list")} data-proto-pending>{t.proto.pending} ({pending})</button>}
            <div className="spacer" />
            <button className="btn primary" type="submit" disabled={busy || !task.trim()}>{busy ? F.drafting : two ? t.proto.draft : F.draft}</button>
          </div>
        </form>
      ) : (
        <div className="form blueprint">
          {bp.method === "fallback" && <div className="notice">{F.fallback}{bp.note ? ` (${bp.note})` : ""}</div>}
          <BlueprintEditor bp={bp} onChange={setBp} requirements={requirements} setRequirements={setRequirements}
            criteria={criteria} setCriteria={setCriteria} specialists={specialists} />
          {executor}
          {error && <div className="error-box" role="alert">{error}</div>}
          <div className="row end"><div className="spacer" />
            <button className="btn" onClick={() => (onBack ? onBack() : setBp(null))}>{F.back}</button>
            <button className="btn primary" onClick={approve} disabled={bp.steps.some((s) => !s.instruction.trim())}>{F.run}</button>
          </div>
        </div>
      )}
    </section>
  );
}
