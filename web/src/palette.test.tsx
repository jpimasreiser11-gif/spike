import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { buildCommands, CommandPalette, filterCommands, type PaletteContext } from "./components/CommandPalette";
import { t } from "./i18n";
import { dicts } from "./i18n";

let host: HTMLDivElement, root: Root;
const h = () => ({
  newChat: vi.fn(), setMode: vi.fn(), selectProject: vi.fn(), openForge: vi.fn(), openCreator: vi.fn(), openResearch: vi.fn(),
  openLab: vi.fn(), openSubtitles: vi.fn(), openDeviceLab: vi.fn(), openDev: vi.fn(), openWorkspace: vi.fn(), openSettings: vi.fn(),
  openHistory: vi.fn(), openSamples: vi.fn(), openDesktop: vi.fn(), toggleSidebar: vi.fn(), toggleTheme: vi.fn(),
});
let handlers = h();
const ctx = (over: Partial<PaletteContext> = {}): PaletteContext => ({
  busy: false, desktopOn: false, inProject: false, handlers,
  specialists: [{ id: "code", name: "Spike Code", description: "" }, { id: "writer", name: "Spike Writer", description: "" }] as never,
  projects: [{ id: "p1", name: "Expenses" }, { id: "p2", name: "Handbook" }] as never,
  ...over,
});
const key = (el: Element, k: string, init: KeyboardEventInit = {}) =>
  act(() => { el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init })); });
const type = (value: string) => {
  const field = host.querySelector<HTMLInputElement>("input")!;
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true })); });
};
const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 5)); });
const names = () => [...host.querySelectorAll('[role="option"]')].map((o) => o.textContent ?? "");

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  handlers = h();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); });

it("is a dialog with a combobox that controls a listbox and points at the active option", () => {
  act(() => root.render(<CommandPalette ctx={ctx()} onClose={() => {}} />));
  const dialog = host.querySelector('[role="dialog"]')!;
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  expect(dialog.getAttribute("aria-label")).toBe(t.palette.title);
  const input = host.querySelector<HTMLInputElement>('input[role="combobox"]')!;
  const list = host.querySelector('[role="listbox"]')!;
  expect(document.activeElement).toBe(input);
  expect(input.getAttribute("aria-expanded")).toBe("true");
  expect(input.getAttribute("aria-controls")).toBe(list.id);
  const options = [...host.querySelectorAll('[role="option"]')];
  expect(options.length).toBeGreaterThan(8);
  expect(input.getAttribute("aria-activedescendant")).toBe(options[0].id);
  expect(options[0].getAttribute("aria-selected")).toBe("true");
  expect(options.slice(1).every((o) => o.getAttribute("aria-selected") === "false")).toBe(true);
});

it("lists the main views, the specialists and the projects", () => {
  const labels = buildCommands(ctx()).map((c) => c.label);
  for (const wanted of [t.newChat, t.history.title, "Forge", t.create, t.research.title, t.lab.title, t.subtitles.title,
    t.deviceLab.title, t.workspaceJobs, t.settings, t.palette.specialist.replace("{name}", "Code"),
    t.palette.project.replace("{name}", "Handbook")]) expect(labels).toContain(wanted);
  expect(labels).not.toContain(t.palette.noProject);
  expect(buildCommands(ctx({ inProject: true })).map((c) => c.label)).toContain(t.palette.noProject);
  expect(buildCommands(ctx({ desktopOn: true })).length).toBe(buildCommands(ctx()).length + 1);
  // views that cannot open while an answer is being written are not offered then
  const busy = buildCommands(ctx({ busy: true })).map((c) => c.label);
  expect(busy).not.toContain("Forge");
  expect(busy).toContain(t.settings);
});

