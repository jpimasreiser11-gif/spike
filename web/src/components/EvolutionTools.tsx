import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { Conversation, PersonalOverview, StrategyLearned, StrategyOverview } from "../types";

const S = lang === "es"
  ? {
      title: "Estrategia de herramientas",
      hint: "SPIKE anota, con tus chats reales, si cada herramienta y cada skill funcionó para cada tipo de tarea (el especialista que respondió y la intención de la pregunta). Cuenta como éxito si la herramienta respondió sin error, no reintentaste ni deshiciste el paso y no corregiste la respuesta. Se usa solo para desempatar entre skills con la misma puntuación del enrutador, con al menos 5 usos de cada una, y solo si la comprobación de Evolución pasa con esos datos aplicados. Las herramientas se anotan y se muestran aquí, pero no cambian lo que SPIKE elige. Los datos se quedan en tu ordenador; los chats temporales no se anotan.",
      auto: "Actualizar el desempate solo cada 20 usos nuevos (si pasa la comprobación)",
      empty: "Aún no hay usos anotados: aparecerán cuando SPIKE use una herramienta o una skill en uno de tus chats.",
      kind: "Tipo", name: "Nombre", task: "Tarea", uses: "Usos", success: "Éxitos", retried: "Reintentos", undone: "Deshechos",
      corrected: "Corregidos", samples: "Muestras", tool: "herramienta", skill: "skill", enough: "suficientes", few: (n: number) => `faltan ${n}`,
      learn: "Aprender el desempate ahora", learning: "Aprendiendo…", rollback: "Volver al anterior", reset: "Olvidar los usos anotados",
      sure: (n: number) => `¿Borrar ${n} usos anotados? SPIKE vuelve al orden del enrutador; las versiones del desempate se quedan en el historial.`,
      yes: "Sí, olvidar", cancel: "Cancelar", forgot: (n: number) => `Olvidados ${n} usos.`,
      inUse: (id: number) => `Desempate en uso: v${id}`, notInUse: "Ningún desempate en uso: se aplica el orden del enrutador.",
      accepted: "Aceptado: en uso", unchanged: "Sin cambios: ya estaba en uso", rejected: "No se usa", total: (n: number) => `${n} usos anotados`,
    }
  : {
      title: "Tool strategy",
      hint: "SPIKE records, from your real chats, whether each tool and skill worked for each task type (the specialist that answered and the intent of the question). It counts as a success if the tool returned without an error, you did not retry or undo the step, and you did not correct the answer. It is used only to break ties between skills the router scores the same, with at least 5 uses of each, and only if the Evolution check passes with those counts applied. Tools are recorded and shown here, but they do not change what SPIKE picks. The data stays on your computer; temporary chats are not recorded.",
      auto: "Refresh the tie-break by itself every 20 new uses (if it passes the check)",
      empty: "No uses recorded yet: they appear when SPIKE uses a tool or a skill in one of your chats.",
      kind: "Type", name: "Name", task: "Task", uses: "Uses", success: "Successes", retried: "Retried", undone: "Undone",
      corrected: "Corrected", samples: "Samples", tool: "tool", skill: "skill", enough: "enough", few: (n: number) => `${n} short`,
      learn: "Learn the tie-break now", learning: "Learning…", rollback: "Go back to the previous one", reset: "Forget the recorded uses",
      sure: (n: number) => `Delete ${n} recorded uses? SPIKE goes back to the router's order; the tie-break versions stay in the history.`,
      yes: "Yes, forget", cancel: "Cancel", forgot: (n: number) => `Forgot ${n} uses.`,
      inUse: (id: number) => `Tie-break in use: v${id}`, notInUse: "No tie-break in use: the router's order applies.",
      accepted: "Accepted: in use", unchanged: "No change: already in use", rejected: "Not used", total: (n: number) => `${n} uses recorded`,
    };

const pct = (good: number, n: number) => (n ? `${Math.round((100 * good) / n)}%` : "–");

