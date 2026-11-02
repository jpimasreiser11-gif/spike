import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fill } from "../explorer";
import { t } from "../i18n";
import type { ViewQuestion, ViewReplay, ViewScript, ViewStatus, ViewStep } from "../types";
import { type ScriptFile, ignoredList, optionLabel, questionText, replayActive, stepLabel, stepRow } from "../viewRecorder";
import "./ViewRecorder.css";

const V = () => t.viewRecorder;

function Steps({ steps, onSecret }: { steps: ViewStep[]; onSecret?: (n: number) => void }) {
  if (steps.length === 0) return <p className="small muted">{V().noSteps}</p>;
  return (
    <ol className="view-steps">
      {steps.map((s) => (
        <li key={s.n} className={s.status ? `step-${s.status}` : ""}>
          <span>{stepLabel(s)}</span>
          {s.secret && <span className="badge ok">{V().secret}</span>}
          {s.submits && <span className="badge warn">{V().submits}</span>}
          {s.status && s.status !== "pending" && <span className="step-note">{V().stepStatus[s.status]}</span>}
          {onSecret && s.action === "type" && !s.secret && <button type="button" className="btn small" onClick={() => onSecret(s.n)}>{V().makeSecret}</button>}
        </li>
      ))}
    </ol>
  );
}

function Question({ q, steps, onAnswer }: { q: ViewQuestion; steps: ViewStep[]; onAnswer: (decision: string, value?: string) => void }) {
  const [secret, setSecret] = useState("");
  const step = steps[q.step];
  return (
    <div className="view-question" role="group" aria-label={questionText(q)}>
      {step && <p className="small"><b>{stepLabel(step)}</b></p>}
      <p>{questionText(q)}</p>
      {q.detail && <pre className="small-pre">{q.detail}</pre>}
      {q.kind === "secret" && (
        <label className="field"><span>{V().secretField}</span>
          <input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
        </label>
      )}
      <div className="row">
        {q.options.map((option) => (
          <button key={option} type="button" className={`btn small${option === "stop" ? " danger" : ""}`}
            disabled={option === "provide" && !secret}
            onClick={() => { onAnswer(option, option === "provide" ? secret : undefined); setSecret(""); }}>
            {optionLabel(option)}
          </button>
        ))}
      </div>
    </div>
  );
}

