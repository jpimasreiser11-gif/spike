"""A3: hand-calculated baselines, read-only SQL, repaired CSVs and reproducible load evidence."""

import hashlib
import io
import json
import zipfile

import pytest

from spike.analytics.contracts import Contract, ContractViolation
from spike.analytics.engine import DataError, Session, run_query
from spike.analytics.forecast import backtest, forecast
from spike.analytics.rescue import rescue_csv
from spike.analytics.tools import DataForecast, DataSql
from spike.proof import build_proof
from spike.tools.builtin import Workspace

pytest.importorskip("duckdb", reason="the data extra")


@pytest.mark.parametrize("method, expected", [
    ("naive", [5, 5]), ("seasonal_naive", [3, 5]), ("drift", [7, 9]),
    ("ses", [3.5, 3.5]), ("holt", [7, 9]),
])
def test_baselines_by_hand(method, expected):
    assert forecast([1, 3, 5], 2, method, season=2) == pytest.approx(expected)


def test_holt_and_seasonal_cycle_by_hand():
    # l0=1,b0=2; after 3: l=3,b=2; after 4: l=4.5,b=1.75.
    assert forecast([1, 3, 4], 2, "holt") == [6.25, 8]
    assert forecast([1, 2, 3, 4], 5, "seasonal_naive", season=3) == [2, 3, 4, 2, 3]


def test_rolling_origin_uses_only_past_and_same_folds():
    out = backtest([1, 3, 5, 7, 9], 2, season=2)
    assert out["method"] == "drift"  # ties resolved in documented method order
    assert out["forecast"] == [11, 13]
    scores = {r["method"]: r for r in out["backtest"]}
    assert scores["naive"]["mae"] == 3
    assert scores["drift"]["mae"] == 0
    assert {r["folds"] for r in scores.values()} == {2}
    assert scores["naive"]["errors"] == [2, 4, 2, 4]
    assert backtest([1, 3, 5, 7, 900], 2, season=2)["backtest"][0]["errors"][:2] == [2, 4]


@pytest.mark.parametrize("values, kwargs", [([], {}), ([1, float("nan")], {}), ([1, 2], {"horizon": 0}),
                                           ([1, 2], {"season": 0}), ([1, 2], {"alpha": 2})])
def test_invalid_forecasts(values, kwargs):
    with pytest.raises(DataError):
        forecast(values, **{"horizon": 1, "method": "naive", **kwargs})
    with pytest.raises(DataError):
        backtest([1, 2], 3)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "sales.csv").write_text("day,amount\n2024-01-01,1\n2024-01-02,3\n2024-01-03,5\n2024-01-04,7\n2024-01-05,9\n", encoding="utf-8")
    return Workspace(tmp_path)


