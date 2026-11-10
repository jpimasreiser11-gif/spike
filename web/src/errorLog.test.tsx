import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { ErrorLog, type ErrorEntry } from "./components/ErrorLog";
import { t } from "./i18n";

let host: HTMLDivElement, root: Root;
const entry: ErrorEntry = { time: 1700000000, kind: "route", where: "GET /api/test/{id}", type: "RuntimeError",
  frames: ["spike/server/app.py:10 in boom"], version: "0.1.0" };
const report = "SPIKE error log (anonymised on this computer; nothing was sent)\n\nSPIKE: 0.1.0\n";
const writeText = vi.fn(async (_text: string) => {});

beforeEach(async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, "get").mockImplementation(async (path: string) =>
    (path === "/api/errors/report" ? { text: report } : { entries: [entry], path: "~/.spike/logs/errors.log" }) as never);
  vi.spyOn(api, "del").mockResolvedValue({ ok: true } as never);
  vi.spyOn(api, "post");
  await act(async () => root.render(<ErrorLog />));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); writeText.mockClear(); });

const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label)!;

it("lists the local entries with their kind, place and frames", () => {
  expect(api.get).toHaveBeenCalledWith("/api/errors");
  expect(host.textContent).toContain("GET /api/test/{id}");
  expect(host.textContent).toContain("RuntimeError");
  expect(host.textContent).toContain(t.errorLog.kinds.route);
  expect(host.textContent).toContain("spike/server/app.py:10 in boom");
  expect(host.textContent).toContain("~/.spike/logs/errors.log");
});

it("copies the issue text to the clipboard and sends nothing", async () => {
  await act(async () => button(t.errorLog.copy).click());
  expect(api.get).toHaveBeenCalledWith("/api/errors/report");
  expect(writeText).toHaveBeenCalledWith(report);
  expect(api.post).not.toHaveBeenCalled();
  expect(host.textContent).toContain(t.errorLog.copied);
});

it("shows the text to copy by hand when the clipboard is refused", async () => {
  writeText.mockRejectedValueOnce(new Error("denied"));
  await act(async () => button(t.errorLog.copy).click());
  expect(host.textContent).toContain(t.errorLog.copyFailed);
  expect(host.querySelector("textarea")?.value).toBe(report);
});

it("clears the log", async () => {
  vi.mocked(api.get).mockImplementation(async () => ({ entries: [], path: "~/.spike/logs/errors.log" }) as never);
  await act(async () => button(t.errorLog.clear).click());
  expect(api.del).toHaveBeenCalledWith("/api/errors");
  expect(host.textContent).toContain(t.errorLog.empty);
});
