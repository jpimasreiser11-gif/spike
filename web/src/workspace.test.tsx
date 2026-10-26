import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ArtifactComments } from "./components/ArtifactComments";
import { ProjectBranches } from "./components/ProjectBranches";
import { WorkspacePanel } from "./components/WorkspacePanel";
import { dicts, t } from "./i18n";
import type { Specialist } from "./types";

let host: HTMLDivElement;
let root: Root;
const requests: { path: string; body: Record<string, unknown>; method: string }[] = [];
let respond: (path: string, body: Record<string, unknown>) => unknown;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  requests.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (path: string, options: RequestInit = {}) => {
    const body = options.body ? JSON.parse(String(options.body)) : {};
    requests.push({ path, body, method: options.method ?? "GET" });
    return { ok: true, json: async () => respond(path, body) };
  }));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const click = async (label: string) => {
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === label);
  expect(button).toBeDefined();
  await act(async () => button!.click());
};
const input = async (el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) => {
  await act(async () => {
    const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
};

it("renders the exact diff and submits its receipt only after approval", async () => {
  respond = (path) => path === "/api/project-branches" ? [{ id: "b" }] : path.endsWith("/compare")
    ? { token: "receipt", parent: "p", files: [{ path: "a.txt", diff: "-old\n+new", conflict: true, before_size: 3, after_size: 3 }] } : { ok: true };
  await act(async () => root.render(<ProjectBranches projectId="b" />));
  await click(t.compareBranch);
  expect(host.textContent).toContain("-old\n+new");
  expect(host.textContent).toContain(t.mergeConflict);
  expect(requests.some((r) => r.path.endsWith("/merge"))).toBe(false);
  await click(t.approveMerge);
  expect(requests.at(-1)?.body).toEqual({ token: "receipt", approved: true });
  expect(host.textContent).toContain(t.mergeDone);
});

it("anchors replies and sends a selected root thread through the explicit UI event", async () => {
  const rows = [{ id: "root", line: 2, text: "review", parent: null }, { id: "reply", line: 2, text: "yes", parent: "root" }];
  respond = (path) => path === "/api/artifact-versions" ? { id: "hash" } : rows;
  const listener = vi.fn(); window.addEventListener("spike-comment-context", listener);
  await act(async () => root.render(<ArtifactComments content={"one\ntwo"} title="test" />));
  expect(host.textContent).toContain("review"); expect(host.textContent).toContain("yes");
  expect(listener).not.toHaveBeenCalled();
  await click(t.replyComment);
  const line = host.querySelector<HTMLInputElement>('input[type="number"]')!;
  expect(line.value).toBe("2"); expect(line.disabled).toBe(true);
  await input(host.querySelector("textarea")!, "another reply");
  await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(requests.find((r) => r.method === "POST" && r.path.endsWith("/comments"))?.body).toEqual({ line: 2, text: "another reply", parent: "root" });
  await click(t.useComments);
  expect((listener.mock.calls[0][0] as CustomEvent).detail).toBe("root");
  window.removeEventListener("spike-comment-context", listener);
});

it("shows queue limits, cancels a job and stores specialist knowledge in its own scope", async () => {
  respond = (path) => path === "/api/jobs" ? { limit: 1, ram_floor: 2 * 1024 ** 3, jobs: [{ id: "job", kind: "training", status: "queued" }] } : [];
  await act(async () => root.render(<WorkspacePanel specialists={[{ id: "code", name: "Code" }, { id: "medicine", name: "Medicine" }] as Specialist[]} onClose={() => {}} />));
  expect(host.textContent).toContain(t.jobTraining); expect(host.textContent).toContain("2.0 GiB");
  await click(t.cancel);
  expect(requests.some((r) => r.path === "/api/jobs/job/cancel")).toBe(true);
  await input(host.querySelector("textarea")!, "knowledge");
  await click(t.saveKnowledge);
  expect(requests.find((r) => r.path === "/api/memory")?.body).toMatchObject({ scope: "specialist:code", text: "knowledge" });
  await input(host.querySelector("select")!, "medicine");
  expect(requests.at(-1)?.path).toBe("/api/memory?scope=specialist:medicine");
});

it("provides both languages for every new panel", () => {
  for (const key of ["projectBranches", "approveMerge", "artifactComments", "specialistKnowledge", "jobs", "ramFloor", "useComments"] as const) {
    expect(dicts.es[key]).toBeTruthy(); expect(dicts.en[key]).toBeTruthy(); expect(dicts.es[key]).not.toBe(dicts.en[key]);
  }
});
