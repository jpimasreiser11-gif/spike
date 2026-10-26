"""CSV rescue before SQL loading, using only the standard library and never changing the source.

Detection is deliberately conservative: numeric/date conversion requires every nonempty cell in a column to
parse. Numeric slash dates use the selected locale (es day-first, en month-first); no locale is inferred from
user data. A nonempty text first row is treated as a header; numeric/date first rows get generated names.
Ragged records fail rather than silently dropping cells. Reports contain counts and checksums, not cell values.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spike.analytics.engine import DataError

MONTHS = {name: n for n, names in enumerate((
    ("jan", "january", "ene", "enero"), ("feb", "february", "febrero"), ("mar", "march", "marzo"),
    ("apr", "april", "abr", "abril"), ("may", "mayo"), ("jun", "june", "junio"),
    ("jul", "july", "julio"), ("aug", "august", "ago", "agosto"), ("sep", "september", "septiembre"),
    ("oct", "october", "octubre"), ("nov", "november", "noviembre"), ("dec", "december", "dic", "diciembre")), 1)
          for name in names}


@dataclass
class Rescued:
    columns: list[str]
    rows: list[list[Any]]
    report: dict[str, Any]


def _date(text: str, locale: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        pass
    pieces = re.split(r"[\s/.,-]+", text.lower())
    try:
        if len(pieces) == 3:
            a, b, year = pieces
            if a in MONTHS:
                return dt.date(int(year), MONTHS[a], int(b))
            if b in MONTHS:
                return dt.date(int(year), MONTHS[b], int(a))
            if len(year) == 4:
                return dt.date(int(year), int(b if locale == "es" else a), int(a if locale == "es" else b))
    except (ValueError, TypeError):
        pass
    return None


def _number(text: str) -> int | float | None:
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    if re.fullmatch(r"[+-]?(?:\d+[.,]\d*|[.,]\d+)(?:[eE][+-]?\d+)?|[+-]?\d+[eE][+-]?\d+", text):
        value = float(text.replace(",", "."))
        if value not in (float("inf"), float("-inf")):
            return value
    return None


def rescue_csv(path: Path, *, locale: str = "es") -> Rescued:
    """Detect UTF-8/BOM or cp1252, separator, preamble/header, decimals/dates, duplicates and empty columns."""
    if locale not in ("es", "en"):
        raise DataError("CSV locale must be es or en")
    raw = path.read_bytes()
    encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp1252"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise DataError("CSV encoding must be UTF-8 or cp1252") from exc
    candidates = []
    for separator in (",", ";", "\t", "|"):
        try:
            rows = [row for row in csv.reader(io.StringIO(text), delimiter=separator, strict=True)
                    if any(v.strip() for v in row)]
        except csv.Error:
            continue  # a wrong separator can make a valid quoted field look malformed
        widths = Counter(len(row) for row in rows)
        width, count = widths.most_common(1)[0] if widths else (0, 0)
        candidates.append((count if width > 1 else 0, width, separator, rows))
    if not candidates:
        raise DataError("invalid quoted CSV")
    _, width, separator, records = max(candidates, key=lambda c: (c[0], c[1]))
    if not records:
        raise DataError("CSV is empty")
    # Skip only narrower preamble lines before the first full-width record.
    skipped = next(i for i, row in enumerate(records) if len(row) == width)
    records = records[skipped:]
    if any(len(row) != width for row in records):
        raise DataError("ragged CSV records; specify a consistent delimiter/header")
    first = [v.strip() for v in records[0]]
    header = any(v and _number(v) is None and _date(v, locale) is None for v in first)
    names = first if header else [f"column_{i + 1}" for i in range(width)]
    taken: set[str] = set()
    columns = []
    for i, name in enumerate(names):
        base = name or f"column_{i + 1}"
        candidate, suffix = base, 2
        while candidate.casefold() in taken:
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        taken.add(candidate.casefold())
        columns.append(candidate)
    rows = [[v.strip() or None for v in row] for row in records[int(header):]]
    before = {"rows": len(rows), "columns": len(columns)}
    steps = [{"code": "encoding", "value": encoding}, {"code": "delimiter", "value": separator},
             {"code": "header", "skipped": skipped, "generated": not header,
              "renamed": sum(a != b for a, b in zip(names, columns, strict=True))}]
    keep = [i for i in range(width) if any(row[i] is not None for row in rows)]
    if len(keep) != width:
        steps.append({"code": "empty_columns", "count": width - len(keep)})
    columns = [columns[i] for i in keep]
    rows = [[row[i] for i in keep] for row in rows]
    for i in range(len(columns)):
        nonempty = [row[i] for row in rows if row[i] is not None]
        numbers = [_number(v) for v in nonempty]
        dates = [_date(v, locale) for v in nonempty]
        if nonempty and all(v is not None for v in numbers):
            commas = sum("," in v for v in nonempty)
            if commas:
                steps.append({"code": "decimal_comma", "column": i, "count": commas})
            for row in rows:
                if row[i] is not None:
                    row[i] = _number(row[i])
        elif nonempty and all(v is not None for v in dates):
            steps.append({"code": "dates", "column": i, "count": len(dates), "locale": locale})
            for row in rows:
                if row[i] is not None:
                    row[i] = _date(row[i], locale)
    unique, seen = [], set()
    for row in rows:
        key = tuple(row)
        if key not in seen:
            unique.append(row)
            seen.add(key)
    if len(unique) != len(rows):
        steps.append({"code": "duplicates", "count": len(rows) - len(unique)})
    if not columns:
        raise DataError("CSV has no nonempty columns")
    canonical = json.dumps({"columns": columns, "rows": unique}, default=str, ensure_ascii=False).encode("utf-8")
    return Rescued(columns, unique, {"before": before, "after": {"rows": len(unique), "columns": len(columns)},
                                    "steps": steps, "sha256": hashlib.sha256(raw).hexdigest(),
                                    "rescued_sha256": hashlib.sha256(canonical).hexdigest()})
