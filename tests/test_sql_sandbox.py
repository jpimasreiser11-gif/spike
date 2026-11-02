"""The SQLite sandbox that runs SQL written by a distillation teacher or by the model under evaluation (no network)."""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

from spike_train import sqlsandbox  # noqa: E402
from spike_train.sqlsandbox import blank, extract_sql, has_order_by, run, same_result  # noqa: E402

SCHEMA = """
CREATE TABLE city (id INTEGER PRIMARY KEY, name TEXT NOT NULL, pop INTEGER);
INSERT INTO city VALUES (1, 'Lima', 10), (2, 'Quito', 3), (3, 'Cusco', 1);
CREATE TABLE trip (id INTEGER PRIMARY KEY, city_id INTEGER REFERENCES city(id), km REAL);
INSERT INTO trip VALUES (1, 1, 12.5), (2, 1, 7.5), (3, 2, 4.0);
"""


def test_a_query_runs_on_a_database_built_from_the_schema():
    got = run(SCHEMA, "SELECT name, pop FROM city WHERE pop > 2 ORDER BY pop DESC;")
    assert got.ok and got.rows == (("Lima", 10), ("Quito", 3)) and got.error == "" and got.stage == ""
    joined = run(SCHEMA, "SELECT c.name, SUM(t.km) FROM city c JOIN trip t ON t.city_id = c.id GROUP BY c.name")
    assert sorted(joined.rows) == [("Lima", 20.0), ("Quito", 4.0)]


def test_a_failing_schema_or_query_says_which_one_failed():
    bad_schema = run("CREATE TABLE a (x INTEGER); INSERT INTO a VALUES (1, 2);", "SELECT x FROM a")
    assert not bad_schema.ok and bad_schema.stage == "schema" and "values" in bad_schema.error
    bad_query = run(SCHEMA, "SELECT missing FROM city")
    assert not bad_query.ok and bad_query.stage == "query" and "missing" in bad_query.error
    for sql in ("", "   ;  "):
        assert run(SCHEMA, sql).stage == "query"


def test_every_call_starts_from_a_fresh_database():
    # a model that tries to leave state behind cannot affect the next call, and a query cannot write at all
    assert not run(SCHEMA, "DELETE FROM city").ok and not run(SCHEMA, "INSERT INTO city VALUES (9, 'X', 1)").ok
    assert not run(SCHEMA, "DROP TABLE city").ok and not run(SCHEMA, "CREATE TABLE z (a)").ok
    assert run(SCHEMA, "SELECT count(*) FROM city").rows == ((3,),)
    assert run("CREATE TABLE city (a); INSERT INTO city VALUES (1);", "SELECT count(*) FROM city").rows == ((1,),)


@pytest.mark.parametrize("sql", [
    "ATTACH DATABASE 'other.db' AS other",
    "ATTACH DATABASE ':memory:' AS other",
    "DETACH DATABASE main",
    "PRAGMA table_info(city)",
    "PRAGMA writable_schema = 1",
    "SELECT load_extension('/lib/x.so')",
    "SELECT readfile('/etc/passwd')",
    "CREATE VIRTUAL TABLE v USING fts5(a)",
])
def test_attach_extensions_pragmas_and_virtual_tables_are_refused_in_a_query(sql):
    got = run(SCHEMA, sql)
    assert not got.ok and got.stage == "query"


