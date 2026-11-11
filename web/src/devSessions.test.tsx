import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as apiModule from "./api";
import { api, ApiError } from "./api";
import { buildCommands } from "./components/CommandPalette";
import { DevSessions } from "./components/DevSessions";
import { dicts, projectError, t } from "./i18n";
import { isolationText } from "./isolation";
import type { ChatEvent } from "./types";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), streamPost: vi.fn() }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const D = t.dev;
const SESSION = { id: "dev_1", folder: "/work/app", conversation_id: "c1", plan: false, running: false, specialist: "code", provider: "local",
  model: "m", history: 2, broad: false, sandbox: "RAW SERVER LINE (English)",
  isolation: { isolated: false, backend: "none", reason: "approved commands run outside the sandbox in auto mode", code: "approved_command" } };
const MESSAGES = [{ id: "m1", role: "user", content: "earlier question", meta: { dev_mode: "act" }, created: 1 },
  { id: "m2", role: "assistant", content: "earlier answer", meta: {}, created: 2 }];
const SKILLS = [{ name: "writing-plans", description: "Plans", enabled: true }, { name: "tdd", description: "Tests", enabled: true }];

let host: HTMLDivElement, root: Root;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 5)); });
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
const click = (el: Element) => act(() => { (el as HTMLElement).click(); });
const type = (el: HTMLInputElement | HTMLTextAreaElement, value: string) => act(() => {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
});
const byText = (sel: string, text: string) => [...host.querySelectorAll<HTMLElement>(sel)].find((b) => b.textContent?.includes(text))!;

let posts: [string, unknown][] = [];
let calls: Record<string, unknown>;
function mockApi(extra: Record<string, unknown> = {}) {
  posts = [];
  calls = { sessions: [], history: [], ...extra };
  vi.spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/dev/sessions") return { active: calls.sessions } as never;
    if (path.startsWith("/api/dev/history")) return { sessions: calls.history } as never;
    if (path.endsWith("/messages")) return { messages: MESSAGES } as never;
    if (path.endsWith("/changes")) return { changes: calls.changes ?? [] } as never;
    if (path === "/api/dev/skills") return { skills: SKILLS } as never;
    throw new Error("unexpected GET " + path);
  });
  vi.spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    posts.push([path, body]);
    if (path === "/api/dev/sessions") return SESSION as never;
    if (path.endsWith("/mode")) return { plan: (body as { plan: boolean }).plan } as never;
    return { ok: true } as never;
  });
  vi.spyOn(api, "del").mockResolvedValue({ ok: true } as never);
}
const mount = async () => { act(() => root.render(<DevSessions onClose={() => {}} />)); await flush(); };
async function openFolder(path = "/work/app") {
  type(q<HTMLInputElement>('[name="dev-folder"]'), path);
  await click(q('[data-testid="dev-open"]'));
  await flush();
}
const stream = () => vi.mocked(apiModule.streamPost);

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); stream().mockReset(); });

describe("opening a folder", () => {
  it("asks for the folder first and opens it only when the user types one", async () => {
    mockApi();
    await mount();
    expect(q<HTMLButtonElement>('[data-testid="dev-open"]').disabled).toBe(true);
    await openFolder("/work/app");
    expect(posts[0]).toEqual(["/api/dev/sessions", { folder: "/work/app", confirm_broad: false }]);
    expect(q('[data-testid="dev-log"]').textContent).toContain("earlier answer");
    expect(host.textContent).toContain(D.earlier);
  });

  it("makes the user confirm the home folder or a disk before it opens", async () => {
    mockApi();
    await mount();
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(409, "dev_folder_broad"));
    await openFolder("/home/me");
    expect(host.querySelector('[data-testid="dev-error"]')!.textContent).toBe(projectError("dev_folder_broad"));
    const confirm = q<HTMLInputElement>('[name="dev-broad"]');
    expect(q<HTMLButtonElement>('[data-testid="dev-open"]').disabled).toBe(true);
    await click(confirm);
    expect(q<HTMLButtonElement>('[data-testid="dev-open"]').disabled).toBe(false);
    await click(q('[data-testid="dev-open"]'));
    await flush();
    expect(posts.at(-1)).toEqual(["/api/dev/sessions", { folder: "/home/me", confirm_broad: true }]);
  });

  it("says in the user's language whether commands are isolated", async () => {
    mockApi();
    await mount();
    await openFolder();
    expect(host.textContent).toContain(isolationText(SESSION.isolation));
    expect(host.textContent).not.toContain("RAW SERVER LINE");  // the line comes from the code, translated, not the raw text
  });

  it("lists the saved sessions of the folder and resumes one by id; an open session can be continued", async () => {
    mockApi({ history: [{ id: "conv9", updated: 1700000000, mode: "code", messages: 4, preview: "fix the parser" }],
      sessions: [{ ...SESSION, id: "dev_old", folder: "/other" }] });
    await mount();
    expect(host.textContent).toContain("/other");
    type(q<HTMLInputElement>('[name="dev-folder"]'), "/work/app");
    await click(q('[data-testid="dev-saved"]'));
    await flush();
    expect(q('[data-testid="dev-saved-list"]').textContent).toContain("fix the parser");
    await click(byText("button", D.resume));
    await flush();
    expect(posts[0]).toEqual(["/api/dev/sessions", { folder: "/work/app", confirm_broad: false, resume_id: "conv9" }]);
  });

  it("shows the server's reason in the user's language when a folder is refused", async () => {
    mockApi();
    await mount();
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(409, "dev_session_open"));
    await openFolder();
    expect(q('[data-testid="dev-error"]').textContent).toBe(projectError("dev_session_open"));
  });
});

