import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamChat } from "./api";
import { AssistantMessage } from "./components/AssistantMessage";
import { Composer } from "./components/Composer";
import { IconMoon, IconPlus, IconSettings, IconSidebar, IconSun, IconTrash } from "./components/Icons";
import { Markdown } from "./components/Markdown";
import { SettingsDialog } from "./components/SettingsDialog";
import { SpecMark } from "./components/SpecMark";
import { t } from "./i18n";
import { applyEvent, emptyRun, runFromStored } from "./run";
import type { Conversation, PermissionState, ProviderInfo, RunState, Specialist, StoredMessage } from "./types";

type Item = { kind: "user"; text: string } | { kind: "assistant"; run: RunState };

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
  const [activeId, setActiveId] = useState<string | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("auto");
  const [providerId, setProviderId] = useState<string | null>(null);
  const [sidebar, setSidebar] = useState(() => window.innerWidth > 860);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [engine, setEngine] = useState<{ running: boolean } | null>(null);
  const [fatal, setFatal] = useState("");
  const [theme, toggleTheme] = useTheme();
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const loadConversations = useCallback(() => api.get<Conversation[]>("/api/conversations").then(setConversations), []);
  const loadProviders = useCallback(() => api.get<ProviderInfo[]>("/api/providers").then(setProviders), []);

  useEffect(() => {
    Promise.all([
      api.get<Specialist[]>("/api/specialists").then(setSpecialists),
      loadProviders(),
      loadConversations(),
      api.get<{ running: boolean }>("/api/runtime").then(setEngine),
    ]).catch((e) => setFatal(String(e.message || e)));
  }, [loadConversations, loadProviders]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [items]);

  const openConversation = async (id: string) => {
    if (busy) return;
    const conv = await api.get<Conversation & { messages: StoredMessage[] }>(`/api/conversations/${id}`);
    setActiveId(id);
    setMode(conv.mode || "auto");
    setItems(conv.messages.map((m) => (m.role === "user" ? { kind: "user", text: m.content } : { kind: "assistant", run: runFromStored(m) })));
    if (window.innerWidth <= 860) setSidebar(false);
  };

  const newChat = () => {
    if (busy) abortRef.current?.abort();
    setActiveId(null);
    setItems([]);
  };

  const updateLast = (fn: (r: RunState) => RunState) =>
    setItems((prev) => {
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last?.kind === "assistant") next[next.length - 1] = { kind: "assistant", run: fn(last.run) };
      return next;
    });

  const send = async (text: string) => {
    setItems((prev) => [...prev, { kind: "user", text }, { kind: "assistant", run: { ...emptyRun(), status: "running" } }]);
    setBusy(true);
    stick.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamChat({ message: text, conversation_id: activeId, mode, provider_id: providerId }, (ev) => {
        if (ev.type === "conversation") {
          setActiveId(ev.id);
          loadConversations();
        } else updateLast((r) => applyEvent(r, ev));
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

  const onPermission = (id: string, status: PermissionState["status"]) =>
    updateLast((r) => ({ ...r, permissions: r.permissions.map((p) => (p.id === id ? { ...p, status } : p)) }));

  const remove = async (id: string) => {
    await api.del(`/api/conversations/${id}`);
    if (id === activeId) newChat();
    loadConversations();
  };

  const empty = items.length === 0;
  const composer = (
    <Composer onSend={send} onStop={() => abortRef.current?.abort()} busy={busy} mode={mode} setMode={setMode}
      providerId={providerId} setProviderId={setProviderId} specialists={specialists.filter((s) => s.id !== "core")}
      providers={providers} followUp={!empty} autoFocus />
  );

  return (
    <div className={`app ${sidebar ? "with-sidebar" : ""}`}>
      <aside className="sidebar" aria-label="Conversations">
        <div className="sidebar-top">
          <div className="brand"><img src="/spike-mark.png" alt="" width={30} height={30} /><span className="wordmark">SPIKE</span></div>
          <button className="icon-btn" onClick={() => setSidebar(false)} aria-label="Close sidebar"><IconSidebar /></button>
        </div>
        <button className="new-chat" onClick={newChat}><IconPlus size={16} /> {t.newChat}</button>
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
          <div className="spacer" />
          <button className="icon-btn" onClick={toggleTheme} aria-label="Toggle theme">{theme === "dark" ? <IconSun /> : <IconMoon />}</button>
        </header>

        {fatal && <div className="fatal"><img src="/states/error.webp" alt="" width={150} height={111} /><div className="error-box" role="alert">{fatal}</div></div>}

        {empty ? (
          <section className="welcome">
            {!fatal && <img className="welcome-mark" src="/states/empty-chat.webp" alt="" width={220} height={144} />}
            <h1>{t.greeting}</h1>
            <p className="muted">{t.greetingSub}</p>
            <div className="welcome-composer">{composer}</div>
            <div className="spec-chips">
              {specialists.filter((s) => s.id !== "core").map((s) => (
                <button key={s.id} className={`chip spec-${s.id} ${mode === s.id ? "selected" : ""}`} onClick={() => setMode(mode === s.id ? "auto" : s.id)} title={s.description}>
                  <SpecMark id={s.id} />{s.name.replace("Spike ", "")}
                </button>
              ))}
            </div>
          </section>
        ) : (
          <>
            <div className="thread" ref={scrollRef} onScroll={(e) => {
              const el = e.currentTarget;
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}>
              <div className="thread-inner">
                {items.map((it, i) =>
                  it.kind === "user" ? (
                    <div key={i} className="msg user"><div className="bubble"><Markdown text={it.text} /></div></div>
                  ) : (
                    <AssistantMessage key={i} run={it.run} specialists={specialists} onPermission={onPermission} />
                  ),
                )}
              </div>
            </div>
            <div className="bottom-composer">{composer}</div>
          </>
        )}
      </main>

      {settingsOpen && (
        <SettingsDialog onClose={() => { setSettingsOpen(false); loadProviders(); api.get<{ running: boolean }>("/api/runtime").then(setEngine); }}
          specialists={specialists} providers={providers} reloadProviders={loadProviders} />
      )}
    </div>
  );
}
