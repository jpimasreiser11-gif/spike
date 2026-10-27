import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamChat } from "./api";
import { ArtifactContext, type ArtifactDoc, ArtifactPanel } from "./components/Artifact";
import { AssistantMessage } from "./components/AssistantMessage";
import { Composer } from "./components/Composer";
import { D as DESKTOP, DesktopTask } from "./components/Desktop";
import { Forge } from "./components/Forge";
import { Creator, type CreatorExtra } from "./components/Creator";
import { IconBack, IconDesktop, IconEdit, IconFolder, IconForge, IconSparkle, IconMoon, IconPlus, IconSettings, IconSidebar, IconSun, IconTrash, IconUpload, IconTimer } from "./components/Icons";
import { Lab } from "./components/Lab";
import { Markdown } from "./components/Markdown";
import { PL, ProjectDialog, ProjectPanel } from "./components/Projects";
import { ProofDownload } from "./components/ProofDownload";
import { Replay } from "./components/Replay";
import { SettingsDialog } from "./components/SettingsDialog";
import { SpecMark } from "./components/SpecMark";
import { t } from "./i18n";
import { applyEvent, emptyRun, recordEvent, runFromStored } from "./run";
import type { Blueprint, ChatEvent, Conversation, DesignSystemInfo, MindsSpec, PermissionState, Project, ProviderInfo, RunState, Specialist, StoredMessage } from "./types";

type Item = { kind: "user"; text: string; images?: string[]; id?: string } | { kind: "assistant"; run: RunState };

/** A sent message, editable in place: sending the edit replaces it and everything after it, or goes on in a branch
 * (a copy of the chat up to this message) so the original stays as it was. */
function UserMessage({ text, images, onEdit, onBranch }: { images?: string[]; text: string; onEdit?: (text: string) => void; onBranch?: (text: string) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  if (draft !== null) {
    return (
      <div className="msg user editing">
        <textarea className="bubble-edit" aria-label={t.edit} rows={Math.min(10, draft.split("\n").length + 1)} value={draft}
          autoFocus onChange={(e) => setDraft(e.target.value)} />
        <div className="row">
          <button className="btn" onClick={() => setDraft(null)}>{t.cancel}</button>
          {onBranch && <button className="btn" disabled={!draft.trim()} title={t.branchHint} onClick={() => { onBranch(draft.trim()); setDraft(null); }}>{t.sendBranch}</button>}
          <button className="btn primary" disabled={!draft.trim()} onClick={() => { onEdit?.(draft.trim()); setDraft(null); }}>{t.resend}</button>
        </div>
      </div>
    );
  }
  return (
    <div className="msg user">
      {onEdit && <button className="icon-btn edit-btn" onClick={() => setDraft(text)} title={t.edit} aria-label={t.edit}><IconEdit size={14} /></button>}
      <div className="bubble"><Markdown text={text} />{images?.map((image, i) => <img key={i} src={image}
        alt={`${t.media.image} ${i + 1}`} style={{ maxWidth: "100%", maxHeight: 240 }} />)}</div>
    </div>
  );
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem("spike-theme") || "auto";
    } catch {
      return "auto";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("spike-theme", theme);
    } catch {
      /* private mode */
    }
  }, [theme]);
  const dark = theme === "dark" || (theme === "auto" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  return [dark ? "dark" : "light", () => setTheme(dark ? "light" : "dark")];
}

function groupByDate(convs: Conversation[]) {
  const now = Date.now() / 1000;
  const groups: Record<string, Conversation[]> = {};
  const label = (ts: number) => {
    const days = (now - ts) / 86400;
    if (days < 1) return lang("Hoy", "Today");
    if (days < 7) return lang("Últimos 7 días", "Previous 7 days");
    if (days < 30) return lang("Últimos 30 días", "Previous 30 days");
    return lang("Anteriores", "Older");
  };
  for (const c of convs) (groups[label(c.updated)] ||= []).push(c);
  return Object.entries(groups);
}
const lang = (es: string, en: string) => (t.newChat === "Nuevo chat" ? es : en);

