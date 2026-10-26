import { describe, expect, it } from "vitest";
import {
  DESKTOP_STRINGS, MAX_BATCH, actionLabel, applyDesktopEvent, batchChoices, cropStyle, decisionText, emptyDesktopRun, estimateText,
  recordAction, regionOf, startBlock, waitingCard,
} from "./desktop";
import type { DesktopRun, DesktopStatus, Estimate, Region } from "./desktop";
import { runFromStored } from "./run";

const es = DESKTOP_STRINGS.es;
const en = DESKTOP_STRINGS.en;

const region: Region = { x: 332, y: 548, w: 360, h: 220, image_w: 1024, image_h: 768, points: [{ x: 512, y: 742 }] };
const card = (over: Record<string, unknown> = {}) => ({
  type: "desktop_action", id: "dsk_a_1", task: "dsk_a", step: 1, action: { name: "left_click", x: 512, y: 742 }, summary: "left click at (512, 742)",
  region, shot: 1, masked: false, auto: false, note: "I will click the search box.", sensitive: null, ...over,
});
const play = (events: Record<string, unknown>[]) =>
  events.reduce<DesktopRun>((run, ev) => applyDesktopEvent(run, ev as { type: string }), emptyDesktopRun("open it"));

describe("the setting and its words", () => {
  it("has the exact label in Spanish and an English one", () => {
    expect(es.setting).toBe("Control del escritorio (solo con un proveedor con computer use)");
    expect(en.setting).toBe("Desktop control (only with a provider that has computer use)");
  });
  it("has the same keys in both languages", () => {
    const keys = (o: object) => Object.keys(o).sort();
    expect(keys(es)).toEqual(keys(en));
    for (const k of ["tools", "driverCodes", "providerCodes", "decided", "sensitive", "reasons", "action"] as const) {
      expect(keys(es[k] as object)).toEqual(keys(en[k] as object));
    }
    expect(es.rules).toHaveLength(en.rules.length);
  });
  it("covers every refusal code the server can give, and every reason a task can end", () => {
    for (const s of [es, en]) {
      for (const code of ["no_provider", "local", "unsupported", "no_key", "paid", "privacy", "limit"]) expect(s.providerCodes[code]).toBeTruthy();
      for (const code of ["wayland", "no_display", "no_xdotool", "no_capture", "display_unreachable", "no_powershell", "no_macos_tools", "unsupported_os"]) {
        expect(s.driverCodes[code]).toBeTruthy();
      }
      for (const kind of ["purchase", "send", "delete", "password", "submit", "close", "labelled"]) expect(s.sensitive[kind]).toBeTruthy();
      for (const reason of ["finished", "stopped", "step_limit", "timeout", "error", "refused", "cut"]) expect(s.reasons[reason]).toBeTruthy();
    }
  });
});

