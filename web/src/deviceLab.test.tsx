import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { ArtifactContext, type ArtifactDoc } from "./components/Artifact";
import { DeviceLab, DeviceLabCard, deviceLabDocument, profileName, reasonLines } from "./components/DeviceLab";
import { dicts, projectError, t } from "./i18n";
import type { DeviceLabProfile, DeviceLabUi } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PNG = "data:image/png;base64,cG5n";
const none = { total: 0, items: [] };
const profile = (over: Partial<DeviceLabProfile>): DeviceLabProfile => ({
  id: "small-phone", name: "Small phone", kind: "phone", builtin: true, viewport: { width: 360, height: 640 }, scale: 2, touch: true, mobile: true,
  user_agent: "SpikeDeviceLab/1.0 (Mobile; phone; touch)", status: "pass", reasons: [], reason: "no problems found", http_status: 200, title: "T", notes: [],
  seconds: 1.2, screenshot: PNG, layout: { viewport_width: 360, viewport_height: 640, document_width: 360, document_height: 900, viewport_meta: true, touch_points: 1, scale: 2 },
  overflow: { ...none, px: 0 }, tap_targets: none, small_text: none, console_errors: none, failed_requests: none, blocked_requests: none, ...over });
const failing = profile({
  status: "fail", reasons: ["overflow", "tap_targets", "small_text", "console_errors", "failed_requests"], reason: "x",
  overflow: { px: 340, total: 1, items: [{ selector: "<img src=x onerror=alert(1)>", tag: "div", kind: "box", left: 0, right: 700, width: 700 }] },
  tap_targets: { total: 1, items: [{ selector: "#tiny", tag: "button", width: 16, height: 16, label: "x" }] },
  small_text: { total: 1, items: [{ selector: "#small", tag: "p", font_size: 10, text: "Tiny print" }] },
  console_errors: { total: 1, items: [{ text: "<script>alert(1)</script>", kind: "console", source: "http://127.0.0.1:1/:6" }] },
  failed_requests: { total: 1, items: [{ url: "http://127.0.0.1:1/missing.png", method: "GET", type: "image", status: 404 }] },
  notes: ["no_viewport_meta"] });
const desktop = profile({ id: "desktop", name: "Desktop", kind: "desktop", viewport: { width: 1920, height: 1080 }, scale: 1, touch: false, mobile: false });
const report: DeviceLabUi = { kind: "device_lab", version: 1, url: "http://127.0.0.1:5173/", started: "2026-11-02T10:00:00+00:00", seconds: 3, browser: "Chromium 140",
  emulated: true, allow_hosts: [], limits: { min_tap: 24, min_font: 12 }, summary: { profiles: 2, pass: 1, fail: 1, error: 0 }, profiles: [failing, desktop], android: null };
const INFO = { profiles: ["small-phone", "large-phone", "tablet-portrait", "tablet-landscape", "laptop", "desktop"].map((id, i) => ({ id, name: id, width: 360 + i, height: 640 })),
  limits: { custom: 6 }, browser: true, adb: false };
const PHONES = { found: true, error: "", devices: [{ serial: "emulator-5554", state: "device", model: "Test_Emulator", kind: "emulator", usable: true },
  { serial: "R58", state: "unauthorized", model: "", kind: "device", usable: false }] };

