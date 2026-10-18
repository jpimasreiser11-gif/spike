import { describe, expect, it } from "vitest";
import { chartSvg, checkSpec } from "./chart";

// jsdom has no canvas; Vega then estimates text widths, which is all an SVG needs
HTMLCanvasElement.prototype.getContext = () => null;

const SPEC = {
  $schema: "https://vega.github.io/schema/vega-lite/v6.json", title: "Ingresos",
  data: { values: [{ x: "norte", y: 90 }, { x: "sur", y: 70 }] }, mark: { type: "bar" },
  encoding: { x: { field: "x", type: "nominal", title: "region", sort: null }, y: { field: "y", type: "quantitative", title: "ingresos" },
    tooltip: [{ field: "x", type: "nominal", title: "region" }, { field: "y", type: "quantitative", title: "ingresos" }] },
  width: "container", height: 260,
};

describe("charts", () => {
  it("accepts what the server builds and refuses anything that could reach out", () => {
    expect(checkSpec(SPEC)).toBeNull();
    expect(checkSpec({ ...SPEC, data: { url: "https://evil.example/data.csv" } })).toMatch(/inline/);
    expect(checkSpec({ ...SPEC, mark: { type: "image" } })).toMatch(/mark/);
    expect(checkSpec({ ...SPEC, encoding: { ...SPEC.encoding, href: { field: "x" } } })).toMatch(/href/);
    expect(checkSpec({ ...SPEC, encoding: { x: { field: "datum.constructor" } } })).toMatch(/field/);
    expect(checkSpec({ ...SPEC, transform: [{ calculate: "1", as: "z" }] })).toMatch(/transform/);
    expect(checkSpec({ ...SPEC, data: { values: [{ x: { nested: 1 } }] } })).toMatch(/value/);
  });

  it("draws the bars as SVG without a browser", async () => {
    const svg = await chartSvg(SPEC, 400);
    expect(svg.startsWith("<svg")).toBe(true);
    expect(svg).toContain("norte");
    expect(svg).toContain("Ingresos");
    expect(svg.match(/<path[^>]*aria-roledescription="bar"/g)?.length).toBe(2);
    await expect(chartSvg({ ...SPEC, data: { url: "x.csv" } })).rejects.toThrow(/refused/);
  });
});
