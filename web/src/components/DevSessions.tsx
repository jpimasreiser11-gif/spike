import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, streamPost } from "../api";
import { projectError, t } from "../i18n";
import { applyEvent, emptyRun, recordEvent } from "../run";
import { mergeTasks, storedStatus, taskFromEvents } from "../taskSpace";
import { isolationText } from "../isolation";
import type { ChatEvent, Isolation, PermissionState, RunState } from "../types";
import { AssistantMessage } from "./AssistantMessage";
import { Markdown } from "./Markdown";
import { TaskSpace } from "./TaskSpace";
import "./DevSessions.css";

const D = t.dev;

export type DevSummary = {
  id: string; folder: string; conversation_id: string; plan: boolean; running: boolean; specialist: string;
  provider: string; model: string; history: number; broad: boolean; sandbox: string; isolation?: Isolation;
};
type Saved = { id: string; updated: number; mode: string; messages: number; preview: string };
type Change = { id: string; tool: string; created: number; undone: boolean; files: string[] };
type Message = { id: string; role: "user" | "assistant"; content: string; meta: Record<string, any> };
type Skill = { name: string; description: string; enabled: boolean };
type Turn = { key: number; user: string; skills: string[]; run: RunState };

const MAX_SKILLS = 3;
const fileSegments = (path: string) => path.split("/").map(encodeURIComponent).join("/");
const when = (seconds: number) => new Date(seconds * 1000).toLocaleString();

/** A folder-bound coding session: the same agent as `spike dev` in the terminal. Edits and commands ask first (the
 * cards of the chat, answered through /api/dev), plan mode cannot write, every file change can be undone. */
