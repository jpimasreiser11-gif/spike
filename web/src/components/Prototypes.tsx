import { useEffect, useRef, useState } from "react";
import { ApiError, api, streamPost } from "../api";
import { t } from "../i18n";
import { type ProtoLive, applyProtoEvent, comparisonOf, emptyLive, leaderText, rowCells } from "../parallel";
import { fill } from "../trust";
import type { Blueprint, PermissionState, ProtoLabel, ProtoResult, ProtoRun, Specialist } from "../types";
import { Permission } from "./AssistantMessage";
import { BlueprintEditor, lines } from "./Forge";

type Stage = "list" | "draft" | "review" | "building" | "result";
type Draft = { label: ProtoLabel; bp: Blueprint; requirements: string; criteria: string };

/** One approach's column of results: what it built, the tests it fails and each check, all from the real run. */
function ApproachCard({ a, leader }: { a: ProtoResult; leader: boolean }) {
  return (
    <div className={`card proto-approach ${leader ? "leader" : ""}`} data-approach={a.label}>
      <div className="card-head">
        <b>{t.proto.approach} {a.label.toUpperCase()}</b>
        {leader && <span className="badge ok">★</span>}
        <span className="muted small">{a.goal}</span>
      </div>
      <div className="small"><span className="muted">{t.proto.branch}:</span> <code>{a.branch}</code></div>
      {a.error && <div className="error-box small-pre">{t.proto.failedBuild}: {a.error}</div>}
      {a.tests && !a.tests.ran && <p className="small warn-text">{t.proto.rowTests}: {t.proto.notRun}{a.tests.reason ? ` (${a.tests.reason})` : ""}</p>}
      {a.tests && a.tests.failed.length > 0 && (
        <div className="small"><b>{t.proto.failedTests}</b>
          <ul className="proto-list">{a.tests.failed.map((f) => <li key={f} className="bad"><code>{f}</code></li>)}</ul>
        </div>
      )}
      {a.checks && a.checks.items.length > 0 && (
        <div className="small"><b>{t.proto.checks}</b>
          <ul className="proto-list">
            {a.checks.items.map((c, i) => (
              <li key={i} className={c.ok ? "ok-text" : "bad"}>{c.ok ? "✓" : "✕"} {c.name}{c.note && <span className="muted"> · {c.note}</span>}</li>
            ))}
          </ul>
        </div>
      )}
      {a.files && a.files.paths.length > 0 && <div className="small muted">{a.files.paths.join(", ")}</div>}
    </div>
  );
}

/** Parallel Prototypes (Forge): two approaches to one task, each built on its own git branch and compared by the same
 * tests. The user picks one; nothing is merged before they approve it. */
