"""SQL Guardian: one parsed statement, read-only transactions, bounded previews and a plain EXPLAIN.

Statement classification uses DuckDB's parser, not keyword matching. The database transaction is also read-only,
so side effects hidden inside a SELECT cannot bypass the default. Approval is a trusted Python caller argument,
never a field in a model tool schema. Even approved statements retain the session's external-access lockdown.
"""

from __future__ import annotations

import json
from typing import Any

from spike.analytics.engine import DataError

# Only writes to the disposable loaded tables are approvable; settings, extensions, COPY and ATTACH stay denied.
WRITES = {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}
ACTIONS = {
    "SCAN": ("Read loaded rows", "Leer filas cargadas"),
    "FILTER": ("Keep matching rows", "Conservar filas coincidentes"),
    "GROUP": ("Aggregate groups", "Agregar grupos"),
    "AGGREGATE": ("Compute aggregates", "Calcular agregados"),
    "ORDER": ("Sort rows", "Ordenar filas"),
    "TOP_N": ("Sort and keep the first rows", "Ordenar y conservar las primeras filas"),
    "JOIN": ("Join tables", "Unir tablas"),
    "PROJECTION": ("Select output columns", "Seleccionar columnas de salida"),
    "LIMIT": ("Cap returned rows", "Limitar filas devueltas"),
}


def statement(con: Any, sql: str, *, approved: bool = False) -> str:
    """Require one SELECT by default; explicitly approved DML/DDL can modify in-memory tables only."""
    statements = con.extract_statements(sql)
    if len(statements) != 1:
        raise DataError("SQL error: Guardian requires one statement")
    kind = str(statements[0].type).rsplit(".", 1)[-1]
    if kind != "SELECT" and not (approved is True and kind in WRITES):
        raise DataError("SQL error: Guardian requires explicit approval for table writes; other statements are refused")
    return kind


def bounded(sql: str, limit: int) -> str:
    """Fetch one sentinel beyond the visible limit to report truncation, with an actual SQL LIMIT."""
    if type(limit) is not int or not 1 <= limit <= 10_000:
        raise DataError("preview limit must be an integer from 1 to 10000")
    return f"SELECT * FROM ({sql.strip().rstrip(';')}) AS spike_preview LIMIT {limit + 1}"


def explain(con: Any, sql: str) -> dict[str, Any]:
    """EXPLAIN never executes the query; traverse the physical plan without an external model."""
    plan = json.loads(con.execute("EXPLAIN (FORMAT JSON) " + sql).fetchall()[0][1])
    labels: dict[str, list[str]] = {"en": [], "es": []}

    def visit(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            visit(node.get("children", []))
            name = node["name"].strip()
            action = next((value for key, value in ACTIONS.items() if key in name),
                          ("Apply operator", "Aplicar operador"))
            for lang, text in zip(("en", "es"), action, strict=True):
                labels[lang].append(f"{text} ({name})")

    visit(plan)
    return {"plan": plan, "explanation": {lang: "; ".join(parts) + "." for lang, parts in labels.items()}}
