import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ArtifactContext } from "./components/Artifact";
import { ArtifactFiles, MAX_PREVIEW_BYTES } from "./components/ArtifactFiles";
import { AssistantMessage } from "./components/AssistantMessage";
import { dicts, t } from "./i18n";
import { emptyRun } from "./run";

const mounted: { root: Root; host: HTMLDivElement }[] = [];
afterEach(async () => {
  for (const { root, host } of mounted.splice(0)) { await act(async () => root.unmount()); host.remove(); }
  vi.unstubAllGlobals();
});

async function mount(files = [{ path: "informe.md", ok: true }], replay = false) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host); mounted.push({ root, host });
  const open = vi.fn();
  const draw = (projectId = "p1") => root.render(<ArtifactContext.Provider value={open}>
    <ArtifactFiles files={files} projectId={projectId} replay={replay} />
  </ArtifactContext.Provider>);
  await act(async () => draw());
  const click = async (path = files[0].path) => {
    const row = [...host.querySelectorAll("[data-artifact-file]")].find((el) => el.getAttribute("data-artifact-file") === path)!;
    await act(async () => (row.querySelector("button") as HTMLButtonElement).click());
  };
  return { host, root, open, draw, click };
}

it("loads only after click and renders text as text, while downloading the original", async () => {
  const payload = "# Informe <img src=x onerror=alert(1)>";
  const fetcher = vi.fn(async () => new Response(payload)); vi.stubGlobal("fetch", fetcher);
  const { host, click, open } = await mount();
  expect(fetcher).not.toHaveBeenCalled();
  expect(host.querySelector("a")?.getAttribute("href")).toBe("/api/projects/p1/files/informe.md");
  await click();
  expect(fetcher.mock.calls).toHaveLength(1);
  expect(host.querySelector("pre")?.textContent).toBe(payload);
  expect(host.querySelector("img")).toBeNull();
  expect(open).not.toHaveBeenCalled();
});

it("opens HTML and SVG in the existing isolated artifact panel", async () => {
  const payload = "<svg><title>Diagrama</title></svg>";
  vi.stubGlobal("fetch", vi.fn(async () => new Response(payload)));
  const { open, click } = await mount([{ path: "figuras/uno.SVG", ok: true }]);
  await click();
  expect(open).toHaveBeenCalledWith({ title: "Diagrama", html: payload, filename: "uno.SVG" });
});

it("does not offer actions for missing files, invalid paths or replay", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const { host } = await mount([{ path: "missing.html", ok: false }, { path: "../secret.txt", ok: true }]);
  expect(host.querySelector("a,button")).toBeNull();
  const replay = await mount([{ path: "old.html", ok: true }], true);
  expect(replay.host.querySelector("a,button")).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
});

it.each([404, "network"])("shows a recoverable error for %s and retries only on click", async (failure) => {
  const fetcher = vi.fn().mockImplementationOnce(async () => {
    if (failure === "network") throw new Error("private transport details");
    return new Response("private path", { status: Number(failure) });
  }).mockResolvedValueOnce(new Response("recovered"));
  vi.stubGlobal("fetch", fetcher);
  const { host, click } = await mount();
  await click();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(t.artifactFiles.failed);
  expect(host.textContent).not.toContain("private");
  expect(fetcher).toHaveBeenCalledTimes(1);
  await click();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(host.querySelector("pre")?.textContent).toBe("recovered");
});

it("shows progress and ignores a late response after another preview is selected", async () => {
  let resolve!: (response: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((r) => { resolve = r; }))
    .mockResolvedValueOnce(new Response("<h1>Second</h1>"));
  vi.stubGlobal("fetch", fetcher);
  const { host, open, click } = await mount([{ path: "first.html", ok: true }, { path: "second.html", ok: true }]);
  await click("first.html");
  expect(host.textContent).toContain(t.artifactFiles.loading);
  await click("second.html");
  await act(async () => resolve(new Response("<h1>First</h1>")));
  expect(open).toHaveBeenCalledTimes(1);
  expect(open.mock.calls[0][0].filename).toBe("second.html");
});

it("ignores a late response after the project changes", async () => {
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((r) => { resolve = r; })));
  const { open, draw, click } = await mount([{ path: "report.html", ok: true }]);
  await click();
  await act(async () => draw("p2"));
  await act(async () => resolve(new Response("<h1>Old project</h1>")));
  expect(open).not.toHaveBeenCalled();
});

it("limits streamed preview size even without a Content-Length header", async () => {
  const cancel = vi.fn();
  const body = new ReadableStream({ start(c) { c.enqueue(new Uint8Array(MAX_PREVIEW_BYTES + 1)); }, cancel });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body)));
  const { host, click, open } = await mount([{ path: "big.html", ok: true }]);
  await click();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(t.artifactFiles.tooLarge);
  expect(cancel).toHaveBeenCalled();
  expect(open).not.toHaveBeenCalled();
});

it("rejects declared oversized files before consuming their body", async () => {
  const cancel = vi.fn();
  const body = new ReadableStream({ cancel });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { headers: { "Content-Length": String(MAX_PREVIEW_BYTES + 1) } })));
  const { host, click } = await mount();
  await click();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(t.artifactFiles.tooLarge);
  expect(cancel).toHaveBeenCalled();
});

it.each([new Uint8Array([255]), new Uint8Array([0])])("rejects binary or invalid UTF-8 content", async (bytes) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(bytes)));
  const { host, click, open } = await mount([{ path: "invalid.html", ok: true }]);
  await click();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(t.artifactFiles.failed);
  expect(open).not.toHaveBeenCalled();
});

it("cancels an obsolete response body instead of reading it after unmount", async () => {
  let resolve!: (response: Response) => void;
  const cancel = vi.fn();
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((r) => { resolve = r; })));
  const { root, click, open } = await mount([{ path: "old.html", ok: true }]);
  await click();
  await act(async () => root.unmount());
  await act(async () => resolve(new Response(new ReadableStream({ cancel }))));
  expect(cancel).toHaveBeenCalled();
  expect(open).not.toHaveBeenCalled();
});

it("keeps Spanish and English artifact actions in sync", () => {
  expect(Object.keys(dicts.es.artifactFiles).sort()).toEqual(Object.keys(dicts.en.artifactFiles).sort());
});

it("makes checked Forge deliverables previewable in the report", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("report body")));
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host); mounted.push({ root, host });
  const run = { ...emptyRun(), forge: { report: { criteria: [], deliverables: [{ path: "report.md", ok: true, bytes: 11, subtask: "t1" }],
    rounds: 1, verified: true, unresolved: [], note: "" } } };
  await act(async () => root.render(<AssistantMessage run={run} specialists={[]} />));
  const preview = host.querySelector(".forge-report button") as HTMLButtonElement;
  expect(preview).not.toBeNull();
  await act(async () => preview.click());
  expect(host.querySelector(".forge-report pre")?.textContent).toBe("report body");
});

it("does not revive a missing Forge deliverable through an earlier successful tool call", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host); mounted.push({ root, host });
  const run = { ...emptyRun(), tools: [{ id: "t1", name: "write_file", arguments: {}, done: true, ok: true, file: "lost.md" }],
    forge: { report: { criteria: [], deliverables: [{ path: "lost.md", ok: false, bytes: 0, subtask: "t1" }],
      rounds: 1, verified: true, unresolved: [], note: "" } } };
  await act(async () => root.render(<AssistantMessage run={run} specialists={[]} />));
  expect(host.querySelector('a[download]')).toBeNull();
});
