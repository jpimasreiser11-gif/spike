"""Vega-Lite charts built by SPIKE from a query's result. The model only names the mark and the columns; the spec
is assembled here with the data inline under fixed field names (x, y, series), so it never loads a URL, links
anywhere, shows images or carries an expression the model wrote."""

from __future__ import annotations

from typing import Any

from spike.analytics.engine import DataError, Result, kind_of

MARKS = ("bar", "line", "area", "point", "arc")
KINDS = ("quantitative", "temporal", "nominal", "ordinal")
MAX_POINTS = 5000
SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"  # an identifier: renderers do not fetch it


def _column(result: Result, name: Any, role: str) -> int:
    if not isinstance(name, str) or name not in result.columns:
        raise DataError(f"{role} must be one of the result's columns: {', '.join(result.columns)}")
    return result.columns.index(name)


def build_chart(result: Result, mark: str = "bar", x: str | None = None, y: str | list[str] | None = None,
                color: str | None = None, title: str = "", x_type: str | None = None) -> dict[str, Any]:
    if mark not in MARKS:
        raise DataError(f"mark must be one of {', '.join(MARKS)}")
    if len(result.columns) < 2:
        raise DataError("a chart needs a query that returns at least two columns (a label and a number)")
    if result.truncated or len(result.rows) > MAX_POINTS:
        raise DataError(f"the query returns more than {MAX_POINTS} rows; aggregate first (GROUP BY)")
    if not result.rows:
        raise DataError("the query returned no rows to draw")
    xi = _column(result, x or result.columns[0], "x")
    ys = [y] if isinstance(y, str) else list(y or [])
    if not ys:
        ys = [next((c for i, c in enumerate(result.columns) if i != xi and kind_of(result.types[i]) == "quantitative"),
                   result.columns[1])]
    yis = [_column(result, name, "y") for name in ys]
    for i in yis:
        if kind_of(result.types[i]) != "quantitative":
            raise DataError(f"y must be numeric; '{result.columns[i]}' is {result.types[i]}")
    ci = _column(result, color, "color") if color else None
    if ci is not None and len(yis) > 1:
        raise DataError("use either several y columns or a color column, not both")

    values = []
    for row in result.rows:
        for i in yis:
            item = {"x": row[xi], "y": row[i]}
            if len(yis) > 1:
                item["series"] = result.columns[i]
            elif ci is not None:
                item["series"] = row[ci]
            values.append(item)

    kind = x_type if x_type in KINDS else kind_of(result.types[xi])
    if mark == "bar" and kind == "quantitative" and not x_type:
        kind = "ordinal"  # years or ids as bars, one per value
    x_enc: dict[str, Any] = {"field": "x", "type": kind, "title": result.columns[xi]}
    if kind in ("nominal", "ordinal"):
        x_enc["sort"] = None  # keep the query's ORDER BY
        labels = {str(row[xi]) for row in result.rows}
        short = len(labels) <= 12 and max(len(label) for label in labels) <= 14
        x_enc["axis"] = {"labelAngle": 0 if short else -40, "labelLimit": 160}
    if kind == "temporal" and result.types[xi].upper() == "DATE":
        x_enc["scale"] = {"type": "utc"}  # a date has no time zone: draw it as written
    y_title = result.columns[yis[0]] if len(yis) == 1 else ""
    y_enc = {"field": "y", "type": "quantitative", "title": y_title}
    series = len(yis) > 1 or ci is not None
    series_title = "" if len(yis) > 1 else (result.columns[ci] if ci is not None else "")

    if mark == "arc":
        if series:
            raise DataError("a pie chart (arc) takes one label column and one number")
        encoding: dict[str, Any] = {"theta": {"field": "y", "type": "quantitative", "title": y_title},
                                    "color": {"field": "x", "type": "nominal", "title": result.columns[xi],
                                              "sort": None}}
    else:
        encoding = {"x": x_enc, "y": y_enc}
        if series:
            encoding["color"] = {"field": "series", "type": "nominal", "title": series_title, "sort": None}
    tooltip = [{"field": "x", "type": "nominal" if mark == "arc" else kind, "title": result.columns[xi]},
               {"field": "y", "type": "quantitative", "title": y_title or "valor"}]
    if series:
        tooltip.append({"field": "series", "type": "nominal", "title": series_title or "serie"})
    encoding["tooltip"] = tooltip
    mark_def: dict[str, Any] = {"type": mark}
    if mark == "line":
        mark_def["point"] = True
    spec: dict[str, Any] = {"$schema": SCHEMA, "data": {"values": values}, "mark": mark_def, "encoding": encoding,
                            "width": "container", "height": 260}
    if title.strip():
        spec["title"] = title.strip()[:120]
    return spec
