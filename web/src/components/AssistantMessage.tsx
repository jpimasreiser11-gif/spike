import { useContext, useState } from "react";
import { ApiError, api } from "../api";
import { t } from "../i18n";
import type { Learn, PermissionState, ProviderInfo, QuestionState, RunState, Specialist, ToolState } from "../types";
import { ArtifactContext, artifactFromCode } from "./Artifact";
import { M } from "./Memory";
import { IconChevron, IconCopy, IconFile, IconLock, IconRetry, IconTool } from "./Icons";
import { Markdown } from "./Markdown";
import { SpecMark } from "./SpecMark";

function Collapsible({ title, children, defaultOpen = false, live = false }: {
  title: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  live?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`trace-item ${live ? "live" : ""}`}>
      <button className="trace-head" onClick={() => setOpen(!open)} aria-expanded={open} type="button">
        <IconChevron size={14} open={open} />
        <span className="trace-title">{title}</span>
      </button>
      {open && <div className="trace-body">{children}</div>}
    </div>
  );
}

/** Put back the files one tool call changed. A file edited again since then is only overwritten on a second click. */
function Undo({ tool }: { tool: ToolState }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "conflict">(tool.undone ? "done" : "idle");
  const [error, setError] = useState("");
  const undo = async (force: boolean) => {
    setState("busy"); setError("");
    try {
      await api.post(`/api/checkpoints/${tool.checkpoint}/undo`, { force });
      setState("done");
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) setState("conflict");
      else if (err.status === 400 && err.message.includes("already undone")) setState("done");
      else { setState("idle"); setError(err.message); }
    }
  };
  if (state === "done") return <div className="undo small muted">{t.undone}</div>;
  return (
    <div className="undo">
      {state === "conflict" ? (
        <><span className="small warn-text">{t.undoConflict}</span>
          <button className="btn small danger" onClick={() => undo(true)}>{t.undoAnyway}</button></>
      ) : (
        <button className="btn small" disabled={state === "busy"} onClick={() => undo(false)}>{t.undo}</button>
      )}
      {error && <span className="bad small">{error}</span>}
    </div>
  );
}

/** What this message taught SPIKE: notes saved at once, with undo, or a rule proposed from a correction to approve. */
function Learned({ initial, messageId }: { initial: Learn; messageId: string }) {
  const [learn, setLearn] = useState(initial);
  const [draft, setDraft] = useState(initial.correction?.text ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const act = async (body: { action: "save" | "dismiss" | "undo"; text?: string; memory?: string }) => {
    setBusy(true); setError("");
    try {
      const next = await api.post<Learn>(`/api/messages/${messageId}/learn`, body);
      setLearn(next);
      if (next.correction) setDraft(next.correction.text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const c = learn.correction;
  return (
    <div className="learned">
      {(learn.saved ?? []).map((s) => (
        <div key={s.id} className="learned-line small" data-learned={s.kind}>
          {s.undone ? <span className="muted">{t.removedFromMemory}: «{s.text}»</span> : (<>
            <span>◆ {t.savedToMemory} · {M.kinds[s.kind] ?? s.kind}: «{s.text}»</span>
            {s.existing ? <span className="muted"> · {t.alreadyInMemory}</span>
              : <button className="link-btn small" disabled={busy} onClick={() => act({ action: "undo", memory: s.id })}>{t.undo}</button>}
          </>)}
        </div>
      ))}
      {c?.status === "proposed" && (
        <div className="learn-card" role="group" aria-label={t.correctionAsk}>
          <div className="small">{t.correctionAsk}</div>
          <textarea rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label={M.kinds.rule} />
          <div className="row">
            <button className="btn small primary" disabled={busy || !draft.trim()} onClick={() => act({ action: "save", text: draft.trim() })}>{t.saveRule}</button>
            <button className="btn small" disabled={busy} onClick={() => act({ action: "dismiss" })}>{t.notNow}</button>
          </div>
        </div>
      )}
      {c?.status === "saved" && (
        <div className="learned-line small" data-learned="correction">
          <span>◆ {t.ruleSaved}: «{c.text}»</span>
          {c.existing && <span className="muted"> · {t.alreadyInMemory}</span>}
          <button className="link-btn small" disabled={busy} onClick={() => act({ action: "undo", memory: c.memory })}>{t.undo}</button>
        </div>
      )}
      {error && <div className="bad small">{error}</div>}
    </div>
  );
}

/** Human handoff: a specialist's question, answered with one of its options or in the user's own words. */
function Question({ q, readOnly }: { q: QuestionState; readOnly?: boolean }) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const reply = async (answer: string) => {
    setSending(true); setError("");
    try {
      await api.post(`/api/questions/${q.id}`, { answer });
    } catch (e) {
      setError((e as Error).message);
      setSending(false);
    }
  };
  if (readOnly || q.status !== "pending") {
    return (
      <div className="question done">
        <span className="question-text">❓ {q.question}</span>
        <span className="muted"> · {q.status === "answered" ? `${t.yourAnswer}: ${q.answer}` : q.status === "pending" ? t.waitingAnswer : t.noAnswer}</span>
      </div>
    );
  }
  return (
    <div className="question" role="alertdialog" aria-label={t.questionFor}>
      <div className="question-title">❓ {t.questionFor}</div>
      <div className="question-text">{q.question}</div>
      {q.options.length > 0 && (
        <div className="question-options">
          {q.options.map((o) => <button key={o} className="btn" disabled={sending} onClick={() => reply(o)}>{o}</button>)}
        </div>
      )}
      <form className="question-reply" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) reply(draft.trim()); }}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t.answerPlaceholder} aria-label={t.answerPlaceholder} autoFocus disabled={sending} />
        <button className="btn primary" type="submit" disabled={sending || !draft.trim()}>{t.answer}</button>
      </form>
      {error && <span className="bad small">{error}</span>}
    </div>
  );
}

