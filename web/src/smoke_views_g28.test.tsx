import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ArtifactPanel } from "./components/Artifact";
import { Creator } from "./components/Creator";
import { DesktopTask } from "./components/Desktop";
import { Forge } from "./components/Forge";
import { Lab } from "./components/Lab";
import { ProjectDialog } from "./components/Projects";
import { Research } from "./components/Research";
import { SettingsDialog } from "./components/SettingsDialog";
import { WorkspacePanel } from "./components/WorkspacePanel";

const hosts: HTMLElement[] = [];
afterEach(() => {
  hosts.forEach((h) => h.remove());
  vi.unstubAllGlobals();
});

function setupTrigger(): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.textContent = "Launch";
  document.body.append(btn);
  hosts.push(btn);
  btn.focus();
  return btn;
}

it("restores focus and makes zero provider POST calls when opening and closing WorkspacePanel, ProjectDialog, SettingsDialog and ArtifactPanel", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const posts: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") posts.push(url);
      if (url.startsWith("/api/jobs")) return new Response(JSON.stringify({ limit: 1, ram_floor: 4e9, jobs: [] }));
      if (url.startsWith("/api/memory")) return new Response(JSON.stringify([]));
      if (url.startsWith("/api/settings")) {
        return new Response(
          JSON.stringify({
            custom_instructions: "",
            use_planner: true,
            parallel: false,
            tools_enabled: true,
            temperature: null,
            max_tokens: 1024,
            reasoning: "default",
            sandbox: "auto",
            tool_policies: {},
            specialist_providers: {},
            specialist_instructions: {},
            disabled_skills: [],
            trust: { enabled: true, external: false, threshold: 0.5, provider_id: "" },
            local_runtime: { model: "", adapters: [], context: 4096, gpu_layers: 99, threads: 4, kv_cache_type: "q8_0" },
          }),
        );
      }
      return new Response(JSON.stringify({}));
    }),
  );

  for (const renderView of [
    (onClose: () => void) => <WorkspacePanel specialists={[]} onClose={onClose} />,
    (onClose: () => void) => (
      <ProjectDialog project={null} specialists={[]} designs={[]} onClose={onClose} onSaved={() => {}} onDeleted={() => {}} />
    ),
    (onClose: () => void) => (
      <SettingsDialog onClose={onClose} onDesktop={() => {}} specialists={[]} providers={[]} reloadProviders={() => {}} />
    ),
    (onClose: () => void) => (
      <ArtifactPanel doc={{ title: "Test", html: "<p>ok</p>", filename: "test.html" }} onClose={onClose} />
    ),
  ]) {
    const trigger = setupTrigger();
    const host = document.createElement("div");
    document.body.append(host);
    hosts.push(host);
    const root = createRoot(host);
    await act(async () => root.render(renderView(() => {})));
    expect(posts).toEqual([]);
    // Move focus inside the mounted view/dialog so unmounting drops focus to body unless restored.
    const innerBtn = host.querySelector("button") as HTMLButtonElement | null;
    innerBtn?.focus();
    await act(async () => root.unmount());
    expect(document.activeElement).toBe(trigger);
  }
});

it("restores focus and makes zero provider calls when opening and closing Research, Lab, Creator, Forge and DesktopTask", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const posts: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") posts.push(url);
      if (url.startsWith("/api/lab/runs")) return new Response(JSON.stringify([]));
      if (url.startsWith("/api/creator/templates")) return new Response(JSON.stringify([]));
      if (url.startsWith("/api/forge/prototypes")) return new Response(JSON.stringify({ git: true, runs: [] }));
      if (url.startsWith("/api/skills")) return new Response(JSON.stringify([]));
      if (url.startsWith("/api/desktop/estimate")) {
        return new Response(
          JSON.stringify({
            provider: "Anthropic",
            model: "claude-sonnet-5-5",
            max_steps: 20,
            calls: 21,
            tokens_in: 40000,
            tokens_out: 4000,
            screenshot_tokens: 1000,
            overhead_tokens: 500,
            cost: null,
            priced: false,
            tool: "auto",
          }),
        );
      }
      return new Response(JSON.stringify({}));
    }),
  );

  for (const renderView of [
    (onClose: () => void) => <Research specialists={[]} providers={[]} onRun={() => {}} onClose={onClose} />,
    (onClose: () => void) => <Lab specialists={[]} providers={[]} onClose={onClose} />,
    (onClose: () => void) => <Creator specialists={[]} providers={[]} designs={[]} onRun={() => {}} onClose={onClose} />,
    (onClose: () => void) => <Forge specialists={[]} providers={[]} onRun={() => {}} onClose={onClose} />,
    (onClose: () => void) => <DesktopTask onClose={onClose} onChat={() => {}} onFinished={() => {}} />,
  ]) {
    const trigger = setupTrigger();
    const host = document.createElement("div");
    document.body.append(host);
    hosts.push(host);
    const root = createRoot(host);
    await act(async () => root.render(renderView(() => {})));
    expect(posts.filter((u) => !u.endsWith("/api/desktop/estimate"))).toEqual([]);
    const innerBtn = host.querySelector("button") as HTMLButtonElement | null;
    innerBtn?.focus();
    await act(async () => root.unmount());
    expect(document.activeElement).toBe(trigger);
  }
});
