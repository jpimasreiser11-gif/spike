import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Replay } from "./components/Replay";
import type { ChatEvent, Specialist } from "./types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SPECIALISTS: Specialist[] = [
  {
    id: "core",
    name: "Spike Core",
    domain: "General",
    description: "Generalist",
    adapter: null,
    adapter_status: "none",
    sensitive: false,
    tools: [],
  },
];

const SAMPLE_EVENTS: ChatEvent[] = [
  { type: "status", message: "starting", t: 0.0 },
  { type: "route", mode: "single", method: "rule", confidence: 1, specialists: [{ id: "core", name: "Spike Core" }], t: 0.1 },
  { type: "tool_call", id: "c1", name: "read_file", arguments: { path: "README.md" }, t: 0.3 },
  { type: "tool_result", id: "c1", name: "read_file", ok: true, content: "ok", t: 0.5 },
  { type: "delta", text: "Respuesta corta", t: 0.8 },
];

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("Replay modal accessibility and step reliability", () => {
  it("does not double-step when ArrowRight/ArrowLeft fires on the range slider, pauses playback on arrow keys, and ignores modifier shortcuts", () => {
    vi.useFakeTimers();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<Replay events={SAMPLE_EVENTS} specialists={SPECIALISTS} onClose={() => {}} />));

    const counter = () => host.querySelector(".modal-head .muted")?.textContent ?? "";
    expect(counter()).toContain("1 / 4");

    const slider = host.querySelector<HTMLInputElement>('input[type="range"]')!;
    slider.focus();

    // Native browser range input updates slider.value before keydown finishes bubbling to window:
    // advancing 0 -> 1 on the slider must land on 2 / 4, not double-step to 3 / 4.
    const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      nativeValueSetter.call(slider, "1");
      slider.dispatchEvent(new Event("input", { bubbles: true }));
      slider.dispatchEvent(new Event("change", { bubbles: true }));
      slider.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true }));
    });
    expect(counter()).toContain("2 / 4");

    // Browser history shortcuts (Alt+ArrowLeft / Meta+ArrowRight) must not hijack replay steps.
    const closeBtn = host.querySelector<HTMLButtonElement>(".modal-head .icon-btn")!;
    closeBtn.focus();
    act(() => {
      closeBtn.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", altKey: true, bubbles: true }));
      closeBtn.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", metaKey: true, bubbles: true }));
    });
    expect(counter()).toContain("2 / 4");

    // Starting playback and pressing ArrowRight manually pauses auto-play and advances exactly one step.
    const playBtn = host.querySelector<HTMLButtonElement>(".replay-controls .btn.primary")!;
    const playLabel = playBtn.textContent;
    act(() => playBtn.click());
    expect(playBtn.textContent).not.toBe(playLabel);

    act(() => {
      closeBtn.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(counter()).toContain("3 / 4");
    expect(playBtn.textContent).toBe(playLabel);

    act(() => root.unmount());
  });

  it("handles empty or quiet-only event lists without rendering 1 / 0 or negative step indices", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const quietOnly: ChatEvent[] = [{ type: "status", message: "stopped" }];
    act(() => root.render(<Replay events={quietOnly} specialists={SPECIALISTS} onClose={() => {}} />));

    const counter = () => host.querySelector(".modal-head .muted")?.textContent ?? "";
    expect(counter()).toContain("0 / 0");

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    });
    expect(counter()).toContain("0 / 0");

    const slider = host.querySelector<HTMLInputElement>('input[type="range"]')!;
    expect(slider.value).toBe("0");
    expect(slider.disabled).toBe(true);
    const playBtn = host.querySelector<HTMLButtonElement>(".replay-controls .btn.primary")!;
    expect(playBtn.disabled).toBe(true);

    act(() => root.unmount());
  });

  it("moves focus into the dialog, traps Tab/Shift+Tab within the modal, and restores focus on close", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Open replay";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    let closed = 0;
    act(() => root.render(<Replay events={SAMPLE_EVENTS} specialists={SPECIALISTS} onClose={() => { closed += 1; }} />));

    const dialog = host.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(dialog.contains(document.activeElement)).toBe(true);

    const focusables = [...dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    )];
    expect(focusables.length).toBeGreaterThan(2);
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    last.focus();
    act(() => {
      const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
      last.dispatchEvent(ev);
    });
    expect(document.activeElement).toBe(first);

    first.focus();
    act(() => {
      const ev = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true });
      first.dispatchEvent(ev);
    });
    expect(document.activeElement).toBe(last);

    act(() => {
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(closed).toBe(1);

    act(() => root.unmount());
    expect(document.activeElement).toBe(trigger);
  });

  it("formats short and missing event text cleanly without literal 'undefined' or unnecessary ellipsis", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const longText = "a".repeat(85);
    const events: ChatEvent[] = [
      { type: "delta", text: "Breve", t: 0.1 },
      { type: "delta", text: longText, t: 0.2 },
      { type: "reasoning", t: 0.3 },
    ];
    act(() => root.render(<Replay events={events} specialists={SPECIALISTS} onClose={() => {}} />));

    const items = [...host.querySelectorAll(".replay-steps li button")].map((b) => b.textContent ?? "");
    expect(items[0]).toContain("Breve");
    expect(items[0]).not.toContain("Breve…");
    expect(items[1]).toContain(`${"a".repeat(70)}…`);
    expect(items[2]).not.toContain("undefined");

    act(() => root.unmount());
  });
});
