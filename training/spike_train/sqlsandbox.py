"""Run SQL written by a model (the distillation teacher, or the model under evaluation) on a small database.

Everything uses the standard library's sqlite3 on a fresh in-memory database for each call: no file, no network, no
ATTACH, no extension loading, a wall-clock limit and caps on the size of one value, of the database and of the result.
The database is built from a schema script (CREATE TABLE and INSERT statements) and the query then runs read-only.
Two executions of the same schema never share state.

The limits catch the usual failures of model output (a runaway recursive query, an enormous string, a script that
tries to ATTACH a file). It is not a security boundary against a hostile program, and model-written Python (pandas) is
out of scope for it: running that would need a real sandbox, so no recipe here asks for it.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from spike_train.metrics import strip_think

TIMEOUT_S = 2.0              # for building the database and running the query together
MAX_ROWS = 1000              # a query returning more is not a question about a small database
MAX_SCRIPT_CHARS = 20_000
MAX_SQL_CHARS = 4_000
MAX_TABLES = 8
MAX_DB_PAGES = 256           # PRAGMA max_page_count: about 1 MB of data at the default 4 KiB page
VALUE_LIMIT = 100_000        # SQLITE_LIMIT_LENGTH: one string, blob or row (zeroblob, randomblob and replace bombs)
CHECK_EVERY = 1000           # virtual machine instructions between two looks at the clock

# Authorizer action codes (sqlite3.h): fixed by SQLite's C interface, written out so the policy reads in one place.
READ, SELECT, PRAGMA, ATTACH, DETACH, FUNCTION, RECURSIVE = 20, 21, 19, 24, 25, 31, 33
CREATE_VTABLE, DROP_VTABLE = 29, 30
OK, DENY = 0, 1
READ_ONLY = {READ, SELECT, FUNCTION, RECURSIVE}      # what a query may do; a script may also create and insert
ALWAYS_DENIED = {ATTACH, DETACH, CREATE_VTABLE, DROP_VTABLE}
ALLOWED_PRAGMAS = {"foreign_keys"}
DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


@dataclass(frozen=True)
class Result:
    """The outcome of a query: its rows, or why it did not run (`stage` says whether the schema or the query failed)."""
    ok: bool
    rows: tuple[tuple, ...] = ()
    error: str = ""
    stage: str = ""


def _policy(writable: bool):
    def authorize(action, arg1, arg2, dbname, source):
        if action in ALWAYS_DENIED:
            return DENY
        if action == PRAGMA:
            return OK if writable and (arg1 or "").lower() in ALLOWED_PRAGMAS else DENY
        if action == FUNCTION and (arg2 or "").lower() in DENIED_FUNCTIONS:
            return DENY
        return OK if writable or action in READ_ONLY else DENY
    return authorize


def _connect(timeout: float) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    if hasattr(conn, "enable_load_extension"):   # off by default; Python builds without the method cannot load any
        conn.enable_load_extension(False)
    conn.execute(f"PRAGMA max_page_count = {MAX_DB_PAGES}")
    for limit, value in ((sqlite3.SQLITE_LIMIT_LENGTH, VALUE_LIMIT), (sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SCRIPT_CHARS),
                         (sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 20), (sqlite3.SQLITE_LIMIT_ATTACHED, 0),
                         (sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH, 200), (sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)):
        conn.setlimit(limit, value)
    deadline = time.monotonic() + timeout
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), CHECK_EVERY)   # nonzero: "interrupted"
    return conn


def run(schema: str, sql: str, timeout: float = TIMEOUT_S) -> Result:
    """Build a database from `schema` and run the single query `sql` on it. Never raises for bad model output."""
    if len(schema) > MAX_SCRIPT_CHARS:
        return Result(False, error=f"schema longer than {MAX_SCRIPT_CHARS} characters", stage="schema")
    query = sql.strip().rstrip(";").strip()
    if not query or len(query) > MAX_SQL_CHARS:
        return Result(False, error="empty query" if not query else f"query longer than {MAX_SQL_CHARS} characters",
                      stage="query")
    if ";" in blank(query):
        return Result(False, error="more than one statement", stage="query")
    conn = _connect(timeout)
    try:
        conn.set_authorizer(_policy(writable=True))
        try:
            conn.executescript(schema)
        except (sqlite3.Error, sqlite3.Warning, OverflowError, ValueError) as exc:
            return Result(False, error=str(exc), stage="schema")
        tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
        if not 1 <= tables <= MAX_TABLES:
            return Result(False, error=f"{tables} tables (need 1 to {MAX_TABLES})", stage="schema")
        conn.set_authorizer(_policy(writable=False))
        try:
            rows = conn.execute(query).fetchmany(MAX_ROWS + 1)
        except (sqlite3.Error, sqlite3.Warning, OverflowError, ValueError) as exc:
            return Result(False, error=str(exc), stage="query")
        if len(rows) > MAX_ROWS:
            return Result(False, error=f"more than {MAX_ROWS} rows", stage="query")
        return Result(True, rows=tuple(tuple(r) for r in rows))
    finally:
        conn.close()


def blank(sql: str) -> str:
    """`sql` with string literals, quoted identifiers and comments replaced by spaces, so that a scan for keywords or
    for ';' does not read the inside of a literal."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"`[":
            close = "]" if c == "[" else c
            j = i + 1
            while j < n:
                if sql[j] == close:
                    if close != "]" and sql[j + 1:j + 2] == close:    # a doubled quote is part of the literal
                        j += 2
                        continue
                    break
                j += 1
            out.append(" " * (min(j, n - 1) - i + 1))
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " * (j - i))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def has_order_by(sql: str) -> bool:
    """Does the query sort its final result (an ORDER BY outside every parenthesis)? Then row order is part of it."""
    text = blank(sql)
    return any(text.count("(", 0, m.start()) == text.count(")", 0, m.start())
               for m in re.finditer(r"\border\s+by\b", text, re.IGNORECASE))


_FENCE = re.compile(r"```[ \t]*([^\s`]*)[ \t]*\r?\n(.*?)```", re.DOTALL)


def extract_sql(response: str) -> str | None:
    """The first fenced SQL block of a model's answer (a fence without a language counts), else the whole answer."""
    body = strip_think(response)
    blocks = _FENCE.findall(body)
    if not blocks:
        return body.strip() or None
    return next((code.strip() for lang, code in blocks if lang.lower() in ("", "sql", "sqlite") and code.strip()), None)


def _canon(value):
    return round(value, 6) if isinstance(value, float) else (bytes(value) if isinstance(value, bytearray) else value)


def same_result(a: Sequence[Sequence], b: Sequence[Sequence], ordered: bool = False) -> bool:
    """Equal result sets: the same rows (column order matters, names do not; floats to six decimals; 1 equals 1.0),
    in the same order when `ordered`, otherwise as multisets."""
    ra, rb = ([tuple(_canon(v) for v in row) for row in rows] for rows in (a, b))
    return ra == rb if ordered else Counter(ra) == Counter(rb)
