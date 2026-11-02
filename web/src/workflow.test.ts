import { describe, expect, it } from "vitest";
import {
  NODE_H, NODE_W, addNode, applyRunEvent, candidates, canvasSize, connect, edgePath, editorKey, emptyRun, moveNode, newDoc, nodeOf,
  patchNode, portPoint, portType, problemsByNode, reaches, removeEdge, removeNode, startEditor, viewOfRecord, whyNot,
  type Editor, type NodeType, type WfDoc,
} from "./workflow";

/** A document with one node of each given type; the ids are n1, n2, ... in order. */
function build(...types: NodeType[]): WfDoc {
  return types.reduce((doc, type) => addNode(doc, type).doc, newDoc("test"));
}
const ids = (doc: WfDoc) => doc.nodes.map((n) => n.id);

describe("adding and removing nodes", () => {
  it("gives every node its own id and a readable unique name, and a place on a grid", () => {
    const doc = build("input", "input", "specialist", "tool", "condition", "output");
    expect(ids(doc)).toEqual(["n1", "n2", "n3", "n4", "n5", "n6"]);
    expect(doc.nodes.map((n) => n.name)).toEqual(["value", "value2", "step", "tool", "check", "result"]);
    expect(new Set(doc.nodes.map((n) => `${n.x},${n.y}`)).size).toBe(6);
    expect(doc.nodes[0]).toMatchObject({ type: "input", kind: "text" });
    expect(doc.nodes[2]).toMatchObject({ type: "specialist", specialist: "auto" });
    expect(doc.nodes[5]).toMatchObject({ type: "output", mode: "artifact", content: "{{input}}" });
  });

  it("never reuses an id after a delete", () => {
    let doc = build("input", "output");
    doc = removeNode(doc, "n1");
    const added = addNode(doc, "specialist");
    expect(added.id).not.toBe("n2");
    expect(new Set(ids(added.doc)).size).toBe(2);
  });

  it("puts a node where it is asked to and keeps moves inside the drawing", () => {
    const doc = addNode(newDoc("t"), "tool", { x: 120.4, y: 80.6 }).doc;
    expect(doc.nodes[0]).toMatchObject({ x: 120, y: 81 });
    expect(moveNode(doc, "n1", -50, 99999).nodes[0]).toMatchObject({ x: 0, y: 4000 });
  });

  it("deleting a node deletes the connections it had", () => {
    let doc = build("input", "specialist", "output");
    doc = connect(doc, "n1", "out", "n2").doc;
    doc = connect(doc, "n2", "out", "n3").doc;
    expect(doc.edges).toHaveLength(2);
    doc = removeNode(doc, "n2");
    expect(ids(doc)).toEqual(["n1", "n3"]);
    expect(doc.edges).toEqual([]);
  });

  it("patches only the node it is told to", () => {
    const doc = patchNode(build("input", "input"), "n2", { name: "topic" });
    expect(doc.nodes.map((n) => n.name)).toEqual(["value", "topic"]);
  });
});

