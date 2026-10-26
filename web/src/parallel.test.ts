import { describe, expect, it } from "vitest";
import { dicts } from "./i18n";
import { applyProtoEvent, comparisonOf, emptyLive, estimateLines, leaderText, mindsSpec, multiplierText, rowCells, whyText } from "./parallel";
import { applyEvent, emptyRun, recordEvent, runAt, runFromStored } from "./run";
import { fill } from "./trust";
import type { ChatEvent, ProtoRun } from "./types";

const counts = (verified: number, unchecked: number) => ({ verified, hypothesis: 0, unchecked });
const mind = (i: number, extra = {}) => ({ index: i, temperature: [0.3, 0.7, 1.0][i], ...extra });

/** The stream of a 3-mind message: each mind's events carry `mind`; the pick comes last, then the chosen one's own trust. */
const STREAM: ChatEvent[] = [
  { type: "minds_start", n: 3, minds: [mind(0), mind(1), mind(2)] },
  { type: "mind_start", mind: 0 }, { type: "mind_start", mind: 1 }, { type: "mind_start", mind: 2 },
  { type: "route", mind: 1, mode: "core", method: "user", confidence: 1, specialists: [{ id: "core", name: "Spike Core", provider: "local", model: "" }] },
  { type: "delta", mind: 0, text: "Fue entrenado en 2019." },
  { type: "delta", mind: 1, text: "El modelo tiene " },
  { type: "delta", mind: 1, text: "12 capas." },
  { type: "delta", mind: 2, text: "Su latencia es de 35 ms." },
  { type: "done", mind: 1, text: "El modelo tiene 12 capas.", error: null },
  { type: "mind_result", mind: 0, index: 0, ok: true, error: null, counts: counts(0, 1), verifier_failed: false, elapsed_s: 0.5, specialists: ["core"], route: [], text: "Fue entrenado en 2019." },
  { type: "mind_result", mind: 1, index: 1, ok: true, error: null, counts: counts(1, 0), verifier_failed: false, elapsed_s: 0.4, specialists: ["core"], route: [], text: "El modelo tiene 12 capas." },
  { type: "mind_result", mind: 2, index: 2, ok: false, error: "boom", counts: counts(0, 0), verifier_failed: false, elapsed_s: 0.1, specialists: [], route: [], text: "" },
  { type: "minds_pick", chosen: 1, ranking: [1, 0, 2], why: "labels", minds: [] },
  { type: "trust", claims: [], counts: counts(1, 0), sources: [], verifier_failed: false, private: false },
  { type: "done", text: "El modelo tiene 12 capas.", error: null, elapsed_s: 1.2 },
];

