"""G13: Analytics reliability suite — malformed CSVs (UTF-16/UTF-8 BOMs, NUL bytes, rare separators, sep= directives,
duplicate/case-insensitive columns, empty cells and header-only tables, ambiguous/contradictory dates, leading-zero
codes, >64-bit integer IDs), multi-sheet Excel workbooks with empty sheets or duplicate headers, oversized file guards,
SQL Guardian comments/errors, and report endpoint error handling without HTTP 500 or silent data corruption."""

from __future__ import annotations

import base64
import sqlite3

import pytest
from fastapi.testclient import TestClient

from spike.analytics import engine
from spike.analytics.contracts import Contract
from spike.analytics.engine import DataError, Session, describe, run_query
from spike.analytics.guardian import bounded, explain, statement
from spike.analytics.rescue import rescue_csv
from spike.analytics.tools import DataDescribe, DataPython, DataSql
from spike.server.app import create_app
from spike.server.state import AppState
from spike.tools.builtin import Workspace
from tests.helpers import ScriptedProvider

pytest.importorskip("duckdb", reason="the data extra (duckdb, pandas)")
pytest.importorskip("pandas")


def test_csv_utf16_bom_double_bom_and_nul_bytes(tmp_path):
    # Excel "Unicode Text" exports use UTF-16 LE or UTF-16 BE with BOM.
    utf16_le = tmp_path / "utf16le.csv"
    utf16_le.write_bytes("región\timporte\nnorte\t12,50\nsur\t7,25\n".encode("utf-16-le"))
    utf16_le.write_bytes(b"\xff\xfe" + utf16_le.read_bytes())
    rescued_le = rescue_csv(utf16_le)
    assert rescued_le.columns == ["región", "importe"]
    assert rescued_le.rows == [["norte", 12.5], ["sur", 7.25]]

    utf16_be = tmp_path / "utf16be.csv"
    utf16_be.write_bytes(b"\xfe\xff" + "región;importe\nnorte;10\n".encode("utf-16-be"))
    rescued_be = rescue_csv(utf16_be)
    assert rescued_be.columns == ["región", "importe"]
    assert rescued_be.rows == [["norte", 10]]

    # Double UTF-8 BOM should not pollute the first column name.
    double_bom = tmp_path / "double_bom.csv"
    double_bom.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbfid,valor\n1,20\n")
    assert rescue_csv(double_bom).columns == ["id", "valor"]

    # Raw binary / NUL bytes without UTF-16/32 BOM must fail with a clear DataError.
    nul_csv = tmp_path / "nul.csv"
    nul_csv.write_bytes(b"a,b\n1\x00,2\n")
    with pytest.raises(DataError, match="NUL"):
        rescue_csv(nul_csv)


def test_csv_rare_separators_and_excel_sep_directive(tmp_path):
    # Excel sep=, on a 2-column CSV must not be mistaken for a 2-column header row.
    sep_comma = tmp_path / "sep_comma.csv"
    sep_comma.write_text("sep=,\nregion,ventas\nnorte,100\nsur,50\n", encoding="utf-8")
    out_comma = rescue_csv(sep_comma)
    assert out_comma.columns == ["region", "ventas"]
    assert out_comma.rows == [["norte", 100], ["sur", 50]]

    # Rare delimiters (: ^ ~) without and with sep= directive.
    for name, delim in (("colon.csv", ":"), ("caret.csv", "^"), ("tilde.csv", "~")):
        p = tmp_path / name
        p.write_text(f"producto{delim}unidades{delim}precio\nA{delim}3{delim}4,5\nB{delim}2{delim}10,0\n",
                     encoding="utf-8")
        out = rescue_csv(p)
        assert out.columns == ["producto", "unidades", "precio"]
        assert out.rows == [["A", 3, 4.5], ["B", 2, 10.0]]

    # Timestamps containing colons in a comma-separated CSV must still choose comma, not colon.
    ts_csv = tmp_path / "timestamps.csv"
    ts_csv.write_text("ts,valor\n2024-01-01 10:20:30,100\n2024-01-02 11:22:33,200\n", encoding="utf-8")
    out_ts = rescue_csv(ts_csv)
    assert out_ts.columns == ["ts", "valor"]
    assert out_ts.rows == [["2024-01-01 10:20:30", 100], ["2024-01-02 11:22:33", 200]]