@pytest.mark.parametrize("schema", [
    "ATTACH DATABASE 'other.db' AS other; CREATE TABLE a (x)",
    "CREATE VIRTUAL TABLE v USING fts5(a); CREATE TABLE a (x)",
    "CREATE TABLE a (x); PRAGMA journal_mode = WAL",
    "CREATE TABLE a (x); SELECT load_extension('x')",
])
def test_the_same_things_are_refused_in_a_schema_script(schema, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = run(schema, "SELECT 1")
    assert not got.ok and got.stage == "schema"
    assert not list(tmp_path.iterdir())                    # nothing was written to disk


def test_foreign_keys_pragma_is_the_only_pragma_a_schema_may_use():
    assert run("PRAGMA foreign_keys = ON;" + SCHEMA, "SELECT count(*) FROM trip").ok


def test_a_runaway_query_is_interrupted_by_the_time_limit():
    forever = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT count(*) FROM n"
    t0 = time.monotonic()
    got = run(SCHEMA, forever, timeout=0.3)
    assert not got.ok and got.stage == "query" and "interrupt" in got.error.lower()
    assert time.monotonic() - t0 < 5
    slow_schema = "CREATE TABLE a AS WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT count(*) AS c FROM n;"
    got = run(slow_schema, "SELECT 1", timeout=0.3)
    assert not got.ok and got.stage == "schema" and "interrupt" in got.error.lower()   # the same clock covers the build


def test_size_limits_on_a_value_a_database_a_script_a_query_and_a_result():
    for sql in ("SELECT zeroblob(1000000000)", "SELECT replace(hex(zeroblob(40000)), '0', hex(zeroblob(40000)))"):
        got = run(SCHEMA, sql)
        assert not got.ok and got.stage == "query" and "too big" in got.error
    big = run("CREATE TABLE a (x);" + "INSERT INTO a VALUES (zeroblob(90000));" * 40, "SELECT 1")
    assert not big.ok and big.stage == "schema" and "full" in big.error          # past PRAGMA max_page_count
    assert run("-- " + "x" * sqlsandbox.MAX_SCRIPT_CHARS + "\n" + SCHEMA, "SELECT 1").stage == "schema"
    assert run(SCHEMA, "SELECT " + "1 + " * 2000 + "1").stage == "query"
    many = run(SCHEMA, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 2000) SELECT i FROM n")
    assert not many.ok and "rows" in many.error
    assert run(SCHEMA, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 1000) SELECT i FROM n").ok


def test_a_query_must_be_one_statement_and_a_schema_one_to_eight_tables():
    got = run(SCHEMA, "SELECT 1; DROP TABLE city")
    assert not got.ok and "more than one statement" in got.error
    assert run(SCHEMA, "SELECT ';' AS semi -- a ; in a comment\n").rows == ((";",),)   # a ; inside a literal is fine
    assert run("INSERT INTO nowhere VALUES (1);", "SELECT 1").stage == "schema"
    assert run("SELECT 1;", "SELECT 1").stage == "schema"                              # no table at all
    nine = "".join(f"CREATE TABLE t{i} (x);" for i in range(9))
    got = run(nine, "SELECT 1")
    assert not got.ok and got.stage == "schema" and "9 tables" in got.error
    assert run(nine.replace("CREATE TABLE t8 (x);", ""), "SELECT 1").ok


def test_blank_hides_literals_identifiers_and_comments():
    assert blank("SELECT 'a;b', \"c;d\", [e;f], `g;h` -- i;j\n, 1 /* k;l */") .count(";") == 0
    assert blank("SELECT 'it''s; here'").count(";") == 0
    assert blank("SELECT 1;").count(";") == 1
    assert len(blank("SELECT 'abc' FROM t")) == len("SELECT 'abc' FROM t")


def test_order_by_counts_only_when_it_sorts_the_final_result():
    assert has_order_by("SELECT a FROM t ORDER BY a")
    assert has_order_by("select a from t order\n  by a desc limit 3")
    assert not has_order_by("SELECT a FROM t")
    assert not has_order_by("SELECT a FROM (SELECT a FROM t ORDER BY a LIMIT 3)")
    assert not has_order_by("SELECT a, 'ORDER BY' FROM t -- order by a")
    assert has_order_by("SELECT a FROM (SELECT a FROM t ORDER BY a LIMIT 3) ORDER BY a DESC")


@pytest.mark.parametrize("response, expected", [
    ("```sql\nSELECT 1\n```", "SELECT 1"),
    ("Here it is:\n```SQL\nSELECT 1;\n```\nIt returns one.", "SELECT 1;"),
    ("```\nSELECT 2\n```", "SELECT 2"),
    ("```sqlite\nSELECT 3\n```", "SELECT 3"),
    ("```python\nprint(1)\n```\n```sql\nSELECT 4\n```", "SELECT 4"),
    ("<think>```sql\nSELECT 0\n```</think>\n```sql\nSELECT 5\n```", "SELECT 5"),
    ("```sql\nSELECT 6\n```\n```sql\nSELECT 7\n```", "SELECT 6"),
    ("SELECT 8", "SELECT 8"),
    ("```python\nprint(1)\n```", None),
    ("", None),
    ("<think>only thinking</think>", None),
])
def test_extract_sql_takes_the_first_sql_block(response, expected):
    assert extract_sql(response) == expected


def test_result_sets_compare_as_multisets_unless_the_order_counts():
    a, b = [(1, "x"), (2, "y"), (2, "y")], [(2, "y"), (1, "x"), (2, "y")]
    assert same_result(a, b) and not same_result(a, b, ordered=True) and same_result(a, a, ordered=True)
    assert not same_result(a, [(1, "x"), (2, "y")])                       # duplicates matter
    assert not same_result([(1, 2)], [(2, 1)])                            # column order matters
    assert same_result([(1, 2.0)], [(1.0, 2)]) and same_result([(0.1 + 0.2,)], [(0.3,)])
    assert not same_result([(1.0,)], [(1.1,)]) and not same_result([("1",)], [(1,)])
    assert same_result([], []) and not same_result([], [(1,)])
