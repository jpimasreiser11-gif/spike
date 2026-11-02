import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { SetupWizard } from "./components/SetupWizard";
import { dicts, t } from "./i18n";

const hosts: HTMLDivElement[] = [];
afterEach(() => { hosts.forEach((h) => h.remove()); vi.unstubAllGlobals(); });

it("matches Spanish and English setup strings", () => {
  expect(Object.keys(dicts.es.setup).sort()).toEqual(Object.keys(dicts.en.setup).sort());
});

it("checks locally and downloads only after explicit click, with unavailable specialists disabled", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const data = { enabled: true, complete: false, can_download: true, disk_free: 20e9, ram_total: 16e9,
    ram_available: 10e9, required_disk: 6e9, required_ram: 8e9, job: { status: "idle", file: "", done: 0, total: 0 },
    specialists: [{ id: "code", name: "Code", available: true }, { id: "law", name: "Law", available: false }] };
  const fetcher = vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith("/download") ? {} : data)));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); hosts.push(host); document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<SetupWizard />));
  expect(fetcher.mock.calls.map((c) => c[0])).toEqual(["/api/setup"]);
  const inputs = host.querySelectorAll("input");
  expect(inputs[1].disabled).toBe(true);
  await act(async () => inputs[0].click());
  const download = [...host.querySelectorAll("button")].find((b) => b.textContent === t.setup.download)!;
  await act(async () => download.click());
  const call = fetcher.mock.calls.find((c) => c[0] === "/api/setup/download") as unknown as [string, RequestInit];
  expect(JSON.parse(call[1].body as string)).toEqual({ specialists: ["code"] });
  await act(async () => root.unmount());
});

it("stays hidden outside the launcher", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(async () => new Response('{"enabled":false}')));
  const host = document.createElement("div"); hosts.push(host);
  const root = createRoot(host);
  await act(async () => root.render(<SetupWizard />));
  expect(host.textContent).toBe("");
  await act(async () => root.unmount());
});

it("blocks download for insufficient resources and shows localized failure without exposing remote errors", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const data = { enabled: true, complete: false, can_download: false, disk_free: 0, ram_total: 4e9,
    ram_available: 1e9, required_disk: 6e9, required_ram: 8e9, specialists: [],
    job: { status: "failed", file: "", done: 0, total: 0 } };
  const fetcher = vi.fn(async () => new Response(JSON.stringify(data)));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); hosts.push(host);
  const root = createRoot(host);
  await act(async () => root.render(<SetupWizard />));
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === t.setup.download)!;
  expect(button.disabled).toBe(true);
  expect(host.textContent).toContain(t.setup.resources);
  expect(host.textContent).toContain(t.setup.failed);
  await act(async () => button.click());
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => root.unmount());
});

it("hides a completed wizard and exposes the explicit launcher quit action", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ enabled: true, complete: true,
    job: { status: "done" } })));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); hosts.push(host);
  const root = createRoot(host);
  await act(async () => root.render(<SetupWizard />));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(host.querySelector("button")?.textContent).toBe(t.setup.quit);
  await act(async () => host.querySelector("button")!.click());
  expect((fetcher.mock.calls as unknown as [string, RequestInit][])[1][0]).toBe("/api/setup/quit");
  await act(async () => root.unmount());
});
