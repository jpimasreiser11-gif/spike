"""The data engine: workspace files loaded into an in-memory DuckDB (MIT), then locked down before any SQL from the
model runs. After loading, the connection cannot read or write files, attach databases, install or load
extensions, see Python objects or change its own settings, so a query can only work on the loaded tables.

CSV/TSV, Parquet and JSON load through DuckDB; Excel (.xlsx) and SQLite through pandas, openpyxl and the standard
`sqlite3` module (the SQLite file is opened read-only). Every table is named after its file."""

from __future__ import annotations

import datetime as dt
import math
import re
import sqlite3
import tempfile
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from spike.tools.builtin import Workspace

MAX_FILE = 256 * 1024**2
MAX_EXCEL = 50 * 1024**2  # openpyxl reads a workbook cell by cell: slow and memory hungry past this
MAX_TOTAL = 512 * 1024**2
MAX_FILES = 8
MAX_TABLES = 40
MAX_CELL = 200  # characters of a text value shown
TIMEOUT_S = 30.0
MEMORY = "1GB"
THREADS = 2
FORMATS = {".csv": "csv", ".tsv": "csv", ".txt": "csv", ".parquet": "parquet", ".pq": "parquet", ".json": "json",
           ".jsonl": "json", ".ndjson": "json", ".xlsx": "excel", ".xlsm": "excel", ".sqlite": "sqlite",
           ".sqlite3": "sqlite", ".db": "sqlite"}
# Applied after the files are loaded; `lock_configuration` last, so nothing can undo the others.
LOCK = ("SET python_enable_replacements=false", "SET enable_external_access=false",
        "SET autoinstall_known_extensions=false", "SET autoload_known_extensions=false",
        "SET allow_community_extensions=false", "SET lock_configuration=true")
NUMERIC = re.compile(r"^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|UHUGEINT|FLOAT|"
                     r"DOUBLE|REAL|DECIMAL)")


class DataError(ValueError):
    pass


def duckdb() -> Any:
    try:
        import duckdb as module
    except ImportError as exc:
        raise DataError("data analysis needs DuckDB and pandas: pip install 'spike-ai[data]'") from exc
    return module


def kind_of(type_name: str) -> str:
    """Vega-Lite's kind of field for a DuckDB type."""
    t = type_name.upper()
    if NUMERIC.match(t):
        return "quantitative"
    if t.startswith(("DATE", "TIMESTAMP")):
        return "temporal"
    return "nominal"


