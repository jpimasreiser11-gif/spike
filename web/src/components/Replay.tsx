import { useEffect, useMemo, useState } from "react";
import { t } from "../i18n";
import { runAt } from "../run";
import type { ChatEvent, Specialist } from "../types";
import { AssistantMessage } from "./AssistantMessage";
import { IconClose } from "./Icons";

const QUIET = new Set(["usage", "status", "permission_resolved"]); // applied, but not steps of their own

function describe(ev: ChatEvent): string {
  const mind = typeof ev.mind === "number" ? `[${t.minds.mind} ${ev.mind + 1}] ` : ""; // Parallel Minds: whose step it is
  return mind + describeEvent(ev);
}

function describeEvent(ev: ChatEvent): string {
  const label = t.ev[ev.type] ?? ev.type;
  switch (ev.type) {
    case "route": return `${label}: ${(ev.specialists ?? []).map((s: { name: string }) => s.name).join(", ")}`;
    case "plan": return `${label}: ${(ev.subtasks ?? []).length}`;
    case "subtask_start": case "subtask_end": return `${label}: ${ev.name ?? ev.specialist}`;
    case "tool_call": case "tool_result": return `${label} ${ev.name}${ev.type === "tool_result" && ev.ok === false ? " ✕" : ""}`;
    case "permission_request": return `${label} ${ev.tool}`;
    case "delta": case "reasoning": return `${label}: ${String(ev.text).replace(/\s+/g, " ").trim().slice(0, 70)}…`;
    case "skill": return `${label} ${(ev.names ?? []).join(", ")}`;
    case "memory": return `${label}: ${(ev.notes ?? []).length + (ev.rules ?? 0)}`;
    case "privacy": return `${label} ${ev.provider}`;
    case "memory_saved": return `${label}: ${(ev.saved ?? []).map((s: { text: string }) => s.text).join(" · ").slice(0, 70)}`;
    case "correction": return `${label}: ${String(ev.text).slice(0, 70)}`;
    case "question": return `${label}: ${String(ev.question).slice(0, 70)}`;
    case "answered": return `${label}: ${String(ev.answer ?? "—").slice(0, 70)}`;
    case "error": return `${label}: ${ev.message}`;
    case "minds_start": return `${label}: ${ev.n}`;
    case "minds_pick": return `${label}: ${t.minds.mind} ${(ev.chosen ?? 0) + 1}`;
    default: return label;
  }
}

/** Replays a stored answer one event at a time: route, plan, each specialist, each tool call, the text. */
export function Replay({ events, specialists, onClose }: { events: ChatEvent[]; specialists: Specialist[]; onClose: () => void }) {
  const steps = useMemo(() => events.map((ev, i) => ({ ev, i })).filter(({ ev }) => !QUIET.has(ev.type)), [events]);
  const [k, setK] = useState(0); // index into steps
  const [playing, setPlaying] = useState(false);
  const run = useMemo(() => runAt(events, (steps[k]?.i ?? events.length - 1) + 1), [events, steps, k]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setK((x) => Math.min(steps.length - 1, x + 1));
      if (e.key === "ArrowLeft") setK((x) => Math.max(0, x - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, steps.length]);

  useEffect(() => {
    if (!playing) return;
    if (k >= steps.length - 1) { setPlaying(false); return; }
    const id = setTimeout(() => setK(k + 1), 700);
    return () => clearTimeout(id);
  }, [playing, k, steps.length]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal replay" role="dialog" aria-modal="true" aria-label={t.replayTitle}>
        <div className="modal-head">
          <h2>{t.replayTitle}</h2>
          <span className="muted small">{t.step} {k + 1} / {steps.length}</span>
          <button className="icon-btn" onClick={onClose} aria-label={t.close}><IconClose /></button>
        </div>
        <div className="replay-body">
          <ol className="replay-steps">
            {steps.map(({ ev }, i) => (
              <li key={i}>
                <button className={i === k ? "active" : i < k ? "past" : ""} onClick={() => { setPlaying(false); setK(i); }} aria-current={i === k ? "step" : undefined}>
                  <span className="replay-time">+{Number(ev.t ?? 0).toFixed(1)} s</span> {describe(ev)}
                </button>
              </li>
            ))}
          </ol>
          <div className="replay-view">
            <AssistantMessage run={run} specialists={specialists} replay />
          </div>
        </div>
        <div className="replay-controls">
          <button className="btn small" onClick={() => setK(Math.max(0, k - 1))} disabled={k === 0} aria-label={t.prevStep}>◀</button>
          <button className="btn small primary" onClick={() => { if (k >= steps.length - 1) setK(0); setPlaying(!playing); }}>{playing ? t.pause : t.play}</button>
          <button className="btn small" onClick={() => setK(Math.min(steps.length - 1, k + 1))} disabled={k >= steps.length - 1} aria-label={t.nextStep}>▶</button>
          <input type="range" className="grow" min={0} max={Math.max(0, steps.length - 1)} value={k} aria-label={t.step}
            onChange={(e) => { setPlaying(false); setK(Number(e.target.value)); }} />
        </div>
      </div>
    </div>
  );
}
