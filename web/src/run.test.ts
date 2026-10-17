import { describe, expect, it } from "vitest";
import { SSEParser } from "./api";
import { applyEvent, emptyRun, runFromStored } from "./run";

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
});
