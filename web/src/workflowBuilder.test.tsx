import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { WorkflowBuilder, failure, portable, problemText } from "./components/WorkflowBuilder";
import { fmt } from "./components/WorkflowCanvas";
import { dicts, t } from "./i18n";

const W = t.workflow;
let root: Root | null = null;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = null;
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

const keysOf = (o: unknown, prefix = ""): string[] =>
  o && typeof o === "object" && !Array.isArray(o)
    ? Object.entries(o).flatMap(([k, v]) => keysOf(v, `${prefix}${k}.`)).concat(prefix ? [prefix.slice(0, -1)] : [])
    : [prefix.slice(0, -1)];

it("has the same strings, in the same places, in Spanish and in English", () => {
  expect(keysOf(dicts.es.workflow).sort()).toEqual(keysOf(dicts.en.workflow).sort());
  // every problem code the server can send has a sentence in both languages
  for (const code of ["cycle", "tool_unknown", "var_unknown", "arg_missing", "edge_type", "specialist_unknown", "input_missing"])
    expect(dicts.es.workflow.problems[code] && dicts.en.workflow.problems[code]).toBeTruthy();
});

it("fills the {placeholders} of a sentence and leaves unknown ones alone", () => {
  expect(fmt("{a} → {b} {c}", { a: "x", b: 2 })).toBe("x → 2 {c}");
  expect(problemText({ code: "cycle", message: "fallback", node: null, params: { nodes: ["a", "b", "a"] } })).toContain("a → b → a");
  expect(problemText({ code: "no_such_code", message: "the server said so", node: null, params: {} })).toBe("the server said so");
});

it("reads a failed request as the problems the server found, or as a sentence", () => {
  const found = failure(new Error(JSON.stringify({ code: "invalid_workflow", problems: [{ code: "cycle", message: "m", node: null, params: {} }] })));
  expect(found.problems).toHaveLength(1);
  expect(failure(new Error("workflow_conflict")).text).toBe(W.errors.workflow_conflict);
  expect(failure(new Error("something unexpected")).text).toBe("something unexpected");
});

it("exports only what travels: no id, no revision", () => {
  const doc = { format: "spike-workflow" as const, version: 1 as const, id: "w1", revision: 3, name: "n", nodes: [], edges: [] };
  expect(portable(doc)).toEqual({ format: "spike-workflow", version: 1, name: "n", nodes: [], edges: [] });
});

// ---------------------------------------------------------------------------- the whole screen against a fake server
const enc = new TextEncoder();
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const catalog = {
  specialists: [{ id: "core", name: "Core" }], tools_enabled: true,
  tools: [{ name: "echo", description: "Echo", risk: "safe", policy: "allow", parameters: { properties: { text: { type: "string" } }, required: ["text"] } }],
};

type Hold = { push: (ev: object) => void; close: () => void };

function fakeServer(options: { validate?: unknown; events?: object[]; hold?: Hold } = {}) {
  const calls: { method: string; path: string; body: any }[] = [];
  const fetcher = vi.fn(async (input: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
    if (path === "/api/workflows/catalog") return json(catalog);
    if (path === "/api/workflows" && method === "GET") return json([]);
    if (path === "/api/workflows" && method === "POST")
      return json({ ...body.workflow, id: "w1", revision: 1 });
    if (path === "/api/workflows/validate") return json(options.validate ?? { ok: true, problems: [] });
    if (path === "/api/workflows/w1/runs" && method === "POST") return json({ id: "r1", status: "running" });
    if (path === "/api/workflows/w1/runs") return json([]);
    if (path === "/api/workflows/w1/runs/r1/stop") return json({ ok: true });
    if (path === "/api/workflows/w1/runs/r1/events") {
      const stream = new ReadableStream({
        start(c) {
          for (const ev of options.events ?? []) c.enqueue(enc.encode(`data: ${JSON.stringify(ev)}\n\n`));
          if (options.hold) options.hold.push = (ev) => c.enqueue(enc.encode(`data: ${JSON.stringify(ev)}\n\n`)), options.hold.close = () => c.close();
          else c.close();
        },
      });
      return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
    }
    return json({ detail: "not_found" }, 404);
  });
  vi.stubGlobal("fetch", fetcher);
  return { calls, fetcher };
}

async function mount() {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(<WorkflowBuilder onClose={() => {}} />));
  return host;
}
const button = (host: HTMLElement, label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement;
const nodeBox = (host: HTMLElement, id: string) => host.querySelector(`[data-node="${id}"]`) as SVGGElement;
const press = async (el: Element, key: string) => act(async () => { el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })); });
const typeInto = async (el: HTMLInputElement | HTMLTextAreaElement, value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")!.set!.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
});
const settle = async () => act(async () => { await new Promise((r) => setTimeout(r, 20)); });

