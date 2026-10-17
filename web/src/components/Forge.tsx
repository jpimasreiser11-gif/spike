import { useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { Blueprint, BlueprintStep, ProviderInfo, Specialist } from "../types";
import { IconPlus, IconTrash } from "./Icons";

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

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);
const nextId = (steps: BlueprintStep[]) => {
  let n = steps.length + 1;
  while (steps.some((s) => s.id === `t${n}`)) n += 1;
  return `t${n}`;
};

/** Forge: a task becomes a blueprint the user approves, then runs as a chat with the team's trace and a report. */
export function Forge({ specialists, providers, projectId, initialTask = "", onRun, onClose }: {
  specialists: Specialist[];
  providers: ProviderInfo[];
  projectId?: string;
  initialTask?: string;
  onRun: (task: string, blueprint: Blueprint, providerId: string | null) => void;
  onClose: () => void;
}) {
  const [task, setTask] = useState(initialTask);
  const [providerId, setProviderId] = useState<string | null>(null);
  const [bp, setBp] = useState<Blueprint | null>(null);
  const [requirements, setRequirements] = useState("");
  const [criteria, setCriteria] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const draft = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const drafted = await api.post<Blueprint>("/api/forge/blueprint", { task, provider_id: providerId, project_id: projectId ?? null });
      setBp(drafted);
      setRequirements(drafted.requirements.join("\n"));
      setCriteria(drafted.criteria.join("\n"));
    } catch (e2) { setError(String((e2 as Error).message)); }
    setBusy(false);
  };

  const setStep = (i: number, patch: Partial<BlueprintStep>) =>
    setBp((b) => b && { ...b, steps: b.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const removeStep = (i: number) =>
    setBp((b) => {
      if (!b) return b;
      const gone = b.steps[i].id;
      return { ...b, steps: b.steps.filter((_, j) => j !== i).map((s) => ({ ...s, depends_on: s.depends_on.filter((d) => d !== gone) })) };
    });
  const addStep = () =>
    setBp((b) => b && { ...b, steps: [...b.steps, { id: nextId(b.steps), specialist: "core", role: "execute", instruction: "", depends_on: [], deliverables: [] }] });

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

  return (
    <section className="forge" aria-label={F.title}>
      <div className="forge-head">
        <h1>{F.title}</h1>
        <div className="spacer" />
        <button className="btn" onClick={onClose}>{F.close}</button>
      </div>
      <p className="muted">{F.intro}</p>
      {!bp ? (
        <form className="form" onSubmit={draft}>
          <label className="field"><span>{F.task}</span>
            <textarea rows={4} required value={task} onChange={(e) => setTask(e.target.value)} placeholder={F.taskPlaceholder} />
          </label>
          {executor}
          {error && <div className="error-box" role="alert">{error}</div>}
          <div className="row end"><div className="spacer" />
            <button className="btn primary" type="submit" disabled={busy || !task.trim()}>{busy ? F.drafting : F.draft}</button>
          </div>
        </form>
      ) : (
        <div className="form blueprint">
          {bp.method === "fallback" && <div className="notice">{F.fallback}{bp.note ? ` (${bp.note})` : ""}</div>}
          <label className="field"><span>{F.goal}</span><input value={bp.goal} onChange={(e) => setBp({ ...bp, goal: e.target.value })} /></label>
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
          {executor}
          {error && <div className="error-box" role="alert">{error}</div>}
          <div className="row end"><div className="spacer" />
            <button className="btn" onClick={() => setBp(null)}>{F.back}</button>
            <button className="btn primary" onClick={approve} disabled={bp.steps.some((s) => !s.instruction.trim())}>{F.run}</button>
          </div>
        </div>
      )}
    </section>
  );
}
