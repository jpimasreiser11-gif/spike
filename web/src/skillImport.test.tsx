import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { SkillImport, type ImportPreview } from "./components/SkillImport";
import { t } from "./i18n";

let host: HTMLDivElement, root: Root;
const T = t.skillImport;
const q = (id: string) => host.querySelector<HTMLElement>(`[data-testid="${id}"]`);
function type(field: HTMLInputElement, value: string) {
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true })); });
}
const preview = (over: Partial<ImportPreview> = {}): ImportPreview => ({
  preview_id: "p1", sha256: "a".repeat(64), name: "meeting-notes", description: "d", can_install: true,
  skill_md: "# Notes <img src=https://evil.example/x.png>", issues: [],
  license: { id: "MIT", status: "allowed", source: "LICENSE", can_enable: true },
  files: [{ path: "SKILL.md", size: 10, binary: false, text: "hi" }, { path: "a.bin", size: 4, binary: true }],
  source: { owner: "o", repo: "r", ref: "HEAD", path: "" }, ...over });

beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); });

it("reviews first, shows files as text, and installs only the reviewed hash", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValueOnce(preview()).mockResolvedValueOnce({ name: "meeting-notes" });
  const done = vi.fn();
  act(() => root.render(<SkillImport onInstalled={done} />));
  type(q("skill-import-url") as HTMLInputElement, "https://github.com/o/r");
  await act(async () => (q("skill-import-review") as HTMLButtonElement).click());
  expect(post).toHaveBeenCalledWith("/api/skills/import-github/preview", { url: "https://github.com/o/r" });
  expect(q("skill-import-license")!.textContent).toContain("MIT");
  expect(q("skill-import-md")!.textContent).toContain("<img src=https://evil.example/x.png>"); // text, not markup
  expect(host.querySelector("img")).toBeNull();
  expect(host.textContent).toContain(T.binary);
  expect(post).toHaveBeenCalledTimes(1); // nothing installed yet
  await act(async () => (q("skill-import-install") as HTMLButtonElement).click());
  expect(post).toHaveBeenLastCalledWith("/api/skills/import-github/install", { preview_id: "p1", sha256: "a".repeat(64) });
  expect(done).toHaveBeenCalled();
  expect(q("skill-import-done")!.textContent).toContain(T.installed);
});

it("blocks the install for a blocked license or validation problems", async () => {
  vi.spyOn(api, "post").mockResolvedValue(preview({ can_install: false,
    license: { id: "GPL-3.0", status: "blocked", source: "LICENSE", can_enable: false }, issues: [{ rule: "tools", location: "SKILL.md" }] }));
  act(() => root.render(<SkillImport onInstalled={() => {}} />));
  type(q("skill-import-url") as HTMLInputElement, "https://github.com/o/r");
  await act(async () => (q("skill-import-review") as HTMLButtonElement).click());
  expect((q("skill-import-install") as HTMLButtonElement).disabled).toBe(true);
  expect(q("skill-import-license")!.textContent).toContain(T.licenseBlocked);
  expect(q("skill-import-issues")!.textContent).toContain(T.rules.tools);
});

it("shows a translated message for a refused address", async () => {
  vi.spyOn(api, "post").mockRejectedValue(new Error("bad_url"));
  act(() => root.render(<SkillImport onInstalled={() => {}} />));
  type(q("skill-import-url") as HTMLInputElement, "https://github.com.evil.example/o/r");
  await act(async () => (q("skill-import-review") as HTMLButtonElement).click());
  expect(q("skill-import-error")!.textContent).toBe(T.errors.bad_url);
});
