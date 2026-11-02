// The canvas model of the workflow builder: pure functions over a plain document, so what the mouse and the keyboard do
// is the same and can be tested without a browser. The server checks every workflow again before a save or a run
// (spike/workflows/model.py); these checks only give the answer right away, while the user is drawing.

export type NodeType = "input" | "specialist" | "tool" | "condition" | "output";
export const NODE_TYPES: NodeType[] = ["input", "specialist", "tool", "condition", "output"];
export type InputKind = "text" | "number" | "file";

export type WfNode = {
  id: string; type: NodeType; name: string; label?: string; x: number; y: number;
  kind?: InputKind; default?: string; // input
  specialist?: string; prompt?: string; // specialist
  tool?: string; arguments?: Record<string, unknown>; // tool
  op?: "contains" | "regex" | "number"; value?: string; compare?: string; case_sensitive?: boolean; // condition
  mode?: "file" | "artifact"; path?: string; content?: string; title?: string; format?: "text" | "html"; // output
};
export type WfEdge = { id: string; from: string; fromPort: string; to: string; toPort: string };
export type WfDoc = { format: "spike-workflow"; version: 1; id?: string; revision?: number; name: string; nodes: WfNode[]; edges: WfEdge[] };
export type Problem = { code: string; message: string; node: string | null; params: Record<string, unknown> };

export const NODE_W = 184;
export const NODE_H = 64;
export const OUT_PORTS: Record<NodeType, string[]> = { input: ["out"], specialist: ["out"], tool: ["out"], condition: ["true", "false"], output: [] };
export const IN_PORTS: Record<NodeType, string[]> = { input: [], specialist: ["in"], tool: ["in"], condition: ["in"], output: ["in"] };
const BASE_NAMES: Record<NodeType, string> = { input: "value", specialist: "step", tool: "tool", condition: "check", output: "result" };

export const newDoc = (name = ""): WfDoc => ({ format: "spike-workflow", version: 1, name, nodes: [], edges: [] });

