"""Spike Geo's tools: `geo_map` draws a GeoJSON or CSV file of the workspace as an SVG map (with a choropleth when
asked) and `geo_measure` gives great-circle distances and areas. The picture is made by code and goes to the app;
the model reads the numbers. Both only read the user's file and compute on this computer."""

from __future__ import annotations

import asyncio
from typing import Any

from spike.geo import data as geodata
from spike.geo import measure
from spike.geo.data import Dataset, GeoError, number
from spike.geo.render import TEXT, check_bins, choropleth_classes, prop_key, render_map
from spike.tools.base import Tool, ToolResult
from spike.tools.builtin import Workspace

MAX_ROWS = 100  # features whose measurements are listed
RADIUS_KM = measure.EARTH_RADIUS_M / 1000
ACCURACY = (f"haversine on a sphere of radius {RADIUS_KM:.4f} km; against an ellipsoidal (WGS 84) calculation expect up "
            "to about 0.5 % in distances and about 1 % in areas")
FILE = {"type": "string", "description": "a .geojson, .json or .csv file in the workspace; GeoJSON positions are "
                                         "[longitude, latitude], a CSV needs latitude and longitude columns"}
COLUMNS = {
    "lat_column": {"type": "string", "description": "CSV latitude column (found by name when omitted: lat, latitude, latitud, y)"},
    "lon_column": {"type": "string", "description": "CSV longitude column (lon, lng, long, longitude, longitud, x)"}}


def km(metres: float) -> float:
    return round(metres / 1000, 3)


def measurements(dataset: Dataset, label: str | None, value: str | None) -> list[dict[str, Any]]:
    """One row per feature: its name and, for what it has, length (lines), perimeter and area (polygons) in km and km2."""
    rows = []
    for f in dataset.features[:MAX_ROWS]:
        row: dict[str, Any] = {"name": f.name(label), "points": len(f.points), "length_km": None, "perimeter_km": None,
                               "area_km2": None}
        if f.lines:
            row["length_km"] = km(sum(measure.path_length(line) for line in f.lines))
        if f.polygons:
            row["perimeter_km"] = km(sum(measure.perimeter(pg[0]) for pg in f.polygons))
            row["area_km2"] = round(sum(measure.polygon_area(pg) for pg in f.polygons) / 1e6, 3)
        if value:
            row["value"] = number(f.props.get(prop_key(dataset, value))) if f.polygons else None
        rows.append(row)
    return rows


def table(rows: list[dict[str, Any]]) -> str:
    def cell(v: Any) -> str:
        return "" if v is None else f"{v:g}" if isinstance(v, float) else str(v)

    keys = ["name", "points", "length_km", "perimeter_km", "area_km2"] + (["value"] if rows and "value" in rows[0] else [])
    return "\n".join([" | ".join(keys)] + [" | ".join(cell(r.get(k)) for k in keys) for r in rows])


def totals(dataset: Dataset) -> dict[str, int]:
    points, lines, polygons = (sum(len(getattr(f, k)) for f in dataset.features) for k in ("points", "lines", "polygons"))
    return {"features": len(dataset.features), "points": points, "lines": lines, "polygons": polygons,
            "vertices": sum(f.vertices() for f in dataset.features)}


def bbox(dataset: Dataset) -> list[float]:
    every = [p for f in dataset.features for p in [*f.points, *(q for ln in f.lines for q in ln),
                                                   *(q for pg in f.polygons for r in pg for q in r)]]
    lats, lons = [p[0] for p in every], [p[1] for p in every]
    return [min(lats), min(lons), max(lats), max(lons)]