def test_messy_csv_fixes_are_reported(tmp_path):
    path = tmp_path / "messy.csv"
    raw = "Exportación\nfecha;importe;vacío\n31/01/2024;10,50;\n01/02/2024;20,25;\n01/02/2024;20,25;\n"
    path.write_bytes(raw.encode("cp1252"))
    out = rescue_csv(path)
    assert out.columns == ["fecha", "importe"]
    assert [[str(v) for v in row] for row in out.rows] == [["2024-01-31", "10.5"], ["2024-02-01", "20.25"]]
    assert out.report["before"] == {"rows": 3, "columns": 3}
    assert out.report["after"] == {"rows": 2, "columns": 2}
    fixes = {step["code"]: step for step in out.report["steps"]}
    assert set(fixes) >= {"encoding", "delimiter", "header", "decimal_comma", "dates", "duplicates", "empty_columns"}
    assert fixes["duplicates"]["count"] == 1
    assert fixes["header"]["skipped"] == 1
    assert out.report["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.read_bytes() == raw.encode("cp1252")
    session = Session(Workspace(tmp_path), ["messy.csv"])
    try:
        session.load()
        result = session.query("SELECT sum(importe) FROM messy", 2)
        assert result.rows == [[30.75]]
        assert [s["operation"] for s in result.lineage] == ["rescue", "load", "query"]
        assert result.lineage[0]["report"] == out.report
    finally:
        session.close()


def test_english_dates_headerless_empty_and_ragged(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("date,value\n12/31/2024,1\nJan 02 2025,2\n", encoding="utf-8")
    assert str(rescue_csv(p, locale="en").rows[0][0]) == "2024-12-31"
    assert str(rescue_csv(p, locale="en").rows[1][0]) == "2025-01-02"
    p.write_text("1;2\n3;4\n", encoding="utf-8")
    assert rescue_csv(p).columns == ["column_1", "column_2"]
    assert len(rescue_csv(p).rows) == 2
    p.write_text("a,b\n1,2,3\n", encoding="utf-8")
    with pytest.raises(DataError, match="ragged"):
        rescue_csv(p)
    p.write_text("", encoding="utf-8")
    with pytest.raises(DataError):
        rescue_csv(p)


def test_contracts_json_yaml_and_load_violations(workspace):
    spec = {"columns": {"day": {"type": "date", "nullable": False}, "amount": {"type": "number"}},
            "rules": [{"column": "amount", "min": 2, "max": 8, "unique": True}]}
    p = workspace.root / "contract.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    contract = Contract.load(p)
    violations = contract.validate(["day", "amount"], [[None, 1], ["2024-01-01", 1]])
    assert {v["code"] for v in violations} == {"nullable", "type", "min", "unique"}
    (workspace.root / "contract.yaml").write_text("columns:\n  amount:\n    type: number\nrules: []\n", encoding="utf-8")
    assert Contract.load(workspace.root / "contract.yaml").validate(["amount"], [[1]]) == []
    session = Session(workspace, ["sales.csv"], contracts={"sales.csv": "contract.json"})
    try:
        with pytest.raises(ContractViolation) as exc:
            session.load()
        assert {v["code"] for v in exc.value.violations} == {"min", "max"}
        assert session.lineage[-1]["operation"] == "contract"
    finally:
        session.close()
    p.write_text('{"columns":{"x":{"type":"invented"}}}', encoding="utf-8")
    with pytest.raises(DataError):
        Contract.load(p)


@pytest.mark.parametrize("sql", ["DELETE FROM sales", "DROP TABLE sales", "CREATE TABLE x(a INT)",
                                 "SELECT 1; DELETE FROM sales", "COPY sales TO 'out.csv'",
                                 "EXPLAIN ANALYZE DELETE FROM sales"])
def test_guardian_refuses_writes(workspace, sql):
    session = Session(workspace, ["sales.csv"])
    try:
        session.load()
        with pytest.raises(DataError, match="SQL error"):
            session.query(sql, 3)
        assert session.query("SELECT count(*) FROM sales", 1).rows == [[5]]
        assert not (workspace.root / "out.csv").exists()
    finally:
        session.close()


def test_guardian_explain_limit_and_trusted_approval(workspace):
    session = Session(workspace, ["sales.csv"])
    try:
        session.load()
        preview = session.preview("SELECT * FROM sales ORDER BY day", 2)
        assert len(preview["result"].rows) == 2 and preview["result"].truncated
        assert "LIMIT 3" in preview["sql"]
        assert preview["plan"] and preview["explanation"]["en"] and preview["explanation"]["es"]
        assert preview["explanation"] == session.preview("SELECT * FROM sales ORDER BY day", 2)["explanation"]
        session.query("DELETE FROM sales WHERE amount=1", 1, approved=True)
        assert session.query("SELECT count(*) FROM sales", 1).rows == [[4]]
        assert any(s.get("approved") is True for s in session.lineage)
        with pytest.raises(DataError):
            session.preview("DELETE FROM sales", 1)
    finally:
        session.close()
    with pytest.raises(DataError):
        run_query(workspace, ["sales.csv"], "SELECT 1", 0)


async def test_tools_show_evidence_forecast_and_proof(workspace):
    result = await DataSql(workspace).run({"files": ["sales.csv"], "sql": "SELECT * FROM sales"})
    assert result.ok
    ui = result.data["ui"]
    assert ui["lineage"] and ui["guardian"]["explanation"]["es"]
    out = await DataForecast(workspace).run({"files": ["sales.csv"], "sql": "SELECT amount FROM sales ORDER BY day",
                                              "horizon": 2, "season": 2})
    assert out.ok and out.data["ui"]["rows"] == [[1, 11], [2, 13]]
    assert "MAE" in out.content and "drift" in out.content
    assert out.data["ui"]["lineage"][-1]["operation"] == "forecast"
    assert len(out.data["ui"]["backtest"]) == 5
    assert out.private == [out.content]
    messages = [{"role": "assistant", "content": out.content, "created": 1,
                 "meta": {"tools": [{"type": "tool_result", "id": "t1", "ui": out.data["ui"]}]}}]
    package = build_proof({"id": "c", "title": "Forecast", "created": 1}, messages, [], [], [], {})
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        saved = json.loads(z.read("chat.json"))["messages"][0]["meta"]["tools"][0]["ui"]
    assert saved["lineage"] == out.data["ui"]["lineage"]


def test_forecast_available_in_data_chat_and_lineage_in_proof(workspace, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from spike.server.app import create_app
    from spike.server.state import AppState
    from tests.helpers import ScriptedProvider, call, text

    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(workspace.root))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([call("data_forecast", {"files": ["sales.csv"],
                             "sql": "SELECT amount FROM sales ORDER BY day", "horizon": 2, "season": 2}), text("Done")],
                             name="spike-local")

    def factory(config):
        local.config = config
        return local

    client = TestClient(create_app(AppState(home=tmp_path / "home", provider_factory=factory)))
    response = client.post("/api/chat", json={"mode": "data", "message": "Forecast sales.csv"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert "data_forecast" in {tool.name for tool in local.requests[0].tools}
    event = next(e for e in events if e["type"] == "tool_result")
    assert event["ok"] and event["ui"]["lineage"][-1]["operation"] == "forecast"
    cid = events[0]["id"]
    package = client.get(f"/api/conversations/{cid}/proof")
    with zipfile.ZipFile(io.BytesIO(package.content)) as z:
        messages = json.loads(z.read("chat.json"))["messages"]
    ui = next(t["ui"] for m in messages for t in m["meta"].get("tools", []) if t.get("ui"))
    assert ui["lineage"] == event["ui"]["lineage"]


def test_contract_enum_missing_types_and_decimal():
    from decimal import Decimal

    contract = Contract({"columns": {"id": {"type": "integer"}, "flag": {"type": "boolean"},
                                     "price": {"type": "number"}, "category": {"type": "string"},
                                     "missing": {"type": "date"}},
                         "rules": [{"column": "category", "enum": ["ok"]}]})
    assert contract.validate(["id", "flag", "price", "category"], [[1, True, Decimal("1.25"), "bad"]]) == [
        {"column": "missing", "row": None, "code": "missing"},
        {"column": "category", "row": 1, "code": "enum"}]


@pytest.mark.parametrize("definition", [None, {"columns": {}}, {"columns": {"a": {"type": "number"}},
    "rules": [{"column": "nope", "min": 1}]}, {"columns": {"a": {"type": "string"}},
    "rules": [{"column": "a", "min": 1}]}, {"columns": {"a": {"type": "number"}},
    "rules": [{"column": "a", "min": 5, "max": 1}]}])
def test_invalid_contract_definitions(definition):
    with pytest.raises(DataError):
        Contract(definition)


def test_contract_cannot_be_skipped_by_typo_or_escape(workspace):
    with pytest.raises(DataError):
        Session(workspace, ["sales.csv"], contracts={"typo.csv": "contract.json"})
    session = Session(workspace, ["sales.csv"], contracts={"sales.csv": "../outside.json"})
    try:
        with pytest.raises(PermissionError):
            session.load()
    finally:
        session.close()


def test_guardian_blocks_side_effects_even_in_select_and_explicit_approval_is_exact(workspace):
    session = Session(workspace, ["sales.csv"])
    try:
        session.load()
        session.query("CREATE SEQUENCE counter", 1, approved=True)
        with pytest.raises(DataError, match="read-only"):
            session.query("SELECT nextval('counter')", 1)
        with pytest.raises(DataError):
            session.query("DELETE FROM sales", 1, approved="true")
        with pytest.raises(DataError):
            session.query("COPY sales TO 'out.csv'", 1, approved=True)
    finally:
        session.close()


def test_explain_only_never_runs_query(workspace):
    session = Session(workspace, ["sales.csv"])
    try:
        session.load()
        plan = session.explain("SELECT error('must not execute')", 2)
        assert plan["plan"] and "LIMIT 3" in plan["sql"]
        assert session.lineage[-1]["operation"] == "explain"
    finally:
        session.close()


async def test_contract_report_is_visible_and_model_cannot_approve_sql(workspace):
    path = workspace.root / "contract.json"
    path.write_text('{"columns":{"amount":{"type":"number"}},"rules":[{"column":"amount","max":2}]}',
                    encoding="utf-8")
    tool = DataSql(workspace)
    result = await tool.run({"files": ["sales.csv"], "sql": "SELECT * FROM sales",
                             "contracts": {"sales.csv": "contract.json"}})
    assert not result.ok and len(result.data["violations"]) == 4
    assert "amount" in result.content
    result = await tool.run({"files": ["sales.csv"], "sql": "DELETE FROM sales", "approved": True})
    assert not result.ok
    result = await tool.run({"files": ["sales.csv"], "sql": "SELECT error('must not execute')", "explain_only": True})
    assert result.ok and result.data["ui"]["guardian"]["explanation"]
    result = await DataForecast(workspace).run({"files": ["sales.csv"], "sql": "SELECT * FROM sales", "horizon": 1})
    assert not result.ok


def test_rescue_quoted_csv_and_reports_header_repairs(tmp_path):
    path = tmp_path / "quoted.csv"
    path.write_text('\ufeff"name";"amount";"amount"\n"a; b";"10,5";"2"\n', encoding="utf-8")
    rescued = rescue_csv(path)
    assert rescued.columns == ["name", "amount", "amount_2"]
    assert rescued.rows == [["a; b", 10.5, 2]]
    assert next(s for s in rescued.report["steps"] if s["code"] == "header")["renamed"] == 1


def test_failed_load_cannot_expose_an_unlocked_database(workspace):
    (workspace.root / "bad.json").write_text('{"columns":{"missing":{"type":"number"}}}', encoding="utf-8")
    session = Session(workspace, ["sales.csv"], contracts={"sales.csv": "bad.json"})
    try:
        with pytest.raises(ContractViolation):
            session.load()
        with pytest.raises(DataError, match="loaded"):
            session.query("SELECT 1", 1)
    finally:
        session.close()


def test_chart_step_is_recorded(workspace):
    import asyncio

    from spike.analytics.tools import DataChart

    out = asyncio.run(DataChart(workspace).run({"files": ["sales.csv"], "sql": "SELECT day, amount FROM sales"}))
    assert out.ok and out.data["ui"]["lineage"][-1]["operation"] == "chart"
