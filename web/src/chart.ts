/** Vega-Lite charts from Spike Data. The server builds each spec from a query's result; here it is checked again
 * (inline values only, known marks, no URLs, links or images), compiled with Vega-Lite and drawn by Vega with its
 * expression interpreter (no generated code) and a loader that refuses every request. Vega loads on first use. */
import type { TopLevelSpec } from "vega-lite";

export type ChartSpec = Record<string, unknown>;

const MARKS = new Set(["bar", "line", "area", "point", "arc"]);
const FIELDS = new Set(["x", "y", "series"]);
const BANNED = new Set(["url", "href", "image", "signals", "params", "transform", "datasets", "usermeta"]);

/** Why a spec is not one SPIKE builds, or null when it is. */
export function checkSpec(spec: unknown): string | null {
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return "not a chart";
  const s = spec as Record<string, unknown>;
  const data = s.data as { values?: unknown } | undefined;
  if (!data || typeof data !== "object" || Object.keys(data).join() !== "values" || !Array.isArray(data.values)) return "data must be inline values";
  for (const row of data.values) {
    if (!row || typeof row !== "object" || Array.isArray(row)) return "bad data row";
    for (const [k, v] of Object.entries(row)) {
      if (!FIELDS.has(k) || (v !== null && typeof v === "object")) return "bad data value";
    }
  }
  const mark = s.mark as { type?: unknown } | undefined;
  if (!mark || !MARKS.has(String(mark.type))) return "unknown mark";
  const walk = (node: unknown): string | null => {
    if (Array.isArray(node)) return node.map(walk).find((x) => x) ?? null;
    if (!node || typeof node !== "object") return null;
    for (const [k, v] of Object.entries(node)) {
      if (BANNED.has(k)) return `'${k}' is not allowed`;
      if (k === "field" && !FIELDS.has(String(v))) return "unknown field";
      const inner = walk(v);
      if (inner) return inner;
    }
    return null;
  };
  return walk({ ...s, data: null });
}

type Libs = [typeof import("vega"), typeof import("vega-lite"), typeof import("vega-interpreter")];
let libs: Promise<Libs> | null = null;
const load = () => (libs ??= Promise.all([import("vega"), import("vega-lite"), import("vega-interpreter")]));

/** Colours and type from the app's CSS variables, so charts follow the light and dark themes; exports (reports,
 * downloads) always use the light ones, since they end up on white paper. */
const LIGHT = { "--text": "#13261c", "--text-2": "#4b5e52", "--border": "#e2e8dd" };

function theme(exported: boolean): Record<string, unknown> {
  const css = !exported && typeof document !== "undefined" ? getComputedStyle(document.documentElement) : null;
  const v = (name: keyof typeof LIGHT) => css?.getPropertyValue(name).trim() || LIGHT[name];
  const muted = v("--text-2");
  const grid = v("--border");
  return {
    background: exported ? "#ffffff" : null, font: "Inter, ui-sans-serif, system-ui, sans-serif",
    range: { category: ["#5FBB47", "#2f7fc1", "#e0913a", "#8e5bc4", "#d1495b", "#1f9e8f", "#9a7b4f", "#88D445"] },
    mark: { color: "#5FBB47" }, title: { color: v("--text"), fontSize: 14, fontWeight: 600, anchor: "start" },
    axis: { labelColor: muted, titleColor: muted, gridColor: grid, domainColor: grid, tickColor: grid },
    legend: { labelColor: muted, titleColor: muted }, view: { stroke: null },
  };
}

type View = InstanceType<typeof import("vega").View>;

export async function chartView(spec: ChartSpec, opts: { container?: HTMLElement; width?: number } = {}): Promise<View> {
  const problem = checkSpec(spec);
  if (problem) throw new Error(`chart refused: ${problem}`);
  const [vega, vl, interpreter] = await load();
  // the width is the whole chart, axes and legend included, so it fits the card it is drawn in
  const width = opts.width ?? (spec.width === "container" ? 560 : spec.width);
  const sized = { ...spec, width, autosize: { type: "fit-x", contains: "padding" } };
  const compiled = vl.compile(sized as TopLevelSpec, { config: theme(!opts.container) as never }).spec;
  const loader = vega.loader();
  const refuse = () => Promise.reject(new Error("SPIKE charts load nothing"));
  Object.assign(loader, { load: refuse, sanitize: refuse, http: refuse, file: refuse });
  const view = new vega.View(vega.parse(compiled, undefined, { ast: true }), {
    expr: interpreter.expressionInterpreter, loader, renderer: opts.container ? "svg" : "none",
    container: opts.container, hover: Boolean(opts.container),
  });
  await view.runAsync();
  return view;
}

/** The chart as SVG text (for the report and downloads). */
export async function chartSvg(spec: ChartSpec, width = 640): Promise<string> {
  const view = await chartView(spec, { width });
  try {
    return await view.toSVG();
  } finally {
    view.finalize();
  }
}

/** The chart as a PNG data URL at twice its size (for Word and PDF reports). */
export async function chartPng(spec: ChartSpec, width = 640): Promise<string> {
  const view = await chartView(spec, { width });
  try {
    return await view.toImageURL("png", 2);
  } finally {
    view.finalize();
  }
}