describe("connecting", () => {
  it("joins an output to an input and numbers the edges", () => {
    let doc = build("input", "specialist", "output");
    const a = connect(doc, "n1", "out", "n2");
    expect(a.error).toBeNull();
    doc = connect(a.doc, "n2", "out", "n3").doc;
    expect(doc.edges).toEqual([
      { id: "e1", from: "n1", fromPort: "out", to: "n2", toPort: "in" },
      { id: "e2", from: "n2", fromPort: "out", to: "n3", toPort: "in" },
    ]);
    expect(removeEdge(doc, "e1").edges.map((e) => e.id)).toEqual(["e2"]);
  });

  it("explains what cannot be joined, with a code the screen turns into words", () => {
    let doc = build("input", "specialist", "output", "condition");
    doc = connect(doc, "n1", "out", "n2").doc;
    expect(whyNot(doc, "n1", "out", "n1")).toBe("self");
    expect(whyNot(doc, "n3", "out", "n2")).toBe("no_output"); // an output node has no output port
    expect(whyNot(doc, "n2", "out", "n1")).toBe("no_input"); // an input node has no input port
    expect(whyNot(doc, "n1", "out", "n2")).toBe("duplicate");
    expect(whyNot(doc, "n2", "nope", "n3")).toBe("no_output");
    expect(whyNot(doc, "zz", "out", "n3")).toBe("missing");
    expect(connect(doc, "n3", "out", "n2").doc).toBe(doc); // refused: the document is the same object
  });

  it("refuses a connection that would close a cycle, however long the way back", () => {
    let doc = build("specialist", "tool", "specialist", "specialist");
    doc = connect(doc, "n1", "out", "n2").doc;
    doc = connect(doc, "n2", "out", "n3").doc;
    doc = connect(doc, "n3", "out", "n4").doc;
    expect(reaches(doc, "n1", "n4")).toBe(true);
    expect(reaches(doc, "n4", "n1")).toBe(false);
    expect(connect(doc, "n4", "out", "n1").error).toBe("cycle");
    expect(connect(doc, "n3", "out", "n1").error).toBe("cycle");
    expect(connect(doc, "n1", "out", "n4").error).toBeNull(); // a shortcut forward is fine
  });

  it("lets a condition have one input and two outputs that go to different places", () => {
    let doc = build("input", "input", "condition", "output", "specialist");
    doc = connect(doc, "n1", "out", "n3").doc;
    expect(whyNot(doc, "n2", "out", "n3")).toBe("condition_full");
    doc = connect(doc, "n3", "true", "n4").doc;
    doc = connect(doc, "n3", "false", "n5").doc;
    expect(doc.edges.map((e) => e.fromPort)).toEqual(["out", "true", "false"]);
    expect(whyNot(doc, "n3", "true", "n4")).toBe("duplicate");
    expect(whyNot(doc, "n3", "false", "n4")).toBeNull(); // the other branch may also reach it
  });

  it("does not send a file to a condition, directly or through another condition", () => {
    let doc = build("input", "condition", "condition");
    doc = patchNode(doc, "n1", { kind: "file" });
    expect(portType(doc, "n1")).toBe("file");
    expect(connect(doc, "n1", "out", "n2").error).toBe("file_to_condition");
    doc = patchNode(doc, "n1", { kind: "number" });
    doc = connect(doc, "n1", "out", "n2").doc;
    expect(portType(doc, "n2")).toBe("number"); // a condition passes on the type it receives
    expect(connect(doc, "n2", "true", "n3").error).toBeNull();
  });

  it("lists the nodes an output could be joined to, left to right", () => {
    let doc = build("input", "specialist", "tool", "output");
    doc = patchNode(patchNode(doc, "n2", { x: 500, y: 40 }), "n3", { x: 300, y: 40 });
    doc = connect(doc, "n1", "out", "n2").doc;
    expect(candidates(doc, "n1", "out")).toEqual(["n3", "n4"]); // n2 is already joined, n1 is itself
    expect(candidates(doc, "n4", "out")).toEqual([]);
  });
});

