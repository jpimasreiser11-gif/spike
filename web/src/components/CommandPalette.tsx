import { useEffect, useId, useMemo, useRef, useState } from "react";
import { DESKTOP_STRINGS } from "../desktop";
import { lang, t } from "../i18n";
import { useRestoreFocus } from "../useRestoreFocus";
import type { Project, Specialist } from "../types";
import { openTour } from "./Tour";
import "./CommandPalette.css";

export type Command = { id: string; label: string; keywords?: string; run: () => void };

export type PaletteHandlers = {
  newChat: () => void; setMode: (id: string) => void; selectProject: (p: Project | null) => void;
  openForge: () => void; openCreator: () => void; openResearch: () => void; openLab: () => void; openSubtitles: () => void;
  openDeviceLab: () => void; openDev: () => void; openWorkspace: () => void; openSettings: () => void; openHistory: () => void;
  openSamples: () => void; openDesktop: () => void; toggleSidebar: () => void; toggleTheme: () => void;
};
export type PaletteContext = {
  busy: boolean; desktopOn: boolean; inProject: boolean;
  specialists: Specialist[]; projects: Project[]; handlers: PaletteHandlers;
};

const P = t.palette;
const fill = (text: string, name: string) => text.replace("{name}", name);
const plain = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** The actions the palette offers: the app's main views, then specialists and projects. Views that are disabled while an
 * answer is being written are left out then, like their buttons are disabled. */
export function buildCommands({ busy, desktopOn, inProject, specialists, projects, handlers: h }: PaletteContext): Command[] {
  const view = (id: string, label: string, run: () => void): Command[] => (busy ? [] : [{ id, label, run }]);
  return [
    { id: "newchat", label: t.newChat, run: h.newChat },
    ...view("history", t.history.title, h.openHistory),
    ...view("forge", "Forge", h.openForge),
    ...view("create", t.create, h.openCreator),
    ...view("research", t.research.title, h.openResearch),
    ...view("lab", t.lab.title, h.openLab),
    ...view("subtitles", t.subtitles.title, h.openSubtitles),
    ...view("devicelab", t.deviceLab.title, h.openDeviceLab),
    ...view("dev", t.dev.title, h.openDev),
    { id: "workspace", label: t.workspaceJobs, run: h.openWorkspace },
    ...(desktopOn ? [{ id: "desktop", label: DESKTOP_STRINGS[lang].open, run: h.openDesktop }] : []),
    { id: "samples", label: P.samples, run: h.openSamples },
    { id: "settings", label: t.settings, run: h.openSettings },
    { id: "sidebar", label: P.sidebar, run: h.toggleSidebar },
    { id: "theme", label: t.toggleTheme, run: h.toggleTheme },
    { id: "tour", label: P.tour, run: openTour },
    { id: "spec:auto", label: fill(P.specialist, t.auto), run: () => h.setMode("auto") },
    ...specialists.filter((s) => s.id !== "core").map((s) => ({
      id: `spec:${s.id}`, label: fill(P.specialist, s.name.replace("Spike ", "")), keywords: s.description, run: () => h.setMode(s.id) })),
    ...(inProject ? [{ id: "project:none", label: P.noProject, run: () => h.selectProject(null) }] : []),
    ...projects.map((p) => ({ id: `project:${p.id}`, label: fill(P.project, p.name), run: () => h.selectProject(p) })),
  ];
}

/** Every word typed must appear in the label (or keywords); labels that start with the first word come first. */
export function filterCommands(commands: Command[], query: string): Command[] {
  const words = plain(query).split(/\s+/).filter(Boolean);
  if (!words.length) return commands;
  const found = commands.filter((c) => { const hay = plain(`${c.label} ${c.keywords ?? ""}`); return words.every((w) => hay.includes(w)); });
  const rank = (c: Command) => (plain(c.label).startsWith(words[0]) ? 0 : 1);
  return found.map((c, i) => ({ c, i })).sort((a, b) => rank(a.c) - rank(b.c) || a.i - b.i).map((x) => x.c);
}

/** Ctrl+K / Cmd+K: a filterable list of actions. A modal combobox: focus stays in the input and aria-activedescendant
 * names the highlighted option. The chosen action runs after the palette has closed and given focus back. */
export function CommandPalette({ ctx, onClose }: { ctx: PaletteContext; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const id = useId();
  const listId = `${id}-list`;
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  useRestoreFocus();
  const found = useMemo(() => filterCommands(buildCommands(ctx), query), [ctx, query]);
  const current = found.length ? Math.min(active, found.length - 1) : -1;
  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => { list.current?.children[current]?.scrollIntoView?.({ block: "nearest" }); }, [current]);

  const choose = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    setTimeout(command.run, 0);
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); }
    else if (e.key === "Tab") e.preventDefault(); // the input is the only stop; options are reached with the arrows
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (found.length) setActive((current + (e.key === "ArrowDown" ? 1 : -1) + found.length) % found.length);
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      setActive(e.key === "Home" ? 0 : Math.max(0, found.length - 1));
    } else if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); choose(found[current]); }
  };

  return (
    <div className="palette-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label={P.title} onKeyDown={onKeyDown}>
        <input ref={input} className="palette-input" type="text" role="combobox" aria-label={P.label} aria-expanded="true"
          aria-controls={listId} aria-autocomplete="list" aria-activedescendant={current >= 0 ? `${id}-${found[current].id}` : undefined}
          autoComplete="off" spellCheck={false} placeholder={P.placeholder} value={query}
          onChange={(e) => { setQuery(e.target.value); setActive(0); }} />
        <ul className="palette-list" id={listId} role="listbox" aria-label={P.list} ref={list}>
          {found.map((c, i) => (
            <li key={c.id} id={`${id}-${c.id}`} role="option" aria-selected={i === current} className={i === current ? "active" : ""}
              onMouseMove={() => i !== current && setActive(i)} onClick={() => choose(c)}>{c.label}</li>
          ))}
        </ul>
        <div className="sr-only" role="status">{found.length ? P.results.replace("{n}", String(found.length)) : P.empty}</div>
        {!found.length && <p className="palette-empty" aria-hidden="true">{P.empty}</p>}
      </div>
    </div>
  );
}