describe("a session", () => {
  const events = (...list: ChatEvent[]) => async (_path: string, _body: unknown, on: (e: ChatEvent) => void) => { for (const e of list) on(e); };

  it("switches between plan and act without sending anything, and says what each mode does", async () => {
    mockApi();
    await mount(); await openFolder();
    expect(q('[data-testid="dev-mode-hint"]').textContent).toBe(D.actHint);
    await click(q('[data-testid="dev-plan"]'));
    await flush();
    expect(posts.at(-1)).toEqual(["/api/dev/sessions/dev_1/mode", { plan: true }]);
    expect(q('[data-testid="dev-mode-hint"]').textContent).toBe(D.planHint);
    expect(q('[data-testid="dev-plan"]').getAttribute("aria-pressed")).toBe("true");
    expect(stream()).not.toHaveBeenCalled();
  });

  it("sends the message with the skills chosen for this turn and shows the streamed answer", async () => {
    mockApi();
    stream().mockImplementation(events({ type: "delta", text: "Done: " }, { type: "delta", text: "x is 2." }, { type: "done", text: "Done: x is 2.", elapsed_s: 1 }));
    await mount(); await openFolder();
    await click(q("summary"));
    await click(q('[name="dev-skill-writing-plans"]'));
    type(q<HTMLTextAreaElement>('[name="dev-input"]'), "set x to 2");
    await click(q('[data-testid="dev-send"]'));
    await flush();
    expect(stream().mock.calls[0].slice(0, 2)).toEqual(["/api/dev/sessions/dev_1/turn", { message: "set x to 2", skills: ["writing-plans"] }]);
    expect(q('[data-testid="dev-log"]').textContent).toContain("set x to 2");
    expect(q('[data-testid="dev-log"]').textContent).toContain("Done: x is 2.");
    expect(q<HTMLButtonElement>('[data-testid="dev-send"]').disabled).toBe(true); // empty draft again
  });

  it("shows a permission card and answers it through the Dev route, never the chat's", async () => {
    mockApi();
    let finish!: () => void;
    stream().mockImplementation(async (_p: string, _b: unknown, on: (e: ChatEvent) => void) => {
      on({ type: "permission_request", id: "perm_1", tool: "edit_file", risk: "write", arguments: { path: "calc.py", old: "1", new: "2" } });
      await new Promise<void>((r) => { finish = r; });
      on({ type: "done", text: "ok", elapsed_s: 1 });
    });
    await mount(); await openFolder();
    type(q<HTMLTextAreaElement>('[name="dev-input"]'), "edit it");
    await click(q('[data-testid="dev-send"]'));
    await flush();
    const card = q('[role="alertdialog"]');
    expect(card.textContent).toContain("edit_file");
    expect(card.textContent).toContain("calc.py");
    expect(q('[data-testid="dev-stop"]')).toBeTruthy();
    await click(byText(".permission-actions button", t.allowOnce));
    await flush();
    expect(posts.at(-1)).toEqual(["/api/dev/permissions/perm_1", { decision: "allow_once" }]);
    expect(posts.some(([p]) => p.startsWith("/api/permissions"))).toBe(false);
    await act(async () => { finish(); });
    await flush();
    expect(q('[data-testid="dev-send"]')).toBeTruthy();
  });

  it("denying sends deny and an ask_user question is answered through the Dev route", async () => {
    mockApi();
    stream().mockImplementation(async (_p: string, _b: unknown, on: (e: ChatEvent) => void) => {
      on({ type: "permission_request", id: "perm_2", tool: "run_command", risk: "execute", arguments: { command: "ls" } });
      on({ type: "question", id: "ask_1", question: "Which file?", options: ["calc.py", "util.py"] });
      await new Promise(() => {});
    });
    await mount(); await openFolder();
    type(q<HTMLTextAreaElement>('[name="dev-input"]'), "go");
    await click(q('[data-testid="dev-send"]'));
    await flush();
    await click(byText(".permission-actions button", t.deny));
    await click(byText(".question-options button", "util.py"));
    await flush();
    expect(posts.filter(([p]) => p.startsWith("/api/dev/permissions") || p.startsWith("/api/dev/questions"))).toEqual([
      ["/api/dev/permissions/perm_2", { decision: "deny" }], ["/api/dev/questions/ask_1", { answer: "util.py" }]]);
  });

  it("stops a running turn through the cancel route and shows it as stopped", async () => {
    mockApi();
    stream().mockImplementation(async (_p: string, _b: unknown, on: (e: ChatEvent) => void) => {
      on({ type: "delta", text: "working" });
      on({ type: "stopped" });
    });
    await mount(); await openFolder();
    type(q<HTMLTextAreaElement>('[name="dev-input"]'), "long task");
    await click(q('[data-testid="dev-send"]'));
    await flush();
    expect(q('[data-testid="dev-log"]').textContent).toContain(t.stopped);
    stream().mockImplementation(async () => { await new Promise(() => {}); });
    type(q<HTMLTextAreaElement>('[name="dev-input"]'), "again");
    await click(q('[data-testid="dev-send"]'));
    await flush();
    await click(q('[data-testid="dev-stop"]'));
    expect(posts.at(-1)?.[0]).toBe("/api/dev/sessions/dev_1/cancel");
  });

  it("lists the changes, undoes the latest, and asks again with force when files changed since", async () => {
    mockApi({ changes: [{ id: "k1", tool: "edit_file", created: 1, undone: false, files: ["calc.py"] }] });
    await mount(); await openFolder();
    expect(q('[data-testid="dev-changes"]').textContent).toContain("calc.py");
    expect(host.textContent).toContain(D.files); // the deliverables list of the changed files
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "dev_undo_conflict", changed: ["calc.py"] }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "k1", tool: "edit_file", files: ["calc.py"] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await click(q('[data-testid="dev-undo"]'));
    await flush();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ force: false });
    expect(q('[data-testid="dev-conflict"]').textContent).toContain("calc.py");
    await click(q('[data-testid="dev-undo-force"]'));
    await flush();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ force: true });
    expect(host.querySelector('[data-testid="dev-conflict"]')).toBeNull();
    vi.unstubAllGlobals();
  });

  it("closes the session through the API and goes back to the folder form", async () => {
    mockApi();
    await mount(); await openFolder();
    await click(q('[data-testid="dev-end"]'));
    await flush();
    expect(api.del).toHaveBeenCalledWith("/api/dev/sessions/dev_1");
    expect(q('[name="dev-folder"]')).toBeTruthy();
  });

  it("aborts the running request when the window is closed", async () => {
    mockApi();
    let signal: AbortSignal | undefined;
    stream().mockImplementation(async (_p: string, _b: unknown, _on: unknown, s?: AbortSignal) => { signal = s; await new Promise(() => {}); });
    await mount(); await openFolder();
    type(q<HTMLTextAreaElement>('[name="dev-input"]'), "go");
    await click(q('[data-testid="dev-send"]'));
    await flush();
    act(() => root.unmount());
    expect(signal?.aborted).toBe(true);
    root = createRoot(host);
  });
});

