"""Geographic data for Spike Geo, read from GeoJSON (RFC 7946: a position is [longitude, latitude]) or from a CSV with
latitude and longitude columns (Spanish or English names, `,` `;` tab or `|` as separator, decimal commas).

Everything becomes plain Python: a `Feature` has its properties and its parts as (lat, lon) tuples in degrees (WGS 84,
which is what GeoJSON uses). Coordinates that are not degrees (a projected file in metres) are refused, not guessed.
Size limits keep a huge file from freezing the app; what they leave out is in `Dataset.truncated`, and what could not
be read in `Dataset.skipped`."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_BYTES = 8 * 1024 * 1024
MAX_FEATURES = 5000
MAX_VERTICES = 200_000
MAX_SKIPPED = 20  # messages kept about what could not be read
LAT_NAMES = ("lat", "latitude", "latitud", "y")
LON_NAMES = ("lon", "lng", "long", "longitude", "longitud", "x")
NAME_KEYS = ("name", "nombre", "title", "titulo", "label", "etiqueta", "city", "ciudad", "id")
GEOMETRIES = ("Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection")
NUMBER = re.compile(r"[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?")
LatLon = tuple[float, float]


class GeoError(ValueError):
    """The data cannot be read or drawn; the message is safe to show."""


@dataclass
class Feature:
    index: int  # 1-based position in the file
    props: dict[str, Any]
    points: list[LatLon] = field(default_factory=list)
    lines: list[list[LatLon]] = field(default_factory=list)
    polygons: list[list[list[LatLon]]] = field(default_factory=list)  # polygon -> rings (outer first) -> corners

    def vertices(self) -> int:
        return len(self.points) + sum(map(len, self.lines)) + sum(len(r) for poly in self.polygons for r in poly)

    def label(self, key: str | None = None) -> str | None:
        """The text naming this feature: the property `key`, else the first usual name property, else None."""
        lowered = {k.lower(): k for k in self.props}
        keys = [lowered[key.lower()]] if key and key.lower() in lowered else []
        for k in [*keys, *(lowered[k] for k in NAME_KEYS if k in lowered)]:
            value = self.props.get(k)
            if value not in (None, "") and not isinstance(value, (dict, list)):
                return str(value)
        return None

    def name(self, key: str | None = None) -> str:
        return self.label(key) or f"#{self.index}"


@dataclass
class Dataset:
    features: list[Feature]
    source: str = ""
    skipped: list[str] = field(default_factory=list)  # what could not be read, one short message each
    truncated: dict[str, int] = field(default_factory=dict)  # "features" / "vertices": how many the file had


def number(value: Any) -> float | None:
    """A finite number from a JSON number or a numeric-looking string (decimal comma allowed), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not NUMBER.fullmatch(text):
            return None
        value = float(text.replace(",", "."))
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def check(lat: float, lon: float, where: str) -> LatLon:
    if abs(lat) > 90 or abs(lon) > 180:
        if max(abs(lat), abs(lon)) > 1000:
            raise GeoError(f"{where}: ({lon:g}, {lat:g}) looks like projected coordinates in metres; Spike Geo reads "
                           "longitude and latitude in degrees (WGS 84)")
        if abs(lat) > 90:
            raise GeoError(f"{where}: latitude {lat:g} is outside -90..90 (GeoJSON order is [longitude, latitude])")
        raise GeoError(f"{where}: longitude {lon:g} is outside -180..180")
    return float(lat), float(lon)


def position(raw: Any, where: str) -> LatLon:
    if not isinstance(raw, list) or len(raw) < 2:
        raise GeoError(f"{where}: a position needs [longitude, latitude]")
    lon, lat = raw[0], raw[1]  # a third value (height) is ignored
    if any(isinstance(v, (bool, str)) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lon, lat)):
        raise GeoError(f"{where}: coordinates must be numbers")
    return check(lat, lon, where)


def positions(raw: Any, where: str, least: int) -> list[LatLon]:
    if not isinstance(raw, list):
        raise GeoError(f"{where}: coordinates must be a list of positions")
    if len(raw) < least:
        raise GeoError(f"{where}: needs at least {least} positions")
    return [position(p, where) for p in raw]


