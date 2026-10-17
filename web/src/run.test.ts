import { describe, expect, it } from "vitest";
import { SSEParser } from "./api";
import { applyEvent, emptyRun, recordEvent, runAt, runFromStored, teamSteps } from "./run";

describe("SSEParser", () => {
  it("handles events split across chunks and CRLF", () => {
    const p = new SSEParser();
    expect(p.feed('data: {"type":"delta","te')).toEqual([]);
    expect(p.feed('xt":"a"}\r\n\r\ndata: {"type":"done"}\n\n')).toEqual([
      { type: "delta", text: "a" },
      { type: "done" },
    ]);
  });
  it("ignores malformed blocks and comments", () => {
    const p = new SSEParser();
    expect(p.feed(": ping\n\ndata: {oops\n\ndata: {\"type\":\"x\"}\n\n")).toEqual([{ type: "x" }]);
  });
});

describe("applyEvent", () => {
  it("builds a multi-specialist run", () => {
    const events = [
      { type: "status", message: "planning" },
      { type: "route", mode: "multi", method: "llm", confidence: 0.6, specialists: [{ id: "finance", name: "Spike Finance" }] },
      { type: "plan", method: "llm", note: "", subtasks: [{ id: "t1", specialist: "finance", instruction: "x" }] },
      { type: "subtask_start", subtask: "t1", specialist: "finance", name: "Spike Finance", instruction: "x" },
      { type: "delta", subtask: "t1", text: "part" },
      { type: "tool_call", id: "c1", name: "calculator", arguments: { expression: "1+1" } },
      { type: "tool_result", id: "c1", ok: true, content: "2" },
      { type: "subtask_end", subtask: "t1", ok: true, elapsed_s: 1.2 },
      { type: "synthesis_start" },
      { type: "delta", text: "Final" },
      { type: "done", text: "Final", elapsed_s: 2 },
    ];
    const run = events.reduce(applyEvent, emptyRun());
    expect(run.status).toBe("done");
    expect(run.text).toBe("Final");
    expect(run.subtasks.t1.text).toBe("part");
    expect(run.subtasks.t1.done).toBe(true);
    expect(run.tools[0]).toMatchObject({ name: "calculator", result: "2", ok: true });
  });
  it("keeps why the browser asks and the domain it can allow", () => {
    const run = applyEvent(emptyRun(), { type: "permission_request", id: "p2", tool: "mcp__playwright__browser_navigate", risk: "network",
      arguments: { url: "https://boe.es" }, reason: "opens boe.es", code: "open", once: false, domain: "boe.es" });
    expect(run.permissions[0]).toMatchObject({ reason: "opens boe.es", code: "open", once: false, domain: "boe.es", status: "pending" });
  });
  it("orders the team's steps with each checker pass after the round it checked", () => {
    const events = [
      { type: "subtask_start", subtask: "t1", task: "t1", specialist: "data", name: "Spike Data", instruction: "a", role: "research", round: 1 },
      { type: "subtask_start", subtask: "t2", task: "t2", specialist: "writing", name: "Spike Writing", instruction: "b", role: "execute", round: 1 },
      { type: "verify_start", round: 1 },
      { type: "verify", round: 1, method: "llm", note: "", returned: [{ subtask: "t2", fix: "save informe.md" }], criteria: [], checks: [] },
      { type: "subtask_start", subtask: "t2.r2", task: "t2", specialist: "writing", name: "Spike Writing", instruction: "b", role: "execute", round: 2, feedback: "save informe.md" },
      { type: "verify", round: 2, method: "llm", note: "", returned: [], criteria: [{ text: "c", ok: true, note: "" }], checks: [] },
      { type: "forge_report", verified: true, note: "", criteria: [{ text: "c", ok: true, note: "" }], deliverables: [], rounds: 2, unresolved: [] },
    ];
    const run = events.reduce(applyEvent, emptyRun());
    expect(teamSteps(run).map((s) => (s.kind === "sub" ? s.id : `check${s.v.round}`))).toEqual(["t1", "t2", "check1", "t2.r2", "check2"]);
    expect(run.subtasks["t2.r2"]).toMatchObject({ role: "execute", round: 2, feedback: "save informe.md" });
    expect(run.forge?.report?.rounds).toBe(2);
    expect(applyEvent(emptyRun(), { type: "verify_start", round: 1 }).status).toBe("verifying");
  });
  it("rebuilds the checker passes and the Forge report of a stored answer", () => {
    const run = runFromStored({ id: "m", role: "assistant", content: "ok", meta: {
      plan: { subtasks: [{ id: "t1", specialist: "data", instruction: "a", role: "research" }] },
      subtasks: { t1: { specialist: "data", text: "x", role: "research", round: 1, task: "t1" }, "t1.r2": { specialist: "data", text: "y", round: 2, task: "t1" } },
      verify: [{ round: 1, method: "llm", note: "", returned: [{ subtask: "t1", fix: "z" }], criteria: [], checks: [] }],
      forge: { report: { verified: true, note: "", criteria: [], deliverables: [], rounds: 2, unresolved: [] } },
    } } as any);
    expect(run.subtasks["t1.r2"]).toMatchObject({ instruction: "a", role: "research", round: 2 });
    expect(teamSteps(run).map((s) => s.kind)).toEqual(["sub", "verify", "sub"]);
    expect(run.forge?.report?.rounds).toBe(2);
  });
  it("gives each result to its own call when a provider repeats tool call ids", () => {
    let run = applyEvent(emptyRun(), { type: "tool_call", id: "c1", name: "write_file", arguments: { path: "a" } });
    run = applyEvent(run, { type: "tool_result", id: "c1", content: "wrote a", ok: true });
    run = applyEvent(run, { type: "tool_call", id: "c1", name: "write_file", arguments: { path: "b" } });
    run = applyEvent(run, { type: "tool_result", id: "c1", content: "wrote b", ok: true });
    expect(run.tools.map((t) => t.result)).toEqual(["wrote a", "wrote b"]);
  });
  it("tracks permission requests and errors", () => {
    let run = applyEvent(emptyRun(), { type: "permission_request", id: "p1", tool: "python", risk: "execute", arguments: {} });
    expect(run.permissions[0].status).toBe("pending");
    run = applyEvent(run, { type: "permission_resolved", id: "p1", decision: "deny" });
    expect(run.permissions[0].status).toBe("deny");
    run = applyEvent(run, { type: "error", message: "boom" });
    run = applyEvent(run, { type: "done", text: "", error: "boom" });
    expect(run.status).toBe("error");
    expect(run.error).toBe("boom");
  });
  it("restores stored messages", () => {
    const run = runFromStored({
      id: "m", role: "assistant", content: "hi", created: 0,
      meta: { route: { mode: "single", specialists: [{ id: "law", name: "Spike Law" }] }, subtasks: {}, tools: [], elapsed_s: 1 },
    });
    expect(run.status).toBe("done");
    expect(run.route?.specialists[0].name).toBe("Spike Law");
  });
  it("records the skills a run used, once each, live and from history", () => {
    let r = emptyRun();
    for (const ev of [
      { type: "skill", names: ["financial-ratio-analysis"], mode: "router", specialist: "finance" },
      { type: "skill", names: ["financial-ratio-analysis"], mode: "router", specialist: "finance", subtask: "t2" },
    ]) r = applyEvent(r, ev);
    expect(r.skills).toEqual(["financial-ratio-analysis"]);
    const stored = runFromStored({ id: "m", role: "assistant", content: "x", created: 0, meta: { skills: ["campaign-brief"] } });
    expect(stored.skills).toEqual(["campaign-brief"]);
  });
});

