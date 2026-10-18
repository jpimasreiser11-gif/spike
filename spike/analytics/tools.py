"""Spike Data's tools: describe data files, query them with SQL, chart a query and run Python on them. Results
show in the chat with the code that produced them; the numbers are computed by DuckDB or pandas, not the model."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from spike.analytics.charts import MARKS, build_chart
from spike.analytics.engine import FORMATS, DataError, Result, describe, files_arg, ident, run_query
from spike.tools.base import Tool, ToolResult
from spike.tools.builtin import PythonRunner, Workspace

MAX_ROWS = 200  # rows a table keeps for the chat; the model reads the first 50
CHART_ROWS = 5000
FILES = {"type": "array", "items": {"type": "string"},
         "description": f"data files in the workspace ({', '.join(sorted(set(FORMATS)))}); each becomes a table "
                        "named after the file, e.g. ventas-2024.csv → ventas_2024"}


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
        except (DataError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")

    async def act(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class DataDescribe(_DataTool):
    name = "data_describe"
    description = ("Look at data files before querying them: each table's name, columns and types, row count, "
                   "per-column statistics (min, max, mean, quartiles, distinct values, % nulls) and the first rows.")
    parameters = {"type": "object", "properties": {"files": FILES}, "required": ["files"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        files = files_arg(args.get("files") or args.get("path"))
        found = await asyncio.to_thread(describe, self.workspace, files)
        parts, ui = [], []
        for table, summary, sample in found:
            parts.append(f"## {table.name} ({table.file}{f', sheet {table.sheet}' if table.sheet else ''}): "
                         f"{table.rows} rows\nColumns: " + ", ".join(f"{ident(n)} {t}" for n, t in table.columns)
                         + f"\n\nStatistics:\n{summary.text(60)}\n\nFirst rows:\n{sample.text()}")
            ui.append({"kind": "data_table", "title": table.name, "sql": f"SUMMARIZE {ident(table.name)}",
                       "tables": [table.to_dict()], "columns": summary.columns, "types": summary.types,
                       "rows": summary.rows, "truncated": summary.truncated})
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
        "files": FILES, "title": {"type": "string", "description": "a short title for the result table"}},
        "required": ["sql", "files"]}

    async def act(self, args: dict[str, Any]) -> ToolResult:
        sql, files = str(args.get("sql") or ""), files_arg(args.get("files"))
        result = await asyncio.to_thread(run_query, self.workspace, files, sql, MAX_ROWS)
        text = f"Tables:\n{tables_text(result)}\n\nResult:\n{result.text()}"
        ui = {"kind": "data_table", "title": str(args.get("title") or "")[:120], "sql": sql,
              "tables": [t.to_dict() for t in result.tables], "columns": result.columns, "types": result.types,
              "rows": result.rows, "truncated": result.truncated}
        return ToolResult(ok=True, content=text, private=[text], data={"ui": ui})


class DataChart(_DataTool):
    name = "data_chart"
    description = ("Draw a chart of a DuckDB SQL query over data files: bar, line, area, point (scatter) or arc "
                   "(pie). The query should return the label column and one or more numeric columns, already "
                   f"aggregated (at most {CHART_ROWS} rows). The user sees the chart, its data and the SQL.")
    parameters = {"type": "object", "properties": {
        "sql": DataSql.parameters["properties"]["sql"], "files": FILES,
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
        result = await asyncio.to_thread(run_query, self.workspace, files, sql, CHART_ROWS)
        title = str(args.get("title") or "")
        spec = build_chart(result, str(args.get("mark") or "bar"), args.get("x"), args.get("y"),
                           args.get("color"), title, args.get("x_type"))
        text = (f"Chart drawn for the user ({spec['mark']['type']}).\nTables:\n{tables_text(result)}\n\n"
                f"Data:\n{result.text()}")
        ui = {"kind": "chart", "title": title[:120], "sql": sql, "spec": spec,
              "tables": [t.to_dict() for t in result.tables], "columns": result.columns, "types": result.types,
              "rows": result.rows[:MAX_ROWS], "truncated": len(result.rows) > MAX_ROWS}
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

    def __init__(self, workspace: Workspace):
        super().__init__(memory_mb=1024)
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


def analytics_tools(workspace: Workspace) -> list[Tool]:
    return [DataDescribe(workspace), DataSql(workspace), DataChart(workspace), DataPython(workspace)]