function Permission({ p, onDecided, readOnly }: { p: PermissionState; onDecided: (id: string, d: PermissionState["status"]) => void; readOnly?: boolean }) {
  const decide = async (decision: "allow_once" | "allow_always" | "deny") => {
    onDecided(p.id, "sending");
    try {
      await api.post(`/api/permissions/${p.id}`, { decision });
    } catch {
      onDecided(p.id, "pending");
    }
  };
  if (readOnly || (p.status !== "pending" && p.status !== "sending")) {
    return (
      <div className="permission done">
        <IconTool size={14} /> <code>{p.tool}</code>{p.status === "pending" ? ` · ${t.permissionAsk}` : ` · ${p.status === "deny" ? t.denied : t.allowed}`}
      </div>
    );
  }
  return (
    <div className="permission" role="alertdialog" aria-label={`${p.tool} ${t.permissionAsk}`}>
      <div className="permission-title">
        <IconTool size={16} /> SPIKE {t.permissionAsk}: <code>{p.tool}</code>
        <span className={`risk risk-${p.risk}`}>{p.risk}</span>
      </div>
      <pre className="permission-args">{JSON.stringify(p.arguments, null, 2)}</pre>
      <div className="permission-actions">
        <button className="btn primary" disabled={p.status === "sending"} onClick={() => decide("allow_once")}>{t.allowOnce}</button>
        <button className="btn" disabled={p.status === "sending"} onClick={() => decide("allow_always")}>{t.allowAlways}</button>
        <button className="btn danger" disabled={p.status === "sending"} onClick={() => decide("deny")}>{t.deny}</button>
      </div>
    </div>
  );
}

/** Download URL of a file a tool wrote: in the project's folder, or in the workspace. */
export const fileUrl = (path: string, projectId?: string) =>
  `${projectId ? `/api/projects/${projectId}/files` : "/api/workspace/files"}/${path.split("/").map(encodeURIComponent).join("/")}`;

