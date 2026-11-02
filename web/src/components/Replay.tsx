import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../i18n";
import { runAt } from "../run";
import type { ChatEvent, Specialist } from "../types";
import { AssistantMessage } from "./AssistantMessage";
import { IconClose } from "./Icons";

const QUIET = new Set(["usage", "status", "permission_resolved"]); // applied, but not steps of their own
const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

function clip(value: unknown, max = 70): string {
  const clean = String(value ?? "").replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max)}…` : clean;
}

function withDetail(label: string, detail: string): string {
  return detail ? `${label}: ${detail}` : label;
}

function describe(ev: ChatEvent): string {
  const mind = typeof ev.mind === "number" ? `[${t.minds.mind} ${ev.mind + 1}] ` : ""; // Parallel Minds: whose step it is
  return mind + describeEvent(ev);
}

function describeEvent(ev: ChatEvent): string {
  const label = t.ev[ev.type] ?? ev.type;
  switch (ev.type) {
    case "route": return withDetail(label, (ev.specialists ?? []).map((s: { name: string }) => s.name).join(", "));
    case "plan": return `${label}: ${(ev.subtasks ?? []).length}`;
    case "subtask_start": case "subtask_end": return withDetail(label, String(ev.name ?? ev.specialist ?? "").trim());
    case "tool_call": case "tool_result": {
      const name = String(ev.name ?? "").trim();
      return `${name ? `${label} ${name}` : label}${ev.type === "tool_result" && ev.ok === false ? " ✕" : ""}`;
    }
    case "permission_request": {
      const tool = String(ev.tool ?? "").trim();
      return tool ? `${label} ${tool}` : label;
    }
    case "delta": case "reasoning": return withDetail(label, clip(ev.text));
    case "skill": {
      const names = (ev.names ?? []).join(", ");
      return names ? `${label} ${names}` : label;
    }
    case "memory": return `${label}: ${(ev.notes ?? []).length + (ev.rules ?? 0)}`;
    case "privacy": return ev.provider ? `${label} ${ev.provider}` : label;
    case "memory_saved": return withDetail(label, clip((ev.saved ?? []).map((s: { text: string }) => s.text).join(" · ")));
    case "correction": return withDetail(label, clip(ev.text));
    case "question": return withDetail(label, clip(ev.question));
    case "answered": return withDetail(label, clip(ev.answer ?? "—"));
    case "error": return withDetail(label, clip(ev.message, 120));
    case "minds_start": return `${label}: ${ev.n ?? 0}`;
    case "minds_pick": return `${label}: ${t.minds.mind} ${(ev.chosen ?? 0) + 1}`;
    default: return label;
  }
}

/** Replays a stored answer one event at a time: route, plan, each specialist, each tool call, the text. */
export function Replay({ events, specialists, onClose }: { events: ChatEvent[]; specialists: Specialist[]; onClose: () => void }) {
  const steps = useMemo(() => events.map((ev, i) => ({ ev, i })).filter(({ ev }) => !QUIET.has(ev.type)), [events]);
  const total = steps.length;
  const [k, setK] = useState(0); // index into steps
  const [playing, setPlaying] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const clampedK = total === 0 ? 0 : Math.min(k, total - 1);
  const run = useMemo(
    () => runAt(events, total === 0 ? events.length : steps[clampedK].i + 1),
    [events, steps, total, clampedK],
  );

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    (closeRef.current ?? dialogRef.current)?.focus();
    return () => {
      if (previous && previous.isConnected) previous.focus();
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const items = [...dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey) {
          if (!active || !dialogRef.current.contains(active) || active === first) {
            e.preventDefault();
            last.focus();
          }
        } else if (!active || !dialogRef.current.contains(active) || active === last) {
          e.preventDefault();
          first.focus();
        }
        return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || total === 0) return;
      if (e.target instanceof HTMLElement && e.target.matches('input, textarea, select, [contenteditable="true"]')) return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setPlaying(false);
        setK((x) => Math.min(total - 1, Math.min(x, total - 1) + 1));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setPlaying(false);
        setK((x) => Math.max(0, Math.min(x, total - 1) - 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, total]);

  useEffect(() => {
    if (!playing) return;
    if (total === 0 || clampedK >= total - 1) { setPlaying(false); return; }
    const id = setTimeout(() => setK(clampedK + 1), 700);
    return () => clearTimeout(id);
  }, [playing, clampedK, total]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} className="modal replay" role="dialog" aria-modal="true" aria-label={t.replayTitle} tabIndex={-1}>
        <div className="modal-head">
          <h2>{t.replayTitle}</h2>
          <span className="muted small">{t.step} {total === 0 ? 0 : clampedK + 1} / {total}</span>
          <button ref={closeRef} className="icon-btn" onClick={onClose} aria-label={t.close}><IconClose /></button>
        </div>
        <div className="replay-body">
          <ol className="replay-steps">
            {steps.map(({ ev }, i) => (
              <li key={i}>
                <button className={i === clampedK ? "active" : i < clampedK ? "past" : ""} onClick={() => { setPlaying(false); setK(i); }} aria-current={i === clampedK ? "step" : undefined}>
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
          <button className="btn small" onClick={() => { setPlaying(false); setK(Math.max(0, clampedK - 1)); }} disabled={total === 0 || clampedK === 0} aria-label={t.prevStep}>◀</button>
          <button className="btn small primary" disabled={total === 0} onClick={() => { if (total === 0) return; if (clampedK >= total - 1) setK(0); setPlaying(!playing); }}>{playing ? t.pause : t.play}</button>
          <button className="btn small" onClick={() => { setPlaying(false); setK(Math.min(total - 1, clampedK + 1)); }} disabled={total === 0 || clampedK >= total - 1} aria-label={t.nextStep}>▶</button>
          <input type="range" className="grow" min={0} max={Math.max(0, total - 1)} value={clampedK} disabled={total <= 1} aria-label={t.step}
            onChange={(e) => { setPlaying(false); setK(Number(e.target.value)); }} />
        </div>
      </div>
    </div>
  );
}