/** EV3: the counts behind the skill router's tie-break, with learn, reset and rollback. Tools are shown, not used. */
export function ToolStrategy({ auto, disabled, setAuto, version }: {
  auto: boolean; disabled: boolean; setAuto: (on: boolean) => void; version: number;
}) {
  const [overview, setOverview] = useState<StrategyOverview | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const load = () => { api.get<StrategyOverview>("/api/evolution/strategy").then(setOverview).catch((e) => setErr(String((e as Error).message))); };
  useEffect(load, [version]);
  const act = async (fn: () => Promise<string>) => {
    setErr(""); setNote(""); setBusy(true);
    try { setNote(await fn()); } catch (e) { setErr(String((e as Error).message)); }
    setBusy(false); setAsking(false); load();
  };
  const rows = overview?.rows ?? [];
  return (
    <>
      <h3>{S.title}</h3>
      <p className="small muted">{S.hint}</p>
      <label className="check"><input type="checkbox" checked={auto} disabled={disabled} onChange={(e) => setAuto(e.target.checked)} />{S.auto}</label>
      {err && <div className="error-box" role="alert">{err}</div>}
      <div data-testid="evo-strategy">
        {rows.length === 0 ? <p className="small muted">{S.empty}</p> : (
          <div className="table-wrap">
            <table className="calls" aria-label={S.title}>
              <thead><tr><th>{S.kind}</th><th>{S.name}</th><th>{S.task}</th><th>{S.uses}</th><th>{S.success}</th><th>{S.retried}</th><th>{S.undone}</th><th>{S.corrected}</th><th>{S.samples}</th></tr></thead>
              <tbody>
                {rows.slice(0, 60).map((r) => (
                  <tr key={`${r.kind}:${r.name}:${r.task_type}`} data-testid="evo-strategy-row">
                    <td>{r.kind === "tool" ? S.tool : S.skill}</td><td>{r.name}</td><td>{r.task_type}</td><td>{r.n}</td>
                    <td>{r.good} · {pct(r.good, r.n)}</td><td>{r.retried}</td><td>{r.undone}</td><td>{r.corrected}</td>
                    <td>{r.enough ? S.enough : S.few((overview?.min_samples ?? 5) - r.n)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="small muted">{S.total(overview?.uses ?? 0)} · {overview?.active ? S.inUse(overview.active.id) : S.notInUse}</p>
      {note && <div className="flash-box" role="status">{note}</div>}
      <div className="row">
        <button className="btn small" disabled={busy || rows.every((r) => r.kind !== "skill")} onClick={() => act(async () => {
          const r = await api.post<StrategyLearned>("/api/evolution/strategy/learn");
          return r.accepted ? (r.unchanged ? S.unchanged : S.accepted) : `${S.rejected}: ${r.reasons.join("; ")}`;
        })}>{busy ? S.learning : S.learn}</button>
        {overview?.active && <button className="btn small" disabled={busy} onClick={() => act(async () => {
          await api.post("/api/evolution/rollback", { component: "strategy" }); return "";
        })}>{S.rollback}</button>}
        {!asking && <button className="btn small" disabled={busy || (overview?.uses ?? 0) === 0} onClick={() => setAsking(true)}>{S.reset}</button>}
      </div>
      {asking && (
        <div className="confirm-box" role="alertdialog" aria-label={S.reset}>
          <p className="small">{S.sure(overview?.uses ?? 0)}</p>
          <div className="row">
            <button className="btn primary small" disabled={busy} onClick={() => act(async () => S.forgot((await api.del<{ deleted: number }>("/api/evolution/strategy")).deleted))}>{S.yes}</button>
            <button className="btn small" onClick={() => setAsking(false)}>{S.cancel}</button>
          </div>
        </div>
      )}
    </>
  );
}

const P = lang === "es"
  ? {
      title: "Adaptador personal",
      hint: "Un adaptador LoRA entrenado solo con tus correcciones aprobadas y los chats que marques aquí, para que el asistente general (Spike Core) conteste más como tú pides. Desactivado por defecto. Solo se usan respuestas del modelo local de SPIKE; puedes excluir cualquier ejemplo. Se entrena en un Mac con Apple silicon, con el mismo proceso, la misma protección de memoria y el mismo criterio de aceptación que los especialistas, y solo se activa si el conocimiento general no baja más de 1,5 puntos. Todo se queda en tu ordenador.",
      enable: "Activar el adaptador personal (desactivado por defecto)",
      unavailable: "No disponible en este ordenador",
      counts: (c: { used: number; needed: number; corrections: number; chat_answers: number; excluded: number; duplicates: number }) =>
        `Para entrenar: ${c.used} ejemplos (se necesitan al menos ${c.needed}) · correcciones aprobadas: ${c.corrections} · respuestas de chats marcados: ${c.chat_answers} · excluidos: ${c.excluded} · repetidos: ${c.duplicates}`,
      needConsent: (n: number) => `Tienes ${n} correcciones aprobadas, pero no se usan mientras «Usar mis correcciones para reentrenar» esté desactivado.`,
      notUsed: (a: number, b: number) => `Respuestas de chats marcados que no se usan: ${a} de otros modelos o servicios o con error, ${b} que tu siguiente mensaje corrigió.`,
      missing: (n: number) => `${n} chats marcados ya no existen.`,
      marked: "Chats marcados", noMarked: "Ningún chat marcado.", unmark: "Quitar", pick: "Elige un chat para marcarlo", mark: "Marcar este chat",
      examples: "Ejemplos", noExamples: "Aún no hay ejemplos: marca un chat o aprueba correcciones.", use: "Usar", repeated: "repetido",
      fromCorrection: "corrección", fromChat: "chat", more: (n: number) => `…y ${n} más`,
      run: "El entrenamiento no se lanza desde la aplicación: tarda horas y usa casi toda la memoria. Ejecútalo en una terminal de tu Mac:",
      active: (id: number) => `Adaptador personal en uso: v${id}`, none: "Aún no hay un adaptador personal aceptado.", rollback: "Volver al anterior",
    }
  : {
      title: "Personal adapter",
      hint: "A LoRA adapter trained only on your approved corrections and the chats you mark here, so the general assistant (Spike Core) answers more the way you ask. Off by default. Only answers from SPIKE's local model are used; you can exclude any example. It trains on a Mac with Apple silicon, with the same process, memory guard and acceptance rule as the specialists, and it is only activated if general knowledge does not drop by more than 1.5 points. Everything stays on your computer.",
      enable: "Turn on the personal adapter (off by default)",
      unavailable: "Not available on this computer",
      counts: (c: { used: number; needed: number; corrections: number; chat_answers: number; excluded: number; duplicates: number }) =>
        `To train on: ${c.used} examples (at least ${c.needed} needed) · approved corrections: ${c.corrections} · marked-chat answers: ${c.chat_answers} · excluded: ${c.excluded} · repeated: ${c.duplicates}`,
      needConsent: (n: number) => `You have ${n} approved corrections, but they are not used while “Use my corrections to retrain” is off.`,
      notUsed: (a: number, b: number) => `Marked-chat answers not used: ${a} from other models or services or with errors, ${b} that your next message corrected.`,
      missing: (n: number) => `${n} marked chats no longer exist.`,
      marked: "Marked chats", noMarked: "No chat marked.", unmark: "Remove", pick: "Choose a chat to mark it", mark: "Mark this chat",
      examples: "Examples", noExamples: "No examples yet: mark a chat or approve corrections.", use: "Use", repeated: "repeated",
      fromCorrection: "correction", fromChat: "chat", more: (n: number) => `…and ${n} more`,
      run: "Training is not started from the app: it takes hours and uses most of the memory. Run it in a terminal on your Mac:",
      active: (id: number) => `Personal adapter in use: v${id}`, none: "No accepted personal adapter yet.", rollback: "Go back to the previous one",
    };

const clip = (s: string, n = 110) => (s.length > n ? `${s.slice(0, n)}…` : s);

/** EV6: what the personal adapter would be trained on, with marks and exclusions; training itself is a command. */
export function PersonalAdapter({ enabled, setEnabled, version }: { enabled: boolean; setEnabled: (on: boolean) => void; version: number }) {
  const [overview, setOverview] = useState<PersonalOverview | null>(null);
  const [chats, setChats] = useState<Conversation[]>([]);
  const [pick, setPick] = useState("");
  const [err, setErr] = useState("");
  const load = () => {
    api.get<PersonalOverview>("/api/evolution/personal").then(setOverview).catch((e) => setErr(String((e as Error).message)));
    if (enabled) api.get<Conversation[]>("/api/conversations").then(setChats).catch(() => setChats([]));
  };
  useEffect(load, [version, enabled]);
  const run = async (fn: () => Promise<unknown>) => {
    setErr("");
    try { await fn(); } catch (e) { setErr(String((e as Error).message)); }
    load();
  };
  const o = overview;
  const markedIds = new Set((o?.marked ?? []).map((m) => m.conversation));
  const free = chats.filter((c) => !markedIds.has(c.id));
  return (
    <>
      <h3>{P.title}</h3>
      <p className="small muted">{P.hint}</p>
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />{P.enable}</label>
      {err && <div className="error-box" role="alert">{err}</div>}
      {enabled && o && (
        <div data-testid="evo-personal">
          {!o.available && <div className="warn-box small" role="status" data-testid="evo-personal-unavailable"><b>{P.unavailable}.</b> {o.reason}</div>}
          <p className="small" data-testid="evo-personal-counts">{P.counts(o.counts)}</p>
          {o.counts.corrections_need_consent && o.counts.approved_corrections > 0 && <p className="small muted">{P.needConsent(o.counts.approved_corrections)}</p>}
          {(o.chats.answers_not_used.origin > 0 || o.chats.answers_not_used.corrected > 0) && <p className="small muted">{P.notUsed(o.chats.answers_not_used.origin, o.chats.answers_not_used.corrected)}</p>}
          {o.chats.missing > 0 && <p className="small muted">{P.missing(o.chats.missing)}</p>}

          <h4>{P.marked}</h4>
          {o.marked.length === 0 && <p className="small muted">{P.noMarked}</p>}
          {o.marked.map((m) => (
            <div key={m.id} className="evo-route small" data-testid="evo-personal-marked">
              <span className="grow">{m.title || m.conversation}</span>
              <button className="btn small" onClick={() => run(() => api.del(`/api/evolution/personal/marks/${m.conversation}`))}>{P.unmark}</button>
            </div>
          ))}
          <div className="row">
            <select aria-label={P.pick} value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">{P.pick}</option>
              {free.slice(0, 100).map((c) => <option key={c.id} value={c.id}>{clip(c.title || c.id, 70)}</option>)}
            </select>
            <button className="btn small" disabled={!pick} onClick={() => run(async () => { await api.post("/api/evolution/personal/marks", { conversation: pick }); setPick(""); })}>{P.mark}</button>
          </div>

          <h4>{P.examples}</h4>
          {o.entries.length === 0 && <p className="small muted">{P.noExamples}</p>}
          {o.entries.slice(0, 50).map((e) => (
            <div key={e.id} className="evo-route small" data-testid="evo-personal-entry">
              <label className="check grow">
                <input type="checkbox" aria-label={`${P.use}: ${clip(e.question, 60)}`} checked={!e.excluded && !e.duplicate} disabled={e.duplicate}
                  onChange={(ev) => run(() => api.put("/api/evolution/personal/exclusions", { ref: e.id, excluded: !ev.target.checked }))} />
                <span><span className="badge">{e.source === "correction" ? P.fromCorrection : P.fromChat}</span>{e.duplicate && <span className="badge warn">{P.repeated}</span>} «{clip(e.question)}» → {clip(e.answer)}</span>
              </label>
            </div>
          ))}
          {o.entries.length > 50 && <p className="small muted">{P.more(o.entries.length - 50)}</p>}

          <p className="small">{P.run}</p>
          <pre className="small"><code>{o.command}</code></pre>
          <p className="small muted">{o.active ? P.active(o.active.id) : P.none}</p>
          {o.active && <button className="btn small" onClick={() => run(() => api.post("/api/evolution/rollback", { component: "adapter:personal" }))}>{P.rollback}</button>}
        </div>
      )}
    </>
  );
}