it("builds a workflow with the keyboard alone, validates it, saves it and shows what the server found", async () => {
  const server = fakeServer({ validate: { ok: false, problems: [{ code: "var_unknown", message: "x", node: "n2", params: { name: "ghost" } }] } });
  const host = await mount();
  expect(host.querySelector('[role="toolbar"]')).not.toBeNull();
  expect(server.calls.map((c) => c.path)).toContain("/api/workflows/catalog");

  await act(async () => button(host, `+ ${W.types.input}`).click());
  await act(async () => button(host, `+ ${W.types.specialist}`).click());
  await act(async () => button(host, `+ ${W.types.output}`).click());
  const boxes = [...host.querySelectorAll("[data-node]")];
  expect(boxes).toHaveLength(3);
  expect(boxes.every((b) => b.getAttribute("role") === "button" && b.getAttribute("tabindex") === "0")).toBe(true);
  expect(nodeBox(host, "n1").getAttribute("aria-label")).toContain(W.types.input);

  // the keyboard path: select a node, c, arrow to the target, Enter
  await act(async () => nodeBox(host, "n1").dispatchEvent(new FocusEvent("focusin", { bubbles: true })));
  await act(async () => (nodeBox(host, "n1") as unknown as HTMLElement).focus());
  expect(nodeBox(host, "n1").getAttribute("aria-pressed")).toBe("true");
  await press(nodeBox(host, "n1"), "c");
  expect(host.querySelector(".wf-live")?.textContent).toBe(fmt(W.notices.connecting, { name: "step" })); // it says which node is chosen
  expect(nodeBox(host, "n2").getAttribute("class")).toContain("chosen"); // the first candidate is already chosen
  await press(nodeBox(host, "n1"), "ArrowRight");
  expect(host.querySelector(".wf-live")?.textContent).toBe(fmt(W.notices.target, { name: "result" })); // and when it changes
  await press(nodeBox(host, "n1"), "ArrowLeft");
  await press(nodeBox(host, "n1"), "Enter");
  expect(host.querySelectorAll(".wf-edge")).toHaveLength(1);
  expect(host.querySelector(".wf-live")?.textContent).toBe(W.notices.connected);

  // the same thing without the canvas: the "connect to" list in the properties panel
  const connectTo = [...host.querySelectorAll<HTMLSelectElement>(".wf-side select")].find((s) => [...s.options].some((o) => o.value === "n3"))!;
  await act(async () => { connectTo.value = "n3"; connectTo.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => button(host, W.connect).click());
  expect(host.querySelectorAll(".wf-edge")).toHaveLength(2);

  // the panel of the node that was joined lists its connection, and one can be removed from there
  await act(async () => (nodeBox(host, "n3") as unknown as HTMLElement).focus());
  expect(host.querySelectorAll(".wf-edges li")).toHaveLength(1);
  await act(async () => button(host, W.disconnect).click());
  expect(host.querySelectorAll(".wf-edge")).toHaveLength(1);
  await act(async () => (nodeBox(host, "n1") as unknown as HTMLElement).focus());
  const again = [...host.querySelectorAll<HTMLSelectElement>(".wf-side select")].find((s) => [...s.options].some((o) => o.value === "n3"))!;
  await act(async () => { again.value = "n3"; again.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => button(host, W.connect).click());
  expect(host.querySelectorAll(".wf-edge")).toHaveLength(2);

  // properties: the specialist's prompt uses a variable nobody defines; the server says so
  await act(async () => (nodeBox(host, "n2") as unknown as HTMLElement).focus());
  const prompt = host.querySelector<HTMLTextAreaElement>(".wf-side textarea")!;
  await typeInto(prompt, "Resume {{ghost}}");
  expect(prompt.value).toBe("Resume {{ghost}}");
  await act(async () => button(host, W.validate).click());
  await settle();
  const validate = server.calls.find((c) => c.path === "/api/workflows/validate")!;
  expect(validate.body.workflow.nodes).toHaveLength(3);
  expect(validate.body.workflow.edges).toHaveLength(2);
  expect(validate.body.workflow.id).toBeUndefined();
  expect(host.querySelector(".wf-problems [data-code=var_unknown]")?.textContent).toContain("ghost");
  expect(nodeBox(host, "n2").getAttribute("aria-label")).toContain(fmt(W.problemBadge, { n: 1 }));

  // save: the document goes to the server without an id, and the screen then offers to run it
  const run = () => button(host, W.run);
  expect(run().disabled).toBe(true);
  await typeInto(host.querySelector<HTMLInputElement>(".wf-bar input[maxlength='80']")!, "Mi flujo");
  await act(async () => button(host, W.save).click());
  await settle();
  const save = server.calls.find((c) => c.method === "POST" && c.path === "/api/workflows")!;
  expect(save.body.workflow.name).toBe("Mi flujo");
  expect(save.body.workflow.id).toBeUndefined();
  expect(host.querySelector('[role="status"]')?.textContent).toBe(fmt(W.saved, { n: 1 }));
  expect(run().disabled).toBe(false);
});

it("deletes a node and its connections with the Delete key and says so", async () => {
  fakeServer();
  const host = await mount();
  await act(async () => button(host, `+ ${W.types.input}`).click());
  await act(async () => button(host, `+ ${W.types.output}`).click());
  await act(async () => (nodeBox(host, "n1") as unknown as HTMLElement).focus());
  await press(nodeBox(host, "n1"), "c");
  await press(nodeBox(host, "n1"), "Enter");
  expect(host.querySelectorAll(".wf-edge")).toHaveLength(1);
  await act(async () => (nodeBox(host, "n1") as unknown as HTMLElement).focus());
  await press(nodeBox(host, "n1"), "Delete");
  expect(host.querySelectorAll("[data-node]")).toHaveLength(1);
  expect(host.querySelectorAll(".wf-edge")).toHaveLength(0);
  expect(host.querySelector(".wf-live")?.textContent).toContain("value");
});

it("runs a saved workflow, shows each node as it goes, asks for permission and can be stopped", async () => {
  const hold: Hold = { push: () => {}, close: () => {} };
  const server = fakeServer({
    hold,
    events: [
      { type: "run_start", run: "r1", order: ["n1", "n2"], nodes: [] },
      { type: "node_start", node: "n1", kind: "input", name: "value" },
      { type: "node_end", node: "n1", status: "ok", elapsed_s: 0.01, output: "hola" },
      { type: "node_start", node: "n2", kind: "tool", name: "tool" },
      { type: "tool_call", node: "n2", id: "c1", name: "echo", arguments: { text: "hola" } },
      { type: "permission_request", node: "n2", id: "p1", tool: "echo", risk: "write", arguments: { text: "hola" } },
    ],
  });
  const host = await mount();
  await act(async () => button(host, `+ ${W.types.input}`).click());
  await act(async () => button(host, `+ ${W.types.tool}`).click());
  await typeInto(host.querySelector<HTMLInputElement>(".wf-bar input[maxlength='80']")!, "Eco");
  await act(async () => button(host, W.save).click());
  await settle();
  expect(button(host, W.run).disabled).toBe(false);

  await act(async () => button(host, W.run).click());
  await settle();
  expect(server.calls.some((c) => c.method === "POST" && c.path === "/api/workflows/w1/runs")).toBe(true);
  // live: the input node is done, the tool node is running and waiting for a decision
  expect(nodeBox(host, "n1").getAttribute("class")).toContain("st-ok");
  expect(nodeBox(host, "n2").getAttribute("class")).toContain("st-running");
  expect(host.querySelector(".wf-run")?.textContent).toContain("echo");
  expect(host.querySelector(".wf-log")).not.toBeNull();
  expect(button(host, W.stop)).toBeDefined();
  expect(button(host, W.run)).toBeUndefined();

  await act(async () => button(host, W.stop).click());
  expect(server.calls.some((c) => c.path === "/api/workflows/w1/runs/r1/stop" && c.method === "POST")).toBe(true);
  await act(async () => {
    hold.push({ type: "node_end", node: "n2", status: "cancelled", elapsed_s: 0.5 });
    hold.push({ type: "run_end", status: "cancelled", elapsed_s: 0.6 });
    hold.close();
  });
  await settle();
  expect(nodeBox(host, "n2").getAttribute("class")).toContain("st-cancelled");
  expect(button(host, W.run)).toBeDefined(); // finished: it can be run again
  expect(button(host, W.stop)).toBeUndefined();
  expect(host.querySelector(".wf-log")?.textContent).toContain(W.status.cancelled);
});

it("asks before a new workflow throws away what was not saved", async () => {
  fakeServer();
  const host = await mount();
  await act(async () => button(host, `+ ${W.types.input}`).click());
  const ask = vi.fn(() => false);
  vi.stubGlobal("confirm", ask);
  await act(async () => button(host, W.newFlow).click());
  expect(ask).toHaveBeenCalledWith(W.discardAsk);
  expect(host.querySelectorAll("[data-node]")).toHaveLength(1); // kept
  ask.mockReturnValue(true);
  await act(async () => button(host, W.newFlow).click());
  expect(host.querySelectorAll("[data-node]")).toHaveLength(0); // discarded on purpose
});
