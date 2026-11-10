import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { DataBackup, type BackupPreview } from "./components/DataBackup";
import { t } from "./i18n";

let host: HTMLDivElement, root: Root;
const T = t.dataBackup;
const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label)!;
const q = <E extends Element = HTMLElement>(id: string) => host.querySelector<E>(`[data-testid="${id}"]`);
function type(field: HTMLInputElement, value: string) {
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true })); });
}
const preview: BackupPreview = { spike_version: "0.1.0", created: 1, include_models: false, total_bytes: 10, add: 1,
  replace: 1, same: 0, files: [{ path: "spike.db", size: 5, action: "replace" }, { path: "skills/a/SKILL.md", size: 5, action: "add" }] };

beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, "get").mockResolvedValue({ word: "DELETE-4821" });
  vi.spyOn(api, "post").mockResolvedValue({ deleted: 9, secrets_deleted: false, models_deleted: false });
  act(() => root.render(<DataBackup />));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); });

it("deletes only after two confirmations and the exact word shown on screen", async () => {
  act(() => button(T.deleteStart).click());
  expect(q("delete-step1")).not.toBeNull();
  expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
  await act(async () => button(T.deleteContinue).click());
  expect(api.get).toHaveBeenCalledWith(expect.stringContaining("/api/privacy/delete-word"));
  expect(q("delete-word")!.textContent).toBe("DELETE-4821");
  const now = button(T.deleteNow) as HTMLButtonElement;
  expect(now.disabled).toBe(true);
  type(q<HTMLInputElement>("delete-input")!, "DELETE");
  expect((button(T.deleteNow) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => button(T.deleteNow).click());
  expect(api.post).not.toHaveBeenCalled();
  type(q<HTMLInputElement>("delete-input")!, "DELETE-4821");
  expect((button(T.deleteNow) as HTMLButtonElement).disabled).toBe(false);
  await act(async () => button(T.deleteNow).click());
  expect(api.post).toHaveBeenCalledWith("/api/privacy/delete", { word: "DELETE-4821", delete_models: false, delete_secrets: false });
  expect(q("delete-done")!.textContent).toContain(T.keptSecrets);
});

it("sends the models and secrets choices only when their boxes are ticked, and cancel stops", async () => {
  act(() => button(T.deleteStart).click());
  act(() => button(T.cancel).click());
  expect(q("delete-step1")).toBeNull();
  act(() => q<HTMLInputElement>("delete-secrets")!.click());
  act(() => button(T.deleteStart).click());
  await act(async () => button(T.deleteContinue).click());
  type(q<HTMLInputElement>("delete-input")!, "DELETE-4821");
  await act(async () => button(T.deleteNow).click());
  expect(api.post).toHaveBeenCalledWith("/api/privacy/delete", { word: "DELETE-4821", delete_models: false, delete_secrets: true });
});

it("previews a backup and restores without overwriting unless the box is ticked", async () => {
  const upload = vi.spyOn(api, "upload").mockImplementation(async (_m, path) =>
    (path === "/api/backup/preview" ? preview : { added: 1, replaced: 0, skipped: 1, same: 0 }) as never);
  const input = q<HTMLInputElement>("backup-file")!;
  const file = new File(["zip"], "b.zip", { type: "application/zip" });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(upload).toHaveBeenCalledWith("POST", "/api/backup/preview", file);
  expect(q("backup-preview")!.textContent).toContain("spike.db");
  expect(q<HTMLInputElement>("backup-overwrite")!.checked).toBe(false);
  await act(async () => button(T.restore).click());
  expect(upload).toHaveBeenLastCalledWith("POST", "/api/backup/restore?overwrite=0", file);
  expect(q("backup-restored")!.textContent).toContain(T.skipped);
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  act(() => q<HTMLInputElement>("backup-overwrite")!.click());
  await act(async () => button(T.restore).click());
  expect(upload).toHaveBeenLastCalledWith("POST", "/api/backup/restore?overwrite=1", file);
});

it("links the export without models unless asked", () => {
  const link = host.querySelector<HTMLAnchorElement>("a[download]")!;
  expect(link.getAttribute("href")).toBe("/api/backup/export?include_models=0");
  act(() => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  expect(link.getAttribute("href")).toBe("/api/backup/export?include_models=1");
});