export function DevSessions({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null), alive = useRef(true), stream = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const [folder, setFolder] = useState(""), [confirmBroad, setConfirmBroad] = useState(false), [needsConfirm, setNeedsConfirm] = useState(false);
  const [open, setOpen] = useState<DevSummary[]>([]), [saved, setSaved] = useState<Saved[] | null>(null);
  const [session, setSession] = useState<DevSummary | null>(null);
  const [history, setHistory] = useState<Message[]>([]), [turns, setTurns] = useState<Turn[]>([]);
  const [changes, setChanges] = useState<Change[]>([]), [conflict, setConflict] = useState<string[] | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]), [chosen, setChosen] = useState<string[]>([]);
  const [draft, setDraft] = useState(""), [busy, setBusy] = useState(false), [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const guard = useCallback(async (fn: () => Promise<void>) => {
    setError("");
    try { await fn(); } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 409 && e.message === projectError("dev_folder_broad")) setNeedsConfirm(true);
      setError(e instanceof Error ? e.message : D.failed);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement as HTMLElement | null;
    const el = dialog.current!; el.showModal();
    api.get<{ active: DevSummary[] }>("/api/dev/sessions").then((r) => { if (alive.current) setOpen(r.active); }).catch(() => { if (alive.current) setError(D.failed); });
    return () => {
      alive.current = false;
      stream.current?.abort(); // closing the window stops a running turn, as Ctrl-C does in the terminal
      el.close(); if (previous?.isConnected) previous.focus();
    };
  }, []);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: "end" }); }, [turns, history]);

  const refresh = useCallback(async (id: string) => {
    const r = await api.get<{ changes: Change[] }>(`/api/dev/sessions/${id}/changes`);
    if (alive.current) setChanges(r.changes);
  }, []);

  const enter = useCallback(async (s: DevSummary) => {
    const [msgs, sk] = await Promise.all([
      api.get<{ messages: Message[] }>(`/api/dev/sessions/${s.id}/messages`),
      api.get<{ skills: Skill[] }>("/api/dev/skills"),
    ]);
    if (!alive.current) return;
    setSession(s); setHistory(msgs.messages); setTurns([]); setSkills(sk.skills.filter((x) => x.enabled)); setChosen([]); setConflict(null);
    setRunning(s.running);
    await refresh(s.id);
  }, [refresh]);

  const openSession = (body: Record<string, unknown>) => guard(async () => {
    setBusy(true);
    try {
      const s = await api.post<DevSummary>("/api/dev/sessions", { folder: folder.trim(), confirm_broad: confirmBroad, ...body });
      await enter(s);
    } finally { if (alive.current) setBusy(false); }
  });
  const listSaved = () => guard(async () => {
    const r = await api.get<{ sessions: Saved[] }>(`/api/dev/history?folder=${encodeURIComponent(folder.trim())}`);
    if (alive.current) setSaved(r.sessions);
  });
  const endSession = () => guard(async () => {
    if (!session) return;
    await api.del(`/api/dev/sessions/${session.id}`);
    if (!alive.current) return;
    setOpen((o) => o.filter((x) => x.id !== session.id)); setSession(null); setSaved(null); setTurns([]); setHistory([]); setChanges([]);
  });
  const setMode = (plan: boolean) => guard(async () => {
    if (!session || running) return;
    const r = await api.post<{ plan: boolean }>(`/api/dev/sessions/${session.id}/mode`, { plan });
    if (alive.current) setSession({ ...session, plan: r.plan });
  });
  const newConversation = () => guard(async () => {
    if (!session || running) return;
    const r = await api.post<{ conversation_id: string }>(`/api/dev/sessions/${session.id}/clear`);
    if (alive.current) { setSession({ ...session, conversation_id: r.conversation_id }); setHistory([]); setTurns([]); }
  });

  const send = async () => {
    const text = draft.trim();
    if (!session || !text || running) return;
    const key = Date.now(), id = session.id, used = chosen;
    setDraft(""); setError(""); setRunning(true);
    setTurns((all) => [...all, { key, user: text, skills: used, run: { ...emptyRun(), status: "running" } }]);
    const update = (fn: (run: RunState) => RunState) => alive.current && setTurns((all) => all.map((x) => (x.key === key ? { ...x, run: fn(x.run) } : x)));
    const ctl = new AbortController(); stream.current = ctl;
    const started = performance.now();
    try {
      await streamPost(`/api/dev/sessions/${id}/turn`, { message: text, skills: used }, (ev: ChatEvent) =>
        update((run) => (ev.type === "stopped" ? { ...run, status: "stopped" }
          : { ...applyEvent(run, ev), events: recordEvent(run.events, ev, (performance.now() - started) / 1000) })), ctl.signal);
      update((run) => (run.status === "running" ? { ...run, status: "done" } : run));
    } catch (e) {
      if (!ctl.signal.aborted) update((run) => ({ ...run, status: "error", error: e instanceof Error ? e.message : D.failed }));
    } finally {
      if (alive.current) { setRunning(false); setChosen([]); await refresh(id).catch(() => {}); }
      if (stream.current === ctl) stream.current = null;
    }
  };
  const stop = () => guard(async () => { if (session) await api.post(`/api/dev/sessions/${session.id}/cancel`); });
  const decided = (key: number) => (permission: string, status: PermissionState["status"]) =>
    setTurns((all) => all.map((x) => (x.key === key ? { ...x, run: { ...x.run, permissions: x.run.permissions.map((p) => (p.id === permission ? { ...p, status } : p)) } } : x)));

  const undo = (force: boolean) => guard(async () => {
    if (!session) return;
    const res = await fetch(`/api/dev/sessions/${session.id}/undo`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force }) });
    if (res.status === 409) {
      const data = await res.json();
      if (alive.current) setConflict(data.changed ?? []);
      return;
    }
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText);
    if (alive.current) setConflict(null);
    await refresh(session.id);
  });

  const pending = changes.filter((c) => !c.undone);
  const deliverables = [...new Set(pending.flatMap((c) => c.files))];
  // O2: the session's task space, rebuilt from the events kept with each saved answer plus the turns of this window
  const task = useMemo(() => ({
    ...mergeTasks([
      ...history.filter((m) => m.role === "assistant").map((m, i) =>
        taskFromEvents(m.meta?.events ?? [], { status: storedStatus(m.meta), tools: [] }, i)),
      ...turns.map((turn) => taskFromEvents(turn.run.events ?? [], turn.run, turn.key)),
    ]),
    deliverables: deliverables.map((path) => ({ path, ok: true })),
  }), [history, turns, changes]); // eslint-disable-line react-hooks/exhaustive-deps -- deliverables come from changes
  const toggleSkill = (name: string) => setChosen((c) => (c.includes(name) ? c.filter((x) => x !== name) : c.length < MAX_SKILLS ? [...c, name] : c));

  return (
    <dialog ref={dialog} className="dev-sessions" aria-labelledby="dev-heading" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <header><div><span className="dev-eyebrow">SPIKE Dev</span><h2 id="dev-heading">{D.title}</h2></div>
        <button className="btn" data-testid="dev-close" onClick={onClose}>{D.closeWindow}</button></header>
      {error && <p className="notice error" role="alert" data-testid="dev-error">{error}</p>}

      {!session && <section className="dev-start" aria-label={D.openFolder}>
        <p>{D.intro}</p>
        <form onSubmit={(e) => { e.preventDefault(); if (folder.trim() && !busy) void openSession({}); }}>
          <label>{D.folder}<input name="dev-folder" value={folder} placeholder={D.folderPlaceholder} autoComplete="off" spellCheck={false}
            onChange={(e) => { setFolder(e.target.value); setNeedsConfirm(false); setConfirmBroad(false); setSaved(null); }} /></label>
          <p className="dev-hint">{D.folderHint}</p>
          {needsConfirm && <label className="dev-check dev-warn"><input type="checkbox" name="dev-broad" checked={confirmBroad} onChange={(e) => setConfirmBroad(e.target.checked)} />{D.broadConfirm}</label>}
          <div className="dev-actions">
            <button className="btn primary" type="submit" data-testid="dev-open" disabled={busy || !folder.trim() || (needsConfirm && !confirmBroad)}>{D.open}</button>
            <button className="btn" type="button" data-testid="dev-saved" disabled={busy || !folder.trim()} onClick={() => void listSaved()}>{D.showSaved}</button>
          </div>
        </form>
        {saved && <div data-testid="dev-saved-list">
          <h3>{D.savedTitle}</h3>
          {saved.length === 0 ? <p className="dev-hint">{D.noSaved}</p> : <ul className="dev-list">{saved.map((s) => <li key={s.id}>
            <div><b>{s.preview || D.noPreview}</b><small>{when(s.updated)} · {s.messages} {D.messages}</small></div>
            <button className="btn" disabled={busy} aria-label={`${D.resume}: ${s.preview || s.id}`} onClick={() => void openSession({ resume_id: s.id })}>{D.resume}</button></li>)}</ul>}
        </div>}
        {open.length > 0 && <div>
          <h3>{D.openTitle}</h3>
          <ul className="dev-list">{open.map((s) => <li key={s.id}>
            <div><code>{s.folder}</code><small>{s.running ? D.runningNow : D.idle}</small></div>
            <button className="btn" disabled={busy} onClick={() => void guard(() => enter(s))}>{D.continue}</button></li>)}</ul>
        </div>}
      </section>}

      {session && <div className="dev-work">
        <section className="dev-main" aria-label={D.conversation}>
          <div className="dev-bar">
            <div><code title={session.folder}>{session.folder}</code>
              <small>{session.provider}{session.model ? ` · ${session.model}` : ""} · {D.sandbox}: {session.isolation ? isolationText(session.isolation) : session.sandbox}</small></div>
            <button className="btn" data-testid="dev-end" disabled={busy} onClick={() => void endSession()}>{D.endSession}</button>
          </div>
          {session.broad && <p className="notice warn" role="note">{D.broadNote}</p>}
          <div className="dev-mode" role="group" aria-label={D.mode}>
            <button type="button" className={`btn ${session.plan ? "primary" : ""}`} aria-pressed={session.plan} data-testid="dev-plan" disabled={running} onClick={() => void setMode(true)}>{D.plan}</button>
            <button type="button" className={`btn ${session.plan ? "" : "primary"}`} aria-pressed={!session.plan} data-testid="dev-act" disabled={running} onClick={() => void setMode(false)}>{D.act}</button>
            <button type="button" className="btn" disabled={running} onClick={() => void newConversation()}>{D.newConversation}</button>
          </div>
          <p className="dev-hint" data-testid="dev-mode-hint">{session.plan ? D.planHint : D.actHint}</p>
          <div className="dev-log" aria-live="polite" data-testid="dev-log">
            {history.length > 0 && <p className="dev-hint">{D.earlier}</p>}
            {history.map((m) => <div key={m.id} className={`dev-msg ${m.role}`} data-role={m.role}>
              <b>{m.role === "user" ? D.you : "SPIKE"}{m.meta?.dev_mode === "plan" ? ` · ${D.plan}` : ""}{m.meta?.stopped ? ` · ${D.stopped}` : ""}</b>
              {m.role === "user" ? <p>{m.content}</p> : <Markdown text={m.content} />}</div>)}
            {turns.map((turn) => <div key={turn.key} className="dev-turn">
              <div className="dev-msg user" data-role="user"><b>{D.you}{turn.skills.length ? ` · ✦ ${turn.skills.join(", ")}` : ""}</b><p>{turn.user}</p></div>
              <AssistantMessage run={turn.run} specialists={[]} onPermission={decided(turn.key)} apiBase="/api/dev"
                fileUrl={(path) => `/api/dev/sessions/${session.id}/files/${fileSegments(path)}`} />
            </div>)}
            <div ref={bottom} />
          </div>
          <form className="dev-composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
            {skills.length > 0 && <details className="dev-skills">
              <summary>{D.skills}{chosen.length ? ` (${chosen.length})` : ""}</summary>
              <p className="dev-hint">{D.skillsHint}</p>
              {skills.map((s) => <label key={s.name} className="dev-check" title={s.description}>
                <input type="checkbox" name={`dev-skill-${s.name}`} checked={chosen.includes(s.name)} disabled={running || (!chosen.includes(s.name) && chosen.length >= MAX_SKILLS)}
                  onChange={() => toggleSkill(s.name)} />{s.name}</label>)}
            </details>}
            <textarea name="dev-input" rows={3} value={draft} placeholder={session.plan ? D.planPlaceholder : D.actPlaceholder} aria-label={D.message}
              onChange={(e) => setDraft(e.target.value)} disabled={running}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void send(); } }} />
            <div className="dev-actions">
              {running
                ? <button type="button" className="btn danger" data-testid="dev-stop" onClick={() => void stop()}>{t.stop}</button>
                : <button type="submit" className="btn primary" data-testid="dev-send" disabled={!draft.trim()}>{D.send}</button>}
              <small className="dev-hint">{D.sendHint}</small>
            </div>
          </form>
        </section>

        <aside className="dev-side" aria-label={t.task.title}>
          <h3 className="dev-side-title">{t.task.title}</h3>
          <TaskSpace view={task} urlFor={(path) => `/api/dev/sessions/${session.id}/files/${fileSegments(path)}`} files={<>
            {changes.length === 0 ? <p className="dev-hint" data-testid="dev-no-changes">{D.noChanges}</p> : <ol className="dev-changes" data-testid="dev-changes">
              {changes.map((c) => <li key={c.id} data-undone={c.undone}><code>{c.tool}</code> {c.files.join(", ")}{c.undone ? <small> · {D.undone}</small> : null}</li>)}
            </ol>}
            <p className="dev-hint">{D.undoHint}</p>
            <button className="btn" data-testid="dev-undo" disabled={running || pending.length === 0} onClick={() => void undo(false)}>{D.undoLast}</button>
            {conflict && <div className="notice warn" role="alertdialog" aria-label={D.conflictTitle} data-testid="dev-conflict">
              <b>{D.conflictTitle}</b>
              <ul>{conflict.map((p) => <li key={p}><code>{p}</code></li>)}</ul>
              <div className="dev-actions">
                <button className="btn danger" data-testid="dev-undo-force" onClick={() => void undo(true)}>{D.undoAnyway}</button>
                <button className="btn" onClick={() => setConflict(null)}>{D.keep}</button>
              </div>
            </div>}
          </>} />
        </aside>
      </div>}
    </dialog>
  );
}