describe("what a card says", () => {
  it("describes each action in both languages", () => {
    expect(actionLabel({ name: "left_click", x: 5, y: 6 }, es)).toBe("Clic en (5, 6)");
    expect(actionLabel({ name: "left_click", x: 5, y: 6 }, en)).toBe("Click at (5, 6)");
    expect(actionLabel({ name: "double_click", x: 5, y: 6, modifiers: "shift" }, en)).toBe("Double click at (5, 6) with shift");
    expect(actionLabel({ name: "right_click" }, es)).toBe("Clic derecho donde está el ratón");
    expect(actionLabel({ name: "left_click_drag", from_x: 1, from_y: 2, x: 3, y: 4 }, en)).toBe("Drag from (1, 2) to (3, 4)");
    expect(actionLabel({ name: "scroll", direction: "down", amount: 3, x: 9, y: 8 }, es)).toBe("Desplazar abajo 3 en (9, 8)");
    expect(actionLabel({ name: "key", key: "ctrl+a", repeat: 2 }, en)).toBe("Press ctrl+a × 2");
    expect(actionLabel({ name: "wait", seconds: 2 }, es)).toBe("Esperar 2 s");
    expect(actionLabel({ name: "screenshot" }, en)).toBe("Screenshot");
    expect(actionLabel({ name: "frobnicate" }, en)).toBe("frobnicate");
  });
  it("shows the text typed, and never a password", () => {
    expect(actionLabel({ name: "type", text: "pictures of cats", chars: 16 }, en)).toBe("Type “pictures of cats”");
    expect(actionLabel({ name: "type", text: "hola", chars: 4 }, es)).toBe("Escribir «hola»");
    const hidden = actionLabel({ name: "type", chars: 14 }, en, true);
    expect(hidden).toBe("Type 14 characters (hidden)");
    expect(actionLabel({ name: "type", text: "hunter2", chars: 7 }, es, true)).not.toContain("hunter2");
  });
  it("crops the screenshot around the action and puts the marker on it", () => {
    const { box, points, scale } = cropStyle(region, "/api/desktop/shots/dsk_a/1", 180);
    expect(scale).toBe(0.5);
    expect(box).toMatchObject({ width: 180, height: 110, backgroundSize: "512px 384px", backgroundPosition: "-166px -274px" });
    expect(points).toEqual([{ left: 90, top: 97 }]);
    expect(String(box.backgroundImage)).toBe("url(/api/desktop/shots/dsk_a/1)");
  });
  it("shows the whole screen for an action that points nowhere", () => {
    const typed = { ...play([card({ region: null, action: { name: "type", text: "hi", chars: 2 } })]).items[0] };
    const c = typed.kind === "card" ? typed.card : null;
    expect(c && regionOf(c)).toBeNull();
    expect(c && regionOf(c, { w: 1024, h: 768 })).toEqual({ x: 0, y: 0, w: 1024, h: 768, image_w: 1024, image_h: 768, points: [] });
    const pointed = play([card()]).items[0];
    expect(pointed.kind === "card" && regionOf(pointed.card, { w: 1, h: 1 })).toEqual(region);
  });
  it("describes stored actions like live ones", () => {
    const stored = recordAction({ step: 1, action: "left_click", x: 5, y: 6, decision: "approve", ok: true });
    expect(stored).toEqual({ name: "left_click", x: 5, y: 6 });
    expect(decisionText("deny", en)).toBe("denied");
    expect(decisionText("refused", es)).toBe("no disponible");
  });
});

describe("a task as it happens", () => {
  it("waits on a card until the user answers, then shows what was decided and whether it worked", () => {
    let run = play([
      { type: "desktop_conversation", id: "c1" },
      { type: "desktop_start", task: "dsk_a", provider: "Anthropic", model: "m", max_steps: 20, tool: "computer_toolset_20260801" },
      { type: "desktop_text", text: "I will click." },
      card(),
    ]);
    expect(run.phase).toBe("running");
    expect(run.conversation).toBe("c1");
    expect(waitingCard(run)?.id).toBe("dsk_a_1");
    run = applyDesktopEvent(run, { type: "desktop_resolved", id: "dsk_a_1", decision: "batch", n: 3, left: 2 });
    expect(waitingCard(run)).toBeUndefined();
    run = applyDesktopEvent(run, { type: "desktop_result", id: "dsk_a_1", ok: true, shot: 2 });
    const done = run.items.find((i) => i.kind === "card");
    expect(done && done.kind === "card" && [done.card.decision, done.card.n, done.card.left, done.card.result]).toEqual(["batch", 3, 2, "ok"]);
  });
  it("shows an action approved ahead of time as such, never as waiting", () => {
    const run = play([card({ auto: true }), { type: "desktop_resolved", id: "dsk_a_1", decision: "auto", left: 1 }]);
    expect(waitingCard(run)).toBeUndefined();
    const only = run.items[0];
    expect(only.kind === "card" && only.card.decision).toBe("auto");
  });
  it("keeps denied and failed actions and passive steps in order", () => {
    const run = play([
      card(), { type: "desktop_resolved", id: "dsk_a_1", decision: "deny" }, { type: "desktop_result", id: "dsk_a_1", ok: false, message: "denied" },
      { type: "desktop_step", id: "dsk_a_2", step: 2, action: { name: "screenshot" }, ok: true },
      { type: "desktop_error", message: "boom" },
      { type: "desktop_done", reason: "error", steps: 2, text: "", error: "boom", usage: { input: 10, output: 5, calls: 2 }, cost: null, shots: [] },
    ]);
    expect(run.items.map((i) => i.kind)).toEqual(["card", "step"]);
    expect(run.phase).toBe("done");
    expect(run.done).toMatchObject({ reason: "error", steps: 2, cost: null });
    expect(run.error).toBe("boom");
  });
  it("marks a sensitive card and keeps the password out of it", () => {
    const run = play([card({ masked: true, action: { name: "type", chars: 14 }, sensitive: { kind: "password", reason: "x" } })]);
    const c = run.items[0];
    expect(c.kind === "card" && c.card.sensitive?.kind).toBe("password");
    expect(JSON.stringify(run)).not.toContain("hunter2");
  });
});