const unique = (taken: Set<string>, base: string) => {
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}${n}`)) n++;
  return `${base}${n}`;
};

/** A new node with the settings a user would start from; `at` is where it goes (default: the next free place of a grid). */
export function addNode(doc: WfDoc, type: NodeType, at?: { x: number; y: number }): { doc: WfDoc; id: string } {
  const id = unique(new Set(doc.nodes.map((n) => n.id)), `n${doc.nodes.length + 1}`);
  const name = unique(new Set(doc.nodes.map((n) => n.name)), BASE_NAMES[type]);
  const slot = doc.nodes.length;
  const pos = at ?? { x: 40 + (slot % 4) * (NODE_W + 56), y: 40 + Math.floor(slot / 4) * (NODE_H + 72) };
  const node: WfNode = { id, type, name, x: Math.round(pos.x), y: Math.round(pos.y) };
  if (type === "input") Object.assign(node, { kind: "text", default: "" });
  if (type === "specialist") Object.assign(node, { specialist: "auto", prompt: "" });
  if (type === "tool") Object.assign(node, { tool: "", arguments: {} });
  if (type === "condition") Object.assign(node, { op: "contains", value: "", compare: ">", case_sensitive: false });
  if (type === "output") Object.assign(node, { mode: "artifact", path: "", content: "{{input}}", title: "", format: "text" });
  return { doc: { ...doc, nodes: [...doc.nodes, node] }, id };
}

export const patchNode = (doc: WfDoc, id: string, patch: Partial<WfNode>): WfDoc =>
  ({ ...doc, nodes: doc.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) });

export const moveNode = (doc: WfDoc, id: string, x: number, y: number): WfDoc =>
  patchNode(doc, id, { x: Math.round(Math.min(Math.max(x, 0), 4000)), y: Math.round(Math.min(Math.max(y, 0), 4000)) });

export const removeNode = (doc: WfDoc, id: string): WfDoc =>
  ({ ...doc, nodes: doc.nodes.filter((n) => n.id !== id), edges: doc.edges.filter((e) => e.from !== id && e.to !== id) });

export const removeEdge = (doc: WfDoc, id: string): WfDoc => ({ ...doc, edges: doc.edges.filter((e) => e.id !== id) });

export const nodeOf = (doc: WfDoc, id: string) => doc.nodes.find((n) => n.id === id);

/** What flows out of a node: text, number or file (a condition passes on the type of what it receives). */
export function portType(doc: WfDoc, id: string, seen: string[] = []): InputKind {
  const node = nodeOf(doc, id);
  if (!node || seen.includes(id)) return "text";
  if (node.type === "input") return node.kind ?? "text";
  if (node.type === "condition") {
    const first = doc.edges.find((e) => e.to === id);
    return first ? portType(doc, first.from, [...seen, id]) : "text";
  }
  return "text";
}

/** Whether `to` can already be reached from `from` by following edges (an edge back would close a cycle). */
export function reaches(doc: WfDoc, from: string, to: string): boolean {
  const seen = new Set<string>();
  const todo = [from];
  while (todo.length) {
    const id = todo.pop()!;
    if (id === to) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const e of doc.edges) if (e.from === id) todo.push(e.to);
  }
  return false;
}

/** Why `from.fromPort` cannot be joined to `to`, as a code the interface shows in the user's language; null when it can. */
export function whyNot(doc: WfDoc, from: string, fromPort: string, to: string): string | null {
  const a = nodeOf(doc, from), b = nodeOf(doc, to);
  if (!a || !b) return "missing";
  if (a.id === b.id) return "self";
  if (!OUT_PORTS[a.type].includes(fromPort)) return "no_output";
  if (!IN_PORTS[b.type].length) return "no_input";
  if (doc.edges.some((e) => e.from === from && e.fromPort === fromPort && e.to === to)) return "duplicate";
  if (b.type === "condition" && doc.edges.some((e) => e.to === to)) return "condition_full";
  if (b.type === "condition" && portType(doc, from) === "file") return "file_to_condition";
  if (reaches(doc, to, from)) return "cycle";
  return null;
}

export function connect(doc: WfDoc, from: string, fromPort: string, to: string): { doc: WfDoc; error: string | null } {
  const error = whyNot(doc, from, fromPort, to);
  if (error) return { doc, error };
  let n = doc.edges.length + 1;
  while (doc.edges.some((e) => e.id === `e${n}`)) n++;
  return { doc: { ...doc, edges: [...doc.edges, { id: `e${n}`, from, fromPort, to, toPort: "in" }] }, error: null };
}

/** The nodes `from.fromPort` could be joined to, left to right and top to bottom. */
export const candidates = (doc: WfDoc, from: string, fromPort: string): string[] =>
  [...doc.nodes].sort((a, b) => a.x - b.x || a.y - b.y).filter((n) => !whyNot(doc, from, fromPort, n.id)).map((n) => n.id);

// ------------------------------------------------------------------ drawing
export function portPoint(node: WfNode, side: "in" | "out", port: string): { x: number; y: number } {
  if (side === "in") return { x: node.x, y: node.y + NODE_H / 2 };
  const ports = OUT_PORTS[node.type];
  const i = Math.max(0, ports.indexOf(port));
  return { x: node.x + NODE_W, y: node.y + (NODE_H * (i + 1)) / (ports.length + 1) };
}

export function edgePath(doc: WfDoc, edge: WfEdge): string {
  const a = nodeOf(doc, edge.from), b = nodeOf(doc, edge.to);
  if (!a || !b) return "";
  const p = portPoint(a, "out", edge.fromPort), q = portPoint(b, "in", edge.toPort);
  const reach = Math.max(40, Math.abs(q.x - p.x) / 2);
  return `M${p.x},${p.y} C${p.x + reach},${p.y} ${q.x - reach},${q.y} ${q.x},${q.y}`;
}

/** The size of the drawing: every node plus some room. */
export const canvasSize = (doc: WfDoc) => ({
  width: Math.max(900, ...doc.nodes.map((n) => n.x + NODE_W + 60)),
  height: Math.max(520, ...doc.nodes.map((n) => n.y + NODE_H + 60)),
});

export const problemsByNode = (problems: Problem[]): Record<string, Problem[]> => {
  const found: Record<string, Problem[]> = {};
  for (const p of problems) if (p.node) (found[p.node] ??= []).push(p);
  return found;
};

// ------------------------------------------------------------------ the keyboard
export type Connecting = { from: string; port: string; target: string | null };
export type Editor = { doc: WfDoc; selected: string | null; connecting: Connecting | null; notice: { code: string; params?: Record<string, string> } | null };
export const startEditor = (doc: WfDoc): Editor => ({ doc, selected: null, connecting: null, notice: null });

/**
 * What a key does to the selected node. Arrows move it (10 px, Shift 40), Delete removes it, "c" starts a connection
 * from its output (t / f from a condition's true / false output); then the arrows or Tab choose the node to join it
 * to, Enter joins it and Escape gives up. Every mouse action has a key here or a control in the properties panel.
 */
export function editorKey(state: Editor, key: string, shift = false): Editor {
  const { doc, selected, connecting } = state;
  const node = selected ? nodeOf(doc, selected) : undefined;
  if (connecting) {
    const list = candidates(doc, connecting.from, connecting.port);
    const at = connecting.target ? list.indexOf(connecting.target) : -1;
    const step = (d: number) => {
      const target = list[(at + d + list.length) % list.length];
      return { ...state, connecting: { ...connecting, target }, notice: { code: "target", params: { name: nodeOf(doc, target)?.name ?? "" } } };
    };
    if (key === "Escape") return { ...state, connecting: null, notice: null };
    if (key === "ArrowRight" || key === "ArrowDown" || (key === "Tab" && !shift)) return list.length ? step(1) : state;
    if (key === "ArrowLeft" || key === "ArrowUp" || (key === "Tab" && shift)) return list.length ? step(-1) : state;
    if (key === "Enter") {
      if (!connecting.target) return { ...state, notice: { code: "choose_target" } };
      const joined = connect(doc, connecting.from, connecting.port, connecting.target);
      return joined.error ? { ...state, connecting: null, notice: { code: joined.error } }
        : { ...state, doc: joined.doc, connecting: null, notice: { code: "connected" } }; // the source stays selected: it is the node that has the focus
    }
    return state;
  }
  if (!node) return state;
  const step = shift ? 40 : 10;
  const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (key in moves) return { ...state, doc: moveNode(doc, node.id, node.x + moves[key][0], node.y + moves[key][1]), notice: null };
  if (key === "Delete" || key === "Backspace") return { ...state, doc: removeNode(doc, node.id), selected: null, notice: { code: "deleted", params: { name: node.name } } };
  const ports = OUT_PORTS[node.type];
  const port = key === "t" ? "true" : key === "f" ? "false" : key === "c" ? (ports[0] ?? "out") : undefined;
  if (port !== undefined) {
    if (!ports.includes(port)) return { ...state, notice: { code: "no_output" } };
    const list = candidates(doc, node.id, port);
    if (!list.length) return { ...state, notice: { code: "no_targets" } };
    return { ...state, connecting: { from: node.id, port, target: list[0] }, notice: { code: "connecting", params: { name: nodeOf(doc, list[0])?.name ?? "" } } };
  }
  if (key === "Escape") return { ...state, selected: null, notice: null };
  return state;
}

// ------------------------------------------------------------------ run state
export type NodeStatus = "pending" | "running" | "ok" | "failed" | "denied" | "skipped" | "cancelled";
export type NodeRun = { status: NodeStatus; output?: string; error?: string; branch?: string; skip?: string; elapsed_s?: number;
  file?: string; artifact?: { title: string; format: "text" | "html"; content: string }; private?: boolean;
  log: { kind: string; text: string }[] };
export type RunView = { id: string; status: string; nodes: Record<string, NodeRun>; elapsed_s?: number; live: boolean };

export const emptyRun = (doc: WfDoc, id = ""): RunView =>
  ({ id, status: "running", live: true, nodes: Object.fromEntries(doc.nodes.map((n) => [n.id, { status: "pending" as NodeStatus, log: [] }])) });

/** Fold one event of the run's stream into the view: statuses, a running log per node, outputs and timings. */
export function applyRunEvent(view: RunView, ev: { type: string; [key: string]: any }): RunView {
  const nodeId: string | undefined = ev.node;
  if (ev.type === "run_end") return { ...view, status: ev.status, elapsed_s: ev.elapsed_s, live: false };
  if (!nodeId || !view.nodes[nodeId]) return view;
  const cur = view.nodes[nodeId];
  const log = (kind: string, text: string, merge = false) => {
    const last = cur.log[cur.log.length - 1];
    return merge && last && last.kind === kind ? [...cur.log.slice(0, -1), { kind, text: last.text + text }] : [...cur.log, { kind, text }];
  };
  let next: NodeRun = cur;
  switch (ev.type) {
    case "node_start": next = { ...cur, status: "running" }; break;
    case "delta": next = { ...cur, log: log("delta", String(ev.text ?? ""), true) }; break;
    case "tool_call": next = { ...cur, log: log("tool_call", `${ev.name} ${JSON.stringify(ev.arguments ?? {})}`) }; break;
    case "tool_result": next = { ...cur, log: log(ev.ok ? "tool_result" : "tool_error", `${ev.name}: ${String(ev.content ?? "").slice(0, 400)}`) }; break;
    case "permission_request": next = { ...cur, log: log("permission", `${ev.tool}`) }; break;
    case "permission_resolved": next = { ...cur, log: log("permission_resolved", String(ev.decision)) }; break;
    case "error": next = { ...cur, log: log("error", String(ev.message ?? "")) }; break;
    case "node_end":
      next = { ...cur, status: ev.status, output: ev.output ?? cur.output, error: ev.error, branch: ev.branch, skip: ev.skip, elapsed_s: ev.elapsed_s,
        file: ev.file, artifact: ev.artifact ?? cur.artifact, private: ev.private };
      break;
    default: return view;
  }
  return { ...view, nodes: { ...view.nodes, [nodeId]: next } };
}

/** A stored run record (GET .../runs/{id}) as the same view. */
export function viewOfRecord(doc: WfDoc, record: any): RunView {
  const view = emptyRun(doc, record.id);
  for (const [id, n] of Object.entries<any>(record.nodes ?? {})) {
    if (!view.nodes[id]) continue;
    view.nodes[id] = { status: n.status, output: n.output, error: n.error, branch: n.branch, skip: n.skip, elapsed_s: n.elapsed_s, file: n.file,
      artifact: n.artifact, private: n.private, log: (n.log ?? []).map((l: any) => ({ kind: l.type, text: l.name ? `${l.name} ${l.arguments ?? ""}`.trim() : String(l.decision ?? "") })) };
  }
  return { ...view, status: record.status, elapsed_s: record.elapsed_s, live: !!record.live };
}
