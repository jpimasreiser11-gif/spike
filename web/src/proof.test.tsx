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