describe("batches, the estimate and starting", () => {
  it("offers 2 to 5 and no more", () => {
    expect(MAX_BATCH).toBe(5);
    expect(batchChoices()).toEqual([2, 3, 4, 5]);
  });
  it("says what a task can cost, or why it cannot", () => {
    const est: Estimate = { max_steps: 20, calls: 21, tokens_in: 400000, tokens_out: 6300, screenshot_tokens: 1049, overhead_tokens: 4500,
      cost: 1.29, priced: true, provider: "Anthropic", model: "claude-sonnet-5-5", tool: "computer_toolset_20260801" };
    const [line, cost] = estimateText(est, en);
    expect(line).toContain("Up to 21 requests to Anthropic");
    expect(cost).toBe("Estimated maximum cost: 1.29 at the prices you entered.");
    expect(estimateText({ ...est, cost: null, priced: false }, es)[1]).toContain("no puede calcular el coste");
  });
  it("blocks starting until the setting is on, a provider can do it and the computer can be driven", () => {
    const status = (over: Partial<DesktopStatus["settings"]>, ok = true, available = true): DesktopStatus => ({
      settings: { enabled: true, provider_id: "anthropic", max_steps: 20, tool: "auto", ...over },
      driver: { available, backend: "xdotool", reason: "", code: "", needs: "", supports: [], notes: [] },
      providers: [{ id: "anthropic", name: "Anthropic", model: "m", ok, code: ok ? "" : "paid", reason: "" }],
      hard_max_steps: 50, running: false, task: null,
    });
    expect(startBlock(null, en)).not.toBe("");
    expect(startBlock(status({}), en)).toBe("");
    expect(startBlock(status({ enabled: false }), en)).not.toBe("");
    expect(startBlock(status({}, false), en)).not.toBe("");
    expect(startBlock(status({}, true, false), en)).not.toBe("");
    expect(startBlock(status({ provider_id: "" }), en)).not.toBe("");
  });
});

describe("a stored desktop task", () => {
  it("comes back with the chat", () => {
    const record = { task: "dsk_a", goal: "x", provider: "Anthropic", model: "m", tool: null, max_steps: 20, steps: 1, reason: "finished", error: null, final: "", actions: [], screenshots: "not kept", shots: [], usage: { input: 1, output: 1, calls: 1 } };
    const run = runFromStored({ id: "m1", role: "assistant", content: "Done.", meta: { desktop: record }, created: 1 });
    expect(run.desktop).toEqual(record);
    expect(runFromStored({ id: "m2", role: "assistant", content: "Hi", meta: {}, created: 1 }).desktop).toBeUndefined();
  });
});