export default function App() {
  const [specialists, setSpecialists] = useState<Specialist[]>([]);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [projectDialog, setProjectDialog] = useState<Project | "new" | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [artifact, setArtifact] = useState<ArtifactDoc | null>(null);
  const [replay, setReplay] = useState<ChatEvent[] | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("auto");
  const [temporary, setTemporary] = useState(false); // a chat kept in memory only, without SPIKE's memory
  const [providerId, setProviderId] = useState<string | null>(null);
  const [designs, setDesigns] = useState<DesignSystemInfo[]>([]);
  const [design, setDesign] = useState(""); // "" = the project's design system (or none)
  const [sidebar, setSidebar] = useState(() => window.innerWidth > 860);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [forgeOpen, setForgeOpen] = useState(false);
  const [labOpen, setLabOpen] = useState(false);
  const [creatorOpen, setCreatorOpen] = useState(false);
  const [desktopOpen, setDesktopOpen] = useState(false);
  const [desktopOn, setDesktopOn] = useState(false); // desktop actions are turned on in Settings
  const [engine, setEngine] = useState<{ running: boolean } | null>(null);
  const [fatal, setFatal] = useState("");
  const [theme, toggleTheme] = useTheme();
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const importRef = useRef<HTMLInputElement>(null);
  const viewContext = useRef(new Map<string, { view: string; name: string; text: string }>());

  useEffect(() => { // `ui/update-model-context` from an MCP App: the latest per view goes with the next message
    const onContext = (e: Event) => {
      const c = (e as CustomEvent<{ view: string; name: string; text: string }>).detail;
      if (c?.text) viewContext.current.set(c.view, c);
      else if (c) viewContext.current.delete(c.view);
    };
    window.addEventListener("spike:view-context", onContext);
    return () => window.removeEventListener("spike:view-context", onContext);
  }, []);

  const projectId = project?.id;
  const loadConversations = useCallback(
    () => api.get<Conversation[]>(`/api/conversations${projectId ? `?project_id=${projectId}` : ""}`).then(setConversations),
    [projectId],
  );
  const loadProjects = useCallback(() => api.get<Project[]>("/api/projects").then(setProjects), []);
  const loadProviders = useCallback(() => api.get<ProviderInfo[]>("/api/providers").then(setProviders), []);
  const loadDesigns = useCallback(() => api.get<DesignSystemInfo[]>("/api/design-systems").then(setDesigns), []);
  const loadDesktop = useCallback(() => api.get<{ settings: { enabled: boolean } }>("/api/desktop").then((d) => setDesktopOn(d.settings.enabled)).catch(() => {}), []);

  useEffect(() => {
    Promise.all([
      api.get<Specialist[]>("/api/specialists").then(setSpecialists),
      loadProviders(),
      loadProjects(),
      loadDesigns(),
      loadDesktop(),
      api.get<{ running: boolean }>("/api/runtime").then(setEngine),
    ]).catch((e) => setFatal(String(e.message || e)));
  }, [loadProjects, loadProviders, loadDesigns, loadDesktop]);

  useEffect(() => {
    loadConversations().catch((e) => setFatal(String(e.message || e)));
  }, [loadConversations]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [items]);

  const openConversation = async (id: string) => {
    if (busy) return;
    setForgeOpen(false);
    setCreatorOpen(false);
    const conv = await api.get<Conversation & { messages: StoredMessage[] }>(`/api/conversations/${id}`);
    setActiveId(id);
    setArtifact(null);
    setMode(conv.mode || "auto");
    setTemporary(Boolean((conv as { temporary?: boolean }).temporary));
    setItems(conv.messages.map((m) => (m.role === "user" ? { kind: "user", text: m.content, images: m.meta.images, id: m.id } : { kind: "assistant", run: runFromStored(m) })));
    if (window.innerWidth <= 860) setSidebar(false);
  };

  const newChat = () => {
    if (busy) abortRef.current?.abort();
    setForgeOpen(false);
    setCreatorOpen(false);
    setActiveId(null);
    setItems([]);
    setArtifact(null);
    setTemporary(false);
    if (project) setMode(project.mode);
  };

  const selectProject = (p: Project | null) => {
    if (busy) abortRef.current?.abort();
    setProject(p);
    setActiveId(null);
    setItems([]);
    setArtifact(null);
    setMode(p?.mode ?? "auto");
    if (window.innerWidth <= 860) setSidebar(false);
  };

  const importProject = async (file: File | undefined) => {
    if (!file) return;
    try {
      const p = await api.upload<Project>("POST", "/api/projects/import", file);
      await loadProjects();
      selectProject(p);
    } catch (e) {
      setFatal(String((e as Error).message));
    }
    if (importRef.current) importRef.current.value = "";
  };

  const updateLast = (fn: (r: RunState) => RunState) =>
    setItems((prev) => {
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last?.kind === "assistant") next[next.length - 1] = { kind: "assistant", run: fn(last.run) };
      return next;
    });

  /** Send a message; `from` (an index into items) replaces that user message and everything after it. */
  const send = async (text: string, from?: number, provider: string | null = providerId, conversationId = activeId, schema?: object,
                    specialist?: string, forge?: Blueprint, extra?: CreatorExtra, minds?: MindsSpec, images?: string[]) => {
    const replaced = from !== undefined ? items[from] : undefined;
    images = images ?? (replaced?.kind === "user" ? replaced.images : undefined);
    const replaceFrom = replaced?.kind === "user" ? replaced.id : undefined;
    if (from !== undefined && !replaceFrom) return; // not saved yet: nothing to replace
    setItems((prev) => [...(from !== undefined ? prev.slice(0, from) : prev), { kind: "user", text, images },
      { kind: "assistant", run: { ...emptyRun(), status: "running" } }]);
    setBusy(true);
    stick.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    const started = performance.now();
    const views = [...viewContext.current.values()].slice(-4); // what MCP App views reported, for this turn only
    viewContext.current.clear();
    try {
      await streamChat({ message: text, images, conversation_id: conversationId, mode: specialist ?? mode, provider_id: provider, project_id: project?.id ?? null,
                         replace_from: replaceFrom ?? null, temporary: temporary && !conversationId,
                         ...(schema ? { response_schema: schema } : {}), ...(forge ? { forge } : {}), ...(minds ? { parallel_minds: minds } : {}),
                         ...(extra?.design_system || design ? { design_system: extra?.design_system || design } : {}),
                         ...(extra?.skills.length ? { skills: extra.skills } : {}),
                         ...(views.length ? { view_context: views } : {}) }, (ev) => {
        if (ev.type === "conversation") {
          setActiveId(ev.id);
          setItems((prev) => prev.map((it, i) => (i === prev.length - 2 && it.kind === "user" ? { ...it, id: ev.user_message_id } : it)));
          loadConversations();
        } else {
          const at = Math.round(performance.now() - started) / 1000;
          updateLast((r) => ({ ...applyEvent(r, ev), events: recordEvent(r.events, ev, at) }));
        }
      }, controller.signal);
    } catch (e) {
      const aborted = (e as Error).name === "AbortError";
      updateLast((r) => ({ ...r, status: aborted ? "stopped" : "error", error: aborted ? undefined : String((e as Error).message) }));
    } finally {
      setBusy(false);
      abortRef.current = null;
      loadConversations();
    }
  };

  /** Run the last turn again; with another specialist, the router first notes it to learn from (Evolution). */
  const retry = async (from: number, provider: string | null, specialist?: string) => {
    const target = items[from];
    if (target?.kind !== "user") return;
    if (specialist && target.id) {
      try { await api.post(`/api/messages/${target.id}/route`, { specialist }); } catch { /* learning is optional */ }
    }
    await send(target.text, from, provider, activeId, undefined, specialist, undefined, undefined, undefined, target.images);
  };

  /** Copy the chat up to user message `from` and send the edited text there; the original chat stays as it was. */
  const branch = async (text: string, from: number) => {
    const target = items[from];
    if (target?.kind !== "user" || !target.id || !activeId) return;
    const title = conversations.find((c) => c.id === activeId)?.title;
    try {
      const conv = await api.post<Conversation>(`/api/conversations/${activeId}/branch`,
        { before: target.id, title: title ? `${title} · ${t.branch}` : undefined });
      setActiveId(conv.id);
      setItems((prev) => prev.slice(0, from));
      await send(text, undefined, providerId, conv.id, undefined, undefined, undefined, undefined, undefined, target.images);
    } catch (e) {
      setFatal(String((e as Error).message));
    }
  };

  /** Run an approved Forge blueprint as a new chat: the team's trace and the report show up as its answer. */
  const runForge = (task: string, blueprint: Blueprint, provider: string | null, extra?: CreatorExtra) => {
    setForgeOpen(false);
    setCreatorOpen(false);
    setActiveId(null);
    setItems([]);
    setArtifact(null);
    setTemporary(false);
    send(task, undefined, provider, null, undefined, undefined, blueprint, extra);
  };

  const onPermission = (id: string, status: PermissionState["status"]) =>
    updateLast((r) => ({ ...r, permissions: r.permissions.map((p) => (p.id === id ? { ...p, status } : p)) }));

  const remove = async (id: string) => {
    await api.del(`/api/conversations/${id}`);
    if (id === activeId) newChat();
    loadConversations();
  };

  const empty = items.length === 0;
  const lastUser = items.map((it) => it.kind).lastIndexOf("user");
  const composer = (
    <Composer onSend={(text, schema, minds, images) => send(text, undefined, providerId, activeId, schema, undefined, undefined, undefined, minds, images)}
      onStop={() => abortRef.current?.abort()} busy={busy} mode={mode} setMode={setMode} projectId={project?.id} conversationId={activeId}
      providerId={providerId} setProviderId={setProviderId} specialists={specialists.filter((s) => s.id !== "core")}
      providers={providers} followUp={!empty} autoFocus designs={designs} design={design} setDesign={setDesign}
      projectDesign={designs.find((d) => d.id === project?.design)?.name} />
  );

  return (
    <ArtifactContext.Provider value={setArtifact}>
    <div className={`app ${sidebar ? "with-sidebar" : ""} ${artifact ? "with-artifact" : ""}`}>
      <aside className="sidebar" aria-label="Conversations">
        <div className="sidebar-top">
          <div className="brand"><img src="/spike-mark.png" alt="" width={30} height={30} /><span className="wordmark">SPIKE</span></div>
          <button className="icon-btn" onClick={() => setSidebar(false)} aria-label="Close sidebar"><IconSidebar /></button>
        </div>
        <button className="new-chat" onClick={newChat}><IconPlus size={16} /> {t.newChat}</button>
        <button className={`side-btn forge-btn ${forgeOpen ? "active" : ""}`} onClick={() => { if (!busy) { setCreatorOpen(false); setForgeOpen(true); if (window.innerWidth <= 860) setSidebar(false); } }} disabled={busy}><IconForge size={16} /> Forge</button>
        <button className={`side-btn forge-btn ${creatorOpen ? "active" : ""}`} onClick={() => { if (!busy) { setForgeOpen(false); setCreatorOpen(true); if (window.innerWidth <= 860) setSidebar(false); } }} disabled={busy}><IconSparkle size={16} /> {t.create}</button>
        <div className="project-list" aria-label={PL.projects}>
          <div className="conv-group project-list-head">
            <span>{PL.projects}</span>
            <button className="icon-btn" onClick={() => importRef.current?.click()} aria-label={PL.importProject} title={PL.importProject}><IconUpload size={14} /></button>
            <button className="icon-btn" onClick={() => setProjectDialog("new")} aria-label={PL.newProject} title={PL.newProject}><IconPlus size={14} /></button>
            <input ref={importRef} type="file" accept=".zip,application/zip" hidden data-testid="project-import" onChange={(e) => importProject(e.target.files?.[0])} />
          </div>
          {projects.map((p) => (
            <button key={p.id} className={`project-item ${project?.id === p.id ? "active" : ""}`} onClick={() => selectProject(project?.id === p.id ? null : p)} title={p.name}>
              <IconFolder size={15} /> <span>{p.name}</span>
            </button>
          ))}
        </div>
        {project && <button className="side-btn back" onClick={() => selectProject(null)}><IconBack size={15} /> {PL.back}</button>}
        <nav className="conv-list">
          {groupByDate(conversations).map(([label, list]) => (
            <div key={label}>
              <div className="conv-group">{label}</div>
              {list.map((c) => (
                <div key={c.id} className={`conv ${c.id === activeId ? "active" : ""}`}>
                  <button className="conv-title" onClick={() => openConversation(c.id)} title={c.title}>{c.title}</button>
                  <button className="icon-btn conv-del" onClick={() => remove(c.id)} aria-label={t.deleteChat}><IconTrash size={14} /></button>
                </div>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          {desktopOn && <button className="side-btn" data-testid="desktop-open" onClick={() => setDesktopOpen(true)}><IconDesktop size={16} /> {DESKTOP.open}</button>}
          <button className="side-btn" onClick={() => setSettingsOpen(true)}><IconSettings size={16} /> {t.settings}</button>
          <div className="engine-status" title={t.localEngine}>
            <span className={`status-dot ${engine?.running ? "on" : ""}`} /> {t.localEngine}: {engine?.running ? t.running : t.stopped2}
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          {!sidebar && <button className="icon-btn" onClick={() => setSidebar(true)} aria-label="Open sidebar"><IconSidebar /></button>}
          {!sidebar && <button className="icon-btn" onClick={newChat} aria-label={t.newChat}><IconPlus /></button>}
          {project && <span className="crumb"><IconFolder size={15} /> {project.name}</span>}
          <div className="spacer" />
          <button className="btn small" disabled={busy} onClick={() => setLabOpen(true)}>{t.lab.title}</button>
          {(empty || temporary) && (
            <button className={`btn small temp-toggle ${temporary ? "on" : ""}`} aria-pressed={temporary} disabled={!empty}
              onClick={() => setTemporary(!temporary)} title={t.temporaryHint}><IconTimer size={15} /> {t.temporaryChat}</button>
          )}
          {activeId && !empty && !busy && (
            <ProofDownload key={activeId} conversationId={activeId} />
          )}
          <button className="icon-btn" onClick={toggleTheme} aria-label="Toggle theme">{theme === "dark" ? <IconSun /> : <IconMoon />}</button>
        </header>

        {fatal && <div className="fatal"><img src="/states/error.webp" alt="" width={150} height={111} /><div className="error-box" role="alert">{fatal}</div></div>}

        {labOpen ? (
          <Lab specialists={specialists} providers={providers} onClose={() => setLabOpen(false)} />
        ) : creatorOpen ? (
          <Creator specialists={specialists} providers={providers} projectId={project?.id} designs={designs} projectDesign={project?.design}
            onRun={runForge} onClose={() => setCreatorOpen(false)} />
        ) : forgeOpen ? (
          <Forge specialists={specialists} providers={providers} projectId={project?.id} onRun={runForge} onClose={() => setForgeOpen(false)} />
        ) : empty ? (
          <section className="welcome">
            {project ? (
              <ProjectPanel project={project} specialists={specialists} designs={designs} onEdit={() => setProjectDialog(project)} />
            ) : (
              <>
                {!fatal && <img className="welcome-mark" src="/states/empty-chat.webp" alt="" width={220} height={144} />}
                <h1>{temporary ? t.temporaryChat : t.greeting}</h1>
                <p className="muted">{temporary ? t.temporaryHint : t.greetingSub}</p>
              </>
            )}
            <div className="welcome-composer">{composer}</div>
            {!project && <div className="spec-chips">
              {specialists.filter((s) => s.id !== "core").map((s) => (
                <button key={s.id} className={`chip spec-${s.id} ${mode === s.id ? "selected" : ""}`} onClick={() => setMode(mode === s.id ? "auto" : s.id)} title={s.description}>
                  <SpecMark id={s.id} />{s.name.replace("Spike ", "")}
                </button>
              ))}
            </div>}
          </section>
        ) : (
          <>
            <div className="thread" ref={scrollRef} onScroll={(e) => {
              const el = e.currentTarget;
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}>
              <div className="thread-inner">
                {temporary && <div className="notice temp-notice"><IconTimer size={14} /> {t.temporaryHint}</div>}
                {items.map((it, i) =>
                  it.kind === "user" ? (
                    <UserMessage key={i} text={it.text} images={it.images} onEdit={!busy && it.id ? (text) => send(text, i) : undefined}
                      onBranch={!busy && it.id && activeId ? (text) => branch(text, i) : undefined} />
                  ) : (
                    <AssistantMessage key={i} run={it.run} specialists={specialists} onPermission={onPermission} projectId={project?.id}
                      providers={providers} onReplay={() => setReplay(it.run.events ?? null)}
                      messageId={items[i - 1]?.kind === "user" ? (items[i - 1] as { id?: string }).id : undefined}
                      question={items[i - 1]?.kind === "user" ? (items[i - 1] as { text: string }).text : undefined}
                      onRetry={!busy && i === items.length - 1 && lastUser === i - 1 && items[lastUser].kind === "user"
                        ? (pid, specialist) => retry(lastUser, pid ?? providerId, specialist) : undefined} />
                  ),
                )}
              </div>
            </div>
            <div className="bottom-composer">{composer}</div>
          </>
        )}
      </main>

      {artifact && <ArtifactPanel doc={artifact} onClose={() => setArtifact(null)} />}

      {replay && <Replay events={replay} specialists={specialists} onClose={() => setReplay(null)} />}

      {projectDialog && (
        <ProjectDialog project={projectDialog === "new" ? null : projectDialog} specialists={specialists} designs={designs} onClose={() => setProjectDialog(null)}
          onSaved={(p) => { setProjectDialog(null); loadProjects(); selectProject(p); }}
          onDeleted={() => { setProjectDialog(null); loadProjects(); selectProject(null); }} />
      )}

      {settingsOpen && (
        <SettingsDialog onClose={() => { setSettingsOpen(false); loadProviders(); loadDesigns(); loadDesktop(); api.get<{ running: boolean }>("/api/runtime").then(setEngine); }}
          onDesktop={() => { setSettingsOpen(false); loadProviders(); loadDesktop(); setDesktopOpen(true); }}
          specialists={specialists} providers={providers} reloadProviders={loadProviders} />
      )}

      {desktopOpen && (
        <DesktopTask onClose={() => { setDesktopOpen(false); loadProviders(); }} onFinished={loadConversations}
          onChat={(id) => { setDesktopOpen(false); openConversation(id); }} />
      )}
    </div>
    </ArtifactContext.Provider>
  );
}
