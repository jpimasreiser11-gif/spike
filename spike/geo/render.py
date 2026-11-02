"""A dataset as one SVG map: plain markup with no scripts, no external files and no basemap tiles, drawn by this module.

Projection: equirectangular with a standard parallel (`project.py`). The picture has a graticule with degree labels, a
scale bar for the standard parallel and a note saying so; points are circles (named ones are labelled when there are
few), lines are paths and polygons are filled paths with holes (even-odd). A choropleth colours polygons by one numeric
property in equal-interval classes with a legend, a "no data" class for missing values, and a sequential ramp that is
defined twice (light and dark) in the picture's own stylesheet, so it follows the viewer's colour scheme and keeps
"more" visibly stronger on both backgrounds. Dense outlines drop vertices closer than 0.4 px to the previous one.
The same dataset and options always give the same bytes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

from spike.geo.data import Dataset, GeoError, number
from spike.geo.measure import EARTH_RADIUS_M
from spike.geo.project import Equirectangular
from spike.memory.graph_svg import clean, short

WIDTH, ML, MT, MB = 960, 60, 46, 74
MR_PLAIN, MR_LEGEND = 24, 214
MIN_SPAN_M = 5000
MAX_LABELS = 40
MIN_BINS, MAX_BINS = 2, 7
STEPS = (0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 45, 90)
LIGHT_RAMP = ((227, 238, 249), (18, 63, 107))  # from the lowest to the highest class
DARK_RAMP = ((32, 56, 79), (183, 220, 255))  # lowest is darkest, so the highest stands out on the dark background

TEXT = {
    "es": {"title": "Mapa", "empty": "No hay datos que dibujar.", "nodata": "Sin datos", "points": "puntos",
           "lines": "líneas", "polygons": "polígonos", "desc": "{n} elementos: {p} puntos, {l} líneas y {g} polígonos",
           "proj": "Proyección equirrectangular, paralelo estándar {lat}. La escala solo es exacta a lo largo de ese paralelo.",
           "labels": "Hay demasiados puntos para poner nombres.", "scale": "escala", "north": "N", "south": "S",
           "east": "E", "west": "O", "dec": ","},
    "en": {"title": "Map", "empty": "There is nothing to draw.", "nodata": "No data", "points": "points",
           "lines": "lines", "polygons": "polygons", "desc": "{n} features: {p} points, {l} lines and {g} polygons",
           "proj": "Equirectangular projection, standard parallel {lat}. The scale is exact only along that parallel.",
           "labels": "There are too many points to label them.", "scale": "scale", "north": "N", "south": "S",
           "east": "E", "west": "W", "dec": "."},
}
STYLE = """
:root{--bg:#ffffff;--fg:#1b1f23;--muted:#5d6672;--grid:#d9dee5;--frame:#9aa4b0;--land:#dfe7f1;--edge:#53606f;
--pt:#c2410c;--ln:#2f6fdd;--nodata:#d4d4d4;%LIGHT%}
@media (prefers-color-scheme:dark){:root{--bg:#14181d;--fg:#e8ebee;--muted:#a3adb8;--grid:#2c343e;--frame:#566170;
--land:#2a3544;--edge:#9aa8b8;--pt:#fb923c;--ln:#7fb0ff;--nodata:#4a4f57;%DARK%}}
.bg{fill:var(--bg)}.frame{fill:none;stroke:var(--frame);stroke-width:1}
.t{font:12px system-ui,sans-serif;fill:var(--fg);paint-order:stroke;stroke:var(--bg);stroke-width:3px}
.m{font:11px system-ui,sans-serif;fill:var(--muted)}.h{font:600 15px system-ui,sans-serif;fill:var(--fg)}
.grid{stroke:var(--grid);stroke-width:1;fill:none}
.poly{fill:var(--land);stroke:var(--edge);stroke-width:.8;fill-rule:evenodd;stroke-linejoin:round}
.poly.nodata,.sw.nodata{fill:url(#g-hatch)}.hb{fill:var(--nodata)}.hl{stroke:var(--edge);stroke-width:1.4}
.sw{stroke:var(--edge);stroke-width:.8}
.line{fill:none;stroke:var(--ln);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.pt{fill:var(--pt);stroke:var(--bg);stroke-width:1.5}.bar{stroke:var(--fg);stroke-width:2;fill:none}
%CLASSES%"""


@dataclass
class Classes:
    """Equal-interval classes of one numeric property of the polygons."""

    key: str
    breaks: list[float]  # edges: one more than the classes; two equal ones when every value is the same
    counts: list[int]
    missing: int  # polygons without a number

    @property
    def n(self) -> int:
        return len(self.counts)

    def bin_of(self, value: float) -> int:
        low, high = self.breaks[0], self.breaks[-1]
        if self.n == 1 or high == low:
            return 0
        return max(0, min(self.n - 1, int((value - low) * self.n / (high - low))))

    def labels(self, lang: str = "en") -> list[str]:
        if self.n == 1:
            return [fmt(self.breaks[0], lang)]
        return [f"{fmt(a, lang)} – {fmt(b, lang)}" for a, b in zip(self.breaks, self.breaks[1:], strict=False)]


def prop_key(dataset: Dataset, key: str) -> str:
    """The property name as the data spells it (matching is case-insensitive)."""
    for feature in dataset.features:
        for k in feature.props:
            if k.lower() == key.lower():
                return k
    return key


def check_bins(bins: object) -> int:
    if isinstance(bins, bool) or not isinstance(bins, int) or not MIN_BINS <= bins <= MAX_BINS:
        raise GeoError(f"bins must be a whole number from {MIN_BINS} to {MAX_BINS}")
    return bins


def choropleth_classes(dataset: Dataset, key: str, bins: int = 5) -> Classes:
    bins = check_bins(bins)
    polygons = [f for f in dataset.features if f.polygons]
    if not polygons:
        raise GeoError("a choropleth needs polygons (Polygon or MultiPolygon features) with a numeric property")
    key = prop_key(dataset, key)
    values = [number(f.props.get(key)) for f in polygons]
    found = [v for v in values if v is not None]
    if not found:
        numeric = sorted({k for f in polygons for k, v in f.props.items() if number(v) is not None})
        raise GeoError(f"'{key}' is not a numeric property of the polygons"
                       + (f"; numeric properties: {', '.join(numeric)}" if numeric else ""))
    low, high = min(found), max(found)
    bins = 1 if low == high else bins
    classes = Classes(key, [low + (high - low) * i / bins for i in range(bins)] + [high] if bins > 1 else [low, high],
                      [0] * bins, len(values) - len(found))
    for v in found:
        classes.counts[classes.bin_of(v)] += 1
    return classes


def fmt(x: float, lang: str = "en") -> str:
    """A number for a label: thousands separated above 9,999, otherwise four significant digits."""
    if abs(x) >= 10_000:
        text = f"{x:,.0f}"
        return text.replace(",", ".") if lang == "es" else text
    text = f"{x:.4g}"
    return text.replace(".", ",") if lang == "es" else text


def degrees(v: float, axis: str, lang: str, decimals: int) -> str:
    words = TEXT["es" if lang == "es" else "en"]
    side = (words["north"] if v >= 0 else words["south"]) if axis == "lat" else (words["east"] if v >= 0 else words["west"])
    return f"{abs(v):.{decimals}f}".replace(".", words["dec"]) + "°" + side


def step_for(span: float) -> float:
    return next((s for s in STEPS if span / s <= 7), STEPS[-1])


def hexcolor(rgb: tuple[float, ...]) -> str:
    return "#" + "".join(f"{round(c):02x}" for c in rgb)


def ramp(n: int, ends: tuple[tuple[int, ...], tuple[int, ...]]) -> list[str]:
    a, b = ends
    return [hexcolor(tuple(a[k] + (b[k] - a[k]) * (i / (n - 1) if n > 1 else 0.5) for k in range(3))) for i in range(n)]


def stylesheet(classes: Classes | None) -> str:
    n = classes.n if classes else 0
    light = "".join(f"--c{i}:{c};" for i, c in enumerate(ramp(n, LIGHT_RAMP)))
    dark = "".join(f"--c{i}:{c};" for i, c in enumerate(ramp(n, DARK_RAMP)))
    rules = "".join(f".poly.c{i},.sw.c{i}{{fill:var(--c{i})}}" for i in range(n))
    return STYLE.replace("%LIGHT%", light).replace("%DARK%", dark).replace("%CLASSES%", rules)


def outline(points: list[tuple[float, float]], close: bool) -> str:
    """An SVG path through pixel points, dropping vertices closer than 0.4 px to the last one kept."""
    kept = [points[0]]
    for x, y in points[1:-1]:
        if abs(x - kept[-1][0]) >= 0.4 or abs(y - kept[-1][1]) >= 0.4:
            kept.append((x, y))
    kept.append(points[-1])
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in kept) + ("Z" if close else "")


def nice_length(target_km: float) -> float:
    if target_km <= 0:
        return 1.0
    base = 10 ** math.floor(math.log10(target_km))
    return max(c * base for c in (1, 2, 5, 10) if c * base <= target_km)


def kinds(dataset: Dataset) -> tuple[int, int, int]:
    return (sum(len(f.points) for f in dataset.features), sum(len(f.lines) for f in dataset.features),
            sum(len(f.polygons) for f in dataset.features))


def frame_svg(heading: str, words: dict, body: str, height: int, desc: str, style: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="100%" '
            f'style="display:block;max-width:{WIDTH}px" role="img" aria-labelledby="g-title g-desc">'
            f'<title id="g-title">{escape(heading)}</title><desc id="g-desc">{escape(desc)}</desc>'
            f'<style>{style}</style><rect class="bg" width="{WIDTH}" height="{height}"/>{body}</svg>')


def render_map(dataset: Dataset, title: str = "", lang: str = "en", labels: str | None = None,
               value: str | None = None, bins: int = 5) -> str:
    """The dataset as an SVG document string. `labels` names the property for point labels (usual name properties
    otherwise); `value` colours the polygons by that numeric property in `bins` equal-interval classes."""
    words = TEXT["es" if lang == "es" else "en"]
    heading = short(title or words["title"], 80)
    classes = choropleth_classes(dataset, value, bins) if value else None
    features = dataset.features
    every = [p for f in features for p in [*f.points, *(q for ln in f.lines for q in ln),
                                           *(q for pg in f.polygons for r in pg for q in r)]]
    if not every:
        text = f'<text class="h" x="{WIDTH / 2}" y="160" text-anchor="middle">{escape(words["empty"])}</text>'
        return frame_svg(heading, words, text, 320, words["empty"], stylesheet(None))
    proj = Equirectangular.fit(every)
    flat = [proj.xy(*p) for p in every]
    xmin, xmax = min(x for x, _ in flat), max(x for x, _ in flat)
    ymin, ymax = min(y for _, y in flat), max(y for _, y in flat)
    xc, yc = (xmin + xmax) / 2, (ymin + ymax) / 2
    dx, dy = max(xmax - xmin, MIN_SPAN_M), max(ymax - ymin, MIN_SPAN_M)
    mr = MR_LEGEND if classes else MR_PLAIN
    mw = WIDTH - ML - mr
    mh = round(max(220, min(520, mw * dy / dx)))
    scale = min((mw - 24) / dx, (mh - 24) / dy)  # pixels per metre
    cx, cy = ML + mw / 2, MT + mh / 2

    def px(lat: float, lon: float) -> tuple[float, float]:
        x, y = proj.xy(lat, lon)
        return round(cx + (x - xc) * scale, 2), round(cy - (y - yc) * scale, 2)

    height = MT + mh + MB
    out = [f'<defs><clipPath id="g-clip"><rect x="{ML}" y="{MT}" width="{mw}" height="{mh}"/></clipPath>'
           '<pattern id="g-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           '<rect class="hb" width="6" height="6"/><path class="hl" d="M0,0V6"/></pattern></defs>',
           f'<text class="h" x="{ML}" y="28">{escape(heading)}</text>']
    # graticule: lines of constant longitude are vertical and of constant latitude horizontal in this projection
    cos_ts = max(0.05, math.cos(math.radians(proj.lat_ts)))
    lat_lo, lat_hi = [math.degrees((yc + (cy - py) / scale) / EARTH_RADIUS_M) for py in (MT + mh, MT)]
    lon_lo, lon_hi = [proj.lon0 + math.degrees((xc + (qx - cx) / scale) / (EARTH_RADIUS_M * cos_ts))
                      for qx in (ML, ML + mw)]
    lat_step, lon_step = step_for(lat_hi - lat_lo), step_for(lon_hi - lon_lo)
    grid, edge_labels = [], []
    for k in range(math.ceil(max(lat_lo, -90) / lat_step), math.floor(min(lat_hi, 90) / lat_step) + 1):
        lat = round(k * lat_step, 6)
        y = px(lat, proj.lon0)[1]
        grid.append(f'<path class="grid" d="M{ML},{y:.1f}H{ML + mw}"/>')
        edge_labels.append(f'<text class="m" x="{ML - 6}" y="{y + 4:.1f}" text-anchor="end">'
                           f'{degrees(lat, "lat", lang, max(0, -math.floor(math.log10(lat_step))))}</text>')
    for k in range(math.ceil(lon_lo / lon_step), math.floor(lon_hi / lon_step) + 1):
        lon = round(k * lon_step, 6)
        x = px(proj.lat_ts, lon)[0]
        shown = ((lon + 180) % 360) - 180
        grid.append(f'<path class="grid" d="M{x:.1f},{MT}V{MT + mh}"/>')
        edge_labels.append(f'<text class="m" x="{x:.1f}" y="{MT - 8}" text-anchor="middle">'
                           f'{degrees(shown, "lon", lang, max(0, -math.floor(math.log10(lon_step))))}</text>')
    out += ['<g clip-path="url(#g-clip)">', *grid]
    values = {f.index: number(f.props.get(classes.key)) for f in features if classes and f.polygons}
    for f in features:
        if f.polygons:
            d = "".join(outline([px(*p) for p in r], True) for pg in f.polygons for r in pg if len(r) > 2)
            klass = "poly"
            if classes:
                v = values[f.index]
                klass = "poly nodata" if v is None else f"poly c{classes.bin_of(v)}"
            tip = f.name(labels) + (f": {fmt(values[f.index], lang)}" if classes and values[f.index] is not None else "")
            out.append(f'<path class="{klass}" d="{d}"><title>{escape(clean(tip))}</title></path>')
    for f in features:
        for line in f.lines:
            out.append(f'<path class="line" d="{outline([px(*p) for p in line], False)}">'
                       f'<title>{escape(clean(f.name(labels)))}</title></path>')
    npoints = sum(len(f.points) for f in features)
    for f in features:
        for lat, lon in f.points:
            x, y = px(lat, lon)
            out.append(f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="4.5"><title>{escape(clean(f.name(labels)))} '
                       f'({lat:.5g}, {lon:.5g})</title></circle>')
    out.append("</g>")
    if 0 < npoints <= MAX_LABELS:  # outside the clip, so a name at the edge of the map stays whole
        for f in features:
            text = f.label(labels)
            if text and f.points:
                x, y = px(*f.points[0])
                text = short(text, 28)
                end = x + 14 + 6.6 * len(text) > ML + mw  # no room on the right of the point: write on its left
                anchor = ' text-anchor="end"' if end else ""
                out.append(f'<text class="t" x="{x + (-8 if end else 8):.1f}" y="{y - 7:.1f}"{anchor}>{escape(text)}</text>')
    out += edge_labels
    out.append(f'<rect class="frame" x="{ML}" y="{MT}" width="{mw}" height="{mh}"/>')
    # scale bar, true along the standard parallel
    px_per_km = scale * 1000
    km = nice_length(mw * 0.22 / px_per_km)
    bar, y = round(km * px_per_km, 1), MT + mh + 26
    out.append(f'<path class="bar" d="M{ML},{y - 5}V{y}H{ML + bar}V{y - 5}"/>'
               f'<text class="m" x="{ML + bar + 8}" y="{y}">{fmt(km, lang)} km ({words["scale"]})</text>')
    lat_text = degrees(proj.lat_ts, "lat", lang, 1)
    out.append(f'<text class="m" x="{ML}" y="{y + 26}">{escape(words["proj"].format(lat=lat_text))}</text>')
    if npoints > MAX_LABELS:
        out.append(f'<text class="m" x="{ML}" y="{y + 42}">{escape(words["labels"])}</text>')
    if classes:
        lx = ML + mw + 18
        out.append(f'<text class="t" x="{lx}" y="{MT + 8}">{escape(short(classes.key, 26))}</text>')
        rows = [(f"c{i}", label, classes.counts[i]) for i, label in enumerate(classes.labels(lang))]
        if classes.missing:
            rows.append(("nodata", words["nodata"], classes.missing))
        for i, (klass, label, count) in enumerate(rows):
            ry = MT + 24 + i * 22
            out.append(f'<rect class="sw {klass}" x="{lx}" y="{ry}" width="16" height="14" rx="2"/>'
                       f'<text class="t" x="{lx + 24}" y="{ry + 12}">{escape(label)} <tspan class="m">({count})</tspan></text>')
    p, ln, pg = kinds(dataset)
    desc = words["desc"].format(n=len(features), p=p, l=ln, g=pg)
    return frame_svg(heading, words, "".join(out), height, desc, stylesheet(classes))