describe("the Device Lab report page", () => {
  it("shows every profile with its verdict and escapes everything the page and the tool produced", () => {
    const doc = deviceLabDocument(report);
    const parsed = new DOMParser().parseFromString(doc.html, "text/html");
    expect(doc.title).toBe(t.deviceLab.report);
    expect(doc.filename).toBe("device-lab-report.html");
    expect(parsed.querySelector("script")).toBeNull();
    expect(parsed.querySelector("img[onerror]")).toBeNull();
    expect(parsed.body.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(parsed.body.textContent).toContain("<script>alert(1)</script>");
    expect(parsed.querySelectorAll("tbody tr")).toHaveLength(2);
    expect([...parsed.querySelectorAll("img")].map((i) => i.getAttribute("src"))).toEqual([PNG, PNG]);
    expect(parsed.body.textContent).toContain(t.deviceLab.emulated);
    expect(parsed.body.textContent).toContain(summaryOf(report));
    const json = parsed.querySelector("pre:last-of-type")!.textContent!;
    expect(JSON.parse(json).profiles[0].id).toBe("small-phone");
    expect(json).not.toContain("base64");
  });
  it("uses a screenshot only when it is a PNG data URL", () => {
    const hostile = profile({ screenshot: 'javascript:alert(1)" onerror="x' });
    const parsed = new DOMParser().parseFromString(deviceLabDocument({ ...report, profiles: [hostile], summary: { ...report.summary, profiles: 1 } }).html, "text/html");
    expect(parsed.querySelector("img")).toBeNull();
    const svg = profile({ screenshot: "data:image/svg+xml;base64,PHN2Zz4=" });
    expect(new DOMParser().parseFromString(deviceLabDocument({ ...report, profiles: [svg] }).html, "text/html").querySelector("img")).toBeNull();
  });
  it("says what failed in the user's language, with the numbers", () => {
    expect(reasonLines(failing)).toEqual([
      t.deviceLab.reasons.overflow.replace("{n}", "340"), t.deviceLab.reasons.tap_targets.replace("{n}", "1"), t.deviceLab.reasons.small_text.replace("{n}", "1"),
      t.deviceLab.reasons.console_errors.replace("{n}", "1"), t.deviceLab.reasons.failed_requests.replace("{n}", "1")]);
    expect(reasonLines(desktop)).toEqual([t.deviceLab.reasons.clean]);
    const broken = profile({ status: "error", reasons: ["navigation"], reason: "the page leads to evil.test, which is not allowed for this run" });
    expect(reasonLines(broken)[0]).toContain("evil.test");
    expect(profileName(failing)).toBe(t.deviceLab.names["small-phone"]);
    expect(profileName(profile({ id: "custom-x", name: "My <b>screen</b>", builtin: false }))).toBe("My <b>screen</b>");
  });
  it("includes the Android screenshot only when it was taken", () => {
    const android = { status: "ok" as const, serial: "emulator-5554", model: "Test_Emulator", kind: "emulator", opened: true, steps: [], screenshot: PNG, error: "" };
    const withPhone = new DOMParser().parseFromString(deviceLabDocument({ ...report, android }).html, "text/html");
    expect(withPhone.querySelectorAll("img")).toHaveLength(3);
    expect(withPhone.body.textContent).toContain(t.deviceLab.androidNote);
    const missing = new DOMParser().parseFromString(deviceLabDocument({ ...report, android: { ...android, status: "no_device", screenshot: "" } }).html, "text/html");
    expect(missing.querySelectorAll("img")).toHaveLength(2);
    expect(missing.body.textContent).toContain(t.deviceLab.androidStatuses.no_device);
  });
});

const summaryOf = (ui: DeviceLabUi) => t.deviceLab.summary.replace("{pass}", String(ui.summary.pass)).replace("{total}", String(ui.summary.profiles));

describe("the chat card", () => {
  it("lists the verdicts and opens the whole report in the artifacts panel", () => {
    const el = document.createElement("div");
    const root = createRoot(el);
    let opened: ArtifactDoc | null = null;
    act(() => root.render(<ArtifactContext.Provider value={(doc) => { opened = doc; }}><DeviceLabCard ui={report} /></ArtifactContext.Provider>));
    expect(el.textContent).toContain(summaryOf(report));
    expect(el.querySelector('[data-status="fail"]')!.textContent).toContain(t.deviceLab.reasons.overflow.replace("{n}", "340"));
    expect(el.querySelector('[data-status="pass"]')!.textContent).toContain(t.deviceLab.names.desktop);
    act(() => el.querySelector("button")!.click());
    expect(opened).not.toBeNull();
    expect(opened!.html).toContain("#tiny");
    act(() => root.unmount());
  });
});

describe("the Device Lab window", () => {
  let host: HTMLDivElement, root: Root;
  const close = vi.fn();
  const opened: ArtifactDoc[] = [];
  const mountLab = async (info = INFO, phones = PHONES) => {
    vi.spyOn(api, "get").mockImplementation(async (path: string) => (path === "/api/device-lab" ? info : phones) as never);
    await act(async () => root.render(<ArtifactContext.Provider value={(doc) => { opened.push(doc); }}><DeviceLab onClose={close} /></ArtifactContext.Provider>));
  };
  const field = (selector: string, value: string) => {
    const input = host.querySelector<HTMLInputElement>(selector)!;
    act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const click = (selector: string) => act(() => host.querySelector<HTMLElement>(selector)!.click());
  const button = (id: string) => host.querySelector<HTMLButtonElement>(`[data-testid="${id}"]`)!;
  beforeEach(() => {
    HTMLDialogElement.prototype.showModal = function () { this.open = true; };
    HTMLDialogElement.prototype.close = function () { this.open = false; };
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  });
  afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); close.mockClear(); opened.length = 0; });

  it("only looks at what is available when it opens: nothing is started", async () => {
    const post = vi.spyOn(api, "post");
    await mountLab();
    expect(api.get).toHaveBeenCalledWith("/api/device-lab");
    expect(api.get).not.toHaveBeenCalledWith("/api/device-lab/android");  // no adb: not even a look at devices
    expect(post).not.toHaveBeenCalled();
    expect(host.querySelectorAll('[name^="profile-"]')).toHaveLength(6);
    expect([...host.querySelectorAll<HTMLInputElement>('[name^="profile-"]')].every((c) => c.checked)).toBe(true);
    expect(host.textContent).toContain(t.deviceLab.androidNone);
    expect(host.textContent).toContain(t.deviceLab.intro);
    expect(button("device-lab-run").disabled).toBe(true);
  });

  it("runs the chosen profiles only after the approval, and the approval goes when the address changes", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue(report as never);
    await mountLab();
    click('[name="profile-laptop"]'); click('[name="profile-desktop"]');
    click('[name="device-lab-approve"]');
    expect(button("device-lab-run").disabled).toBe(false);
    field('[name="device-lab-url"]', "http://localhost:3000/");
    expect(host.querySelector<HTMLInputElement>('[name="device-lab-approve"]')!.checked).toBe(false);
    expect(button("device-lab-run").disabled).toBe(true);
    click('[name="device-lab-approve"]');
    field('[name="device-lab-hosts"]', "staging.example.test, api.example.test");
    expect(host.querySelector<HTMLInputElement>('[name="device-lab-approve"]')!.checked).toBe(false);
    click('[name="device-lab-approve"]');
    await act(async () => button("device-lab-run").click());
    expect(post).toHaveBeenCalledWith("/api/device-lab/run", { url: "http://localhost:3000/", profiles: ["small-phone", "large-phone", "tablet-portrait", "tablet-landscape"],
      custom: [], allow_hosts: ["staging.example.test", "api.example.test"], approved: true });
    expect(host.querySelector('[data-testid="device-lab-results"]')!.textContent).toContain(summaryOf(report));
    expect(host.querySelectorAll('tr[data-status]')).toHaveLength(2);
    expect(host.querySelector('tr[data-status="fail"]')!.textContent).toContain(t.deviceLab.reasons.tap_targets.replace("{n}", "1"));
  });

  it("adds a custom profile, validates it, and sends it with the run", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue(report as never);
    await mountLab();
    field('[name="custom-name"]', "Kiosk");
    field('[name="custom-width"]', "50");
    expect(button("device-lab-add").disabled).toBe(true);
    expect(host.textContent).toContain(t.deviceLab.customInvalid);
    field('[name="custom-width"]', "800"); field('[name="custom-height"]', "1280"); field('[name="custom-scale"]', "2");
    click('[name="custom-touch"]');
    click('[data-testid="device-lab-add"]');
    expect(host.textContent).toContain("Kiosk");
    for (const id of ["small-phone", "large-phone", "tablet-portrait", "tablet-landscape", "laptop", "desktop"]) click(`[name="profile-${id}"]`);
    expect(button("device-lab-run").disabled).toBe(true);  // not approved yet
    click('[name="device-lab-approve"]');
    await act(async () => button("device-lab-run").click());
    expect(post).toHaveBeenCalledWith("/api/device-lab/run", expect.objectContaining({
      profiles: [], custom: [{ name: "Kiosk", width: 800, height: 1280, scale: 2, touch: false, mobile: false }], approved: true }));
  });

  it("opens the report in the artifacts panel and closes itself, and downloads the JSON", async () => {
    vi.spyOn(api, "post").mockResolvedValue(report as never);
    const created = vi.fn(() => "blob:report");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() }));
    await mountLab();
    click('[name="device-lab-approve"]');
    await act(async () => button("device-lab-run").click());
    click('[data-testid="device-lab-open"]');
    expect(opened).toHaveLength(1);
    expect(opened[0].html).toContain(t.deviceLab.report);
    expect(close).toHaveBeenCalled();
    const link = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const downloadButton = [...host.querySelectorAll("button")].find((b) => b.textContent === t.deviceLab.downloadJson)!;
    act(() => downloadButton.click());
    expect(created).toHaveBeenCalled();
    expect(link).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows the server's refusal in the user's language", async () => {
    vi.spyOn(api, "post").mockRejectedValue(new ApiError(403, "device_lab_host"));
    await mountLab();
    field('[name="device-lab-url"]', "https://example.com/");
    click('[name="device-lab-approve"]');
    await act(async () => button("device-lab-run").click());
    expect(host.querySelector('[role="alert"]')!.textContent).toBe(projectError("device_lab_host"));
    expect(host.querySelector('[role="alert"]')!.textContent).not.toBe("device_lab_host");
  });

  it("lists Android devices from adb, and the screenshot needs its own approval", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ android: { status: "ok", serial: "emulator-5554", model: "Test_Emulator", kind: "emulator", opened: true,
      steps: [{ step: "open", ok: true }, { step: "screenshot", ok: true }], screenshot: PNG, error: "" } } as never);
    await mountLab({ ...INFO, adb: true });
    expect(api.get).toHaveBeenCalledWith("/api/device-lab/android");
    const options = [...host.querySelectorAll<HTMLOptionElement>('[name="android-device"] option')];
    expect(options.map((o) => [o.value, o.disabled])).toEqual([["emulator-5554", false], ["R58", true]]);
    expect(button("device-lab-android-shot").disabled).toBe(true);
    click('[name="android-approve"]');
    expect(button("device-lab-android-shot").disabled).toBe(false);
    click('[name="android-open"]');
    await act(async () => button("device-lab-android-shot").click());
    expect(post).toHaveBeenCalledWith("/api/device-lab/android", { url: "http://localhost:5173/", serial: "emulator-5554", open_url: false, allow_hosts: [], approved: true });
    expect(host.querySelector<HTMLImageElement>('[data-testid="device-lab-android-result"] img')!.getAttribute("src")).toBe(PNG);
    expect(host.querySelector<HTMLInputElement>('[name="android-approve"]')!.checked).toBe(false);  // one yes, one capture
    expect(host.textContent).toContain(t.deviceLab.androidNote);
  });

  it("says so when adb lists nothing or fails", async () => {
    await mountLab({ ...INFO, adb: true }, { found: true, devices: [], error: "" });
    expect(host.textContent).toContain(t.deviceLab.androidEmpty);
    expect(host.querySelector('[data-testid="device-lab-android-shot"]')).toBeNull();
  });

  it("closes with the button and with Escape", async () => {
    await mountLab();
    click('[data-testid="device-lab-close"]');
    expect(close).toHaveBeenCalledTimes(1);
    act(() => { host.querySelector("dialog")!.dispatchEvent(new Event("cancel", { cancelable: true })); });
    expect(close).toHaveBeenCalledTimes(2);
  });
});

