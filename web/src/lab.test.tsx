import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { Lab } from "./components/Lab";
import { dicts, t } from "./i18n";
import type { ProviderInfo, Specialist } from "./types";

const hosts: HTMLDivElement[] = [];
afterEach(() => { hosts.forEach((h) => h.remove()); vi.unstubAllGlobals(); });

it("has matching Spanish and English Lab strings", () => {
  expect(Object.keys(dicts.es.lab).sort()).toEqual(Object.keys(dicts.en.lab).sort());
});

it("only reads history on mount; preview and execution require distinct clicks", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith("/runs") ? [] :
    path.endsWith("/preview") ? { id: "q", calls: 5, estimated_cost: 0.1, blocked: false, targets: [] } :
    { id: "r", kind: "probe", created: 0, rows: [] }), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); hosts.push(host); document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<Lab specialists={[{ id: "core", name: "Core" } as Specialist]}
    providers={[{ id: "p", name: "Provider" } as ProviderInfo]} onClose={() => {}} />));
  expect(fetcher.mock.calls.map((c) => c[0])).toEqual(["/api/lab/runs"]);
  const button = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
  await act(async () => button(t.lab.probePreview).click());
  expect(fetcher.mock.calls.map((c) => c[0])).toEqual(["/api/lab/runs", "/api/lab/preview"]);
  expect(host.textContent).toContain("0.100000");
  await act(async () => button(t.lab.execute).click());
  expect(fetcher.mock.calls.filter((c) => c[0] === "/api/lab/execute")).toHaveLength(1);
  expect(host.querySelector('a[download]')?.getAttribute("href")).toBe("/api/lab/runs/r/export");
  expect(button(t.lab.execute)).toBeUndefined();
  await act(async () => root.unmount());
});

it("disables execution for a blocked provider and discards the quote when targets change", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith("/runs") ? [] :
    { id: "q", calls: 5, estimated_cost: null, blocked: true, targets: [] }), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); hosts.push(host); document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<Lab specialists={[{ id: "core", name: "Core" } as Specialist]}
    providers={[]} onClose={() => {}} />));
  const button = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
  await act(async () => button(t.lab.probePreview).click());
  expect(host.textContent).toContain(t.lab.noPrice);
  expect(button(t.lab.execute).disabled).toBe(true);
  await act(async () => button(t.lab.execute).click());
  expect(fetcher.mock.calls.some((c) => c[0] === "/api/lab/execute")).toBe(false);
  await act(async () => button(t.lab.add).click());
  expect(button(t.lab.execute)).toBeUndefined();
  await act(async () => root.unmount());
});