describe("Parallel Minds in the run", () => {
  it("keeps each mind's text apart and makes the chosen one the answer", () => {
    const midway = STREAM.slice(0, 9).reduce(applyEvent, emptyRun());
    expect(midway.text).toBe(""); // nothing of a mind leaks into the answer before the pick
    expect(midway.minds?.minds.map((m) => m.run.text)).toEqual(["Fue entrenado en 2019.", "El modelo tiene 12 capas.", "Su latencia es de 35 ms."]);
    expect(midway.minds?.minds.map((m) => m.run.status)).toEqual(["running", "running", "running"]);
    expect(midway.route).toBeUndefined(); // a mind's route is not the answer's until it is chosen
    const done = STREAM.reduce(applyEvent, emptyRun());
    expect(done.status).toBe("done");
    expect(done.text).toBe("El modelo tiene 12 capas.");
    expect(done.route?.specialists[0].id).toBe("core"); // the chosen mind's run became the answer's own
    expect(done.minds).toMatchObject({ n: 3, chosen: 1, ranking: [1, 0, 2], why: "labels" });
    expect(done.minds?.minds.map((m) => [m.ok, m.counts, m.run.status])).toEqual([
      [true, counts(0, 1), "done"], [true, counts(1, 0), "done"], [false, counts(0, 0), "error"]]);
    expect(done.minds?.minds[2].run.error).toBe("boom");
    expect(done.trust?.counts).toEqual(counts(1, 0)); // the chosen answer's labels, as for any answer
  });

  it("answers a permission or a question of a mind once, in the answer", () => {
    const run = [STREAM[0], { type: "permission_request", mind: 2, id: "p1", tool: "web_fetch", risk: "network", arguments: {} }]
      .reduce(applyEvent, emptyRun());
    expect(run.permissions.map((p) => p.id)).toEqual(["p1"]);
    expect(run.minds?.minds[2].run.permissions).toEqual([]);
  });

  it("says no mind answered", () => {
    const run = [{ type: "minds_start", n: 2, minds: [mind(0), mind(1)] },
      { type: "minds_pick", chosen: null, ranking: [0, 1], why: "none", minds: [] },
      { type: "done", text: "", error: "none of the 2 minds answered" }].reduce(applyEvent, emptyRun());
    expect(run.status).toBe("error");
    expect(run.text).toBe("");
    expect(run.minds?.chosen).toBeNull();
  });

  it("is rebuilt from the stored answer with every mind's text and labels", () => {
    const meta = { minds: { n: 3, chosen: 1, ranking: [1, 0, 2], why: "labels", minds: [
      { index: 0, temperature: 0.3, ok: true, counts: counts(0, 1), text: "Fue entrenado en 2019.", elapsed_s: 0.5, verifier_failed: false },
      { index: 1, temperature: 0.7, ok: true, counts: counts(1, 0), text: "El modelo tiene 12 capas.", elapsed_s: 0.4, verifier_failed: false },
      { index: 2, temperature: 1, ok: false, counts: counts(0, 0), text: "", error: "boom", elapsed_s: 0.1, verifier_failed: false }] } };
    const run = runFromStored({ id: "m", role: "assistant", content: "El modelo tiene 12 capas.", created: 0, meta } as any);
    expect(run.minds?.chosen).toBe(1);
    expect(run.minds?.minds.map((m) => m.run.text)).toEqual(["Fue entrenado en 2019.", "El modelo tiene 12 capas.", ""]);
    expect(run.minds?.minds.map((m) => m.run.status)).toEqual(["done", "done", "error"]);
    expect(runFromStored({ id: "m", role: "assistant", content: "x", created: 0, meta: {} } as any).minds).toBeUndefined();
    const cut = runFromStored({ id: "m", role: "assistant", content: "", created: 0, meta: { minds: { n: 2, chosen: null, minds: [{ index: 0 }, { index: 1 }] } } } as any);
    expect(cut.minds?.minds.map((m) => m.run.status)).toEqual(["stopped", "stopped"]); // stopped before the pick
  });

  it("replays step by step without mixing the minds", () => {
    const recorded = STREAM.reduce<ChatEvent[]>((events, ev, i) => recordEvent(events, ev, i), []);
    expect(recorded.filter((e) => e.type === "delta" && e.mind === 1).map((e) => e.text)).toEqual(["El modelo tiene 12 capas."]);
    expect(recorded.filter((e) => e.type === "delta").length).toBe(3); // three minds, three pieces
    expect(runAt(recorded, 9).minds?.minds[1].run.text).toBe("El modelo tiene 12 capas.");
  });
});

describe("the request and what is shown before it runs", () => {
  it("sends nothing when off, n minds, or one entry per pick", () => {
    expect(mindsSpec(false, 3, null)).toBeNull();
    expect(mindsSpec(true, 3, null)).toEqual({ n: 3 });
    const picks = [{ mode: "finance", provider_id: "" }, { mode: "", provider_id: "openai" }, { mode: "math", provider_id: "x" }, { mode: "", provider_id: "" }];
    expect(mindsSpec(true, 2, picks)).toEqual({ picks: [{ mode: "finance" }, { provider_id: "openai" }] });
  });

  it("shows the multiplier in both languages and the cost when there is one", () => {
    expect(fill(dicts.es.minds.multiplier, { n: 3 })).toBe("×3 tiempo y tokens");
    expect(fill(dicts.en.minds.multiplier, { n: 3 })).toBe("×3 time and tokens");
    expect(multiplierText(4)).toMatch(/^×4 /);
    const local = { n: 3, multiplier: 3, multi_step: false, cost: null, unpriced: [], blocked: null,
      providers: [{ provider_id: "l", name: "Local", local: true, paid: false, calls: 3, tokens_in: 30, tokens_out: 6000, cost: null, blocked: null }] };
    expect(estimateLines(local)).toHaveLength(2);
    expect(estimateLines(local)[1]).toMatch(/local/); // a local model has no API cost to estimate
    const paid = { ...local, cost: 0.0312, providers: [{ ...local.providers[0], local: false, paid: true, cost: 0.0312 }] };
    expect(estimateLines(paid)[1]).toMatch(/0\.03/);
    const unpriced = { ...paid, cost: null, unpriced: ["OpenAI"], multi_step: true };
    expect(estimateLines(unpriced).join(" ")).toContain("OpenAI");
    expect(estimateLines(unpriced).length).toBe(3); // multiplier, no price, more calls if a mind takes several steps
  });

  it("explains the pick from the labels", () => {
    expect(whyText("labels", 1)).toContain("2");
    expect(whyText("none", null)).not.toBe("");
  });

  it("has the same strings in Spanish and English", () => {
    for (const key of ["minds", "proto"] as const) {
      expect(Object.keys(dicts.es[key]).sort()).toEqual(Object.keys(dicts.en[key]).sort());
    }
    expect(Object.keys(dicts.es.minds.why).sort()).toEqual(Object.keys(dicts.en.minds.why).sort());
    expect(Object.keys(dicts.es.proto.status).sort()).toEqual(Object.keys(dicts.en.proto.status).sort());
    expect(Object.keys(dicts.es.proto.phase).sort()).toEqual(Object.keys(dicts.en.proto.phase).sort());
  });
});