it("filters by typing, ignoring case and accents, and says when nothing matches", () => {
  const cmds = buildCommands(ctx());
  expect(filterCommands(cmds, "  ").length).toBe(cmds.length);
  expect(filterCommands(cmds, "FORGE").map((c) => c.id)).toEqual(["forge"]);
  expect(filterCommands(cmds, "handbook").map((c) => c.id)).toEqual(["project:p2"]);
  act(() => root.render(<CommandPalette ctx={ctx()} onClose={() => {}} />));
  type("zzzzqq");
  expect(host.querySelectorAll('[role="option"]').length).toBe(0);
  expect(host.querySelector('[role="status"]')?.textContent).toBe(t.palette.empty);
  expect(host.querySelector("input")!.hasAttribute("aria-activedescendant")).toBe(false);
  type("writer");
  expect(names().length).toBe(1);
  expect(host.querySelector('[role="status"]')?.textContent).toBe(t.palette.results.replace("{n}", "1"));
});

it("moves with the arrows (wrapping), runs the active option with Enter and closes first", async () => {
  const onClose = vi.fn();
  act(() => root.render(<CommandPalette ctx={ctx()} onClose={onClose} />));
  const input = host.querySelector("input")!;
  const options = () => [...host.querySelectorAll('[role="option"]')];
  key(input, "ArrowDown");
  expect(input.getAttribute("aria-activedescendant")).toBe(options()[1].id);
  key(input, "ArrowUp"); key(input, "ArrowUp");
  expect(input.getAttribute("aria-activedescendant")).toBe(options().at(-1)!.id);
  key(input, "Home");
  expect(input.getAttribute("aria-activedescendant")).toBe(options()[0].id);
  type("forge");
  key(input, "Enter");
  expect(onClose).toHaveBeenCalledTimes(1);
  await tick();
  expect(handlers.openForge).toHaveBeenCalledTimes(1);
});

it("runs specialist and project commands with their ids, and a click runs the option", async () => {
  act(() => root.render(<CommandPalette ctx={ctx()} onClose={() => {}} />));
  type("writer"); key(host.querySelector("input")!, "Enter"); await tick();
  expect(handlers.setMode).toHaveBeenCalledWith("writer");
  type("expenses");
  await act(async () => host.querySelector<HTMLElement>('[role="option"]')!.click()); await tick();
  expect(handlers.selectProject).toHaveBeenCalledWith(expect.objectContaining({ id: "p1" }));
});

it("opens the tour again through its event", async () => {
  const opened = vi.fn();
  window.addEventListener("spike:open-tour", opened);
  act(() => root.render(<CommandPalette ctx={ctx()} onClose={() => {}} />));
  type(t.palette.tour); key(host.querySelector("input")!, "Enter"); await tick();
  expect(opened).toHaveBeenCalledTimes(1);
  window.removeEventListener("spike:open-tour", opened);
});

it("closes with Escape or a click outside, keeps Tab inside, and opening it does nothing else", () => {
  const onClose = vi.fn();
  act(() => root.render(<CommandPalette ctx={ctx()} onClose={onClose} />));
  const input = host.querySelector("input")!;
  const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
  act(() => { input.dispatchEvent(tab); });
  expect(tab.defaultPrevented).toBe(true);
  key(input, "Escape");
  expect(onClose).toHaveBeenCalledTimes(1);
  act(() => { host.querySelector(".palette-backdrop")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
  expect(onClose).toHaveBeenCalledTimes(2);
  Object.values(handlers).forEach((fn) => expect(fn).not.toHaveBeenCalled());
});

it("restores focus to the element that had it", () => {
  const button = document.createElement("button"); document.body.append(button); button.focus();
  act(() => root.render(<CommandPalette ctx={ctx()} onClose={() => {}} />));
  expect(document.activeElement).not.toBe(button);
  act(() => root.render(<div />));
  expect(document.activeElement).toBe(button);
  button.remove();
});

it("has the same strings in both languages", () => {
  const shape = (o: unknown): unknown => typeof o === "object" && o ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, shape(v)])) : "s";
  expect(shape(dicts.es.palette)).toEqual(shape(dicts.en.palette));
  expect(shape(dicts.es.tour)).toEqual(shape(dicts.en.tour));
});
