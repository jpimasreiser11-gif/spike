import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TaskDialog, TaskSpace } from "./components/TaskSpace";
import { dicts, t } from "./i18n";
import { emptyRun, recordEvent, runFromStored } from "./run";
import { actionDetail, hasTask, mergeTasks, storedStatus, taskFromEvents } from "./taskSpace";
import type { ChatEvent } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const T = t.task;

// A Forge-like run as the server records it: a plan of two steps, an edit allowed once, a command denied, a write the
// settings allow, a call the settings block, the checker's report.
const FORGE: ChatEvent[] = [
  { type: "route", mode: "auto", method: "lexical", confidence: 1, specialists: [{ id: "code", name: "Code" }] },
  { type: "plan", method: "llm", note: "", subtasks: [{ id: "s1", specialist: "code", instruction: "Edit calc.py" }, { id: "s2", specialist: "writing", instruction: "Write the notes" }] },
  { type: "subtask_start", subtask: "s1", specialist: "code", name: "Code", instruction: "Edit calc.py", round: 1 },
  { type: "tool_call", id: "c1", name: "edit_file", arguments: { path: "calc.py", old: "1", new: "2" }, specialist: "code", subtask: "s1" },
  { type: "permission_request", id: "p1", tool: "edit_file", risk: "write", arguments: { path: "calc.py" }, call_id: "c1" },
  { type: "permission_resolved", id: "p1", decision: "allow_once" },
  { type: "tool_result", id: "c1", name: "edit_file", ok: true, content: "edited", file: "calc.py", checkpoint: "cp1" },
  { type: "tool_call", id: "c2", name: "run_command", arguments: { command: "rm -rf build" }, specialist: "code" },
  { type: "permission_request", id: "p2", tool: "run_command", risk: "exec", arguments: {}, call_id: "c2" },
  { type: "permission_resolved", id: "p2", decision: "deny" },
  { type: "tool_result", id: "c2", name: "run_command", ok: false, content: "error: the user denied this tool call" },
  { type: "subtask_end", subtask: "s1", ok: true, elapsed_s: 1 },
  { type: "subtask_start", subtask: "s2", specialist: "writing", name: "Writing", instruction: "Write the notes", round: 1 },
  { type: "tool_call", id: "c3", name: "write_file", arguments: { path: "NOTES.md", content: "x" } },
  { type: "tool_result", id: "c3", name: "write_file", ok: true, content: "written", file: "NOTES.md", checkpoint: "cp2" },
  { type: "tool_call", id: "c4", name: "web_fetch", arguments: { url: "https://example.org/a" } },
  { type: "tool_result", id: "c4", name: "web_fetch", ok: false, content: "error: the user has disabled the 'web_fetch' tool" },
  { type: "subtask_end", subtask: "s2", ok: true, elapsed_s: 1 },
  { type: "forge_report", verified: true, note: "", rounds: 1, unresolved: [], criteria: [{ text: "x is 2", ok: true, note: "" }],
    deliverables: [{ subtask: "s2", path: "NOTES.md", ok: true, bytes: 1 }] },
  { type: "delta", text: "Done." },
  { type: "done", text: "Done.", error: null },
];