describe("Parallel Prototypes", () => {
  const start: ChatEvent = {
    type: "proto_start", id: "ab12cd34", task: "Haz slugify", status: "building", base: { branch: "main", commit: "c0ffee" }, dirty: 0,
    tests: { files: ["tests/test_slug.py"], checks: [] },
    approaches: [{ label: "a", branch: "spike/proto-ab12cd34-a", goal: "A", start: "s1", blueprint: {} }, { label: "b", branch: "spike/proto-ab12cd34-b", goal: "B", start: "s2", blueprint: {} }],
    comparison: {}, merged: null,
  };
  const row = (label: string, passed: number) => ({ label, built: true, tests_passed: passed, tests_total: 3, tests_ran: true, checks_passed: 2, checks_total: 2,
    files_changed: 1, insertions: 8, deletions: 0, seconds: 1.234 });

  it("follows the build, the tests and the comparison", () => {
    const events: ChatEvent[] = [
      start,
      { type: "proto_build", proto: "a", branch: "spike/proto-ab12cd34-a", goal: "A" },
      { type: "subtask_start", proto: "a", subtask: "t1" },
      { type: "permission_request", proto: "b", id: "p1", tool: "python", risk: "execute", arguments: { code: "x" } },
      { type: "proto_checks", proto: "a" },
      { type: "proto_result", proto: "a", status: "built", tests: { ran: true, reason: "", passed: 3, total: 3, failed: [] }, checks: { passed: 2, total: 2, items: [] },
        files: { count: 1, paths: ["slug.py"], insertions: 8, deletions: 0 }, seconds: { build: 1, tests: 0.2, total: 1.2 }, error: null, commit: "x" },
      { type: "proto_result", proto: "b", status: "failed", error: "boom", tests: { ran: false, reason: "no tests", passed: 0, total: 0, failed: [] } },
      { type: "proto_compare", id: "ab12cd34", rows: [row("a", 3), row("b", 2)], leader: "a", basis: "tests" },
    ];
    const mid = events.slice(0, 5).reduce(applyProtoEvent, emptyLive());
    expect(mid.phase).toEqual({ a: "checking", b: "waiting" });
    expect(mid.steps.a).toBe(1);
    expect(mid.permissions.map((p) => [p.id, p.status])).toEqual([["p1", "pending"]]);
    const live = events.reduce(applyProtoEvent, emptyLive());
    expect(live.phase).toEqual({ a: "done", b: "failed" });
    expect(live.run?.status).toBe("built");
    expect(live.run?.approaches[0]).toMatchObject({ label: "a", status: "built", tests: { passed: 3, total: 3 } });
    expect(live.run?.approaches[1]).toMatchObject({ label: "b", status: "failed", error: "boom" });
    const comparison = comparisonOf(live.run as ProtoRun);
    expect(comparison?.leader).toBe("a");
    expect(comparisonOf({ ...(live.run as ProtoRun), comparison: {} })).toBeNull();
    expect(applyProtoEvent(live, { type: "permission_resolved", id: "p1", decision: "allow_once" }).permissions[0].status).toBe("allow_once");
    expect(applyProtoEvent(emptyLive(), { type: "error", message: "git is not installed" }).error).toBe("git is not installed");
    expect(applyProtoEvent(emptyLive(), { type: "error", proto: "a", message: "tagged" }).error).toBeUndefined();
  });

  it("builds the table cells from the numbers and suggests only what they allow", () => {
    expect(rowCells(row("a", 3) as any)).toEqual({ tests: "3/3", checks: "2/2", files: "1", lines: "+8 −0", time: "1.2 s" });
    expect([dicts.es.proto.notRun, dicts.en.proto.notRun]).toContain(rowCells({ ...row("b", 0), tests_ran: false } as any).tests); // not "0/0"
    expect(leaderText({ rows: [], leader: "b", basis: "checks" })).toMatch(/B/);
    expect(leaderText({ rows: [], leader: null, basis: null })).toMatch(/./);
    expect(leaderText({ rows: [], leader: null, basis: null })).not.toMatch(/[AB]\b:/);
  });
});