def ring(raw: Any, where: str) -> list[LatLon]:
    corners = positions(raw, where, 4)  # the RFC: a closed ring has at least four positions
    return corners[:-1] if corners[0] == corners[-1] else corners


def parts(geometry: Any, where: str, depth: int = 0) -> tuple[list[LatLon], list[list[LatLon]], list[list[list[LatLon]]]]:
    """(points, lines, polygons) of one GeoJSON geometry; a GeometryCollection is flattened."""
    if not isinstance(geometry, dict):
        raise GeoError(f"{where}: a geometry must be an object")
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    points: list[LatLon] = []
    lines: list[list[LatLon]] = []
    polygons: list[list[list[LatLon]]] = []
    if kind == "GeometryCollection":
        if depth >= 4 or not isinstance(geometry.get("geometries"), list):
            raise GeoError(f"{where}: a GeometryCollection needs a list of geometries (nested at most 4 deep)")
        for inner in geometry["geometries"]:
            p, ln, pg = parts(inner, where, depth + 1)
            points += p
            lines += ln
            polygons += pg
    elif kind == "Point":
        points.append(position(coords, where))
    elif kind == "MultiPoint":
        points += positions(coords, where, 0)
    elif kind == "LineString":
        lines.append(positions(coords, where, 2))
    elif kind == "MultiLineString":
        lines += [positions(c, where, 2) for c in listed(coords, where)]
    elif kind == "Polygon":
        polygons.append(rings(coords, where))
    elif kind == "MultiPolygon":
        polygons += [rings(c, where) for c in listed(coords, where)]
    else:
        raise GeoError(f"{where}: geometry type '{kind}' is not supported "
                       "(Point, LineString, Polygon, their Multi versions and GeometryCollection are)")
    return points, lines, polygons


def listed(raw: Any, where: str) -> list[Any]:
    if not isinstance(raw, list):
        raise GeoError(f"{where}: coordinates must be a list")
    return raw


def rings(raw: Any, where: str) -> list[list[LatLon]]:
    if not isinstance(raw, list) or not raw:
        raise GeoError(f"{where}: a polygon needs at least one ring")
    return [ring(r, where) for r in raw]


def count_vertices(node: Any) -> int:
    """Positions in a coordinates tree, without validating it (for the part of a file past the size limit)."""
    if isinstance(node, dict):
        return sum(count_vertices(v) for v in node.values() if isinstance(v, (list, dict)))
    if isinstance(node, list):
        if node and all(isinstance(v, (int, float)) for v in node):
            return 1
        return sum(count_vertices(v) for v in node)
    return 0


def note(skipped: list[str], message: str) -> None:
    if len(skipped) < MAX_SKIPPED:
        skipped.append(message)
    elif len(skipped) == MAX_SKIPPED:
        skipped.append("… and more")


def parse_geojson(text: str, source: str = "") -> Dataset:
    """A FeatureCollection, a Feature or a bare geometry. Features without geometry are skipped (and said)."""
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise GeoError(f"not valid JSON: {exc}") from exc
    kind = doc.get("type") if isinstance(doc, dict) else None
    if kind == "FeatureCollection" and isinstance(doc.get("features"), list):
        items = doc["features"]
    elif kind == "Feature":
        items = [doc]
    elif kind in GEOMETRIES:
        items = [{"type": "Feature", "properties": {}, "geometry": doc}]
    else:
        raise GeoError("not GeoJSON: expected a FeatureCollection, a Feature or a geometry"
                       + (f" (found type '{kind}')" if isinstance(kind, str) else ""))
    out = Dataset(features=[], source=source)
    seen = vertices = total_vertices = 0
    cut_features = cut_vertices = False
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict) or item.get("type") != "Feature":
            note(out.skipped, f"feature {n}: not a Feature")
            continue
        if item.get("geometry") is None:
            note(out.skipped, f"feature {n}: no geometry")
            continue
        seen += 1
        if cut_features or cut_vertices:  # past a limit: only count
            total_vertices += count_vertices(item["geometry"])
            continue
        points, lines, polygons = parts(item["geometry"], f"feature {n}")
        props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        feature = Feature(n, props, points, lines, polygons)
        size = feature.vertices()
        total_vertices += size
        if len(out.features) >= MAX_FEATURES:
            cut_features = True
        elif vertices + size > MAX_VERTICES:
            if not out.features:
                raise GeoError(f"feature {n} has {size} positions; Spike Geo draws at most {MAX_VERTICES}")
            cut_vertices = True
        else:
            out.features.append(feature)
            vertices += size
    if not out.features:
        raise GeoError("the file has no features with a geometry")
    if cut_features or cut_vertices:
        out.truncated = {"features": seen}
        if cut_vertices:
            out.truncated = {"vertices": total_vertices, "features": seen}
    return out


