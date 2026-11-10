import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { Tour } from "./components/Tour";
import { t } from "./i18n";

let host: HTMLDivElement, root: Root;
let seen = false;
let setup: { enabled: boolean; complete: boolean } = { enabled: false, complete: true };
const get = vi.fn(async (path: string) => (path === "/api/setup" ? setup : { onboarding: { tour_seen: seen } }));
const put = vi.fn(async () => ({}));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  seen = false; setup = { enabled: false, complete: true };
  get.mockClear(); put.mockClear();
  vi.spyOn(api, "get").mockImplementation(get as never);
  vi.spyOn(api, "put").mockImplementation(put as never);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.useRealTimers(); document.querySelectorAll(".setup-backdrop").forEach((e) => e.remove()); });

const mount = async () => { await act(async () => root.render(<Tour />)); await act(async () => {}); };
const dialog = () => host.querySelector<HTMLElement>('[role="dialog"]');
const button = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
const press = (k: string, init: KeyboardEventInit = {}) =>
  act(() => { document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init })); });

it("shows the tour the first time, step by step, and records that it was seen", async () => {
  await mount();
  const d = dialog()!;
  expect(d.getAttribute("aria-modal")).toBe("true");
  expect(d.getAttribute("aria-label")).toBe(t.tour.title);
  expect(d.getAttribute("aria-describedby")).toBeTruthy();
  expect(host.querySelector("h2")!.textContent).toBe(t.tour.s1Title);
  expect(d.textContent).toContain(t.tour.step.replace("{n}", "1").replace("{total}", "5"));
  expect(button(t.tour.back).disabled).toBe(true);
  const titles = [t.tour.s2Title, t.tour.s3Title, t.tour.s4Title, t.tour.s5Title];
  for (const title of titles) {
    await act(async () => button(t.tour.next).click());
    expect(host.querySelector("h2")!.textContent).toBe(title);
  }
  expect(put).not.toHaveBeenCalled();
  await act(async () => button(t.tour.done).click());
  expect(put).toHaveBeenCalledWith("/api/settings", { onboarding: { tour_seen: true } });
  expect(dialog()).toBeNull();
});

it("names the sample projects button of the Projects header and the privacy basics", () => {
  expect(t.tour.s4Body).toMatch(/Proyectos de ejemplo|Sample projects/);
  expect(t.tour.s5Body).toMatch(/Privacidad|Privacy/);
  expect(t.tour.s2Body).toMatch(/API/);
});

it("does not show when it was already seen, and makes no request but the two local reads", async () => {
  seen = true;
  await mount();
  expect(dialog()).toBeNull();
  expect(get.mock.calls.map((c) => c[0])).toEqual(["/api/settings"]);
  expect(put).not.toHaveBeenCalled();
});

it("Escape and Skip skip it and keep that", async () => {
  await mount();
  expect(dialog()).not.toBeNull();
  press("Escape");
  expect(dialog()).toBeNull();
  expect(put).toHaveBeenCalledWith("/api/settings", { onboarding: { tour_seen: true } });
  put.mockClear();
  act(() => { window.dispatchEvent(new Event("spike:open-tour")); });
  await act(async () => button(t.tour.skip).click());
  expect(dialog()).toBeNull();
  expect(put).toHaveBeenCalledTimes(1);
});

it("can be opened again on demand even when seen", async () => {
  seen = true;
  await mount();
  act(() => { window.dispatchEvent(new Event("spike:open-tour")); });
  expect(dialog()).not.toBeNull();
  expect(host.querySelector("h2")!.textContent).toBe(t.tour.s1Title);
});

it("waits while the first-run wizard is showing and appears when it closes", async () => {
  vi.useFakeTimers();
  setup = { enabled: true, complete: false };
  const wizard = document.createElement("div"); wizard.className = "setup-backdrop"; document.body.append(wizard);
  await mount();
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(dialog()).toBeNull();
  wizard.remove();
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(dialog()).not.toBeNull();
});

it("traps focus inside, starts on the primary button and gives focus back when closed", async () => {
  const opener = document.createElement("button"); document.body.append(opener); opener.focus();
  await mount();
  const d = dialog()!;
  expect(d.contains(document.activeElement)).toBe(true);
  const buttons = [...d.querySelectorAll("button")].filter((b) => !b.disabled);
  buttons.at(-1)!.focus();
  const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
  act(() => { document.activeElement!.dispatchEvent(tab); });
  expect(tab.defaultPrevented).toBe(true);
  expect(document.activeElement).toBe(buttons[0]);
  const back = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true });
  act(() => { document.activeElement!.dispatchEvent(back); });
  expect(document.activeElement).toBe(buttons.at(-1));
  press("Escape");
  expect(document.activeElement).toBe(opener);
  opener.remove();
});