function Replay({ replay, onAnswer, onStop }: { replay: ViewReplay; onAnswer: (q: ViewQuestion, decision: string, value?: string) => void; onStop: () => void }) {
  const v = V();
  if (replay.state === "idle") return null;
  return (
    <div className="view-replay" aria-label={v.replay}>
      <div className="row">
        <b className="small">{v.replay}: {replay.script?.name}</b>
        <span className={`badge ${replay.state === "done" ? "ok" : replay.state === "error" ? "warn" : ""}`}>{v.state[replay.state]}</span>
        <span className="muted small">{Math.min(replay.index + (replay.state === "done" ? 0 : 1), replay.total)}/{replay.total}</span>
        <div className="spacer" />
        {replayActive(replay.state) && <button type="button" className="btn small danger" onClick={onStop}>{v.stopReplay}</button>}
      </div>
      {replay.state === "stopped" && replay.reason && <p className="small muted">{v.reasons[replay.reason] ?? replay.reason}</p>}
      {replay.question && <Question key={replay.question.id} q={replay.question} steps={replay.steps} onAnswer={(d, value) => onAnswer(replay.question!, d, value)} />}
      <Steps steps={replay.steps} />
    </div>
  );
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Spike View's recorder (A16): record what the browser connector does as a local script, and replay it under the browser's rules. */
export function ViewRecorder() {
  const [status, setStatus] = useState<ViewStatus | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [shown, setShown] = useState<{ id: string; steps: ViewStep[] } | null>(null);
  const refresh = useCallback(async () => {
    try { setStatus(await api.get<ViewStatus>("/api/browser/recorder")); } catch (e) { setErr(String((e as Error).message)); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const busy = !!status && (status.recording.recording || replayActive(status.replay.state));
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void refresh(), 700);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  const run = async (action: () => Promise<unknown>) => {
    setErr("");
    try { await action(); } catch (e) { setErr(String((e as Error).message)); }
    await refresh();
  };
  const finish = () => run(async () => {
    const done = await api.post<{ saved: { id: string; steps: number } | null }>("/api/browser/recorder/stop");
    setNote(done.saved ? `${V().saved}: ${done.saved.steps} ${V().steps}` : V().nothing);
    setName("");
  });
  const show = async (id: string) => {
    if (shown?.id === id) { setShown(null); return; }
    await run(async () => {
      const file = await api.get<ScriptFile>(`/api/browser/scripts/${encodeURIComponent(id)}`);
      setShown({ id, steps: file.steps.map((s, n) => stepRow(s, n)) });
    });
  };
  const exportScript = (id: string) => run(async () => download(`${id}.json`, JSON.stringify(await api.get(`/api/browser/scripts/${encodeURIComponent(id)}`), null, 2)));
  const makeSecret = (id: string, n: number) => run(async () => {
    await api.post(`/api/browser/scripts/${encodeURIComponent(id)}/secret/${n}`);
    const file = await api.get<ScriptFile>(`/api/browser/scripts/${encodeURIComponent(id)}`);
    setShown({ id, steps: file.steps.map((s, i) => stepRow(s, i)) });
  });

  const v = V();
  if (!status) return err ? <div className="error-box" role="alert">{err}</div> : null;
  const rec = status.recording;
  const replaying = replayActive(status.replay.state);
  return (
    <div className="view-recorder" aria-label={v.title}>
      <b className="small">{v.title}</b>
      <p className="small muted">{v.intro}</p>
      <p className="small muted">{v.privacy}</p>
      {!status.running && <p className="small">{v.off}</p>}

      {rec.recording ? (
        <div className="view-recording">
          <div className="row"><span className="badge warn">{v.recording}</span><b className="small">{rec.name}</b><span className="muted small">{rec.steps.length} {v.steps}</span><div className="spacer" />
            <button type="button" className="btn small" onClick={finish}>{v.finish}</button>
            <button type="button" className="btn small" onClick={() => run(() => api.post("/api/browser/recorder/cancel"))}>{v.discard}</button>
          </div>
          <p className="small muted">{v.hint}</p>
          <Steps steps={rec.steps} />
          {Object.keys(rec.ignored).length > 0 && <p className="small muted">{fill(v.ignored, { list: ignoredList(rec.ignored) })}</p>}
          {rec.truncated && <p className="small muted">{v.truncated}</p>}
        </div>
      ) : (
        <form className="row" onSubmit={(e) => { e.preventDefault(); setNote(""); void run(() => api.post("/api/browser/recorder/start", { name: name.trim() })); }}>
          <label className="field"><span>{v.name}</span><input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
          <button className="btn align-end" type="submit" disabled={!status.running || replaying}>{v.record}</button>
        </form>
      )}
      {note && <p className="small" role="status">{note}</p>}

      <b className="small">{v.scripts}</b>
      {status.scripts.length === 0 ? <p className="small muted">{v.none}</p> : (
        <ul className="view-scripts">
          {status.scripts.map((s: ViewScript) => (
            <li key={s.id}>
              <div className="row">
                <b>{s.name ?? s.id}</b>
                {s.error ? <span className="badge warn" title={s.error}>{v.broken}</span> : <span className="muted small">{s.steps} {v.steps}</span>}
                <div className="spacer" />
                {!s.error && <>
                  <button type="button" className="btn small" disabled={!status.running || rec.recording || replaying} onClick={() => run(() => api.post("/api/browser/replay", { script: s.id, mode: "auto" }))}>{v.play}</button>
                  <button type="button" className="btn small" disabled={!status.running || rec.recording || replaying} onClick={() => run(() => api.post("/api/browser/replay", { script: s.id, mode: "step" }))}>{v.stepByStep}</button>
                  <button type="button" className="btn small" onClick={() => void show(s.id)}>{shown?.id === s.id ? v.hide : v.show}</button>
                  <button type="button" className="btn small" onClick={() => void exportScript(s.id)}>{v.download}</button>
                </>}
                <button type="button" className="btn small danger" disabled={replaying && status.replay.script?.id === s.id}
                  onClick={() => run(async () => { await api.del(`/api/browser/scripts/${encodeURIComponent(s.id)}`); setShown(null); })}>{v.remove}</button>
              </div>
              {shown?.id === s.id && <Steps steps={shown.steps} onSecret={(n) => void makeSecret(s.id, n)} />}
            </li>
          ))}
        </ul>
      )}

      <Replay replay={status.replay}
        onAnswer={(q, decision, value) => run(() => api.post("/api/browser/replay/answer", { question: q.id, decision, value }))}
        onStop={() => run(() => api.post("/api/browser/replay/stop"))} />
      {err && <div className="error-box" role="alert">{err}</div>}
    </div>
  );
}
