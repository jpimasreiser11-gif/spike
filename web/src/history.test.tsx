import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { HistorySearch, type HistoryHit } from "./components/HistorySearch";

let host: HTMLDivElement, root: Root;
const onSelect = vi.fn(async () => {});
const hit: HistoryHit = { id: 1, conversation_id: "c", message_id: "m", title: "Decision", project_id: null,
  project_name: null, role: "assistant", created: 1, segments: [{ text: "<script>unsafe</script>", matched: true }] };
const page = { results: [hit], has_more: false, next_offset: null };
function input(value: string) {
  const field = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true })); });
}
async function submit() {
  await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
}
beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, "post").mockResolvedValue(page);
  act(() => root.render(<HistorySearch projects={[]} projectId={undefined} onClose={() => {}} onSelect={onSelect} />));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); onSelect.mockClear(); });

it("only searches after explicit submission and renders highlights as text", async () => {
  expect(api.post).not.toHaveBeenCalled(); input("decision"); expect(api.post).not.toHaveBeenCalled();
  await submit();
  expect(api.post).toHaveBeenCalledWith("/api/history/search", expect.objectContaining({ query: "decision", scope: "workspace" }));
  expect(host.querySelector("script")).toBeNull();
  expect(host.querySelector("mark")?.textContent).toBe("<script>unsafe</script>");
  await act(async () => host.querySelector<HTMLButtonElement>(".history-hit")!.click());
  expect(onSelect).toHaveBeenCalledWith(hit);
});
it("discards pending responses when the query changes", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api.post).mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
  input("old"); await submit(); input("new"); await act(async () => resolve(page));
  expect(host.querySelector(".history-hit")).toBeNull();
});
it("resets results when filters change", async () => {
  input("decision"); await submit();
  act(() => { const select = host.querySelector<HTMLSelectElement>('[name="scope"]')!;
    select.value = "all"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(host.querySelector(".history-hit")).toBeNull(); await submit();
  expect(api.post).toHaveBeenLastCalledWith("/api/history/search", expect.objectContaining({ scope: "all" }));
});
it("shows a recoverable error instead of a stale result", async () => {
  vi.mocked(api.post).mockRejectedValueOnce(new Error("offline")); input("decision"); await submit();
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  await submit(); expect(host.querySelector(".history-hit")).not.toBeNull();
});

it("appends subsequent pages with the same filters and a stable cutoff", async () => {
  vi.mocked(api.post).mockResolvedValueOnce({ ...page, has_more: true, next_offset: 20 });
  input("decision"); await submit();
  vi.mocked(api.post).mockResolvedValueOnce({ ...page, results: [{ ...hit, id: 2 }] });
  await act(async () => host.querySelector<HTMLButtonElement>(".history-more")!.click());
  expect(api.post).toHaveBeenLastCalledWith("/api/history/search", expect.objectContaining({ query: "decision", offset: 20, after: 0 }));
  expect(host.querySelectorAll(".history-hit")).toHaveLength(2);
});
it("keeps the dialog usable when a selected conversation has been deleted", async () => {
  onSelect.mockRejectedValueOnce(new Error("deleted")); input("decision"); await submit();
  await act(async () => host.querySelector<HTMLButtonElement>(".history-hit")!.click());
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  expect(host.querySelector<HTMLInputElement>('input[type="search"]')!.disabled).toBe(false);
});
