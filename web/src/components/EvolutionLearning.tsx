import { useEffect, useState } from "react";
import { api, streamPost } from "../api";
import { lang } from "../i18n";
import type { EvolutionItem, LearnedPrompt, PromptComparison } from "../types";
import { Markdown } from "./Markdown";

const L = lang === "es"
  ? {
      prompts: "Instrucciones aprendidas", promptsHint: "SPIKE prueba, para un especialista, añadir o quitar las reglas que guardaste de tus correcciones (y las que escribas aquí) y activar o apagar sus skills. Se queda con un cambio solo si aprueba más preguntas aceptadas de ese especialista, no suspende ninguna que antes aprobaba y lo repite en una segunda pasada. Usa el modelo: puede tardar.",
      questions: "preguntas con comprobación", needMore: "Acepta al menos 3 preguntas de este especialista para optimizarlo.",
      inUse: "En uso", none: "Sin cambios aprendidos", optimize: "Optimizar", optimizing: "Probando", stop: "Parar",
      tryLines: "Otras instrucciones que probar (una por línea)", rollback: "Volver a la anterior", ideas: "ideas para probar",
      done: (a: number, b: number, n: number) => `Aceptado: ${a} → ${b} de ${n} preguntas.`, notDone: "Sin cambios",
      answers: "respuestas", skill: "skill",
      saveCandidate: "Guardar como candidata", candidate: "Candidata", waiting: "sin comparar", within: "dentro de la tolerancia", blockedBadge: "bloqueada",
      candidateHint: "Una candidata no cambia nada hasta que la actives: SPIKE la compara con la versión en uso con tus preguntas de evaluación (las de tus correcciones y fallos arreglados) y la bloquea si saca más de 2 puntos menos. El resultado queda en el historial de versiones.",
      candidateSaved: "Candidata guardada: aún no se usa.", activate: "Comparar y activar", activating: "Comparando…",
      activated: "Activada: ", notActivated: "Bloqueada, no cambió nada: ",
      verdict: (r: PromptComparison) => r.evaluated && r.baseline && r.candidate
        ? `${r.candidate.passed}/${r.questions} preguntas frente a ${r.baseline.passed}/${r.questions} con la versión en uso (${(-(r.drop_points ?? 0) + 0).toFixed(1)} puntos; tolerancia -${r.tolerance_points})`
        : `solo ${r.questions} preguntas de evaluación aceptadas con comprobación; acepta al menos 3 para poder comparar`,
      training: "Reentrenar con mis correcciones", trainingOpt: "Usar mis correcciones para reentrenar (desactivado por defecto)",
      trainingHint: "Cada corrección guardada puede convertirse en un ejemplo: tu pregunta, la respuesta tras corregir y la que corregiste. Solo se usan respuestas del modelo local de SPIKE (nunca de servicios externos ni de otros modelos), que pasen las comprobaciones, y solo las que apruebes. Todo se queda en tu ordenador; el archivo lo usa `training/prepare.py --corrections`.",
      review: "Buscar ejemplos nuevos", approve: "Aprobar", reject: "Rechazar", approved: "aprobados", skipped: "No utilizables",
      chosen: "Respuesta tras corregir", rejected: "Respuesta corregida", noExamples: "No hay ejemplos pendientes.",
      download: "Descargar ejemplos (.jsonl)", pairs: "Pares para DPO (.jsonl)",
    }
  : {
      prompts: "Learned instructions", promptsHint: "For one specialist, SPIKE tries adding or dropping the rules you saved from your corrections (and any you type here) and turning its skills on or off. It keeps a change only if it passes more of that specialist's accepted questions, fails none it passed before, and does so again on a second run. It runs the model: it can take a while.",
      questions: "questions with checks", needMore: "Accept at least 3 questions for this specialist to optimise it.",
      inUse: "In use", none: "Nothing learned", optimize: "Optimise", optimizing: "Trying", stop: "Stop",
      tryLines: "Other instructions to try (one per line)", rollback: "Go back to the previous one", ideas: "ideas to try",
      done: (a: number, b: number, n: number) => `Accepted: ${a} → ${b} of ${n} questions.`, notDone: "No change",
      answers: "answers", skill: "skill",
      saveCandidate: "Save as candidate", candidate: "Candidate", waiting: "not compared", within: "within the tolerance", blockedBadge: "blocked",
      candidateHint: "A candidate changes nothing until you activate it: SPIKE compares it with the version in use on your eval questions (from your corrections and fixed failures) and blocks it if it scores more than 2 points lower. The result is kept in the version history.",
      candidateSaved: "Candidate saved: not in use yet.", activate: "Compare and activate", activating: "Comparing…",
      activated: "Activated: ", notActivated: "Blocked, nothing changed: ",
      verdict: (r: PromptComparison) => r.evaluated && r.baseline && r.candidate
        ? `${r.candidate.passed}/${r.questions} questions against ${r.baseline.passed}/${r.questions} for the version in use (${(-(r.drop_points ?? 0) + 0).toFixed(1)} points; tolerance -${r.tolerance_points})`
        : `only ${r.questions} accepted eval questions with checks; accept at least 3 to compare`,
      training: "Retrain with my corrections", trainingOpt: "Use my corrections to retrain (off by default)",
      trainingHint: "Each saved correction can become an example: your question, the answer after the correction and the one you corrected. Only answers from SPIKE's local model are used (never from external services or other models), only if they pass the checks, and only the ones you approve. Everything stays on your computer; `training/prepare.py --corrections` reads the file.",
      review: "Look for new examples", approve: "Approve", reject: "Reject", approved: "approved", skipped: "Not usable",
      chosen: "Answer after the correction", rejected: "Corrected answer", noExamples: "No examples to review.",
      download: "Download examples (.jsonl)", pairs: "Pairs for DPO (.jsonl)",
    };

