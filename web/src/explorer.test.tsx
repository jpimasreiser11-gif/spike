import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArtifactContext, type ArtifactDoc } from "./components/Artifact";
import { ArchitectureCard, GeoCard } from "./components/Explorer";
import { ViewRecorder } from "./components/ViewRecorder";
import { architectureDocument, fill, geoDocument, safeSvg, svgImage } from "./explorer";
import { dicts, t } from "./i18n";
import type { ArchitectureUi, GeoUi, ViewStatus } from "./types";
import { ignoredList, questionText, stepLabel, stepRow } from "./viewRecorder";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="100%"><title id="t">Mapa</title><style>.a{fill:#123}</style><rect class="a" width="10" height="10"/><text x="1" y="2">Madrid &lt;b&gt;</text></svg>';
const geo = (over: Partial<GeoUi> = {}): GeoUi => ({
  kind: "geo_map", title: "Ciudades", svg: SVG, source: "ciudades.geojson", projection: "equirectangular", lat_ts: 40, radius_km: 6371.0088,
  stats: { features: 2, points: 2, lines: 0, polygons: 0 }, bbox: [40, -3, 41, 2], value: null, legend: [],
  rows: [{ name: "<img src=x onerror=alert(1)>", points: 1, length_km: null, perimeter_km: null, area_km2: null }], rows_truncated: false, skipped: [], truncated: null, ...over });
const graph = (over: Partial<ArchitectureUi> = {}): ArchitectureUi => ({
  kind: "architecture", title: "proyecto", svg: SVG, lazy: false, cycles_total: 1,
  cycles: [{ size: 2, members: ["a.py", "<b>.py"], more: 0, path: ["a.py", "<b>.py", "a.py"] }],
  stats: { modules: 3, python: 3, javascript: 0, edges: 2, static: 2, lazy: 0, type: 0, external: 4, unresolved: 1, cycles: 1, in_cycles: 2, shown: 3 },
  truncated: {}, errors: [], ...over });

const hosts: HTMLDivElement[] = [];
afterEach(() => { hosts.forEach((h) => h.remove()); hosts.length = 0; vi.unstubAllGlobals(); });
function mount(node: React.ReactNode) {
  const host = document.createElement("div"); hosts.push(host); document.body.append(host);
  const root = createRoot(host);
  act(() => root.render(node));
  return { host, root };
}

describe("the explorer's text", () => {
  it("has the same keys in Spanish and English, and covers every question the replay can ask", () => {
    for (const block of ["explorer", "viewRecorder"] as const) expect(Object.keys(dicts.es[block]).sort()).toEqual(Object.keys(dicts.en[block]).sort());
    for (const block of ["questions", "options", "actions", "state", "stepStatus", "reasons"] as const)
      expect(Object.keys(dicts.es.viewRecorder[block]).sort()).toEqual(Object.keys(dicts.en.viewRecorder[block]).sort());
    expect(Object.keys(dicts.es.explorer.left).sort()).toEqual(Object.keys(dicts.en.explorer.left).sort());
    const codes = ["type_submit", "enter", "click_submit", "click_unnamed", "recorded", "open", "blocked", "scheme", "tool_blocked", "no_target", "failed", "secret", "step"];
    for (const code of codes) expect(dicts.es.viewRecorder.questions[code], code).toBeTruthy();
    for (const option of ["allow_once", "allow_domain", "skip", "stop", "retry", "next", "provide"]) expect(dicts.en.viewRecorder.options[option], option).toBeTruthy();
  });
  it("fills the numbers of a text", () => {
    expect(fill("{n} of {m}", { n: 3, m: 5 })).toBe("3 of 5");
    expect(fill("{x}", {})).toBe("{x}");
  });
});

describe("the drawing the server made", () => {
  it("is shown only when it is an SVG with nothing that can run or load", () => {
    expect(safeSvg(SVG)).toBe(SVG);
    for (const bad of [
      '<svg><script>alert(1)</script></svg>', '<svg onload="alert(1)"></svg>', '<svg><foreignObject><div/></foreignObject></svg>',
      '<svg><a href="javascript:alert(1)"><text>x</text></a></svg>', '<svg><image href="https://evil.test/x.png"/></svg>',
      '<svg><rect style="fill:url(https://evil.test/x)"/></svg>', '<svg><style>@import "https://evil.test/x.css";</style></svg>',
      '<div>not an svg</div>', '<svg>', '', null, 42]) expect(safeSvg(bad), String(bad)).toBeNull();
    expect(safeSvg('<svg><text>online = 3 and one = 1</text></svg>')).not.toBeNull(); // words in a label are not handlers
  });
  it("is an image in the chat, which can run no script", () => {
    expect(svgImage(SVG)).toMatch(/^data:image\/svg\+xml;charset=utf-8,%3Csvg/);
  });
});

describe("map card and page", () => {
  it("escapes every name in the page it opens in the artifacts panel", () => {
    const doc = geoDocument(geo())!;
    const parsed = new DOMParser().parseFromString(doc.html, "text/html");
    expect(parsed.querySelectorAll("img")).toHaveLength(0);
    expect(parsed.querySelector("script")).toBeNull();
    expect(parsed.querySelector("svg")).not.toBeNull();
    expect(parsed.body.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(parsed.body.textContent).toMatch(/6\D?371[.,]0088/); // the radius of the sphere is stated
    expect(doc.filename).toBe("ciudades.html");
    expect(geoDocument(geo({ svg: "<svg><script>x</script></svg>" }))).toBeNull();
  });
  it("shows the picture as an image and opens the page on click", () => {
    let opened: ArtifactDoc | null = null;
    const { host, root } = mount(<ArtifactContext.Provider value={(d) => { opened = d; }}><GeoCard ui={geo()} /></ArtifactContext.Provider>);
    expect(host.querySelector("img.explorer-svg")?.getAttribute("src")).toBe(svgImage(SVG));
    expect(host.querySelector("svg")).toBeNull(); // never injected into the app's own page
    expect(host.textContent).toContain("<img src=x onerror=alert(1)>"); // a feature's name is text
    expect(host.querySelectorAll("img")).toHaveLength(1);
    act(() => [...host.querySelectorAll("button")].find((b) => b.textContent === t.explorer.openPanel)!.click());
    expect(opened).not.toBeNull();
    expect(opened!.title).toBe("Ciudades");
    act(() => root.unmount());
  });
  it("draws when the server sends an empty `truncated` map and says in words what a cut file left out", () => {
    // the server sends {} when nothing was cut (found by the browser test: an object as a React child stopped the whole chat)
    const whole = mount(<GeoCard ui={geo({ truncated: {} })} />);
    expect(whole.host.querySelector("img.explorer-svg")).not.toBeNull();
    expect(whole.host.textContent).not.toContain("[object Object]");
    act(() => whole.root.unmount());
    const cut = { features: 9000, vertices: 250000 };
    const { host, root } = mount(<GeoCard ui={geo({ truncated: cut })} />);
    expect(host.textContent).toMatch(/9\D?000/);
    expect(host.textContent).toMatch(/250\D?000/);
    act(() => root.unmount());
    const page = new DOMParser().parseFromString(geoDocument(geo({ truncated: cut }))!.html, "text/html");
    expect(page.body.textContent).toMatch(/250\D?000/);
    expect(geoDocument(geo({ truncated: {} }))!.html).not.toContain("[object Object]");
  });
  it("says so instead of drawing an unsafe picture", () => {
    const { host, root } = mount(<ArtifactContext.Provider value={() => {}}><GeoCard ui={geo({ svg: "<svg><script>x</script></svg>" })} /></ArtifactContext.Provider>);
    expect(host.querySelector("img")).toBeNull();
    expect(host.textContent).toContain(t.explorer.unsafe);
    expect([...host.querySelectorAll("button")].every((b) => b.disabled)).toBe(true);
    act(() => root.unmount());
  });
});

describe("architecture card and page", () => {
  it("lists each cycle with its path, escaped, in the card and in the page", () => {
    const { host, root } = mount(<ArtifactContext.Provider value={() => {}}><ArchitectureCard ui={graph()} /></ArtifactContext.Provider>);
    expect(host.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(host.querySelector("tbody code")?.textContent).toBe("a.py → <b>.py → a.py");
    expect(host.querySelector("b > b")).toBeNull();
    expect(host.textContent).toContain(t.explorer.lazyOff);
    expect(host.textContent).toContain("4"); // what was left out is said
    act(() => root.unmount());
    const doc = architectureDocument(graph())!;
    const parsed = new DOMParser().parseFromString(doc.html, "text/html");
    expect(parsed.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(parsed.querySelector("tbody code")?.textContent).toBe("a.py → <b>.py → a.py");
    expect(parsed.querySelector("svg")).not.toBeNull();
    expect(doc.filename).toBe("proyecto-architecture.html");
  });
  it("says there are no cycles, what was truncated and what the cycles count", () => {
    const ui = graph({ cycles: [], lazy: true, truncated: { files: 3000, large: 2 }, errors: ["x.py: SyntaxError"],
      stats: { ...graph().stats, cycles: 0, in_cycles: 0, shown: 2 } });
    const { host, root } = mount(<ArchitectureCard ui={ui} />);
    expect(host.textContent).toContain(t.explorer.noCycles);
    expect(host.textContent).toContain(t.explorer.lazyOn);
    expect(host.textContent).toContain(fill(t.explorer.showing, { n: 2, m: 3 }));
    expect(host.textContent).toContain(fill(t.explorer.left.files, { n: 3000 }));
    expect(host.textContent).toContain(fill(t.explorer.left.large, { n: 2 }));
    expect(host.textContent).toContain("x.py: SyntaxError");
    act(() => root.unmount());
  });
});

describe("the recorder panel", () => {
  it("never shows the text of a secret step and describes every step the same way", () => {
    expect(stepLabel(stepRow({ action: "type", secret: true, target: { by: "role", role: "textbox", name: "Clave" } }, 0))).toContain(t.viewRecorder.asksText);
    expect(stepLabel(stepRow({ action: "type", text: "Ana", target: { by: "role", role: "textbox", name: "Nombre" } }, 1))).toContain("Ana");
    expect(stepRow({ action: "click", target: { by: "none" }, element: "algo" }, 2).name).toBe("algo");
    expect(stepRow({ action: "click", target: { by: "role", role: "button", name: "Enviar" }, submits: true }, 3).submits).toBe(true);
    expect(stepLabel(stepRow({ action: "navigate", url: "https://a.test/" }, 4))).toContain("https://a.test/");
    expect(ignoredList({ browser_hover: 2, browser_press_key: 1 })).toBe("hover: 2, press_key: 1");
    const question = { id: "q", kind: "domain" as const, code: "open", step: 0, domain: "boe.es", detail: "", reason: "opens boe.es", options: [] };
    expect(questionText(question)).toContain("boe.es");
    expect(questionText({ ...question, code: "something_new" })).toBe("opens boe.es"); // a code the app does not know: the server's own words
  });

  const status = (over: Partial<ViewStatus> = {}): ViewStatus => ({
    running: true, scripts: [{ id: "pedido", name: "Pedido", steps: 3 }],
    recording: { recording: false, name: "", steps: [], ignored: {}, truncated: false },
    replay: { state: "idle", reason: "", mode: "auto", script: null, index: 0, total: 0, steps: [], question: null }, ...over });

  it("starts a replay, shows the question the replay waits on and answers it, with the secret text only in that answer", async () => {
    let current = status();
    const calls: { path: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (path === "/api/browser/replay" && init?.method === "POST") {
        current = status({ replay: { state: "waiting", reason: "", mode: "auto", script: { id: "pedido", name: "Pedido" }, index: 1, total: 2,
          steps: [{ n: 0, action: "navigate", name: "", url: "https://shop.test/", status: "done" }, { n: 1, action: "type", name: "Clave", secret: true, status: "pending" }],
          question: { id: "q1", kind: "secret", code: "secret", step: 1, domain: null, detail: "", reason: "", options: ["provide", "skip", "stop"] } } });
      }
      return new Response(JSON.stringify(path.startsWith("/api/browser/recorder") ? current : { ok: true }), { status: 200 });
    }));
    let host!: HTMLDivElement; let root!: ReturnType<typeof createRoot>;
    await act(async () => { ({ host, root } = mount(<ViewRecorder />)); });
    const button = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
    expect(host.textContent).toContain(t.viewRecorder.privacy);
    await act(async () => button(t.viewRecorder.play).click());
    expect(calls.find((c) => c.path === "/api/browser/replay")?.body).toEqual({ script: "pedido", mode: "auto" });
    expect(host.textContent).toContain(questionText(current.replay.question!));
    expect(button(t.viewRecorder.options.provide).disabled).toBe(true); // no text yet
    const input = host.querySelector('input[type="password"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "mi-clave");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => button(t.viewRecorder.options.provide).click());
    expect(calls.find((c) => c.path === "/api/browser/replay/answer")?.body).toEqual({ question: "q1", decision: "provide", value: "mi-clave" });
    expect(host.textContent).not.toContain("mi-clave");
    await act(async () => button(t.viewRecorder.stopReplay).click());
    expect(calls.some((c) => c.path === "/api/browser/replay/stop")).toBe(true);
    await act(async () => root.unmount());
  });

  it("cannot record or replay while Spike View is off, and says so", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(status({ running: false })), { status: 200 })));
    let host!: HTMLDivElement; let root!: ReturnType<typeof createRoot>;
    await act(async () => { ({ host, root } = mount(<ViewRecorder />)); });
    expect(host.textContent).toContain(t.viewRecorder.off);
    expect([t.viewRecorder.record, t.viewRecorder.play, t.viewRecorder.stepByStep].every((n) => [...host.querySelectorAll("button")].find((b) => b.textContent === n)!.disabled)).toBe(true);
    await act(async () => root.unmount());
  });
});