describe("the keyboard does everything the mouse does", () => {
  const key = (state: Editor, ...keys: string[]) => keys.reduce((s, k) => editorKey(s, k), state);
  const select = (doc: WfDoc, id: string): Editor => ({ ...startEditor(doc), selected: id });

  it("connects two nodes without a pointer: c, arrows or Tab to choose, Enter", () => {
    const doc = build("input", "specialist", "output");
    let s = key(select(doc, "n1"), "c");
    expect(s.connecting).toEqual({ from: "n1", port: "out", target: "n2" }); // the first candidate is already chosen
    expect(s.notice?.code).toBe("connecting");
    s = key(s, "ArrowRight");
    expect(s.connecting?.target).toBe("n3");
    s = key(s, "ArrowRight"); // wraps round
    expect(s.connecting?.target).toBe("n2");
    s = key(s, "ArrowLeft");
    expect(s.connecting?.target).toBe("n3");
    s = key(s, "Enter");
    expect(s.connecting).toBeNull();
    expect(s.selected).toBe("n1"); // the node with the focus stays the selected one
    expect(s.doc.edges).toEqual([{ id: "e1", from: "n1", fromPort: "out", to: "n3", toPort: "in" }]);
    expect(s.notice?.code).toBe("connected");
  });

  it("t and f start from a condition's true and false outputs", () => {
    const doc = build("input", "condition", "output", "output");
    let s = key(select(connect(doc, "n1", "out", "n2").doc, "n2"), "t");
    expect(s.connecting).toMatchObject({ from: "n2", port: "true" });
    s = key(s, "Enter");
    const f = key(select(s.doc, "n2"), "f", "ArrowRight", "Enter");
    expect(f.doc.edges.map((e) => `${e.fromPort}>${e.to}`)).toEqual(["out>n2", "true>n3", "false>n4"]);
  });

  it("says why it cannot connect instead of doing nothing", () => {
    const doc = build("output", "input");
    expect(key(select(doc, "n1"), "c").notice?.code).toBe("no_output"); // an output node has none
    expect(key(select(doc, "n1"), "t").notice?.code).toBe("no_output"); // nor a true/false output
    const lonely = build("input");
    expect(key(select(lonely, "n1"), "c").notice?.code).toBe("no_targets");
  });

  it("Escape gives up a connection, and then lets go of the node", () => {
    const doc = build("input", "output");
    let s = key(select(doc, "n1"), "c", "Escape");
    expect(s.connecting).toBeNull();
    expect(s.doc.edges).toEqual([]);
    expect(s.selected).toBe("n1");
    s = key(s, "Escape");
    expect(s.selected).toBeNull();
  });

  it("moves with the arrows (Shift for big steps) and deletes with Delete", () => {
    const doc = addNode(newDoc("t"), "tool", { x: 100, y: 100 }).doc;
    let s = key(select(doc, "n1"), "ArrowRight", "ArrowDown");
    expect(nodeOf(s.doc, "n1")).toMatchObject({ x: 110, y: 110 });
    s = editorKey(s, "ArrowLeft", true);
    expect(nodeOf(s.doc, "n1")).toMatchObject({ x: 70, y: 110 });
    s = key(s, "Delete");
    expect(s.doc.nodes).toEqual([]);
    expect(s.selected).toBeNull();
    expect(s.notice).toEqual({ code: "deleted", params: { name: "tool" } });
  });

  it("ignores keys when nothing is selected and other keys while connecting", () => {
    const doc = build("input", "output");
    const idle = startEditor(doc);
    expect(editorKey(idle, "Delete")).toBe(idle);
    const connecting = key(select(doc, "n1"), "c");
    expect(editorKey(connecting, "x")).toBe(connecting);
    expect(editorKey(connecting, "Delete").doc).toBe(doc);
  });
});

describe("drawing", () => {
  it("puts the ports on the edges of the box and a curve between them", () => {
    let doc = build("input", "condition", "output");
    doc = connect(doc, "n1", "out", "n2").doc;
    doc = connect(doc, "n2", "true", "n3").doc;
    const c = nodeOf(doc, "n2")!;
    expect(portPoint(c, "in", "in")).toEqual({ x: c.x, y: c.y + NODE_H / 2 });
    const t = portPoint(c, "out", "true"), f = portPoint(c, "out", "false");
    expect(t.x).toBe(c.x + NODE_W);
    expect(t.y).toBeLessThan(f.y);
    expect(edgePath(doc, doc.edges[1])).toMatch(/^M[\d.-]+,[\d.-]+ C/);
    expect(edgePath(doc, { id: "x", from: "gone", fromPort: "out", to: "n3", toPort: "in" })).toBe("");
  });

  it("makes room for every node", () => {
    expect(canvasSize(newDoc("t"))).toEqual({ width: 900, height: 520 });
    const far = addNode(newDoc("t"), "tool", { x: 2000, y: 900 }).doc;
    expect(canvasSize(far).width).toBeGreaterThan(2000 + NODE_W);
    expect(canvasSize(far).height).toBeGreaterThan(900 + NODE_H);
  });

  it("groups the server's problems by node", () => {
    const found = problemsByNode([
      { code: "tool_unknown", message: "", node: "n1", params: {} },
      { code: "arg_missing", message: "", node: "n1", params: {} },
      { code: "no_nodes", message: "", node: null, params: {} },
    ]);
    expect(Object.keys(found)).toEqual(["n1"]);
    expect(found.n1).toHaveLength(2);
  });
});