function Files({ files, projectId }: { files: string[]; projectId?: string }) {
  const openArtifact = useContext(ArtifactContext);
  const preview = async (path: string) => {
    const r = await fetch(fileUrl(path, projectId));
    if (r.ok && openArtifact) openArtifact({ ...artifactFromCode(await r.text(), path.endsWith(".svg") ? "svg" : "html"), filename: path.split("/").pop() || path });
  };
  return (
    <div className="file-chips" aria-label={t.filesCreated}>
      {files.map((path) => (
        <span key={path} className="file-chip">
          <IconFile size={15} />
          <a href={fileUrl(path, projectId)} download title={path}>{path.split("/").pop()}</a>
          {/\.(html?|svg)$/i.test(path) && <button type="button" className="link-btn" onClick={() => preview(path)}>{t.preview}</button>}
        </span>
      ))}
    </div>
  );
}

/** Run the turn again, on the same model or on another provider the user picks (never a paid one they did not allow). */
function Retry({ providers, onRetry, failed }: { providers: ProviderInfo[]; onRetry: (pid: string | null) => void; failed: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="retry">
      <button className="icon-btn" onClick={() => setOpen(!open)} title={t.retry} aria-label={t.retry} aria-expanded={open}>
        <IconRetry size={15} />
      </button>
      {failed && !open && <button className="link-btn small" onClick={() => setOpen(true)}>{t.localFailedHint}</button>}
      {open && (
        <span className="retry-menu" role="menu" aria-label={t.retryWith}>
          <button role="menuitem" className="btn small" onClick={() => { setOpen(false); onRetry(null); }}>{t.sameModel}</button>
          {providers.map((p) => {
            const blocked = p.paid && !p.allow_paid;
            return (
              <button key={p.id} role="menuitem" className="btn small" disabled={blocked} title={blocked ? t.noPaidPermission : p.model}
                onClick={() => { setOpen(false); onRetry(p.id); }}>
                {p.name}{blocked ? ` · ${t.noPaidPermission}` : ""}
              </button>
            );
          })}
        </span>
      )}
    </span>
  );
}