describe("files written by tools", () => {
  it("keeps the file of a successful tool result, live and from history", () => {
    let s = applyEvent(emptyRun(), { type: "tool_call", id: "c1", name: "create_docx", arguments: {} });
    s = applyEvent(s, { type: "tool_result", id: "c1", name: "create_docx", ok: true, content: "wrote", file: "informes/q3.docx" });
    expect(s.tools[0].file).toBe("informes/q3.docx");
    const stored = runFromStored({ role: "assistant", content: "ok", meta: { tools: [
      { type: "tool_call", id: "c1", name: "create_docx", arguments: {} },
      { type: "tool_result", id: "c1", ok: true, content: "wrote", file: "informes/q3.docx" },
    ] } } as any);
    expect(stored.tools[0].file).toBe("informes/q3.docx");
  });
});

describe("memory", () => {
  it("shows what an answer recalled, live and from history", () => {
    const ev = { type: "memory", rules: 1, semantic: false, notes: [{ id: "m1", kind: "fact", source: "", preview: "paga a 60 días", by: ["words"] }] };
    expect(applyEvent(emptyRun(), ev).memory?.notes[0].preview).toBe("paga a 60 días");
    const stored = runFromStored({ role: "assistant", content: "ok", meta: { memory: ev } } as any);
    expect(stored.memory?.rules).toBe(1);
  });
});