describe("texts and the palette", () => {
  it("every Dev text and error code exists in Spanish and English", () => {
    expect(Object.keys(dicts.es.dev).sort()).toEqual(Object.keys(dicts.en.dev).sort());
    for (const code of ["dev_folder_relative", "dev_folder_missing", "dev_folder_not_dir", "dev_folder_forbidden", "dev_folder_broad", "dev_session_open",
      "dev_session_unknown", "dev_turn_running", "dev_resume_unknown", "dev_nothing_to_undo"]) {
      expect(projectError(code, "es")).not.toBe(code);
      expect(projectError(code, "en")).not.toBe(code);
    }
  });

  it("the command palette offers the view", () => {
    const openDev = vi.fn();
    const handlers = new Proxy({ openDev } as never, { get: (target, key) => (target as Record<string, unknown>)[key as string] ?? vi.fn() });
    const commands = buildCommands({ busy: false, desktopOn: false, inProject: false, specialists: [], projects: [], handlers });
    commands.find((c) => c.id === "dev")!.run();
    expect(openDev).toHaveBeenCalled();
    expect(commands.find((c) => c.id === "dev")!.label).toBe(t.dev.title);
    expect(buildCommands({ busy: true, desktopOn: false, inProject: false, specialists: [], projects: [], handlers }).some((c) => c.id === "dev")).toBe(false);
  });
});
