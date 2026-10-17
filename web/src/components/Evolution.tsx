import { useEffect, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { CheckResult, Checks, EvolutionItem, EvolutionOverview, RouterSplit, Settings } from "../types";
import { IconCopy } from "./Icons";

export const E = lang === "es"
  ? {
      intro: "SPIKE aprende de cómo lo usas, en tu ordenador: tus correcciones, cuando reintentas con otro especialista y los fallos. Nada cambia lo que hace sin pasar antes una comprobación local, y todo se puede deshacer. Los chats temporales no se registran.",
      enabled: "Aprender de mi uso", autoRouter: "Ajustar el enrutador solo cuando reintento con otro especialista (si pasa la comprobación)",
      router: "Enrutador", builtIn: "Integrado", learned: "Aprendido", first: "Porcentaje de preguntas en que el primer especialista elegido es el correcto.", test: "prueba protegida", dev: "desarrollo", questions: "preguntas",
      learnNow: "Aprender ahora", rollback: "Volver a la anterior", words: "Palabras aprendidas", routes: "Reintentos con otro especialista",
      routed: "el enrutador eligió", picked: "elegiste", ignore: "Ignorar", use: "Usar", ignored: "ignorado",
      accepted: "Aceptado: en uso", rejected: "No se usa", noRoutes: "Cuando reintentes una respuesta con otro especialista, aparecerá aquí.",
      candidates: "Preguntas de evaluación propuestas", candidatesHint: "Salen de tus correcciones y de los fallos arreglados. Revisa la pregunta y las comprobaciones (texto que la respuesta debe contener o no) antes de aceptarla.",
      include: "Debe contener (separado por comas)", exclude: "No debe contener", accept: "Aceptar", reject: "Rechazar", save: "Guardar",
      tooClose: "Demasiado parecida a una pregunta de", acceptedN: "aceptadas", exportJsonl: "Exportar (.jsonl)", noCandidates: "No hay propuestas pendientes.",
      fromCorrection: "de una corrección", fromFailure: "de un fallo arreglado", reference: "Lo que dijiste",
      failures: "Fallos", failuresHint: "Errores de una respuesta o de una herramienta. Anota la causa y el arreglo; cuando lo compruebes, SPIKE propone una pregunta para vigilar que no vuelva.",
      cause: "Causa", fix: "Arreglo", verified: "Arreglo comprobado", copyIssue: "Copiar como issue", copied: "Copiado: no incluye tu pregunta",
      noFailures: "Ningún fallo registrado.", open: "abierto", fixed: "arreglado",
      check: "Comprobación", checkHint: "La misma que `spike evolve check`: enrutador frente a su prueba protegida, catálogo, skills y adaptadores instalados.",
      replay: "Repetir también las preguntas aceptadas (usa el modelo)", runCheck: "Comprobar ahora", checking: "Comprobando…",
      pass: "pasa", fail: "falla", noChecks: "sin comprobación de texto: solo que responda sin error",
      versions: "Versiones", noVersions: "Aún no hay versiones: se usan el enrutador integrado y los adaptadores que instalaste.",
      inUse: "en uso",
      names: { router: "Enrutador", catalog: "Catálogo", skills: "Skills", adapters: "Adaptadores", replay: "Preguntas aceptadas" } as Record<string, string>,
      catalogOk: (n: number) => `${n} especialistas; todas sus herramientas existen`, skillsOk: (n: number) => `${n} skills válidas`,
      adaptersOk: (n: number) => n ? `${n} adaptadores instalados coinciden con los aceptados` : "ningún adaptador versionado",
      replayOk: (p: number, n: number) => n ? `${p} de ${n} pasan sus comprobaciones` : "no hay preguntas aceptadas",
    }
  : {
      intro: "SPIKE learns from how you use it, on your computer: your corrections, when you retry with another specialist, and failures. Nothing changes what it does without passing a local check first, and everything can be undone. Temporary chats are never recorded.",
      enabled: "Learn from my use", autoRouter: "Tune the router by itself when I retry with another specialist (if it passes the check)",
      router: "Router", builtIn: "Built-in", learned: "Learned", first: "Share of questions where the first specialist picked is the right one.", test: "protected test", dev: "dev", questions: "questions",
      learnNow: "Learn now", rollback: "Go back to the previous one", words: "Learned words", routes: "Retries with another specialist",
      routed: "the router picked", picked: "you picked", ignore: "Ignore", use: "Use", ignored: "ignored",
      accepted: "Accepted: in use", rejected: "Not used", noRoutes: "When you retry an answer with another specialist, it shows up here.",
      candidates: "Proposed eval questions", candidatesHint: "They come from your corrections and fixed failures. Check the question and its checks (text the answer must or must not contain) before accepting it.",
      include: "Must contain (comma-separated)", exclude: "Must not contain", accept: "Accept", reject: "Reject", save: "Save",
      tooClose: "Too close to a question in the", acceptedN: "accepted", exportJsonl: "Export (.jsonl)", noCandidates: "Nothing to review.",
      fromCorrection: "from a correction", fromFailure: "from a fixed failure", reference: "What you said",
      failures: "Failures", failuresHint: "Errors of an answer or a tool. Write down the cause and the fix; once you verify it, SPIKE proposes a question that checks it stays fixed.",
      cause: "Cause", fix: "Fix", verified: "Fix verified", copyIssue: "Copy as issue", copied: "Copied: your question is not included",
      noFailures: "No failures recorded.", open: "open", fixed: "fixed",
      check: "Check", checkHint: "The same as `spike evolve check`: router against its protected test, catalog, skills and installed adapters.",
      replay: "Also answer the accepted questions again (runs the model)", runCheck: "Check now", checking: "Checking…",
      pass: "pass", fail: "fail", noChecks: "no text checks: only that it answers without error",
      versions: "Versions", noVersions: "No versions yet: the built-in router and the adapters you installed are used.",
      inUse: "in use",
      names: { router: "Router", catalog: "Catalog", skills: "Skills", adapters: "Adapters", replay: "Accepted questions" } as Record<string, string>,
      catalogOk: (n: number) => `${n} specialists; every tool they list exists`, skillsOk: (n: number) => `${n} skills valid`,
      adaptersOk: (n: number) => n ? `${n} installed adapters match the accepted files` : "no versioned adapters",
      replayOk: (p: number, n: number) => n ? `${p} of ${n} pass their checks` : "no accepted questions",
    };

/** A check's result in the reader's language; a failure keeps the technical detail SPIKE reported. */
function summary(c: CheckResult): string {
  if (!c.ok && c.name !== "replay") return c.detail;
  switch (c.name) {
    case "router": {
      const s = c.current ?? c.built_in;
      return s ? `${c.current ? E.learned : E.builtIn} · ${splits(s)}` : c.detail;
    }
    case "catalog": return E.catalogOk(c.count ?? 0);
    case "skills": return E.skillsOk(c.count ?? 0);
    case "adapters": return E.adaptersOk(c.count ?? 0);
    case "replay": return E.replayOk(c.passed ?? 0, c.total ?? 0);
    default: return c.detail;
  }
}

const pct = (v: number | null | undefined) => v == null ? "–" : `${Math.round(v * 100)}%`;
const split = (s?: RouterSplit) => s ? `${pct(s.primary)} (${s.n} ${E.questions})` : "–";
const splits = (s: Record<string, RouterSplit>) => `${E.test}: ${split(s.test)} · ${E.dev}: ${split(s.dev)}`;
const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const date = (ts: number) => new Date(ts * 1000).toLocaleString();

function Candidate({ item, run }: { item: EvolutionItem; run: (fn: () => Promise<unknown>) => void }) {
  const [question, setQuestion] = useState<string>(item.question);
  const checks: Checks = item.checks ?? {};
  const [include, setInclude] = useState((checks.include ?? []).join(", "));
  const [exclude, setExclude] = useState((checks.exclude ?? []).join(", "));
  const patch = (status?: string) => run(() => api.patch(`/api/evolution/items/${item.id}`, {
    question, checks: { include: list(include), exclude: list(exclude) }, ...(status ? { status } : {}),
  }));
  return (
    <div className="card evo-item" data-testid="evo-candidate">
      <div className="card-head">
        <span className="badge">{item.from === "failure" ? E.fromFailure : E.fromCorrection}</span>
        {item.specialist && <span className="badge">{item.specialist}</span>}
        <span className="small muted">{date(item.created)}</span>
      </div>
      <textarea rows={2} aria-label="question" value={question} onChange={(e) => setQuestion(e.target.value)} />
      {item.reference && <p className="small muted">{E.reference}: {item.reference}</p>}
      <div className="row">
        <label className="field grow"><span>{E.include}</span><input aria-label={E.include} value={include} onChange={(e) => setInclude(e.target.value)} /></label>
        <label className="field grow"><span>{E.exclude}</span><input aria-label={E.exclude} value={exclude} onChange={(e) => setExclude(e.target.value)} /></label>
      </div>
      {item.contamination && <div className="error-box small">{E.tooClose} {item.contamination.with} ({Math.round(item.contamination.score * 100)}%): «{item.contamination.text}»</div>}
      <div className="row">
        <button className="btn primary small" onClick={() => patch("accepted")}>{E.accept}</button>
        <button className="btn small" onClick={() => patch()}>{E.save}</button>
        <button className="btn small" onClick={() => run(() => api.patch(`/api/evolution/items/${item.id}`, { status: "rejected" }))}>{E.reject}</button>
      </div>
    </div>
  );
}

function Failure({ item, run }: { item: EvolutionItem; run: (fn: () => Promise<unknown>) => void }) {
  const [cause, setCause] = useState<string>(item.cause ?? "");
  const [fix, setFix] = useState<string>(item.fix ?? "");
  const [copied, setCopied] = useState(false);
  const save = (extra: Record<string, unknown> = {}) => run(() => api.patch(`/api/evolution/items/${item.id}`, { cause, fix, ...extra }));
  const copy = async () => {
    const res = await fetch(`/api/evolution/items/${item.id}/issue`);
    const md = await res.text();
    try { await navigator.clipboard.writeText(md); } catch { /* the text stays readable below */ }
    setCopied(true);
  };
  return (
    <div className="card evo-item" data-testid="evo-failure">
      <div className="card-head">
        <span className={`badge ${item.status === "fixed" ? "ok" : "warn"}`}>{item.status === "fixed" ? E.fixed : E.open}</span>
        <span className="badge">{item.what === "tool" ? item.tool : "run"}</span>
        <span className="small muted">{date(item.created)}</span>
      </div>
      <code className="small evo-error">{item.error}</code>
      <div className="row">
        <label className="field grow"><span>{E.cause}</span><textarea rows={2} value={cause} onChange={(e) => setCause(e.target.value)} onBlur={() => cause !== (item.cause ?? "") && save()} /></label>
        <label className="field grow"><span>{E.fix}</span><textarea rows={2} value={fix} onChange={(e) => setFix(e.target.value)} onBlur={() => fix !== (item.fix ?? "") && save()} /></label>
      </div>
      <div className="row">
        <label className="check"><input type="checkbox" checked={!!item.verified} onChange={(e) => save({ verified: e.target.checked })} />{E.verified}</label>
        <div className="spacer" />
        <button className="btn small" onClick={copy}><IconCopy size={13} /> {E.copyIssue}</button>
        {copied && <span className="small muted">{E.copied}</span>}
      </div>
    </div>
  );
}

export function Evolution({ settings, save }: { settings: Settings; save: (p: Partial<Settings>) => void }) {
  const [overview, setOverview] = useState<EvolutionOverview | null>(null);
  const [items, setItems] = useState<EvolutionItem[]>([]);
  const [checks, setChecks] = useState<CheckResult[] | null>(null);
  const [replay, setReplay] = useState(false);
  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const evo = settings.evolution ?? { enabled: true, auto_router: true };

  const load = async () => {
    try {
      setOverview(await api.get<EvolutionOverview>("/api/evolution"));
      setItems(await api.get<EvolutionItem[]>("/api/evolution/items"));
    } catch (e) { setErr(String((e as Error).message)); }
  };
  useEffect(() => { load(); }, []);
  const run = async (fn: () => Promise<unknown>) => {
    setErr(""); setNote("");
    try { await fn(); } catch (e) { setErr(String((e as Error).message)); }
    load();
  };
  const of = (kind: string, status?: string) => items.filter((i) => i.kind === kind && (!status || i.status === status));
  const router = overview?.router;
  const active = router?.active;
  const overlay: Record<string, Record<string, number>> = active?.data.overlay ?? {};
  const rollbackable = [...new Set((overview?.versions ?? []).filter((v) => v.active).map((v) => v.component))];

  return (
    <div className="form evolution">
      <p className="small muted">{E.intro}</p>
      <label className="check"><input type="checkbox" checked={evo.enabled} onChange={(e) => save({ evolution: { ...evo, enabled: e.target.checked } })} />{E.enabled}</label>
      <label className="check"><input type="checkbox" checked={evo.auto_router} disabled={!evo.enabled} onChange={(e) => save({ evolution: { ...evo, auto_router: e.target.checked } })} />{E.autoRouter}</label>
      {note && <div className="flash-box">{note}</div>}
      {err && <div className="error-box" role="alert">{err}</div>}

      <h3>{E.router}</h3>
      {router && (
        <div className="small" data-testid="evo-router">
          <div className="muted">{E.first}</div>
          <div>{E.builtIn} · {splits(router.built_in)}</div>
          {active && router.current && <div><b>{E.learned} v{active.id}</b> · {splits(router.current)}</div>}
          {active && <div className="muted">{E.words}: {Object.entries(overlay).map(([sid, words]) => `${sid}: ${Object.keys(words).join(", ")}`).join(" · ")}</div>}
        </div>
      )}
      <div className="row">
        <button className="btn small" disabled={!of("route").length} onClick={() => run(async () => {
          const r = await api.post<{ accepted: boolean; reasons: string[] }>("/api/evolution/router/learn");
          setNote(r.accepted ? E.accepted : `${E.rejected}: ${r.reasons.join("; ")}`);
        })}>{E.learnNow}</button>
        {active && <button className="btn small" onClick={() => run(() => api.post("/api/evolution/rollback", { component: "router" }))}>{E.rollback}</button>}
      </div>
      <h4>{E.routes}</h4>
      {of("route").length === 0 && <p className="small muted">{E.noRoutes}</p>}
      {of("route").map((r) => (
        <div key={r.id} className="evo-route small" data-testid="evo-route">
          <span className="grow">«{r.query}» · {E.routed} <b>{(r.routed ?? []).join(", ")}</b>, {E.picked} <b>{r.specialist}</b>{r.status === "ignored" ? ` · ${E.ignored}` : ""}</span>
          <button className="btn small" onClick={() => run(() => api.patch(`/api/evolution/items/${r.id}`, { status: r.status === "ignored" ? "new" : "ignored" }))}>{r.status === "ignored" ? E.use : E.ignore}</button>
        </div>
      ))}

      <h3>{E.candidates}</h3>
      <p className="small muted">{E.candidatesHint}</p>
      {of("candidate", "proposed").length === 0 && <p className="small muted">{E.noCandidates}</p>}
      {of("candidate", "proposed").map((c) => <Candidate key={c.id} item={c} run={run} />)}
      <div className="row">
        <span className="small"><b>{of("candidate", "accepted").length}</b> {E.acceptedN}</span>
        {of("candidate", "accepted").length > 0 && <a className="btn small" href="/api/evolution/candidates.jsonl" download>{E.exportJsonl}</a>}
      </div>

      <h3>{E.failures}</h3>
      <p className="small muted">{E.failuresHint}</p>
      {of("failure").length === 0 && <p className="small muted">{E.noFailures}</p>}
      {of("failure").slice(0, 30).map((f) => <Failure key={f.id} item={f} run={run} />)}

      <h3>{E.check}</h3>
      <p className="small muted">{E.checkHint}</p>
      <label className="check"><input type="checkbox" checked={replay} onChange={(e) => setReplay(e.target.checked)} />{E.replay}</label>
      <div className="row">
        <button className="btn primary small" disabled={checking} onClick={async () => {
          setChecking(true); setErr("");
          try { setChecks((await api.post<{ checks: CheckResult[] }>("/api/evolution/check", { replay })).checks); }
          catch (e) { setErr(String((e as Error).message)); }
          setChecking(false);
        }}>{checking ? E.checking : E.runCheck}</button>
      </div>
      {checks && (
        <ul className="evo-checks small" data-testid="evo-checks">
          {checks.map((c) => (
            <li key={c.name} className={c.ok ? "ok" : "fail"}>
              <b>{c.ok ? "✓" : "✗"} {E.names[c.name] ?? c.name}</b> {summary(c)}
              {c.results?.map((r) => (
                <div key={r.id} className="muted">{r.passed ? E.pass : E.fail}: {r.question}{r.problems.length ? ` (${r.problems.join("; ")})` : ""}{r.checked ? "" : ` · ${E.noChecks}`}</div>
              ))}
            </li>
          ))}
        </ul>
      )}

      <h3>{E.versions}</h3>
      {(overview?.versions.length ?? 0) === 0 && <p className="small muted">{E.noVersions}</p>}
      {rollbackable.filter((c) => c !== "router").map((c) => (
        <button key={c} className="btn small" onClick={() => run(() => api.post("/api/evolution/rollback", { component: c }))}>{E.rollback}: {c}</button>
      ))}
      <ul className="evo-versions small">
        {overview?.versions.slice(0, 40).map((v) => (
          <li key={v.id}><b>{v.component}</b> v{v.id} · {date(v.created)}{v.active ? ` · ${E.inUse}` : ""} · <span className="muted">{v.reason}</span></li>
        ))}
      </ul>
    </div>
  );
}