def normalise(header: str) -> str:
    plain = unicodedata.normalize("NFKD", header).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def column(header: list[str], norm: list[str], given: str | None, names: tuple[str, ...], what: str) -> int:
    if given:
        wanted = normalise(given)
        if wanted in norm:
            return norm.index(wanted)
        raise GeoError(f"the {what} column '{given}' is not in the file; columns: {', '.join(header)}")
    for name in names:
        if name in norm:
            return norm.index(name)
    raise GeoError(f"no {what} column found (looked for {', '.join(names)}); columns: {', '.join(header)}")


def parse_csv(text: str, lat_column: str | None = None, lon_column: str | None = None, source: str = "") -> Dataset:
    """One point per row. The other columns become properties (numeric-looking cells become numbers)."""
    text = text.lstrip("﻿")
    first = text.split("\n", 1)[0]
    delimiter = max(",;\t|", key=first.count) if any(d in first for d in ",;\t|") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    if not rows or not any(c.strip() for c in rows[0]):
        raise GeoError("the file is empty")
    header = [h.strip() for h in rows[0]]
    norm = [normalise(h) for h in header]
    lat_i = column(header, norm, lat_column, LAT_NAMES, "latitude")
    lon_i = column(header, norm, lon_column, LON_NAMES, "longitude")
    out = Dataset(features=[], source=source)
    seen = 0
    for n, row in enumerate(rows[1:], 2):
        if not any(c.strip() for c in row):
            continue
        lat = number(row[lat_i]) if lat_i < len(row) else None
        lon = number(row[lon_i]) if lon_i < len(row) else None
        if lat is None or lon is None:
            note(out.skipped, f"row {n}: latitude or longitude is empty or not a number")
            continue
        try:
            point = check(lat, lon, f"row {n}")
        except GeoError as exc:
            note(out.skipped, str(exc))
            continue
        seen += 1
        if len(out.features) >= MAX_FEATURES:
            continue
        props = {}
        for i, cell in enumerate(row[:len(header)]):
            if i not in (lat_i, lon_i):
                value = number(cell)
                props[header[i]] = value if value is not None else cell.strip()
        out.features.append(Feature(n, props, points=[point]))
    if not out.features:
        raise GeoError("the file has no rows with a valid latitude and longitude"
                       + (f" ({out.skipped[0]})" if out.skipped else ""))
    if seen > len(out.features):
        out.truncated = {"features": seen}
    return out


def load(path: Path, lat_column: str | None = None, lon_column: str | None = None) -> Dataset:
    """Read a .geojson / .json / .csv / .tsv file (up to MAX_BYTES)."""
    suffix = path.suffix.lower()
    if suffix not in (".geojson", ".json", ".csv", ".tsv"):
        raise GeoError(f"{path.name}: Spike Geo reads .geojson, .json, .csv and .tsv files")
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            raise GeoError(f"{path.name} is {size // 1024} KB; Spike Geo reads files up to {MAX_BYTES // 1024} KB")
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise GeoError(f"cannot read {path.name}: {exc.strerror or exc}") from exc
    if suffix in (".geojson", ".json"):
        return parse_geojson(text, path.name)
    return parse_csv(text, lat_column, lon_column, path.name)
