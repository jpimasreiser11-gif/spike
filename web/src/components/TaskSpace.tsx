import { useEffect, useRef, type ReactNode } from "react";
import { t } from "../i18n";
import type { TaskView } from "../taskSpace";
import { ArtifactFiles } from "./ArtifactFiles";
import { IconClose } from "./Icons";
import "./TaskSpace.css";

const T = t.task;
const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

/** O2: one task in four parts, each always present so the place of things never moves: the plan, every action with
 * the permission it got, the files it changed and what it delivered. `files` replaces the changed-files list when the
 * caller has a more current one (a Dev session lists its changes with their undo state from the server). */
export function TaskSpace({ view, files, projectId, urlFor }: {
  view: TaskView; files?: ReactNode; projectId?: string; urlFor?: (path: string) => string;
}) {
  const stepsDone = view.steps.filter((s) => s.status === "done").length;
  return (
    <div className="task-space" data-testid="task-space" data-status={view.status}>
      <p className="task-status"><span className={`task-chip ${view.status}`}>{T.status[view.status]}</span>
        {view.verified !== undefined && <span className={`task-chip ${view.verified ? "done" : "error"}`}>{view.verified ? T.verified : T.notVerified}</span>}</p>

      <section aria-labelledby="task-plan">
        <h3 id="task-plan">{T.plan}{view.steps.length > 0 && <small> {stepsDone}/{view.steps.length}</small>}</h3>
        {view.steps.length === 0 ? <p className="task-empty">{T.noPlan}</p> : <ol className="task-steps" data-testid="task-steps">
          {view.steps.map((s) => <li key={s.id} data-status={s.status}>
            <span className={`task-dot ${s.status}`} aria-hidden="true" />
            <div><b>{s.name}</b>{s.round && s.round > 1 ? <small> · {T.round} {s.round}</small> : null}
              <small className="task-state"> · {T.step[s.status]}</small>
              {s.instruction && <p>{s.instruction}</p>}</div>
          </li>)}
        </ol>}
        {view.criteria.length > 0 && <>
          <h4>{T.criteria}</h4>
          <ul className="task-criteria">{view.criteria.map((c, i) => <li key={i} data-ok={c.ok === null ? "unchecked" : String(c.ok)}>
            <span aria-hidden="true">{c.ok === null ? "○" : c.ok ? "✓" : "✕"}</span> {c.text}{c.note ? <small> · {c.note}</small> : null}</li>)}</ul>
        </>}
      </section>

      <section aria-labelledby="task-actions">
        <h3 id="task-actions">{T.actions}{view.actions.length > 0 && <small> {view.actions.length}</small>}</h3>
        {view.actions.length === 0 ? <p className="task-empty">{T.noActions}</p> : <ol className="task-actions" data-testid="task-actions">
          {view.actions.map((a) => <li key={a.key} data-status={a.status} data-permission={a.permission}>
            <div className="task-action-head"><code>{a.tool}</code>{a.detail && <span className="task-detail" title={a.detail}>{a.detail}</span>}</div>
            <small><span className={`task-perm ${a.permission}`}>{T.permission[a.permission]}</span> · {T.action[a.status]}
              {a.undone ? ` · ${T.undone}` : ""}{a.specialist ? ` · ${a.specialist}` : ""}</small>
          </li>)}
        </ol>}
      </section>

      <section aria-labelledby="task-files">
        <h3 id="task-files">{T.files}</h3>
        {files ?? (view.files.length === 0 ? <p className="task-empty">{T.noFiles}</p> : <ul className="task-files" data-testid="task-files">
          {view.files.map((f) => <li key={f.checkpoint ?? f.path} data-undone={f.undone}><code>{f.path}</code> <small>{f.tool}{f.undone ? ` · ${T.undone}` : ""}</small></li>)}
        </ul>)}
      </section>

      <section aria-labelledby="task-deliverables">
        <h3 id="task-deliverables">{T.deliverables}</h3>
        {view.deliverables.length === 0 ? <p className="task-empty">{T.noDeliverables}</p>
          : <ArtifactFiles files={view.deliverables} projectId={projectId} urlFor={urlFor} />}
      </section>
    </div>
  );
}

/** The task space of a chat answer, over the conversation. It follows a running answer as its events arrive. */
export function TaskDialog({ view, projectId, onClose }: { view: TaskView; projectId?: string; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null), close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "Tab" || !box.current) return;
      const items = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1], active = document.activeElement as HTMLElement | null;
      if (e.shiftKey ? !active || !box.current.contains(active) || active === first : !active || !box.current.contains(active) || active === last) {
        e.preventDefault(); (e.shiftKey ? last : first).focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); if (previous?.isConnected) previous.focus(); };
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} className="modal task-dialog" role="dialog" aria-modal="true" aria-label={T.title} tabIndex={-1}>
        <div className="modal-head">
          <h2>{T.title}</h2>
          <button ref={close} className="icon-btn" onClick={onClose} aria-label={t.close}><IconClose /></button>
        </div>
        <p className="muted small">{T.rebuilt}</p>
        <TaskSpace view={view} projectId={projectId} />
      </div>
    </div>
  );
}