class _GeoTool(Tool):
    risk = "read"
    default_policy = "allow"  # reads the user's file and computes; nothing leaves the computer

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def load(self, args: dict[str, Any]) -> Dataset:
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            raise GeoError("path is required: a .geojson, .json or .csv file in the workspace")
        path = self.workspace.resolve(args["path"])
        if not path.is_file():
            raise GeoError(f"{args['path']} is not a file in the workspace")
        return geodata.load(path, args.get("lat_column"), args.get("lon_column"))

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            return await asyncio.to_thread(self.act, args)
        except (GeoError, PermissionError, OSError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")

    def act(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class GeoMap(_GeoTool):
    name = "geo_map"
    description = ("Draw a GeoJSON or CSV (latitude/longitude columns) file of the workspace as an SVG map, with no "
                   "basemap and no network: points, lines and polygons on an equirectangular projection with a graticule "
                   "and a scale bar. With `value` (a numeric polygon property) it is a choropleth in equal-interval "
                   "classes with a legend. The user sees the map; you get the counts, the classes and each feature's "
                   "length and area.")
    parameters = {"type": "object", "properties": {
        "path": FILE, **COLUMNS,
        "label": {"type": "string", "description": "property or column that names the features (name, nombre, title… are "
                                                   "found when omitted)"},
        "value": {"type": "string", "description": "numeric polygon property to colour by (a choropleth)"},
        "bins": {"type": "integer", "minimum": 2, "maximum": 7, "description": "choropleth classes, default 5"},
        "title": {"type": "string"},
        "lang": {"type": "string", "enum": ["es", "en"], "description": "language of the map's own text; default es"}},
        "required": ["path"]}

    def act(self, args: dict[str, Any]) -> ToolResult:
        lang = args.get("lang", "es")
        if lang not in ("es", "en"):
            raise GeoError("lang must be es or en")
        label, value, bins = args.get("label") or None, args.get("value") or None, check_bins(args.get("bins", 5))
        dataset = self.load(args)
        title = str(args.get("title") or "").strip()[:120]
        svg = render_map(dataset, title=title, lang=lang, labels=label, value=value, bins=bins)
        classes = choropleth_classes(dataset, value, bins) if value else None
        rows = measurements(dataset, label, value)
        stats, box = totals(dataset), bbox(dataset)
        legend = [{"label": text, "count": classes.counts[i]} for i, text in enumerate(classes.labels(lang))] if classes else []
        if classes and classes.missing:
            legend.append({"label": TEXT[lang]["nodata"], "count": classes.missing})
        lines = [f"Map drawn for the user from {dataset.source}: {stats['features']} features ({stats['points']} points, "
                 f"{stats['lines']} lines, {stats['polygons']} polygons).",
                 f"Bounding box (lat, lon): {box[0]:g}, {box[1]:g} to {box[2]:g}, {box[3]:g}.",
                 "Projection: equirectangular, standard parallel at the middle latitude; the picture is for looking, "
                 f"the numbers below are computed on a sphere ({ACCURACY})."]
        if classes:
            lines.append(f"Choropleth of '{classes.key}' in {classes.n} equal-interval classes: " + "; ".join(
                f"{legend[i]['label']} ({classes.counts[i]})" for i in range(classes.n))
                + (f"; no data ({classes.missing})" if classes.missing else ""))
        lines.append("Per feature (km and km2):\n" + table(rows))
        if len(dataset.features) > MAX_ROWS:
            lines.append(f"[only the first {MAX_ROWS} features are listed]")
        lines += [f"[not read: {m}]" for m in dataset.skipped[:5]]
        if dataset.truncated:
            lines.append(f"[the file was cut to the first {len(dataset.features)} features: {dataset.truncated}]")
        content = "\n".join(lines)
        ui = {"kind": "geo_map", "title": title, "svg": svg, "source": dataset.source, "projection": "equirectangular",
              "lat_ts": round((box[0] + box[2]) / 2, 1), "radius_km": RADIUS_KM, "stats": stats, "bbox": box,
              "value": classes.key if classes else None, "legend": legend, "rows": rows,
              "rows_truncated": len(dataset.features) > MAX_ROWS, "skipped": dataset.skipped, "truncated": dataset.truncated}
        return ToolResult(ok=True, content=content, private=[content], data={"ui": ui})


class GeoMeasure(_GeoTool):
    name = "geo_measure"
    description = ("Great-circle distance between two coordinates, or the length, perimeter and area of every feature of "
                   "a GeoJSON/CSV file in the workspace, computed by code on a sphere (haversine; spherical excess). "
                   "Use these numbers; do not compute them yourself.")
    parameters = {"type": "object", "properties": {
        "a": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
              "description": "first point as [latitude, longitude] in degrees"},
        "b": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
              "description": "second point as [latitude, longitude]"},
        "path": FILE, **COLUMNS, "label": {"type": "string"}}}

    def act(self, args: dict[str, Any]) -> ToolResult:
        if args.get("path"):
            dataset = self.load(args)
            rows = measurements(dataset, args.get("label") or None, None)
            content = f"{dataset.source}: {len(dataset.features)} features ({ACCURACY}).\n" + table(rows)
            if len(dataset.features) > MAX_ROWS:
                content += f"\n[only the first {MAX_ROWS} features are listed]"
            return ToolResult(ok=True, content=content, private=[content])
        points = []
        for key in ("a", "b"):
            raw = args.get(key)
            if not isinstance(raw, list) or len(raw) != 2:
                raise GeoError("give two points a and b as [latitude, longitude], or a file path")
            if any(isinstance(v, (bool, str)) or number(v) is None for v in raw):
                raise GeoError(f"{key}: latitude and longitude must be numbers")
            points.append(geodata.check(float(raw[0]), float(raw[1]), key))
        metres = measure.haversine(points[0], points[1])
        content = (f"Great-circle distance: {metres / 1000:.1f} km ({metres / 1609.344:.1f} mi), {ACCURACY}.")
        return ToolResult(ok=True, content=content)


def geo_tools(workspace: Workspace) -> list[Tool]:
    return [GeoMap(workspace), GeoMeasure(workspace)]