export function Prototypes({ specialists, projectId, initialTask = "", initialProvider = null, onBack, onClose }: {
  specialists: Specialist[];
  projectId?: string;
  initialTask?: string; // drafts the two plans at once; empty: the list of earlier runs
  initialProvider?: string | null;
  onBack: () => void;
  onClose: () => void;
}) {
  const [stage, setStage] = useState<Stage>(initialTask ? "draft" : "list");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [unitTest, setUnitTest] = useState("");
  const [snippet, setSnippet] = useState("");
  const [live, setLive] = useState<ProtoLive>(emptyLive());
  const [current, setCurrent] = useState<ProtoRun | null>(null);
  const [runs, setRuns] = useState<ProtoRun[]>([]);
  const [git, setGit] = useState(true);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<ProtoLabel | null>(null);
  const [busy, setBusy] = useState(false);
  const liveRef = useRef<ProtoLive>(emptyLive());
  const abort = useRef<AbortController | null>(null);
  const query = projectId ? `?project_id=${projectId}` : "";

  const loadRuns = () =>
    api.get<{ git: boolean; runs: ProtoRun[] }>(`/api/forge/prototypes${query}`)
      .then((r) => { setGit(r.git); setRuns(r.runs); })
      .catch((e) => setError(String((e as Error).message)));

  useEffect(() => { loadRuns(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [projectId]);
  useEffect(() => () => abort.current?.abort(), []);

  const draftPlans = async () => {
    setBusy(true); setError("");
    try {
      const r = await api.post<{ approaches: { label: ProtoLabel; blueprint: Blueprint }[] }>("/api/forge/prototypes/blueprints",
        { task: initialTask, provider_id: initialProvider, project_id: projectId ?? null });
      setDrafts(r.approaches.map((a) => ({ label: a.label, bp: a.blueprint, requirements: a.blueprint.requirements.join("\n"),
        criteria: a.blueprint.criteria.join("\n") })));
      setStage("review");
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  };
  useEffect(() => { if (initialTask) draftPlans(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const setDraft = (label: ProtoLabel, patch: Partial<Draft>) => setDrafts((ds) => ds.map((d) => (d.label === label ? { ...d, ...patch } : d)));

  const build = async () => {
    const tests = {
      files: unitTest.trim() ? { "tests/test_acceptance.py": unitTest } : {},
      checks: snippet.trim() ? [{ kind: "python", name: "", code: snippet }] : [],
    };
    const body = { task: initialTask, tests, provider_id: initialProvider, project_id: projectId ?? null,
      blueprints: drafts.map((d) => ({ ...d.bp, requirements: lines(d.requirements), criteria: lines(d.criteria) })) };
    liveRef.current = emptyLive();
    setLive(liveRef.current);
    setError(""); setConfirm(null); setStage("building");
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamPost("/api/forge/prototypes", body, (ev) => {
        liveRef.current = applyProtoEvent(liveRef.current, ev);
        setLive(liveRef.current);
      }, controller.signal);
      if (liveRef.current.run) { setCurrent(liveRef.current.run); setStage("result"); }
      else setStage("review");
    } catch (e) {
      const aborted = (e as Error).name === "AbortError";
      if (!aborted) setError(e instanceof ApiError ? e.message : String((e as Error).message));
      if (liveRef.current.run) { setCurrent(liveRef.current.run); setStage("result"); } // it was saved: it can be discarded or reopened
      else setStage("review");
    } finally {
      abort.current = null;
      loadRuns();
    }
  };

  const onPermission = (id: string, status: PermissionState["status"]) => {
    liveRef.current = { ...liveRef.current, permissions: liveRef.current.permissions.map((p) => (p.id === id ? { ...p, status } : p)) };
    setLive(liveRef.current);
  };

  const act = async (what: "merge" | "discard", choice?: ProtoLabel) => {
    if (!current) return;
    setBusy(true); setError("");
    try {
      const r = await api.post<{ run: ProtoRun }>(`/api/forge/prototypes/${current.id}/${what}`, what === "merge" ? { choice, approve: true } : {});
      setCurrent(r.run);
      setConfirm(null);
      loadRuns();
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  };

  const header = (
    <>
      <div className="forge-head">
        <h1>{t.proto.title}</h1>
        <div className="spacer" />
        <button className="btn" onClick={onClose}>{t.proto.close}</button>
      </div>
      {!git && <div className="error-box" role="alert">{t.proto.gitMissing}</div>}
    </>
  );

  if (stage === "list") {
    return (
      <section className="forge proto" aria-label={t.proto.title} data-proto-stage="list">
        {header}
        <h2 className="proto-h">{t.proto.pending}</h2>
        {runs.length === 0 && <p className="muted small">—</p>}
        {runs.map((r) => (
          <div key={r.id} className="card" data-proto-run={r.id}>
            <div className="card-head"><b>{r.task.slice(0, 90)}</b><span className="badge">{t.proto.status[r.status] ?? r.status}</span>
              <div className="spacer" />
              <button className="btn small" onClick={() => { setCurrent(r); setStage("result"); }}>{t.proto.open}</button></div>
          </div>
        ))}
        {error && <div className="error-box" role="alert">{error}</div>}
        <div className="row end"><div className="spacer" /><button className="btn" onClick={onBack}>{t.proto.back}</button></div>
      </section>
    );
  }

  if (stage === "draft") {
    return (
      <section className="forge proto" aria-label={t.proto.title} data-proto-stage="draft">
        {header}
        {error ? <div className="error-box" role="alert">{error}</div> : <p className="muted">{t.proto.drafting}</p>}
        <div className="row end"><div className="spacer" />
          <button className="btn" onClick={onBack}>{t.proto.back}</button>
          {error && <button className="btn primary" onClick={draftPlans} disabled={busy}>{t.proto.draft}</button>}
        </div>
      </section>
    );
  }

  if (stage === "review") {
    return (
      <section className="forge proto" aria-label={t.proto.title} data-proto-stage="review">
        {header}
        <p className="muted">{t.proto.intro}</p>
        {drafts.map((d) => (
          <div key={d.label} className="card proto-draft" data-draft={d.label}>
            <h2 className="proto-h">{t.proto.approach} {d.label.toUpperCase()}</h2>
            <BlueprintEditor bp={d.bp} onChange={(bp) => setDraft(d.label, { bp })} requirements={d.requirements}
              setRequirements={(requirements) => setDraft(d.label, { requirements })} criteria={d.criteria}
              setCriteria={(criteria) => setDraft(d.label, { criteria })} specialists={specialists} />
          </div>
        ))}
        <div className="card">
          <h2 className="proto-h">{t.proto.tests}</h2>
          <p className="small muted">{t.proto.testsIntro}</p>
          <label className="field"><span>{t.proto.unittestLabel}</span>
            <textarea rows={5} spellCheck={false} value={unitTest} onChange={(e) => setUnitTest(e.target.value)} placeholder={t.proto.unittestPlaceholder} />
          </label>
          <label className="field"><span>{t.proto.snippetLabel}</span>
            <textarea rows={3} spellCheck={false} value={snippet} onChange={(e) => setSnippet(e.target.value)} placeholder={t.proto.snippetPlaceholder} />
          </label>
        </div>
        <p className="small muted">{t.proto.plan}</p>
        <p className="small"><b data-proto-multiplier>{t.proto.multiplier}</b></p>
        {error && <div className="error-box" role="alert">{error}</div>}
        <div className="row end"><div className="spacer" />
          <button className="btn" onClick={onBack}>{t.proto.back}</button>
          <button className="btn primary" onClick={build} // every step has an instruction and each plan saves at least one file
            disabled={!git || drafts.some((d) => d.bp.steps.some((s) => !s.instruction.trim()) || !d.bp.steps.some((s) => s.deliverables.length > 0))}>
            {t.proto.approve}
          </button>
        </div>
      </section>
    );
  }

  if (stage === "building") {
    return (
      <section className="forge proto" aria-label={t.proto.title} data-proto-stage="building">
        {header}
        <div className="proto-cols">
          {(["a", "b"] as ProtoLabel[]).map((l) => (
            <div key={l} className="card" data-phase={live.phase[l]} data-building={l}>
              <b>{t.proto.approach} {l.toUpperCase()}</b>
              <span className="small muted">{t.proto.phase[live.phase[l]]}{live.steps[l] ? ` · ${live.steps[l]} ${t.proto.steps}` : ""}</span>
            </div>
          ))}
        </div>
        {live.permissions.map((p) => <Permission key={p.id} p={p} onDecided={onPermission} />)}
        {error && <div className="error-box" role="alert">{error}</div>}
        <div className="row end"><div className="spacer" />
          <button className="btn danger" onClick={() => abort.current?.abort()}>{t.proto.cancel}</button></div>
      </section>
    );
  }

  const run = current;
  const comparison = run ? comparisonOf(run) : null;
  return (
    <section className="forge proto" aria-label={t.proto.title} data-proto-stage="result">
      {header}
      {run && (
        <>
          <p className="muted small">{run.task} · <code>{run.base.branch}</code> · <span className="badge" data-proto-status={run.status}>{t.proto.status[run.status] ?? run.status}</span></p>
          {run.dirty > 0 && run.status === "built" && <p className="small warn-text">{fill(t.proto.dirty, { n: run.dirty })}</p>}
          {comparison && (
            <div className="card" data-proto-compare>
              <h2 className="proto-h">{t.proto.compare}</h2>
              <table className="proto-table">
                <thead><tr><th scope="col" />{comparison.rows.map((r) => <th key={r.label} scope="col" className={comparison.leader === r.label ? "leader" : ""}>{t.proto.approach} {r.label.toUpperCase()}</th>)}</tr></thead>
                <tbody>
                  {(["tests", "checks", "files", "lines", "time"] as const).map((k) => (
                    <tr key={k}>
                      <th scope="row">{{ tests: t.proto.rowTests, checks: t.proto.rowChecks, files: t.proto.rowFiles, lines: t.proto.rowLines, time: t.proto.rowTime }[k]}</th>
                      {comparison.rows.map((r) => <td key={r.label} data-cell={`${k}-${r.label}`} className={comparison.leader === r.label ? "leader" : ""}>{rowCells(r)[k]}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small" data-proto-leader>{leaderText(comparison)}</p>
              <p className="small muted">{t.proto.numbersOnly}</p>
            </div>
          )}
          <div className="proto-cols">
            {run.approaches.map((a) => <ApproachCard key={a.label} a={a} leader={comparison?.leader === a.label} />)}
          </div>
          {run.merged && <div className="notice ok-text" data-proto-merged>{fill(t.proto.merged, { into: run.merged.into, commit: run.merged.commit.slice(0, 8), kept: run.merged.kept_branch })}</div>}
          {run.status === "discarded" && <div className="notice" data-proto-discarded>{t.proto.discarded}</div>}
          {error && <div className="error-box" role="alert">{error}</div>}
          {confirm && run.status === "built" && (
            <div className="card" role="alertdialog" aria-label={fill(t.proto.confirm, { label: confirm.toUpperCase(), into: run.base.branch })} data-proto-confirm>
              <b>{fill(t.proto.confirm, { label: confirm.toUpperCase(), into: run.base.branch })}</b>
              <p className="small">{fill(t.proto.confirmBody, { branch: run.approaches.find((a) => a.label === confirm)?.branch ?? "", into: run.base.branch })}</p>
              <div className="row">
                <button className="btn primary" disabled={busy} onClick={() => act("merge", confirm)}>{t.proto.approveMerge}</button>
                <button className="btn" disabled={busy} onClick={() => setConfirm(null)}>{t.proto.cancel}</button>
              </div>
            </div>
          )}
          <div className="row end">
            {(run.status === "built" || run.status === "interrupted" || run.status === "building") && (
              <button className="btn danger" disabled={busy} onClick={() => act("discard")} data-proto-discard>{t.proto.discard}</button>
            )}
            <div className="spacer" />
            {run.status === "built" && run.approaches.map((a) => (
              <button key={a.label} className="btn primary" disabled={busy || a.status === "failed"} onClick={() => setConfirm(a.label)} data-proto-use={a.label}>
                {fill(t.proto.use, { label: a.label.toUpperCase() })}
              </button>
            ))}
            <button className="btn" onClick={() => { setCurrent(null); setStage("list"); loadRuns(); }}>{t.proto.back}</button>
          </div>
        </>
      )}
    </section>
  );
}
