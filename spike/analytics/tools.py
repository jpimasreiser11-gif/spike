"""Spike Data's tools: describe data files, query them with SQL, chart a query and run Python on them. Results
show in the chat with the code that produced them; the numbers are computed by DuckDB or pandas, not the model."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from spike.analytics.charts import MARKS, build_chart
from spike.analytics.contracts import ContractViolation
from spike.analytics.engine import FORMATS, DataError, Result, describe, files_arg, ident, run_query
from spike.analytics.forecast import backtest
from spike.tools.base import Tool, ToolResult
from spike.tools.builtin import PythonRunner, Workspace
from spike.tools.sandbox import Sandbox

MAX_ROWS = 200  # rows a table keeps for the chat; the model reads the first 50
CHART_ROWS = 5000
FILES = {"type": "array", "items": {"type": "string"},
         "description": f"data files in the workspace ({', '.join(sorted(set(FORMATS)))}); each becomes a table "
                        "named after the file, e.g. ventas-2024.csv → ventas_2024"}

OPTIONS = {
    "contracts": {"type": "object", "additionalProperties": {"type": "string"},
                  "description": "data filename -> JSON/YAML contract path inside the workspace"},
    "locale": {"type": "string", "enum": ["es", "en"],
               "description": "CSV date convention: es day-first (default), en month-first"},
}


def data_options(args: dict[str, Any]) -> dict[str, Any]:
    contracts = args.get("contracts", {})
    if not isinstance(contracts, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                               for k, v in contracts.items()):
        raise DataError("contracts must map data filenames to workspace contract paths")
    locale = args.get("locale", "es")
    if locale not in ("es", "en"):
        raise DataError("locale must be es or en")
    return {"contracts": contracts, "locale": locale}


def evidence(result: Result) -> dict[str, Any]:
    return {"lineage": result.lineage, "guardian": result.guardian}


def evidence_text(result: Result) -> str:
    return "\n\nEvidence / Evidencia:\n" + json.dumps(evidence(result), ensure_ascii=False)


def tables_text(result: Result) -> str:
    return "\n".join(f"- {t.name}{f' (sheet {t.sheet})' if t.sheet else ''} from {t.file}: {t.rows} rows; "
                     + ", ".join(f"{ident(n)} {ty}" for n, ty in t.columns) for t in result.tables)


class _DataTool(Tool):
    risk = "read"
    default_policy = "allow"  # reads the user's files and computes; nothing leaves the computer

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            return await self.act(args)
        except ContractViolation as exc:
            text = json.dumps(exc.violations, ensure_ascii=False)
            return ToolResult(ok=False, content=f"Data contract / Contrato de datos: {text}", private=[text],
                              data={"violations": exc.violations})
        except (DataError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")

    async def act(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class DataDescribe(_DataTool):
    name = "data_describe"
    description = ("Look at data files before querying them: each table's name, columns and types, row count, "
                   "per-column statistics (min, max, mean, quartiles, distinct values, % nulls) and the first rows.")
    parameters = {"type": "object", "properties": {"files": FILES, **OPTIONS}, "required": ["files"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        files = files_arg(args.get("files") or args.get("path"))
        found = await asyncio.to_thread(describe, self.workspace, files, **data_options(args))
        parts, ui = [], []
        for table, summary, sample in found:
            parts.append(f"## {table.name} ({table.file}{f', sheet {table.sheet}' if table.sheet else ''}): "
                         f"{table.rows} rows\nColumns: " + ", ".join(f"{ident(n)} {t}" for n, t in table.columns)
                         + f"\n\nStatistics:\n{summary.text(60)}\n\nFirst rows:\n{sample.text()}" + evidence_text(sample))
            ui.append({"kind": "data_table", "title": table.name, "sql": f"SUMMARIZE {ident(table.name)}",
                       "tables": [table.to_dict()], "columns": summary.columns, "types": summary.types,
                       "rows": summary.rows, "truncated": summary.truncated, **evidence(sample)})
        text = "\n\n".join(parts)
        return ToolResult(ok=True, content=text, private=[text], data={"ui": {"kind": "data_tables", "items": ui}})


class DataSql(_DataTool):
    name = "data_sql"
    description = ("Answer a question about data files with one DuckDB SQL query (GROUP BY, window functions, "
                   "date_trunc, strftime, percentile_cont…). The files are loaded as tables; the query cannot "
                   "read anything else. Use the numbers it returns; do not compute them yourself.")
    parameters = {"type": "object", "properties": {
        "sql": {"type": "string", "description": "DuckDB SQL over the tables, e.g. SELECT region, sum(sales) FROM "
                                                 "ventas_2024 GROUP BY region ORDER BY 2 DESC"},
        "files": FILES, **OPTIONS,
        "explain_only": {"type": "boolean", "description": "show EXPLAIN without executing the query"},
        "title": {"type": "string", "description": "a short title for the result table"}},
        "required": ["sql", "files"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        sql, files = str(args.get("sql") or ""), files_arg(args.get("files"))
        result = await asyncio.to_thread(run_query, self.workspace, files, sql, MAX_ROWS,
                                         explain_only=args.get("explain_only") is True, **data_options(args))
        text = f"Tables:\n{tables_text(result)}\n\nResult:\n{result.text()}"
        ui = {"kind": "data_table", "title": str(args.get("title") or "")[:120], "sql": sql,
              "tables": [t.to_dict() for t in result.tables], "columns": result.columns, "types": result.types,
              "rows": result.rows, "truncated": result.truncated, **evidence(result)}
        text += evidence_text(result)
        return ToolResult(ok=True, content=text, private=[text], data={"ui": ui})


class DataChart(_DataTool):
    name = "data_chart"
    description = ("Draw a chart of a DuckDB SQL query over data files: bar, line, area, point (scatter) or arc "
                   "(pie). The query should return the label column and one or more numeric columns, already "
                   f"aggregated (at most {CHART_ROWS} rows). The user sees the chart, its data and the SQL.")
    parameters = {"type": "object", "properties": {
        "sql": DataSql.parameters["properties"]["sql"], "files": FILES, **OPTIONS,
        "mark": {"type": "string", "enum": list(MARKS)},
        "x": {"type": "string", "description": "column for the horizontal axis (or the pie's slices); default: first"},
        "y": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
              "description": "numeric column(s) for the vertical axis; several draw one series each"},
        "color": {"type": "string", "description": "optional column that splits the data into series"},
        "title": {"type": "string"},
        "x_type": {"type": "string", "enum": ["quantitative", "temporal", "nominal", "ordinal"]}},
        "required": ["sql", "files"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        sql, files = str(args.get("sql") or ""), files_arg(args.get("files"))
        result = await asyncio.to_thread(run_query, self.workspace, files, sql, CHART_ROWS, **data_options(args))
        title = str(args.get("title") or "")
        spec = build_chart(result, str(args.get("mark") or "bar"), args.get("x"), args.get("y"),
                           args.get("color"), title, args.get("x_type"))
        result.lineage.append({"step": len(result.lineage) + 1, "operation": "chart", "mark": spec["mark"]["type"],
                               "encoding": spec["encoding"]})
        text = (f"Chart drawn for the user ({spec['mark']['type']}).\nTables:\n{tables_text(result)}\n\n"
                f"Data:\n{result.text()}")
        ui = {"kind": "chart", "title": title[:120], "sql": sql, "spec": spec,
              "tables": [t.to_dict() for t in result.tables], "columns": result.columns, "types": result.types,
              "rows": result.rows[:MAX_ROWS], "truncated": len(result.rows) > MAX_ROWS, **evidence(result)}
        text += evidence_text(result)
        return ToolResult(ok=True, content=text, private=[text], data={"ui": ui})


class DataForecast(_DataTool):
    name = "data_forecast"
    description = ("Forecast an ordered, equally spaced numeric series from a one-column SQL query. "
                   "Compare naive, seasonal naive, drift, SES and Holt using rolling-origin MAE; show every score. "
                   "Use ORDER BY time, aggregate to a regular frequency and resolve missing periods first. "
                   "Smoothing parameters are fixed at 0.5; these are baselines, not measured future accuracy.")
    parameters = {"type": "object", "properties": {
        "sql": DataSql.parameters["properties"]["sql"], "files": FILES, **OPTIONS,
        "horizon": {"type": "integer", "minimum": 1, "maximum": 100},
        "season": {"type": "integer", "minimum": 1}, "title": {"type": "string"}},
        "required": ["sql", "files", "horizon"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        sql, files = str(args.get("sql") or ""), files_arg(args.get("files"))
        result = await asyncio.to_thread(run_query, self.workspace, files, sql, 10_000, **data_options(args))
        if len(result.columns) != 1 or result.truncated:
            raise DataError("forecast needs one numeric column, ordered in time, at most 10000 observations")
        comparison = await asyncio.to_thread(backtest, [r[0] for r in result.rows], args.get("horizon"),
                                             season=args.get("season", 1))
        lineage = [*result.lineage, {"step": len(result.lineage) + 1, "operation": "forecast", **comparison}]
        scores = "Method / Método | MAE | Folds / Ventanas\n" + "\n".join(
            f"{r['method']} | {r['mae']:.12g} | {r['folds']}" for r in comparison["backtest"])
        ui = {"kind": "data_table", "title": str(args.get("title") or "Forecast / Previsión")[:120],
              "sql": sql, "tables": [t.to_dict() for t in result.tables],
              "columns": ["Step / Paso", result.columns[0]], "types": ["INTEGER", "DOUBLE"],
              "rows": [[i, v] for i, v in enumerate(comparison["forecast"], 1)], "truncated": False,
              "lineage": lineage, "guardian": result.guardian, "backtest": comparison["backtest"],
              "forecast": {k: v for k, v in comparison.items() if k not in ("forecast", "backtest")}}
        text = f"{comparison['method']}\n{scores}\n\nStep / Paso | Forecast / Previsión\n" + "\n".join(
            f"{i} | {v:.12g}" for i, v in enumerate(comparison["forecast"], 1))
        text += "\n\nEvidence / Evidencia:\n" + json.dumps({"lineage": lineage}, ensure_ascii=False)
        return ToolResult(ok=True, content=text, private=[text], data={"ui": ui})


class DataPython(PythonRunner):
    name = "data_python"
    description = ("Run a Python 3 script on data files when SQL is not enough (pandas and duckdb are available). "
                   "The files are copied into ./data/ of a temporary folder, so the originals cannot change; "
                   "print() the results. Same limits as python (20 s CPU, 1 GB memory on Linux).")
    parameters = {"type": "object", "properties": {
        "code": {"type": "string", "description": "e.g. import pandas as pd; df = pd.read_csv('data/ventas.csv'); "
                                                  "print(df.groupby('region')['sales'].sum())"},
        "files": {**FILES, "description": "workspace files to copy into ./data/ (keeping their names)"}},
        "required": ["code"]}

    def __init__(self, workspace: Workspace, sandbox: Sandbox | None = None):
        super().__init__(memory_mb=1024, sandbox=sandbox)
        self.workspace = workspace

    def prepare(self, folder: Path, args: dict[str, Any]) -> None:
        if not args.get("files"):
            return
        data = folder / "data"
        data.mkdir()
        for given in files_arg(args.get("files")):
            source = self.workspace.resolve(given)
            if not source.is_file():
                raise DataError(f"'{given}' is not a file in the workspace")
            shutil.copyfile(source, data / source.name)

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            result = await super().run(args)
        except (DataError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        names = [Path(f).name for f in files_arg(args["files"])] if args.get("files") else []
        ui = {"kind": "code_run", "language": "python", "code": str(args.get("code", "")), "output": result.content,
              "files": names, "returncode": result.data.get("returncode")}
        return ToolResult(ok=result.ok, content=result.content, private=[result.content] if names else [],
                          data={**result.data, "ui": ui})


def analytics_tools(workspace: Workspace, sandbox: Sandbox | None = None) -> list[Tool]:
    return [DataDescribe(workspace), DataSql(workspace), DataChart(workspace), DataForecast(workspace), DataPython(workspace, sandbox)]
