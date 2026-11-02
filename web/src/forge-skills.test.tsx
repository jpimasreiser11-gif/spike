import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ForgeSkills } from "./components/ForgeSkills";
import { Forge } from "./components/Forge";
import { dicts, t } from "./i18n";
import type { Blueprint, SkillInfo, Specialist } from "./types";

const roots: Root[] = [];
const hosts: HTMLDivElement[] = [];
afterEach(async () => {
  await act(async () => roots.splice(0).forEach((r) => r.unmount()));
  hosts.splice(0).forEach((h) => h.remove()); vi.unstubAllGlobals();
});
const skill = (name: string, enabled = true, source: SkillInfo["source"] = "bundled"): SkillInfo => ({
  name, enabled, source, description: `Instructions for ${name}`, license: "MIT", specialists: [], keywords: [], resources: [],
});
const inventory = [skill("writing-plans"), skill("disabled-skill", false), skill("personal-review", true, "user")];
const blueprint: Blueprint = { goal: "Create a report", requirements: ["Editable"], criteria: ["Includes sources"],
  method: "llm", note: "", steps: [{ id: "t1", specialist: "core", instruction: "Write report", role: "execute", depends_on: [], deliverables: ["report.md"] }] };

async function mount(ui: React.ReactNode) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div"); document.body.append(host); hosts.push(host);
  const root = createRoot(host); roots.push(root);
  await act(async () => root.render(ui));
  return host;
}
function Picker({ changed = () => {}, ready = () => {} }: { changed?: (v: string[]) => void; ready?: (v: boolean) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  return <ForgeSkills selected={selected} onChange={(v) => { setSelected(v); changed(v); }} onReady={ready} />;
}
function mockApi(mode = "auto") {
  const fetcher = vi.fn(async (path: string) => new Response(JSON.stringify(path === "/api/skills" ? inventory :
    path === "/api/settings" ? { skill_mode: mode } : path === "/api/forge/blueprint" ? blueprint : { runs: [] })));
  vi.stubGlobal("fetch", fetcher); return fetcher;
}

it("loads installed skills without model requests and selects only enabled entries", async () => {
  const fetcher = mockApi(); const changed = vi.fn();
  const host = await mount(<Picker changed={changed} />);
  expect(fetcher.mock.calls.map((c) => c[0]).sort()).toEqual(["/api/settings", "/api/skills"]);
  expect(host.querySelector("details")?.open).toBe(false);
  expect(host.textContent).toContain(t.forgeSkills.auto);
  expect(host.textContent).toContain(t.forgeSkills.user);
  const boxes = host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  expect(boxes[1].disabled).toBe(true);
  await act(async () => boxes[0].click());
  expect(changed).toHaveBeenLastCalledWith(["writing-plans"]);
  expect(host.textContent).toContain("writing-plans");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("keeps global skills off and exposes a recoverable inventory error", async () => {
  const fetcher = mockApi("off"); const changed = vi.fn();
  const host = await mount(<Picker changed={changed} />);
  expect(host.textContent).toContain(t.forgeSkills.off);
  for (const input of host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')) expect(input.disabled).toBe(true);
  expect(changed).not.toHaveBeenCalledWith(["writing-plans"]);
  fetcher.mockRejectedValue(new Error("private response"));
  await act(async () => host.querySelector<HTMLButtonElement>('[data-skills-refresh]')!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(t.forgeSkills.loadFailed);
  expect(host.textContent).not.toContain("private response");
  fetcher.mockImplementation(async (path: string) => new Response(JSON.stringify(path === "/api/skills" ? inventory : { skill_mode: "auto" })));
  await act(async () => host.querySelector<HTMLButtonElement>('[data-skills-refresh]')!.click());
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.disabled).toBe(false);
});

it("imports a ZIP only after file selection and does not automatically select the imported skill", async () => {
  let imported = false;
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/skills/import") { expect(options?.method).toBe("POST"); imported = true; return new Response('{"names":["new-skill"]}'); }
    return new Response(JSON.stringify(path === "/api/skills" ? (imported ? [...inventory, skill("new-skill", true, "user")] : inventory) : { skill_mode: "auto" }));
  });
  vi.stubGlobal("fetch", fetcher); const changed = vi.fn();
  const host = await mount(<Picker changed={changed} />);
  expect(imported).toBe(false);
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["fixture ZIP"], "my-skill.zip", { type: "application/zip" });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(fetcher.mock.calls.find(([path]) => path === "/api/skills/import")?.[1]?.body).toBe(file);
  expect(host.textContent).toContain("new-skill");
  expect(host.textContent).toContain(t.forgeSkills.imported);
  expect(changed).not.toHaveBeenCalledWith(["new-skill"]);
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].every((c) => !c.checked)).toBe(true);
});