describe("following a run", () => {
  const doc = build("input", "tool", "output");

  it("starts everything pending and folds each event into its node", () => {
    let v = emptyRun(doc, "r1");
    expect(Object.values(v.nodes).map((n) => n.status)).toEqual(["pending", "pending", "pending"]);
    v = applyRunEvent(v, { type: "node_start", node: "n1", kind: "input", name: "value" });
    expect(v.nodes.n1.status).toBe("running");
    v = applyRunEvent(v, { type: "node_end", node: "n1", status: "ok", elapsed_s: 0.01, output: "hola" });
    v = applyRunEvent(v, { type: "node_start", node: "n2" });
    v = applyRunEvent(v, { type: "tool_call", node: "n2", name: "echo", arguments: { text: "hola" } });
    v = applyRunEvent(v, { type: "permission_request", node: "n2", tool: "echo" });
    v = applyRunEvent(v, { type: "permission_resolved", node: "n2", decision: "allow_once" });
    v = applyRunEvent(v, { type: "tool_result", node: "n2", name: "echo", ok: true, content: "hola" });
    v = applyRunEvent(v, { type: "node_end", node: "n2", status: "denied", error: "no", elapsed_s: 1.5 });
    expect(v.nodes.n1).toMatchObject({ status: "ok", output: "hola", elapsed_s: 0.01 });
    expect(v.nodes.n2.status).toBe("denied");
    expect(v.nodes.n2.log.map((l) => l.kind)).toEqual(["tool_call", "permission", "permission_resolved", "tool_result"]);
    expect(v.nodes.n3.status).toBe("pending");
    expect(v.live).toBe(true);
    v = applyRunEvent(v, { type: "run_end", status: "failed", elapsed_s: 2 });
    expect(v).toMatchObject({ live: false, status: "failed", elapsed_s: 2 });
  });

  it("joins streamed text into one log line and keeps what a skipped branch says", () => {
    let v = emptyRun(doc, "r");
    v = applyRunEvent(v, { type: "delta", node: "n2", text: "Ho" });
    v = applyRunEvent(v, { type: "delta", node: "n2", text: "la" });
    expect(v.nodes.n2.log).toEqual([{ kind: "delta", text: "Hola" }]);
    v = applyRunEvent(v, { type: "node_end", node: "n3", status: "skipped", skip: "dead_branch" });
    expect(v.nodes.n3).toMatchObject({ status: "skipped", skip: "dead_branch" });
  });

  it("ignores events of nodes it does not know and events of no node", () => {
    const v = emptyRun(doc, "r");
    expect(applyRunEvent(v, { type: "node_start", node: "ghost" })).toBe(v);
    expect(applyRunEvent(v, { type: "run_start", run: "r" })).toBe(v);
    expect(applyRunEvent(v, { type: "heartbeat", node: "n1" })).toBe(v);
  });

  it("shows a stored record like a live run", () => {
    const v = viewOfRecord(doc, {
      id: "r9", status: "completed", elapsed_s: 0.4,
      nodes: {
        n1: { status: "ok", output: "x", elapsed_s: 0.01, log: [] },
        n2: { status: "ok", elapsed_s: 0.2, log: [{ type: "tool_call", name: "echo", arguments: "{}" }, { type: "permission", decision: "allow_once" }] },
        n3: { status: "ok", elapsed_s: 0.01, file: "informes/a.md", private: true },
        ghost: { status: "ok" },
      },
    });
    expect(v).toMatchObject({ id: "r9", status: "completed", live: false, elapsed_s: 0.4 });
    expect(v.nodes.n2.log).toEqual([{ kind: "tool_call", text: "echo {}" }, { kind: "permission", text: "allow_once" }]);
    expect(v.nodes.n3).toMatchObject({ file: "informes/a.md", private: true });
    expect(v.nodes.ghost).toBeUndefined();
  });
});
