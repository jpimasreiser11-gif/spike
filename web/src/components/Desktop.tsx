import { useEffect, useRef, useState } from "react";
import { ApiError, api, streamPost } from "../api";
import {
  DESKTOP_STRINGS, actionLabel, applyDesktopEvent, batchChoices, cropStyle, decisionText, emptyDesktopRun, estimateText, recordAction,
  regionOf, shotUrl, startBlock, waitingCard,
} from "../desktop";
import type { Card, DesktopRecord, DesktopRun, DesktopStatus, Estimate } from "../desktop";
import { lang } from "../i18n";
import type { Settings } from "../types";
import { IconClose } from "./Icons";

export const D = DESKTOP_STRINGS[lang];

const message = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

// ------------------------------------------------------------------ Settings > Desktop
export function Desktop({ settings, save, onStart }: {
  settings: Settings;
  save: (p: Partial<Settings>) => void | Promise<void>;
  onStart: () => void;
}) {
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [error, setError] = useState("");
  const cfg = settings.desktop ?? { enabled: false, provider_id: "", max_steps: 20, tool: "auto" };
  const load = () => api.get<DesktopStatus>("/api/desktop").then(setStatus).catch((e) => setError(message(e)));
  useEffect(() => { load(); }, [settings.desktop]);

  const change = async (patch: Partial<NonNullable<Settings["desktop"]>>) => {
    setError("");
    try {
      await save({ desktop: { ...cfg, ...patch } });
    } catch (e) {
      setError(message(e)); // another computer on the network, or a value the server refused
    }
  };
  const block = startBlock(status, D);
  const driver = status?.driver;

  return (
    <div className="form">
      <p className="small muted">{D.intro}</p>
      <label className="check">
        <input type="checkbox" data-testid="desktop-enabled" checked={cfg.enabled} onChange={(e) => change({ enabled: e.target.checked })} />
        <b>{D.setting}</b>
      </label>
      <ul className="small muted dsk-rules">
        {D.rules.map((r) => <li key={r}>{r}</li>)}
      </ul>
      {error && <div className="error-box" role="alert">{error}</div>}

      <label className="field">
        <span>{D.provider}</span>
        <select data-testid="desktop-provider" value={cfg.provider_id} onChange={(e) => change({ provider_id: e.target.value })}>
          <option value="">{D.noProvider}</option>
          {(status?.providers ?? []).map((p) => (
            <option key={p.id} value={p.id} disabled={!p.ok}>
              {p.name}{p.model ? ` · ${p.model}` : ""}{p.ok ? "" : ` — ${D.providerCodes[p.code] ?? p.reason}`}
            </option>
          ))}
        </select>
      </label>
      <div className="row">
        <label className="field">
          <span>{D.maxSteps}</span>
          <input type="number" min={1} max={status?.hard_max_steps ?? 50} value={cfg.max_steps}
            onChange={(e) => e.target.value && change({ max_steps: Math.max(1, Math.min(status?.hard_max_steps ?? 50, Math.round(Number(e.target.value)))) })} />
          <small>{D.maxStepsHint}</small>
        </label>
        <label className="field">
          <span>{D.tool}</span>
          <select value={cfg.tool} onChange={(e) => change({ tool: e.target.value })}>
            {Object.entries(D.tools).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <small>{D.toolHint}</small>
        </label>
      </div>

      <div className="card" data-testid="desktop-driver">
        <div className="card-head"><b>{D.driver}</b></div>
        {!driver ? null : driver.available ? (
          <>
            <p className="small">{D.driverOk}: <b>{driver.backend}</b></p>
            <p className="small muted">{D.can}: {driver.supports.join(", ")}</p>
          </>
        ) : (
          <>
            <p className="small">{D.driverNo}: {D.driverCodes[driver.code] ?? driver.reason}</p>
            {driver.needs && <p className="small muted">{D.needs}: {driver.needs}</p>}
          </>
        )}
        {driver?.notes.map((n) => <p key={n} className="small muted">{D.notes}: {n}</p>)}
      </div>

      <div className="row end">
        <button className="btn primary" data-testid="desktop-start" disabled={Boolean(block)} title={block} onClick={onStart}>{D.start}</button>
        {block && <small className="muted">{block}</small>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ one card
function Crop({ run, card }: { run: DesktopRun; card: Card }) {
  const region = regionOf(card, run.shot);
  if (!region || !run.task) return null;
  const { box, points } = cropStyle(region, shotUrl(run.task, card.shot));
  return (
    <div className="dsk-crop" style={box} data-testid="desktop-crop">
      {points.map((p, i) => <span key={i} className="dsk-dot" style={{ left: p.left, top: p.top }} />)}
    </div>
  );
}

function WaitingCard({ run, card, answer }: { run: DesktopRun; card: Card; answer: (decision: string, n?: number) => void }) {
  const [batch, setBatch] = useState(3);
  const sensitive = card.sensitive;
  return (
    <div className={`dsk-card waiting ${sensitive ? "sensitive" : ""}`} role="group" aria-label={D.waiting} data-testid="desktop-card">
      <div className="dsk-head">
        <b>{D.stepsLeft(card.step, run.maxSteps ?? 0)}</b>
        {sensitive && <span className="chip dsk-chip" data-testid="desktop-sensitive">{D.sensitive[sensitive.kind] ?? sensitive.kind}</span>}
      </div>
      <Crop run={run} card={card} />
      <div className="dsk-action" data-testid="desktop-action">{actionLabel(card.action, D, card.masked)}</div>
      {card.masked && <small className="muted">{D.password}</small>}
      {card.note && <p className="small muted">{D.model}: “{card.note}”</p>}
      {sensitive && <p className="small dsk-warn">{D.alwaysAsks}: {D.sensitive[sensitive.kind] ?? sensitive.kind}.</p>}
      <div className="row">
        <button className="btn primary" data-testid="desktop-approve" onClick={() => answer("approve")}>{D.approve}</button>
        {!sensitive && (
          <span className="dsk-batch">
            <select aria-label={D.approveNext} value={batch} onChange={(e) => setBatch(Number(e.target.value))}>
              {batchChoices().map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <button className="btn" data-testid="desktop-approve-next" onClick={() => answer("approve_batch", batch)}>{D.approveNext} {batch}</button>
          </span>
        )}
        <button className="btn danger" data-testid="desktop-deny" onClick={() => answer("deny")}>{D.deny}</button>
      </div>
    </div>
  );
}

function Past({ item }: { item: DesktopRun["items"][number] }) {
  if (item.kind === "text") return <p className="small muted dsk-said">{item.text}</p>;
  if (item.kind === "step") {
    const s = item.step;
    return <div className={`dsk-past ${s.ok ? "" : "bad"}`}>{s.ok ? "·" : "✕"} {actionLabel(s.action, D)}{s.message ? ` — ${s.message}` : ""}</div>;
  }
  const c = item.card;
  const state = c.decision === "deny" || c.decision === "stop" || c.decision === "timeout" ? "bad" : c.result === "failed" ? "bad" : "";
  return (
    <div className={`dsk-past ${state}`} data-testid="desktop-past">
      {c.result === "ok" ? "✓" : c.result === "failed" || state ? "✕" : "…"} {actionLabel(c.action, D, c.masked)}
      {" — "}{decisionText(c.decision, D)}{c.decision === "batch" && c.n ? ` (${c.n})` : ""}
      {c.result === "ok" ? ` · ${D.resultOk}` : c.result === "failed" && c.decision !== "deny" ? ` · ${D.resultFailed}${c.message ? `: ${c.message}` : ""}` : ""}
      {c.decision === "auto" && c.left !== undefined ? ` · ${D.batchLeft(c.left)}` : ""}
    </div>
  );
}

// ------------------------------------------------------------------ the task
export function DesktopTask({ onClose, onChat, onFinished }: {
  onClose: () => void;
  onChat: (conversationId: string) => void;
  onFinished: () => void;
}) {
  const [goal, setGoal] = useState("");
  const [keep, setKeep] = useState(false);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [problem, setProblem] = useState("");
  const [run, setRun] = useState<DesktopRun>(emptyDesktopRun());
  const abort = useRef<AbortController | null>(null);
  const running = run.phase === "starting" || run.phase === "running";

  const refreshEstimate = () => {
    setEstimate(null);
    setProblem("");
    api.post<Estimate>("/api/desktop/estimate", {}).then(setEstimate).catch((e) => setProblem(message(e)));
  };
  useEffect(refreshEstimate, []);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !running && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, running]);

  const begin = async () => {
    const text = goal.trim();
    if (!text || running) return;
    setProblem("");
    setRun({ ...emptyDesktopRun(text), phase: "starting" });
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamPost("/api/desktop/run", { goal: text, keep_screenshots: keep }, (ev) => setRun((r) => applyDesktopEvent(r, ev)), controller.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setProblem(message(e));
        setRun((r) => (r.phase === "starting" ? emptyDesktopRun() : { ...r, phase: "done", error: r.error ?? message(e) }));
      }
    } finally {
      abort.current = null;
      onFinished();
    }
  };

  const answer = async (card: Card, decision: string, n?: number) => {
    try {
      await api.post(`/api/desktop/actions/${card.id}`, { decision, ...(n ? { n } : {}) });
    } catch (e) {
      setProblem(message(e));
    }
  };
  const stop = () => api.post("/api/desktop/stop").catch(() => {});
  const stopAndClose = () => { stop(); abort.current?.abort(); onClose(); };

  const waiting = waitingCard(run);
  const done = run.done;
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !running && onClose()}>
      <div className="modal dsk-modal" role="dialog" aria-modal="true" aria-label={D.title} data-testid="desktop-task">
        <div className="modal-head">
          <h2>{D.title}</h2>
          {running && <span className="flash-box" aria-live="polite">{D.running}{run.maxSteps ? ` · ${run.items.filter((i) => i.kind !== "text").length}/${run.maxSteps}` : ""}</span>}
          {running && <button className="btn danger dsk-stop" data-testid="desktop-stop" onClick={stop}>{D.stop}</button>}
          <button className="icon-btn" onClick={running ? stopAndClose : onClose} aria-label={running ? D.stopClose : D.close} title={running ? D.stopClose : D.close}><IconClose /></button>
        </div>
        <div className="dsk-body">
          {run.phase === "idle" && (
            <div className="form">
              <label className="field">
                <span>{D.goal}</span>
                <textarea data-testid="desktop-goal" rows={3} value={goal} placeholder={D.goalPlaceholder} onChange={(e) => setGoal(e.target.value)} autoFocus />
              </label>
              <label className="check">
                <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
                <span>{D.keep}<br /><small className="muted">{D.keepHint}</small></span>
              </label>
              <div className="card" data-testid="desktop-estimate">
                <div className="card-head"><b>{D.estimate}</b></div>
                {estimate ? estimateText(estimate, D).map((line) => <p key={line} className="small">{line}</p>)
                  : problem ? null : <p className="small muted">{D.estimating}</p>}
              </div>
              {problem && <div className="error-box" role="alert">{problem}</div>}
              <div className="row end">
                <button className="btn" onClick={onClose}>{D.cancel}</button>
                <button className="btn primary" data-testid="desktop-begin" disabled={!goal.trim() || !estimate} onClick={begin}>{D.begin}</button>
              </div>
            </div>
          )}
          {run.phase !== "idle" && (
            <div className="dsk-log">
              <p className="small"><b>{run.goal}</b></p>
              {run.items.filter((it) => !(it.kind === "card" && it.card.id === waiting?.id)).map((it, i) => <Past key={i} item={it} />)}
              {waiting && <WaitingCard run={run} card={waiting} answer={(d, n) => answer(waiting, d, n)} />}
              {run.phase === "starting" && <p className="small muted">{D.estimating}</p>}
              {problem && <div className="error-box" role="alert">{problem}</div>}
              {run.error && run.phase !== "done" && <div className="error-box" role="alert">{run.error}</div>}
              {done && (
                <div className="dsk-done card" data-testid="desktop-done">
                  <b>{D.summary(done.steps, D.reasons[done.reason] ?? done.reason)}</b>
                  {done.text && <p className="small">{done.text}</p>}
                  {done.error && <div className="error-box" role="alert">{done.error}</div>}
                  <small className="muted">
                    {(done.usage.input + done.usage.output).toLocaleString()} {D.tokens}
                    {done.cost !== null ? ` · ${D.cost} ${done.cost.toFixed(2)}` : ""}
                    {" · "}{done.shots.length ? D.shotsKept : D.shotsNot}
                  </small>
                  <div className="row end">
                    {run.conversation && <button className="btn" onClick={() => onChat(run.conversation as string)}>{D.openChat}</button>}
                    <button className="btn" onClick={() => { setRun(emptyDesktopRun()); refreshEstimate(); }}>{D.another}</button>
                    <button className="btn primary" onClick={onClose}>{D.close}</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ in a chat
/** A stored desktop task in its chat: how it went and every action with what the user decided (never images). */
export function DesktopRecordView({ record }: { record: DesktopRecord }) {
  return (
    <div className="dsk-record card" data-testid="desktop-record">
      <div className="card-head">
        <b>{D.summary(record.steps, D.reasons[record.reason] ?? record.reason)}</b>
        <span className="muted small">{record.provider}{record.model ? ` · ${record.model}` : ""}</span>
      </div>
      {record.actions.length > 0 && (
        <ol className="dsk-actions small">
          {record.actions.map((a, i) => (
            <li key={i} className={a.ok ? "" : "bad"}>
              {actionLabel(recordAction(a), D)} — {decisionText(a.decision, D)} · {a.ok ? D.resultOk : D.resultFailed}
              {a.sensitive ? ` · ${D.sensitive[a.sensitive] ?? a.sensitive}` : ""}
            </li>
          ))}
        </ol>
      )}
      {record.error && <div className="error-box" role="alert">{record.error}</div>}
      <small className="muted">
        {(record.usage.input + record.usage.output).toLocaleString()} {D.tokens} · {record.screenshots === "kept" ? D.shotsKept : D.shotsNot}
      </small>
    </div>
  );
}