def test_csv_empty_cells_nbsp_and_header_only_table(tmp_path):
    # Cells containing only NBSP (\u00a0) or zero-width space (\u200b) must be treated as empty (None)
    # so they do not break numeric conversion of the column.
    nbsp = tmp_path / "nbsp.csv"
    nbsp.write_text("region,importe\nnorte,10\nsur,\u00a0\neste,\u200b\noeste,25\n", encoding="utf-8")
    out = rescue_csv(nbsp)
    assert out.rows == [["norte", 10], ["sur", None], ["este", None], ["oeste", 25]]

    # A header-only CSV (0 data rows) preserves its declared schema instead of failing with 'no nonempty columns'.
    header_only = tmp_path / "empty_rows.csv"
    header_only.write_text("id,nombre,importe\n", encoding="utf-8")
    out_empty = rescue_csv(header_only)
    assert out_empty.columns == ["id", "nombre", "importe"]
    assert out_empty.rows == []
    ws = Workspace(tmp_path)
    res = run_query(ws, ["empty_rows.csv"], "SELECT count(*) FROM empty_rows", 10)
    assert res.rows == [[0]]


def test_csv_silent_corruption_guards_leading_zeros_and_huge_ints(tmp_path):
    # Leading-zero codes (postal codes, SKUs) must never be converted to int (which strips leading zeros),
    # and 20-digit integer IDs (> 2**63 - 1) must never be converted to DOUBLE (which silently rounds digits).
    codes = tmp_path / "codes.csv"
    big_id = "12345678901234567899"
    codes.write_text(f"cp,cuenta,big_id,importe\n08001,00123,{big_id},10\n28013,00456,{big_id},20\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    res = run_query(ws, ["codes.csv"], "SELECT cp, cuenta, big_id, sum(importe) OVER () FROM codes ORDER BY cp", 10)
    assert res.types[:3] == ["VARCHAR", "VARCHAR", "VARCHAR"]
    assert res.rows[0] == ["08001", "00123", big_id, 30]
    assert res.rows[1] == ["28013", "00456", big_id, 30]


def test_csv_dates_yyyy_slash_ambiguous_flag_and_contradictory_dates(tmp_path):
    # YYYY/MM/DD and YYYY.MM.DD are unambiguous ISO-ordered dates and should parse to DATE.
    ymd = tmp_path / "ymd.csv"
    ymd.write_text("fecha,v\n2024/01/31,1\n2024.02.15,2\n", encoding="utf-8")
    out_ymd = rescue_csv(ymd)
    assert [str(r[0]) for r in out_ymd.rows] == ["2024-01-31", "2024-02-15"]
    date_step = next(s for s in out_ymd.report["steps"] if s["code"] == "dates")
    assert date_step.get("ambiguous") is False

    # Numeric slash dates where every row has 1 <= a, b <= 12 and a != b are parsed according to locale
    # and explicitly flagged as ambiguous in the rescue report.
    ambig = tmp_path / "ambig.csv"
    ambig.write_text("fecha,v\n01/02/2024,1\n03/04/2024,2\n", encoding="utf-8")
    out_ambig = rescue_csv(ambig, locale="es")
    assert [str(r[0]) for r in out_ambig.rows] == ["2024-02-01", "2024-04-03"]
    ambig_step = next(s for s in out_ambig.report["steps"] if s["code"] == "dates")
    assert ambig_step.get("ambiguous") is True

    # Contradictory DD/MM/YYYY and MM/DD/YYYY rows in the same column must stay text (never guess per-row)
    # and report 'ambiguous_dates' in rescue steps.
    contra = tmp_path / "contra.csv"
    contra.write_text("fecha,v\n31/01/2024,1\n01/31/2024,2\n", encoding="utf-8")
    out_contra = rescue_csv(contra, locale="es")
    assert out_contra.rows == [["31/01/2024", 1], ["01/31/2024", 2]]
    assert any(s["code"] == "ambiguous_dates" for s in out_contra.report["steps"])


def test_excel_multisheet_with_empty_sheet_and_duplicate_columns(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    # 1. Workbook with a populated sheet, a completely empty sheet, and a sheet with duplicate/blank headers.
    book = openpyxl.Workbook()
    s1 = book.active
    s1.title = "Ventas"
    s1.append(["Ventas", "ventas", "", "Notas"])
    s1.append([100, 200, "x", None])
    s1.append([150, 250, "y", None])
    book.create_sheet("HojaVacía")  # 0 rows, 0 columns
    book.save(tmp_path / "multi.xlsx")

    ws = Workspace(tmp_path)
    res = run_query(ws, ["multi.xlsx"], 'SELECT "Ventas", ventas_2 FROM multi_ventas ORDER BY 1', 10)
    assert res.rows == [[100, 200], [150, 250]]
    assert [t.name for t in res.tables] == ["multi_ventas"]
    [(table, summary, _)] = describe(ws, ["multi.xlsx"])
    assert [c[0] for c in table.columns[:2]] == ["Ventas", "ventas_2"]
    assert len(summary.rows) == 4

    # 2. Workbook where ALL sheets are empty raises a clear DataError.
    empty_book = openpyxl.Workbook()
    empty_book.save(tmp_path / "empty.xlsx")
    with pytest.raises(DataError, match="no tables"):
        run_query(ws, ["empty.xlsx"], "SELECT 1", 1)


def test_sqlite_view_with_duplicate_columns_does_not_crash_with_500(tmp_path):
    import pandas as pd

    db_path = tmp_path / "dup.sqlite"
    con = sqlite3.connect(db_path)
    con.executescript("CREATE TABLE base (id INTEGER, nombre TEXT); INSERT INTO base VALUES (1, 'Ana'); "
                      "CREATE VIEW v_dup AS SELECT id AS col, nombre AS COL, id AS Col FROM base;")
    con.commit()
    con.close()

    ws = Workspace(tmp_path)
    res = run_query(ws, ["dup.sqlite"], 'SELECT col, "COL:1", "Col:2" FROM v_dup', 10)
    assert res.rows == [[1, "Ana", 1]]

    # Direct DataFrame with exact duplicate column names must not raise AttributeError on frame[col].dtype.
    session = Session(ws, ["dup.sqlite"])
    try:
        session._from_frame(pd.DataFrame([[1, "x", 2]], columns=["a", "a", "A"]), "df_dup")
        rows = session.con.execute("SELECT a, a_2, A_3 FROM df_dup").fetchall()
        assert rows == [(1, "x", 2)]
    finally:
        session.close()


async def test_oversized_files_and_duplicate_basenames_rejected_everywhere(tmp_path, monkeypatch):
    (tmp_path / "big.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    monkeypatch.setattr(engine, "MAX_FILE", 4)

    with pytest.raises(DataError, match="larger than"):
        run_query(ws, ["big.csv"], "SELECT * FROM big", 10)

    out_sql = await DataSql(ws).run({"files": ["big.csv"], "sql": "SELECT * FROM big"})
    assert not out_sql.ok and "larger than" in out_sql.content

    out_py = await DataPython(ws).run({"files": ["big.csv"], "code": "print(1)"})
    assert not out_py.ok and "larger than" in out_py.content

    monkeypatch.setattr(engine, "MAX_FILE", 1024 * 1024)
    (tmp_path / "d1").mkdir()
    (tmp_path / "d2").mkdir()
    (tmp_path / "d1" / "same.csv").write_text("a\n1\n", encoding="utf-8")
    (tmp_path / "d2" / "same.csv").write_text("a\n2\n", encoding="utf-8")
    out_dup = await DataPython(ws).run({"files": ["d1/same.csv", "d2/same.csv"], "code": "print(1)"})
    assert not out_dup.ok and "duplicate" in out_dup.content.lower()


async def test_duckdb_errors_and_sql_comments_handled_cleanly(tmp_path):
    (tmp_path / "sales.csv").write_text("region,importe\nnorte,10\nsur,20\n", encoding="utf-8")
    (tmp_path / "bad.json").write_text("{corrupt json", encoding="utf-8")
    (tmp_path / "bad.parquet").write_bytes(b"not a parquet file")
    ws = Workspace(tmp_path)

    # SQL ending with a single-line comment (-- ...) and optional semicolon must not break bounded() preview.
    res = run_query(ws, ["sales.csv"], "SELECT region, importe FROM sales ORDER BY importe; -- comentario final", 10)
    assert res.rows == [["norte", 10], ["sur", 20]]

    # Direct guardian calls on syntax errors raise DataError, never raw duckdb.Error.
    session = Session(ws, ["sales.csv"])
    try:
        session.load()
        with pytest.raises(DataError, match="SQL error"):
            statement(session.con, "SELECT * FROM (")
        with pytest.raises(DataError, match="SQL error"):
            explain(session.con, bounded("SELECT non_existent_col FROM sales", 5))
    finally:
        session.close()

    # Corrupt JSON / Parquet and missing contract files surface as DataError / ToolResult(ok=False).
    for bad_file in ("bad.json", "bad.parquet"):
        out = await DataDescribe(ws).run({"files": [bad_file]})
        assert not out.ok and "could not read" in out.content

    with pytest.raises(DataError):
        Contract.load(tmp_path / "missing_contract.json")


def test_analytics_report_endpoint_never_returns_500_on_corrupt_png_or_bad_bytes(tmp_path, monkeypatch):
    for name, value in (("SPIKE_HOME", tmp_path / "home"), ("SPIKE_WORKSPACE", tmp_path / "ws"),
                        ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")
    state = AppState(home=tmp_path / "home", provider_factory=lambda cfg: local)
    client = TestClient(create_app(state))

    # 1. Valid PNG magic bytes followed by corrupted payload -> HTTP 400 (not 500).
    corrupt_png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\ncorrupted-payload").decode()
    r1 = client.post("/api/analytics/report", json={
        "format": "pdf", "title": "Informe", "blocks": [{"kind": "image", "png": corrupt_png}],
    })
    assert r1.status_code == 400

    # 2. Non-UTF-8 raw body -> HTTP 400 (not 500).
    r2 = client.post("/api/analytics/report", content=b"\xff\xfe\x00\x00",
                     headers={"Content-Type": "application/json"})
    assert r2.status_code == 400