def cell(value: Any) -> Any:
    """A JSON-safe value: dates as ISO text, decimals as numbers, NaN as null, long text cut."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if abs(value) < 2**53 else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, (list, tuple)):
        return [cell(v) for v in value[:50]]
    if isinstance(value, dict):
        return {str(k)[:MAX_CELL]: cell(v) for k, v in list(value.items())[:50]}
    text = str(value)
    return text if len(text) <= MAX_CELL else text[:MAX_CELL] + "…"


def show(value: Any) -> str:
    """A value as the model reads it in a result table."""
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value).replace("\n", " ").replace("|", "/")


def ident(name: str, reserved: set[str] = frozenset()) -> str:
    """How a table or column must be written in SQL: bare when it can be, double-quoted otherwise."""
    if re.fullmatch(r"[a-z_][a-z0-9_]*", name) and name not in reserved:
        return name
    return '"' + name.replace('"', '""') + '"'


def table_name(raw: str, taken: set[str], reserved: set[str]) -> str:
    ascii_name = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9_]+", "_", ascii_name.lower()).strip("_") or "data"
    if name[0].isdigit() or name in reserved:
        name = f"t_{name}"
    base, n = name[:60], 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    taken.add(name)
    return name


@dataclass
class Table:
    name: str
    file: str
    rows: int
    columns: list[tuple[str, str]]  # (name, DuckDB type)
    sheet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "file": self.file, "rows": self.rows, "sheet": self.sheet,
                "columns": [{"name": n, "type": t} for n, t in self.columns]}


@dataclass
class Result:
    columns: list[str]
    types: list[str]
    rows: list[list[Any]]
    truncated: bool
    tables: list[Table] = field(default_factory=list)

    def text(self, limit: int = 50) -> str:
        if not self.columns:
            return "(the statement ran and returned no rows)"
        lines = [" | ".join(self.columns)] + [" | ".join(show(v) for v in r) for r in self.rows[:limit]]
        more = len(self.rows) - limit if len(self.rows) > limit else 0
        note = f"\n(first {limit} of {len(self.rows)}{'+' if self.truncated else ''} rows shown)" if more else (
            f"\n(first {len(self.rows)} rows; there are more)" if self.truncated else "")
        return "\n".join(lines) + note


def files_arg(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise DataError("give the data files to use: files: [\"sales.csv\"] (paths in the workspace)")
    if len(value) > MAX_FILES:
        raise DataError(f"at most {MAX_FILES} files per query")
    return [v.strip() for v in value]


class Session:
    """One in-memory DuckDB with the given files loaded as tables and then locked. Use it from one thread."""

    def __init__(self, workspace: Workspace, files: list[str], timeout_s: float | None = None):
        self.workspace, self.files, self.timeout_s = workspace, files, timeout_s or TIMEOUT_S
        self.tables: list[Table] = []
        self._tmp = tempfile.TemporaryDirectory(prefix="spike-data-")
        self.db = duckdb()
        self.con = self.db.connect(":memory:", config={"memory_limit": MEMORY, "threads": THREADS,
                                                        "temp_directory": self._tmp.name,
                                                        "max_temp_directory_size": "2GB"})
        self.reserved = {r[0] for r in self.con.execute(
            "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category = 'reserved'").fetchall()}

    # ---------------------------------------------------------------- loading
    def load(self) -> None:
        paths, total = [], 0
        for given in self.files:
            path = self.workspace.resolve(given)
            if not path.is_file():
                raise DataError(f"'{given}' is not a file in the workspace")
            size = path.stat().st_size
            if size > MAX_FILE:
                raise DataError(f"'{given}' is larger than {MAX_FILE // 1024**2} MB")
            total += size
            fmt = FORMATS.get(path.suffix.lower())
            if not fmt:
                raise DataError(f"'{given}': unsupported type '{path.suffix}' (use CSV, TSV, Parquet, JSON, "
                                ".xlsx or SQLite; an old .xls can be saved as .xlsx)")
            paths.append((given, path, fmt))
        if total > MAX_TOTAL:
            raise DataError(f"the files add up to more than {MAX_TOTAL // 1024**2} MB")
        taken: set[str] = set()
        for given, path, fmt in paths:
            try:
                getattr(self, f"_load_{fmt}")(given, path, taken)
            except self.db.Error as exc:
                raise DataError(f"could not read '{given}': {first_lines(exc)}") from exc
        for statement in LOCK:
            self.con.execute(statement)

    def _table(self, name: str, given: str, sheet: str | None = None) -> None:
        cols = [(r[0], r[1]) for r in self.con.execute(f"DESCRIBE {ident(name, self.reserved)}").fetchall()]
        rows = self.con.execute(f"SELECT count(*) FROM {ident(name, self.reserved)}").fetchone()[0]
        self.tables.append(Table(name, given, rows, cols, sheet))
        if len(self.tables) > MAX_TABLES:
            raise DataError(f"more than {MAX_TABLES} tables")

    def _load_csv(self, given: str, path: Path, taken: set[str]) -> None:
        name = table_name(path.stem, taken, self.reserved)
        sql = f"CREATE TABLE {ident(name)} AS SELECT * FROM read_csv(?, auto_detect=true{{}})"
        self.con.execute(sql.format(""), [str(path)])
        delimiter = self.con.execute("SELECT Delimiter FROM sniff_csv(?)", [str(path)]).fetchone()[0]
        if delimiter == ";":  # Spanish and other European exports: decimal commas, when that types more numbers
            numbers = self._numeric_columns(name)
            alt = f"{name}__comma"
            try:
                self.con.execute(sql.replace(ident(name), alt).format(", decimal_separator=','"), [str(path)])
            except self.db.Error:
                pass
            else:
                if self._numeric_columns(alt) > numbers:
                    self.con.execute(f"DROP TABLE {ident(name)}")
                    self.con.execute(f"ALTER TABLE {alt} RENAME TO {ident(name)}")
                else:
                    self.con.execute(f"DROP TABLE {alt}")
        self._table(name, given)

    def _numeric_columns(self, name: str) -> int:
        return sum(kind_of(r[1]) == "quantitative" for r in self.con.execute(f"DESCRIBE {ident(name)}").fetchall())

    def _load_parquet(self, given: str, path: Path, taken: set[str]) -> None:
        name = table_name(path.stem, taken, self.reserved)
        self.con.execute(f"CREATE TABLE {ident(name)} AS SELECT * FROM read_parquet(?)", [str(path)])
        self._table(name, given)

    def _load_json(self, given: str, path: Path, taken: set[str]) -> None:
        name = table_name(path.stem, taken, self.reserved)
        self.con.execute(f"CREATE TABLE {ident(name)} AS SELECT * FROM read_json_auto(?)", [str(path)])
        self._table(name, given)

    def _from_frame(self, frame: Any, name: str) -> None:
        import pandas as pd

        frame = frame.copy()
        frame.columns = [str(c) for c in frame.columns]
        for col in frame.columns:  # a column mixing numbers and text becomes text, as a spreadsheet shows it
            if frame[col].dtype == object and len({type(v) for v in frame[col].dropna()}) > 1:
                frame[col] = frame[col].map(lambda v: None if pd.isna(v) else str(v))
        view = f"frame_{uuid.uuid4().hex[:8]}"
        self.con.register(view, frame)
        try:
            self.con.execute(f"CREATE TABLE {ident(name)} AS SELECT * FROM {view}")
        finally:
            self.con.unregister(view)

    def _load_excel(self, given: str, path: Path, taken: set[str]) -> None:
        if path.stat().st_size > MAX_EXCEL:
            raise DataError(f"'{given}' is larger than {MAX_EXCEL // 1024**2} MB; save it as CSV or Parquet")
        try:
            import pandas as pd

            sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
        except ImportError as exc:
            raise DataError("Excel files need pandas and openpyxl: pip install 'spike-ai[data]'") from exc
        except Exception as exc:  # a damaged or protected workbook
            raise DataError(f"could not read '{given}': {exc}") from exc
        for sheet, frame in sheets.items():
            name = table_name(path.stem if len(sheets) == 1 else f"{path.stem}_{sheet}", taken, self.reserved)
            self._from_frame(frame, name)
            self._table(name, given, str(sheet))

    def _load_sqlite(self, given: str, path: Path, taken: set[str]) -> None:
        import pandas as pd

        with path.open("rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                raise DataError(f"'{given}' is not a SQLite database")
        src = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            names = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                                               "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
            if not names:
                raise DataError(f"'{given}' has no tables")
            for raw in names[:MAX_TABLES]:
                frame = pd.read_sql_query(f'SELECT * FROM "{raw.replace(chr(34), chr(34) * 2)}"', src)
                name = table_name(raw, taken, self.reserved)
                self._from_frame(frame, name)
                self._table(name, given, raw)
        except sqlite3.Error as exc:
            raise DataError(f"could not read '{given}': {exc}") from exc
        finally:
            src.close()

    # ---------------------------------------------------------------- queries
    def query(self, sql: str, limit: int) -> Result:
        if not sql.strip():
            raise DataError("the SQL is empty")
        timer = threading.Timer(self.timeout_s, self.con.interrupt)
        timer.start()
        try:
            self.con.execute(sql)
            if self.con.description is None:
                return Result([], [], [], False, self.tables)
            columns = [d[0] for d in self.con.description]
            types = [str(d[1]) for d in self.con.description]
            rows = self.con.fetchmany(limit + 1)
        except self.db.InterruptException as exc:
            raise DataError(f"the query ran longer than {self.timeout_s:.0f} s and was stopped; filter or "
                            "aggregate first") from exc
        except self.db.Error as exc:
            raise DataError(f"SQL error: {first_lines(exc)}") from exc
        finally:
            timer.cancel()
        return Result(columns, types, [[cell(v) for v in r] for r in rows[:limit]], len(rows) > limit, self.tables)

    def summary(self, table: Table) -> Result:
        """DuckDB's SUMMARIZE of one table: per column min, max, distinct values, mean, quartiles and nulls."""
        return self.query(f"SUMMARIZE {ident(table.name, self.reserved)}", 500)

    def close(self) -> None:
        self.con.close()
        self._tmp.cleanup()


def first_lines(exc: Exception, limit: int = 600) -> str:
    text = " ".join(str(exc).split("\n")[:4]).strip()
    return text[:limit]


def run_query(workspace: Workspace, files: list[str], sql: str, limit: int) -> Result:
    session = Session(workspace, files)
    try:
        session.load()
        return session.query(sql, limit)
    finally:
        session.close()


def describe(workspace: Workspace, files: list[str], sample: int = 5) -> list[tuple[Table, Result, Result]]:
    session = Session(workspace, files)
    try:
        session.load()
        return [(t, session.summary(t), session.query(f"SELECT * FROM {ident(t.name, session.reserved)}", sample))
                for t in session.tables]
    finally:
        session.close()