type Activation = PromptComparison & { activated: boolean; version: number };
type Report = { accepted: boolean; reasons: string[]; questions: number; baseline?: { passed: number }; confirmed?: { passed: number }; changes?: string[] };

function Specialist({ p, reload }: { p: LearnedPrompt; reload: () => void }) {
  const [lines, setLines] = useState("");
  const [busy, setBusy] = useState<AbortController | null>(null);
  const [step, setStep] = useState("");
  const [result, setResult] = useState("");
  const [comparing, setComparing] = useState(false);
  const learned = p.active?.data ?? {};
  const typed = () => lines.split("\n").map((x) => x.trim()).filter(Boolean);
  const saveCandidate = async () => {
    setResult("");
    try {
      await api.post(`/api/evolution/prompts/${p.specialist}/candidate`, { instructions: typed() });
      setLines(""); setResult(L.candidateSaved);
    } catch (e) { setResult(String((e as Error).message)); }
    reload();
  };
  const activate = async (version: number) => {
    setComparing(true); setResult("");
    try {
      const r = await api.post<Activation>(`/api/evolution/prompts/${p.specialist}/activate`, { version });
      setResult(r.activated ? `${L.activated}${L.verdict(r)}` : `${L.notActivated}${r.reason ?? L.verdict(r)}`);
    } catch (e) { setResult(String((e as Error).message)); }
    setComparing(false); reload();
  };
  const blocked = p.candidate?.report?.status === "blocked";
  const regression: PromptComparison | undefined = p.candidate?.report?.regression;
  const optimize = async () => {
    const controller = new AbortController();
    setBusy(controller); setResult(""); setStep("");
    try {
      await streamPost(`/api/evolution/prompts/${p.specialist}/optimize`, { instructions: typed() }, (ev) => {
        const e = ev as unknown as { type: string; label?: string; calls?: number; report?: Report; message?: string };
        if (e.type === "try") setStep(`${e.label} · ${e.calls} ${L.answers}`);
        if (e.type === "error") setResult(e.message ?? "");
        if (e.type === "done" && e.report) {
          const r = e.report;
          setResult(r.accepted ? L.done(r.baseline?.passed ?? 0, r.confirmed?.passed ?? 0, r.questions) : `${L.notDone}: ${r.reasons.join("; ")}`);
        }
      }, controller.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setResult(String((e as Error).message));
    }
    setBusy(null); setStep(""); reload();
  };
  return (
    <div className="card evo-item" data-testid={`evo-prompt-${p.specialist}`}>
      <div className="card-head"><b>{p.name}</b><span className="small muted">{p.questions} {L.questions} · {p.ideas.length} {L.ideas}</span></div>
      {p.active ? (
        <div className="small"><b>{L.inUse} v{p.active.id}:</b>
          <ul>
            {(learned.instructions ?? []).map((x: string) => <li key={x}>{x}</li>)}
            {Object.entries(learned.skills ?? {}).map(([k, v]) => <li key={k}>{L.skill} {k}: {String(v)}</li>)}
          </ul>
        </div>
      ) : <p className="small muted">{L.none}</p>}
      {p.questions < 3 ? <p className="small muted">{L.needMore}</p> : (
        <>
          <label className="field"><span>{L.tryLines}</span><textarea rows={2} value={lines} onChange={(e) => setLines(e.target.value)} /></label>
          <div className="row">
            {busy ? <button className="btn small" onClick={() => busy.abort()}>{L.stop}</button>
              : <button className="btn primary small" onClick={optimize}>{L.optimize}</button>}
            <button className="btn small" disabled={!!busy || !lines.trim()} onClick={saveCandidate}>{L.saveCandidate}</button>
            {p.active && !busy && <button className="btn small" onClick={async () => { await api.post("/api/evolution/rollback", { component: `prompt:${p.specialist}` }); reload(); }}>{L.rollback}</button>}
            {step && <span className="small muted">{L.optimizing}: {step}</span>}
          </div>
        </>
      )}
      {p.candidate && (
        <div className="small" data-testid={`evo-candidate-${p.specialist}`}>
          <b>{L.candidate} v{p.candidate.id}</b> <span className={`badge ${blocked ? "warn" : ""}`}>{blocked ? L.blockedBadge : regression?.ok ? L.within : L.waiting}</span>
          <ul>{(p.candidate.report?.changes ?? []).map((x: string) => <li key={x}>{x}</li>)}</ul>
          {regression && <p className="muted">{L.verdict(regression)}</p>}
          <p className="muted">{L.candidateHint}</p>
          {p.questions >= 3 && <button className="btn primary small" disabled={comparing || !!busy} onClick={() => activate(p.candidate!.id)}>{comparing ? L.activating : L.activate}</button>}
        </div>
      )}
      {result && <p className="small" role="status">{result}</p>}
    </div>
  );
}

/** Evolution level 2: specialists whose prompt can be tuned against the user's accepted questions. */
export function LearnedPrompts({ version }: { version: number }) {
  const [prompts, setPrompts] = useState<LearnedPrompt[]>([]);
  const load = () => { api.get<LearnedPrompt[]>("/api/evolution/prompts").then(setPrompts).catch(() => setPrompts([])); };
  useEffect(load, [version]);
  const shown = prompts.filter((p) => p.questions > 0 || p.active || p.candidate);
  return (
    <>
      <h3>{L.prompts}</h3>
      <p className="small muted">{L.promptsHint}</p>
      {shown.length === 0 && <p className="small muted">{L.needMore}</p>}
      {shown.map((p) => <Specialist key={p.specialist} p={p} reload={load} />)}
    </>
  );
}

/** Evolution level 3: corrections as training examples, only with the user's consent and approval. */
export function TrainingExamples({ enabled, items, setEnabled, run }: {
  enabled: boolean; items: EvolutionItem[]; setEnabled: (on: boolean) => void; run: (fn: () => Promise<unknown>) => void;
}) {
  const of = (status: string) => items.filter((i) => i.kind === "example" && i.status === status);
  return (
    <>
      <h3>{L.training}</h3>
      <p className="small muted">{L.trainingHint}</p>
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />{L.trainingOpt}</label>
      {enabled && (
        <>
          <div className="row">
            <button className="btn small" onClick={() => run(() => api.post("/api/evolution/examples/build"))}>{L.review}</button>
            <span className="small"><b>{of("approved").length}</b> {L.approved}</span>
            {of("approved").length > 0 && <a className="btn small" href="/api/evolution/training.jsonl" download>{L.download}</a>}
            {of("approved").length > 0 && <a className="btn small" href="/api/evolution/preferences.jsonl" download>{L.pairs}</a>}
          </div>
          {of("proposed").length === 0 && <p className="small muted">{L.noExamples}</p>}
          {of("proposed").map((x) => (
            <div key={x.id} className="card evo-item" data-testid="evo-example">
              <div className="card-head">{x.specialist && <span className="badge">{x.specialist}</span>}<span className="small">«{x.question}»</span></div>
              <div className="small"><b>{L.chosen}</b><Markdown text={x.chosen} /></div>
              <div className="small muted"><b>{L.rejected}</b><Markdown text={x.rejected} /></div>
              <div className="row">
                <button className="btn primary small" onClick={() => run(() => api.patch(`/api/evolution/items/${x.id}`, { status: "approved" }))}>{L.approve}</button>
                <button className="btn small" onClick={() => run(() => api.patch(`/api/evolution/items/${x.id}`, { status: "rejected" }))}>{L.reject}</button>
              </div>
            </div>
          ))}
          {of("skipped").length > 0 && (
            <details className="small"><summary>{L.skipped} ({of("skipped").length})</summary>
              <ul>{of("skipped").map((x) => <li key={x.id}>«{x.question}»: {x.reason}</li>)}</ul>
            </details>
          )}
        </>
      )}
    </>
  );
}
