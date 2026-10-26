import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { Project, StudyTopic, StudyTopics } from "../types";
import { IconTrash } from "./Icons";

const S = lang === "es"
  ? {
      intro: "Lo que estudias, cuánto lo dominas y cuándo repasarlo. Los repasos se programan con el método SM-2 (repetición espaciada): cuanto mejor lo recuerdas, más tarde vuelve a tocar. El especialista de Educación ve en su prompt los temas pendientes y puede registrar un repaso. Todo se guarda en tu ordenador.",
      scope: "Temas de", global: "Global", name: "Tema que estudias", notes: "Nota (opcional)", level: "Nivel inicial", add: "Añadir tema",
      empty: "Todavía no hay temas.", due: (n: number) => n === 1 ? "1 tema toca repasar ahora" : `${n} temas tocan repasar ahora`, none: "Nada pendiente de repaso.",
      mastery: "Dominio", dueNow: "Toca repasar", overdue: (d: number) => d === 1 ? "desde hace 1 día" : `desde hace ${d} días`,
      next: (d: number) => d <= 0 ? "en menos de un día" : d === 1 ? "en 1 día" : `en ${d} días`, last: "Último repaso", never: "sin repasar",
      grade: "¿Cómo te fue?", again: "Otra vez", hard: "Difícil", good: "Bien", easy: "Fácil", remove: "Eliminar",
      stats: (t: StudyTopic) => `${t.reviews} ${t.reviews === 1 ? "repaso" : "repasos"} · ${t.lapses} ${t.lapses === 1 ? "olvido" : "olvidos"} · facilidad ${t.ease}`,
    }
  : {
      intro: "What you are studying, how well you know it and when to review it. Reviews are scheduled with the SM-2 method (spaced repetition): the better you recall a topic, the later it comes back. The Education specialist sees the due topics in its prompt and can record a review. Everything is stored on your computer.",
      scope: "Topics of", global: "Global", name: "Topic you study", notes: "Note (optional)", level: "Starting level", add: "Add topic",
      empty: "No topics yet.", due: (n: number) => n === 1 ? "1 topic is due for review now" : `${n} topics are due for review now`, none: "Nothing is due for review.",
      mastery: "Mastery", dueNow: "Due", overdue: (d: number) => d === 1 ? "for 1 day" : `for ${d} days`,
      next: (d: number) => d <= 0 ? "in under a day" : d === 1 ? "in 1 day" : `in ${d} days`, last: "Last review", never: "not reviewed yet",
      grade: "How did it go?", again: "Again", hard: "Hard", good: "Good", easy: "Easy", remove: "Delete",
      stats: (t: StudyTopic) => `${t.reviews} ${t.reviews === 1 ? "review" : "reviews"} · ${t.lapses} ${t.lapses === 1 ? "lapse" : "lapses"} · ease ${t.ease}`,
    };

const GRADES = [[1, "again"], [3, "hard"], [4, "good"], [5, "easy"]] as const;
const DAY = 86400;

function Meter({ level }: { level: number }) {
  return (
    <span className="mastery" role="img" aria-label={`${S.mastery} ${level}/5`} title={`${S.mastery} ${level}/5`}>
      {[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= level ? "on" : ""} />)}
    </span>
  );
}

export function Tutor() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [scope, setScope] = useState("global");
  const [data, setData] = useState<StudyTopics | null>(null);
  const [draft, setDraft] = useState({ name: "", notes: "", mastery: 0 });
  const [err, setErr] = useState("");

  const load = async () => {
    try { setData(await api.get<StudyTopics>(`/api/tutor?scope=${encodeURIComponent(scope)}`)); } catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { api.get<Project[]>("/api/projects").then(setProjects).catch(() => {}); }, []);
  useEffect(() => { load(); }, [scope]);
  const run = async (fn: () => Promise<unknown>) => {
    setErr("");
    try { await fn(); } catch (e) { setErr((e as Error).message); }
    load();
  };

  return (
    <div className="form" data-testid="tutor">
      <p className="small muted">{S.intro}</p>
      <div className="row end">
        <label className="field inline"><span>{S.scope}</span>
          <select aria-label={S.scope} value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="global">{S.global}</option>
            {projects.map((p) => <option key={p.id} value={`project:${p.id}`}>{p.name}</option>)}
          </select>
        </label>
        {data && <b className={data.due ? "tutor-due" : "muted small"} data-testid="tutor-due">{data.due ? S.due(data.due) : S.none}</b>}
      </div>

      <div className="memory-add">
        <div className="row">
          <label className="field"><span>{S.name}</span><input aria-label={S.name} value={draft.name} maxLength={200} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label className="field"><span>{S.notes}</span><input aria-label={S.notes} value={draft.notes} maxLength={1000} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
          <label className="field narrow"><span>{S.level}</span>
            <select aria-label={S.level} value={draft.mastery} onChange={(e) => setDraft({ ...draft, mastery: Number(e.target.value) })}>
              {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} / 5</option>)}
            </select>
          </label>
        </div>
        <div className="row">
          <button className="btn primary" disabled={!draft.name.trim()}
            onClick={() => run(async () => { await api.post("/api/tutor", { ...draft, scope }); setDraft({ name: "", notes: "", mastery: 0 }); })}>{S.add}</button>
        </div>
      </div>
      {err && <div className="error-box" role="alert">{err}</div>}

      {data && data.topics.length === 0 && <p className="small muted">{S.empty}</p>}
      {data?.topics.map((t) => {
        const days = Math.round((t.next_review - data.now) / DAY);
        return (
          <div key={t.id} className={`card tutor-topic${t.due ? " due" : ""}`} data-testid="tutor-topic" data-due={t.due}>
            <div className="card-head">
              <b>{t.name}</b>
              <Meter level={t.mastery} />
              {t.due
                ? <span className="badge warn">{S.dueNow}{t.overdue_days > 0 ? ` · ${S.overdue(t.overdue_days)}` : ""}</span>
                : <span className="badge">{S.next(days)}</span>}
              <div className="spacer" />
              <button className="icon-btn" aria-label={`${S.remove}: ${t.name}`} onClick={() => run(() => api.del(`/api/tutor/${t.id}`))}><IconTrash size={14} /></button>
            </div>
            {t.notes && <p className="small muted">{t.notes}</p>}
            <div className="small muted">
              {S.last}: {t.last_review ? new Date(t.last_review * 1000).toLocaleDateString() : S.never} · {S.stats(t)}
            </div>
            <div className="row end">
              <span className="small">{S.grade}</span>
              {GRADES.map(([grade, key]) => (
                <button key={grade} className="btn small" data-grade={grade} onClick={() => run(() => api.post(`/api/tutor/${t.id}/review`, { grade }))}>{S[key]}</button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
