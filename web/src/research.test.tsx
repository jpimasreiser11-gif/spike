import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { Research } from "./components/Research";
import { dicts, t } from "./i18n";

afterEach(() => { document.body.replaceChildren(); vi.unstubAllGlobals(); });

it("has matching es/en research strings and errors", () => {
  expect(Object.keys(dicts.es.research).sort()).toEqual(Object.keys(dicts.en.research).sort());
  expect(Object.keys(dicts.es.research.errors).sort()).toEqual(Object.keys(dicts.en.research.errors).sort());
});

it("does nothing on open, exposes only the selected chat notebook and invalidates previews on changes", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ id: "q", sources: [], calls: 1,
    provider: { name: "Test", model: "test", local: true }, blocked: "files_blocked", estimated_cost: null })));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<Research conversationId="selected" specialists={[]} providers={[]}
    onRun={() => {}} onClose={() => {}} />));
  expect(fetcher).not.toHaveBeenCalled();
  expect(host.querySelector("a[download]")?.getAttribute("href")).toBe("/api/research/notebooks/selected");
  const input = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, "paper.pdf");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const button = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
  await act(async () => button(t.research.preview).click());
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(button(t.research.analyze).disabled).toBe(true);
  expect(host.textContent).toContain(t.research.errors.files_blocked);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, "other.pdf");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(button(t.research.analyze)).toBeUndefined();
  await act(async () => root.unmount());
});