describe("Device Lab strings", () => {
  const same = (a: unknown, b: unknown): void => {
    if (a && typeof a === "object") {
      expect(Object.keys(a as object).sort()).toEqual(Object.keys(b as object).sort());
      for (const k of Object.keys(a as object)) same((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]);
    } else expect(typeof a === "string" && (a as string).length > 0 && typeof b === "string" && (b as string).length > 0).toBe(true);
  };
  it("exist in Spanish and English with the same keys", () => {
    same(dicts.es.deviceLab, dicts.en.deviceLab);
    expect(dicts.es.deviceLab.intro).not.toBe(dicts.en.deviceLab.intro);
    for (const id of ["small-phone", "large-phone", "tablet-portrait", "tablet-landscape", "laptop", "desktop"]) {
      expect(dicts.es.deviceLab.names[id]).toBeTruthy();
      expect(dicts.en.deviceLab.names[id]).toBeTruthy();
    }
    for (const code of ["overflow", "tap_targets", "small_text", "console_errors", "failed_requests", "navigation", "timeout", "clean"]) {
      expect(dicts.es.deviceLab.reasons[code]).toBeTruthy();
      expect(dicts.en.deviceLab.reasons[code]).toBeTruthy();
    }
  });
  it("translate the permission reasons and every error code the routes can answer", () => {
    for (const code of ["device_lab", "device_lab_host", "device_lab_android", "device_lab_browser"]) {
      expect(dicts.es.review[code]).toBeTruthy();
      expect(dicts.en.review[code]).toBeTruthy();
      expect(dicts.es.review[code]).not.toBe(dicts.en.review[code]);
    }
    for (const code of ["device_lab_approval", "device_lab_android_approval", "device_lab_url", "device_lab_host", "device_lab_hosts", "device_lab_profile",
      "device_lab_custom", "device_lab_browser", "device_lab_android", "device_lab_busy"]) {
      expect(projectError(code, "es")).not.toBe(code);
      expect(projectError(code, "en")).not.toBe(code);
      expect(projectError(code, "es")).not.toBe(projectError(code, "en"));
    }
  });
});