describe("privacy", () => {
  it("keeps the most passages withheld per provider, live and stored", () => {
    let run = applyEvent(emptyRun(), { type: "privacy", provider: "OpenAI", withheld: 1 });
    run = applyEvent(run, { type: "privacy", provider: "OpenAI", withheld: 3 });
    run = applyEvent(run, { type: "privacy", provider: "OpenAI", withheld: 2 });
    expect(run.privacy).toEqual({ OpenAI: 3 });
    expect(runFromStored({ role: "assistant", content: "ok", meta: { privacy: { DeepSeek: 1 } } } as any).privacy).toEqual({ DeepSeek: 1 });
  });
});

describe("step by step", () => {
  it("records merged text pieces and rebuilds the run at any step", () => {
    let events = recordEvent([], { type: "route", mode: "direct", method: "lexical", confidence: 1, specialists: [] }, 0);
    events = recordEvent(events, { type: "delta", text: "Ho" }, 0.1);
    events = recordEvent(events, { type: "delta", text: "la" }, 0.2);
    events = recordEvent(events, { type: "done", text: "Hola", elapsed_s: 0.3 }, 0.3);
    expect(events.map((e) => e.type)).toEqual(["route", "delta", "done"]);
    expect(events[1]).toMatchObject({ text: "Hola", t: 0.1 });
    expect(runAt(events, 1).text).toBe("");
    expect(runAt(events, 2).text).toBe("Hola");
    expect(runAt(events, 3).status).toBe("done");
  });
});

describe("learning from the user", () => {
  it("keeps what a message saved and the rule proposed from a correction, live and stored", () => {
    const saved = [{ id: "m1", kind: "rule", text: "Nunca uses emojis.", scope: "global" }];
    let run = applyEvent(emptyRun(), { type: "memory_saved", saved });
    expect(run.learn?.saved).toEqual(saved);
    run = applyEvent(emptyRun(), { type: "correction", text: "El IVA general es del 21 %." });
    expect(run.learn?.correction).toEqual({ text: "El IVA general es del 21 %.", status: "proposed" });
    const learn = { correction: { text: "x y z w", status: "saved", memory: "m2" } };
    expect(runFromStored({ role: "assistant", content: "ok", meta: { learn } } as any).learn).toEqual(learn);
  });
});

describe("questions", () => {
  it("shows a pending question, then the answer, live and stored", () => {
    let run = applyEvent(emptyRun(), { type: "question", id: "ask_1", question: "¿País?", options: ["España"] });
    expect(run.questions?.[0]).toMatchObject({ status: "pending", options: ["España"] });
    run = applyEvent(run, { type: "answered", id: "ask_1", answer: "España" });
    expect(run.questions?.[0]).toMatchObject({ status: "answered", answer: "España" });
    expect(applyEvent(run, { type: "answered", id: "ask_1", answer: null }).questions?.[0].status).toBe("unanswered");
    const stored = runFromStored({ role: "assistant", content: "ok", meta: { questions: [{ id: "q", question: "¿?", options: [] }] } } as any);
    expect(stored.questions?.[0].status).toBe("unanswered");
  });
});

describe("answer contracts", () => {
  it("keeps whether the answer follows the schema, live and stored", () => {
    const run = applyEvent(emptyRun(), { type: "contract", valid: false, attempts: 2, errors: ["(root): 'total' is a required property"] });
    expect(run.contract).toEqual({ valid: false, attempts: 2, errors: ["(root): 'total' is a required property"] });
    const stored = runFromStored({ role: "assistant", content: "{}", meta: { contract: { valid: true, attempts: 1, errors: [] } } } as any);
    expect(stored.contract?.valid).toBe(true);
  });
});

describe("design systems", () => {
  it("shows the design system live and after a reload", () => {
    const live = applyEvent(emptyRun(), { type: "design", id: "minimal", name: "Minimal" });
    expect(live.design).toEqual({ id: "minimal", name: "Minimal" });
    const stored = runFromStored({ id: "m1", role: "assistant", content: "ok", created: 0, meta: { design: { id: "spike", name: "SPIKE" } } } as any);
    expect(stored.design).toEqual({ id: "spike", name: "SPIKE" });
    expect(runFromStored({ id: "m2", role: "assistant", content: "ok", created: 0, meta: {} } as any).design).toBeUndefined();
  });
});
