import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { ProofDownload } from "./components/ProofDownload";

it("lets the owner select sections and starts with environment only", () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  const root = createRoot(host);
  act(() => root.render(<ProofDownload conversationId="example" />));
  expect(host.querySelector("a")?.getAttribute("href")).toBe("/api/conversations/example/proof?include=environment");
  const chat = host.querySelector<HTMLInputElement>('input[value="chat"]')!;
  act(() => chat.click());
  expect(host.querySelector("a")?.getAttribute("href")).toContain("include=chat%2Cenvironment");
  act(() => root.unmount());
});

it("closes the section picker on Escape (restoring summary focus) and on outside pointer down", () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  const outside = document.createElement("button");
  document.body.append(host, outside);
  const root = createRoot(host);
  act(() => root.render(<ProofDownload conversationId="example" />));

  const details = host.querySelector<HTMLDetailsElement>("details.proof-download")!;
  const summary = details.querySelector<HTMLElement>("summary")!;
  const checkbox = details.querySelector<HTMLInputElement>('input[value="chat"]')!;

  details.open = true;
  checkbox.focus();
  act(() => {
    checkbox.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  });
  expect(details.open).toBe(false);
  expect(document.activeElement).toBe(summary);

  details.open = true;
  act(() => {
    checkbox.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  });
  expect(details.open).toBe(true);

  act(() => {
    outside.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  });
  expect(details.open).toBe(false);

  act(() => root.unmount());
  host.remove();
  outside.remove();
});