it("submits chosen skills with the approved plan, never with drafting or before approval", async () => {
  const fetcher = mockApi(); const onRun = vi.fn();
  const host = await mount(<Forge specialists={[{ id: "core", name: "Core" } as Specialist]} providers={[]}
    initialTask="Create a report" onClose={() => {}} onRun={onRun} />);
  await act(async () => host.querySelector<HTMLInputElement>('[data-forge-skill="writing-plans"]')!.click());
  await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(onRun).not.toHaveBeenCalled();
  const draftCall = fetcher.mock.calls.find(([path]) => path === "/api/forge/blueprint") as unknown as [string, RequestInit];
  expect(JSON.parse(draftCall[1].body as string)).not.toHaveProperty("skills");
  await act(async () => host.querySelector<HTMLButtonElement>('[data-forge-approve]')!.click());
  expect(onRun).toHaveBeenCalledWith("Create a report", blueprint, null, { skills: ["writing-plans"] });
});

it("matches English and Spanish labels", () => {
  expect(Object.keys(dicts.es.forgeSkills).sort()).toEqual(Object.keys(dicts.en.forgeSkills).sort());
});

it("limits explicit selection to three skills while allowing deselection", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(path === "/api/skills"
    ? ["one", "two", "three", "four"].map((n) => skill(n)) : { skill_mode: "auto" }))));
  const changed = vi.fn(); const host = await mount(<Picker changed={changed} />);
  const boxes = host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  for (let i = 0; i < 3; i++) await act(async () => boxes[i].click());
  expect(boxes[3].disabled).toBe(true);
  expect(boxes[0].disabled).toBe(false);
  expect(host.textContent).toContain(t.forgeSkills.limit);
  await act(async () => boxes[0].click());
  expect(boxes[3].disabled).toBe(false);
  expect(changed).toHaveBeenLastCalledWith(["two", "three"]);
});

it("shows a loading or error explanation even when the section stays collapsed", async () => {
  let reject!: (e: Error) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((_, no) => { reject = no; })));
  const host = await mount(<Picker />);
  expect(host.querySelector("summary")?.textContent).toContain(t.forgeSkills.loading);
  await act(async () => reject(new Error("offline")));
  expect(host.querySelector("summary")?.textContent).toContain(t.forgeSkills.loadFailed);
});

it("drops a selection on refresh when it is disabled or global skills are turned off", async () => {
  const fetcher = mockApi(); const changed = vi.fn();
  const host = await mount(<Picker changed={changed} />);
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  fetcher.mockImplementation(async (path: string) => new Response(JSON.stringify(path === "/api/skills" ? inventory : { skill_mode: "off" })));
  await act(async () => host.querySelector<HTMLButtonElement>('[data-skills-refresh]')!.click());
  expect(changed).toHaveBeenLastCalledWith([]);
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
});

it("rejects invalid files without upload and handles malformed import results without leaking them", async () => {
  const fetcher = mockApi(); const host = await mount(<Picker />);
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [new File(["x"], "not-a-skill.exe")], configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(t.forgeSkills.invalid);
  fetcher.mockImplementation(async () => new Response('{"names":[{"private":"value"}]}'));
  Object.defineProperty(input, "files", { value: [new File(["x"], "skill.zip")], configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(t.forgeSkills.importFailed);
  expect(host.textContent).not.toContain("[object Object]");
});

it("filters the list without losing selected skills and rejects oversized ZIPs locally", async () => {
  const fetcher = mockApi(); const changed = vi.fn(); const host = await mount(<Picker changed={changed} />);
  await act(async () => host.querySelector<HTMLInputElement>('[data-forge-skill="writing-plans"]')!.click());
  const search = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search, "personal");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(1);
  expect(host.querySelector("summary")?.textContent).toContain("writing-plans");
  const file = new File(["x"], "huge.zip"); Object.defineProperty(file, "size", { value: 20_000_001 });
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(t.forgeSkills.invalid);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("ignores a late inventory result after leaving Forge", async () => {
  let resolve!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn((path: string) => path === "/api/skills" ? new Promise<Response>((yes) => { resolve = yes; }) :
    Promise.resolve(new Response('{"skill_mode":"auto"}'))));
  const ready = vi.fn(); const changed = vi.fn(); await mount(<Picker ready={ready} changed={changed} />);
  await act(async () => roots.pop()!.unmount());
  await act(async () => resolve(new Response(JSON.stringify(inventory))));
  expect(ready).toHaveBeenCalledTimes(1);
  expect(ready).toHaveBeenLastCalledWith(false);
  expect(changed).not.toHaveBeenCalled();
});

it("keeps initial Creator plans on their existing skills contract", async () => {
  const fetcher = mockApi(); const onRun = vi.fn();
  const host = await mount(<Forge specialists={[{ id: "core", name: "Core" } as Specialist]} providers={[]}
    initialTask="Create a report" initialBlueprint={blueprint} onClose={() => {}} onRun={onRun} />);
  expect(host.querySelector(".forge-skills")).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => host.querySelector<HTMLButtonElement>('[data-forge-approve]')!.click());
  expect(onRun).toHaveBeenCalledWith("Create a report", blueprint, null, undefined);
});