export function AssistantMessage({ run, specialists, onPermission, projectId, providers = [], onRetry, onReplay, replay = false, messageId }: {
  run: RunState;
  specialists: Specialist[];
  onPermission?: (id: string, status: PermissionState["status"]) => void;
  projectId?: string;
  providers?: ProviderInfo[];
  onRetry?: (providerId: string | null) => void; // only on the chat's last answer
  onReplay?: () => void;
  replay?: boolean; // shown inside the step-by-step view: nothing in it acts
  messageId?: string; // the user's message this answers, for what it taught SPIKE
}) {
  const [copied, setCopied] = useState(false);
  const live = run.status === "running" || run.status === "planning" || run.status === "synthesizing";
  const routeSpecs = run.route?.specialists ?? [];
  const sensitive = routeSpecs.some((r) => specialists.find((s) => s.id === r.id)?.sensitive);
  const pending = [...run.permissions.filter((p) => p.status === "pending" || p.status === "sending"),
    ...(run.questions ?? []).filter((q) => q.status === "pending")];
  const files = [...new Set(run.tools.filter((x) => x.ok && x.file).map((x) => x.file as string))];

  return (
    <div className="msg assistant">
      {routeSpecs.length > 0 && (
        <div className="route">
          {routeSpecs.map((s) => (
            <span key={s.id} className={`chip spec-${s.id}`} title={`${s.provider} · ${s.model || ""}${s.adapter ? ` · ${t.adapter}: ${s.adapter}` : ""}${s.profile_only ? ` · ${t.promptProfile}` : ""}`}>
              <SpecMark id={s.id} />
              {s.name}
              {s.profile_only && <span className="chip-note">β</span>}
            </span>
          ))}
          {(run.skills ?? []).map((name) => (
            <span key={name} className="chip skill-chip" title={t.skill}>✦ {name}</span>
          ))}
          {run.memory && (
            <span className="chip memory-chip" tabIndex={0} title={[
              ...(run.memory.rules ? [`${run.memory.rules} × ${M.kinds.rule}`] : []),
              ...run.memory.notes.map((n) => `${M.kinds[n.kind] ?? n.kind}: ${n.preview}`),
            ].join("\n")}>◆ {t.memoryUsed} · {run.memory.rules + run.memory.notes.length}</span>
          )}
          {run.privacy && Object.keys(run.privacy).length > 0 && (
            <span className="chip privacy-chip" tabIndex={0} title={`${t.withheldTitle} ${Object.keys(run.privacy).join(", ")}`}>
              <IconLock size={13} /> {t.withheld}
            </span>
          )}
          {run.route?.method && run.route.method !== "user" && (
            <span className="route-meta">{run.route.mode} · {run.route.method}</span>
          )}
        </div>
      )}

      {(run.order.length > 0 || run.tools.length > 0 || run.reasoning) && (
        <div className="trace">
          {run.reasoning && (
            <Collapsible title={t.reasoning} live={live && !run.text}>
              <div className="reasoning">{run.reasoning}</div>
            </Collapsible>
          )}
          {run.order.map((id) => {
            const st = run.subtasks[id];
            return (
              <Collapsible key={id} live={!st.done} title={<><b>{st.name}</b> <span className="muted">{st.instruction.slice(0, 90)}</span>{st.done && st.elapsed !== undefined && <span className="muted"> · {st.elapsed.toFixed(1)}s</span>}</>}>
                <Markdown text={st.text || "…"} />
              </Collapsible>
            );
          })}
          {run.tools.map((tool) => (
            <Collapsible key={tool.id} live={tool.result === undefined} title={<><IconTool size={13} /> <code>{tool.name}</code>{tool.ok === false && <span className="bad"> ✕</span>}</>}>
              <div className="tool-io">
                <div className="label">{t.tool}</div>
                <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
                {tool.result !== undefined && (<><div className="label">{t.result}</div><pre>{tool.result}</pre></>)}
                {tool.ok && tool.checkpoint && !replay && <Undo tool={tool} />}
              </div>
            </Collapsible>
          ))}
        </div>
      )}

      {run.permissions.map((p) => (
        <Permission key={p.id} p={p} onDecided={(id, s) => onPermission?.(id, s)} readOnly={replay} />
      ))}

      {(run.questions ?? []).map((q) => <Question key={q.id} q={q} readOnly={replay} />)}

      {run.trimmed ? <div className="notice">{run.trimmed} {t.contextTrimmed}</div> : null}

      {run.contract && (
        <div className={`contract small ${run.contract.valid ? "ok" : "bad"}`} title={run.contract.errors.join("\n")}>
          {run.contract.valid ? `✓ ${t.contractOk}` : `✕ ${t.contractBad}: ${run.contract.errors.join("; ")}`}
          {run.contract.attempts > 1 && <span className="muted"> · {run.contract.attempts} {t.attempts}</span>}
        </div>
      )}
      {run.text && run.contract ? (
        <pre className="json-answer"><code>{run.text}</code></pre>
      ) : run.text ? (
        <Markdown text={run.text} />
      ) : live && pending.length === 0 ? (
        <div className="typing" aria-live="polite">
          <span className="dot" /><span className="dot" /><span className="dot" />
          <span className="muted">{run.status === "planning" ? t.planning : run.status === "synthesizing" ? t.synthesizing : t.thinking}</span>
        </div>
      ) : null}

      {files.length > 0 && !replay && <Files files={files} projectId={projectId} />}

      {run.learn && !live && !replay && messageId && <Learned initial={run.learn} messageId={messageId} />}

      {run.error && <div className="error-box" role="alert">{t.error}: {run.error}</div>}
      {run.status === "stopped" && <div className="notice">{t.stopped}</div>}

      {!live && !replay && (run.text || onRetry) && (
        <div className="msg-actions">
          {run.text && <button className="icon-btn" onClick={() => { navigator.clipboard?.writeText(run.text); setCopied(true); setTimeout(() => setCopied(false), 1500); }} title={t.copy} aria-label={t.copy}>
            <IconCopy size={15} />
          </button>}
          {onRetry && <Retry providers={providers} onRetry={onRetry} failed={run.status === "error"} />}
          {onReplay && run.events?.length ? <button className="link-btn small" onClick={onReplay}>{t.replay}</button> : null}
          {copied && <span className="muted small">{t.copied}</span>}
          {run.elapsed !== undefined && <span className="muted small">{run.elapsed.toFixed(1)} s</span>}
          {sensitive && <span className="muted small disclaimer">{t.disclaimerSensitive}</span>}
        </div>
      )}
    </div>
  );
}