describe("taskFromEvents", () => {
  it("rebuilds the plan, each action with its permission, the changed files and the deliverables", () => {
    const view = taskFromEvents(FORGE);
    expect(view.status).toBe("done");
    expect(view.steps.map((s) => [s.id, s.name, s.status])).toEqual([["s1", "Code", "done"], ["s2", "Writing", "done"]]);
    expect(view.actions.map((a) => [a.tool, a.detail, a.permission, a.status])).toEqual([
      ["edit_file", "calc.py", "allow_once", "ok"],
      ["run_command", "rm -rf build", "deny", "failed"],
      ["write_file", "NOTES.md", "auto", "ok"],
      ["web_fetch", "https://example.org/a", "refused", "failed"],
    ]);
    expect(view.files).toEqual([{ path: "calc.py", tool: "edit_file", checkpoint: "cp1", undone: false },
      { path: "NOTES.md", tool: "write_file", checkpoint: "cp2", undone: false }]);
    expect(view.deliverables).toEqual([{ path: "NOTES.md", ok: true }]);
    expect(view.criteria).toEqual([{ text: "x is 2", ok: true, note: "" }]);
    expect(view.verified).toBe(true);
  });

  it("follows a running task and settles what never finished when it is stopped", () => {
    const partial = FORGE.slice(0, 5); // the edit waits for the card
    const live = taskFromEvents(partial, { ...emptyRun(), status: "running" });
    expect(live.status).toBe("running");
    expect(live.steps.map((s) => s.status)).toEqual(["running", "waiting"]);
    expect(live.actions.map((a) => [a.permission, a.status])).toEqual([["pending", "running"]]);
    const stopped = taskFromEvents(partial, { ...emptyRun(), status: "stopped" });
    expect(stopped.steps.map((s) => s.status)).toEqual(["stopped", "waiting"]);
    expect(stopped.actions.map((a) => [a.permission, a.status])).toEqual([["unanswered", "stopped"]]);
    expect(stopped.files).toEqual([]);
  });

  it("is the same from a stored answer after a restart, with the undo the server recorded since", () => {
    let events: ChatEvent[] = [];
    FORGE.forEach((ev, i) => { events = recordEvent(events, ev, i / 10); });
    const stored = runFromStored({ id: "a1", role: "assistant", content: "Done.", created: 1,
      meta: { events, tools: [FORGE[3], { ...FORGE[6], undone: true }] } } as never);
    const view = taskFromEvents(stored.events, stored);
    expect(view.actions[0].undone).toBe(true);
    expect(view.files[0]).toEqual({ path: "calc.py", tool: "edit_file", checkpoint: "cp1", undone: true });
    expect(view.actions.map((a) => a.permission)).toEqual(taskFromEvents(FORGE).actions.map((a) => a.permission));
  });

  it("keeps a step sent back by the checker as the same planned step, with its round", () => {
    const view = taskFromEvents([FORGE[1], { type: "subtask_start", subtask: "s1#2", task: "s1", specialist: "code", name: "Code", round: 2 },
      { type: "subtask_end", subtask: "s1#2", ok: false }, { type: "done", text: "", error: "x" }]);
    expect(view.status).toBe("error");
    expect(view.steps.map((s) => [s.id, s.status, s.round])).toEqual([["s1", "failed", 2], ["s2", "waiting", undefined]]);
  });

  it("leaves out what one mind of Parallel Minds did on its own", () => {
    const view = taskFromEvents([{ type: "tool_call", id: "m", name: "read_file", arguments: { path: "a" }, mind: 1 }, ...FORGE.slice(3, 7)]);
    expect(view.actions.map((a) => a.id)).toEqual(["c1"]);
  });

  it("merges a Dev session's turns: the latest plan, every action and file", () => {
    const a = taskFromEvents(FORGE, undefined, 0), b = taskFromEvents(FORGE.slice(3, 7), undefined, 1);
    const merged = mergeTasks([a, b]);
    expect(merged.actions).toHaveLength(5);
    expect(new Set(merged.actions.map((x) => x.key)).size).toBe(5);
    expect(merged.files).toHaveLength(3);
    expect(merged.steps).toEqual([]);
    expect(mergeTasks([]).status).toBe("idle");
  });

  it("helpers: the detail of a call, the stored status, which answers have a task", () => {
    expect(actionDetail({ content: "line one\nline two" })).toBe("line one line two");
    expect(actionDetail({ path: "a/b.py", content: "x" })).toBe("a/b.py");
    expect(actionDetail({ query: "x".repeat(200) })).toHaveLength(91);
    expect([storedStatus({}), storedStatus({ stopped: true }), storedStatus({ cancelled: true }), storedStatus({ error: "x" })])
      .toEqual(["done", "stopped", "stopped", "error"]);
    expect(hasTask({ ...emptyRun(), events: FORGE, tools: [{ id: "c", name: "x", arguments: {} }] })).toBe(true);
    expect(hasTask({ ...emptyRun(), events: [{ type: "delta", text: "hi" }] })).toBe(false);
    expect(hasTask({ ...emptyRun(), tools: [{ id: "c", name: "x", arguments: {} }] })).toBe(false); // nothing to rebuild from
  });
});

describe("TaskSpace", () => {
  let host: HTMLDivElement, root: Root;
  beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
  afterEach(() => { act(() => root.unmount()); host.remove(); });

  it("shows the four parts with each action's permission in words", () => {
    act(() => root.render(<TaskSpace view={taskFromEvents(FORGE)} />));
    const text = host.textContent ?? "";
    for (const heading of [T.plan, T.actions, T.files, T.deliverables]) expect(text).toContain(heading);
    const rows = [...host.querySelectorAll('[data-testid="task-actions"] li')];
    expect(rows.map((r) => r.getAttribute("data-permission"))).toEqual(["allow_once", "deny", "auto", "refused"]);
    expect(rows[1].textContent).toContain(T.permission.deny);
    expect(rows[3].textContent).toContain(T.permission.refused);
    expect(host.querySelector("#task-plan")!.textContent).toContain("2/2");
    expect(text).toContain(T.verified);
    expect(text).toContain("NOTES.md");
  });

  it("says when a part is empty instead of hiding it, and takes the caller's file list", () => {
    act(() => root.render(<TaskSpace view={taskFromEvents([])} files={<p data-testid="own">own list</p>} />));
    const text = host.textContent ?? "";
    expect(text).toContain(T.noPlan);
    expect(text).toContain(T.noActions);
    expect(text).toContain(T.noDeliverables);
    expect(host.querySelector('[data-testid="own"]')).not.toBeNull();
    expect(text).not.toContain(T.noFiles);
  });

  it("the dialog closes with Escape and says nothing runs again", () => {
    let closed = 0;
    act(() => root.render(<TaskDialog view={taskFromEvents(FORGE)} onClose={() => { closed++; }} />));
    expect(document.body.textContent).toContain(T.rebuilt);
    expect(document.activeElement?.getAttribute("aria-label")).toBe(t.close);
    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(closed).toBe(1);
  });

  it("has every text in both languages", () => {
    const keys = (o: object): string[] => Object.entries(o).flatMap(([k, v]) => (typeof v === "object" ? keys(v).map((x) => `${k}.${x}`) : [k]));
    expect(keys(dicts.es.task)).toEqual(keys(dicts.en.task));
    expect(keys(dicts.es.task.permission)).toEqual(["auto", "pending", "allow_once", "allow_always", "deny", "refused", "unanswered"]);
  });
});
