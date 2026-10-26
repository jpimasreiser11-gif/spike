"""Local JSON/YAML contracts: required columns, logical types/nullability and per-column quality rules.

Contract definitions are validated before data is examined. Rules support min/max, enum and uniqueness; a
violation is a machine-readable code, column index/name and 1-based data row, never the cell's private value.
A failed contract aborts loading; callers can inspect ContractViolation.violations to correct the input.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from spike.analytics.engine import DataError

SCHEMA = {
    "type": "object", "required": ["columns"], "additionalProperties": False,
    "properties": {
        "columns": {"type": "object", "minProperties": 1, "additionalProperties": {
            "type": "object", "required": ["type"], "additionalProperties": False,
            "properties": {"type": {"enum": ["string", "integer", "number", "boolean", "date", "datetime"]},
                           "nullable": {"type": "boolean"}}}},
        "rules": {"type": "array", "items": {
            "type": "object", "required": ["column"], "minProperties": 2, "additionalProperties": False,
            "properties": {"column": {"type": "string"}, "min": {"type": "number"},
                           "max": {"type": "number"}, "unique": {"type": "boolean"},
                           "enum": {"type": "array", "minItems": 1, "items": {"type": [
                               "string", "number", "boolean", "null"]}}}}},
    },
}


class ContractViolation(DataError):
    def __init__(self, violations: list[dict[str, Any]]):
        self.violations = violations
        super().__init__(f"data contract: {len(violations)} violations")


@dataclass
class Contract:
    definition: dict[str, Any]

    def __post_init__(self) -> None:
        try:
            jsonschema.Draft202012Validator(SCHEMA).validate(self.definition)
        except jsonschema.ValidationError as exc:
            raise DataError(f"invalid data contract at {list(exc.absolute_path)}") from exc
        for rule in self.definition.get("rules", []):
            column = self.definition["columns"].get(rule["column"])
            if column is None:
                raise DataError("contract rule refers to an undeclared column")
            if any(k in rule for k in ("min", "max")) and column["type"] not in ("integer", "number"):
                raise DataError("contract min/max rules require a numeric column")
            if rule.get("min", -math.inf) > rule.get("max", math.inf):
                raise DataError("contract min must not exceed max")
            if any(not math.isfinite(rule[k]) for k in ("min", "max") if k in rule):
                raise DataError("contract bounds must be finite")

    @classmethod
    def load(cls, path: Path) -> Contract:
        """Read a definition as UTF-8; YAML uses safe_load and JSON never resolves external references."""
        try:
            text = path.read_text(encoding="utf-8")
            definition = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
            return cls(definition)
        except (ValueError, yaml.YAMLError, RecursionError) as exc:
            raise DataError("invalid JSON/YAML data contract") from exc

    def validate(self, columns: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
        """Return all violations; extra data columns are allowed and nulls skip value rules."""
        out = []
        types = {"string": lambda v: isinstance(v, str), "integer": lambda v: type(v) is int,
                 "number": lambda v: (type(v) in (int, float) and math.isfinite(v)) or (
                     isinstance(v, Decimal) and v.is_finite()),
                 "boolean": lambda v: type(v) is bool, "date": lambda v: type(v) is dt.date,
                 "datetime": lambda v: isinstance(v, dt.datetime)}
        for name, spec in self.definition["columns"].items():
            if name not in columns:
                out.append({"column": name, "row": None, "code": "missing"})
                continue
            index = columns.index(name)
            for row_no, row in enumerate(rows, 1):
                value = row[index]
                code = ("nullable" if not spec.get("nullable", True) else None) if value is None else (
                    "type" if not types[spec["type"]](value) else None)
                if code:
                    out.append({"column": name, "row": row_no, "code": code})
        for rule in self.definition.get("rules", []):
            name, seen = rule["column"], set()
            if name not in columns:
                continue
            for row_no, row in enumerate(rows, 1):
                value = row[columns.index(name)]
                if value is None:
                    continue
                codes = []
                for bound, op in (("min", lambda a, b: a < b), ("max", lambda a, b: a > b)):
                    if bound in rule and (type(value) not in (int, float, Decimal) or op(value, rule[bound])):
                        codes.append(bound)
                if "enum" in rule and value not in rule["enum"]:
                    codes.append("enum")
                key = (type(value).__name__, str(value))
                if rule.get("unique") and key in seen:
                    codes.append("unique")
                seen.add(key)
                out.extend({"column": name, "row": row_no, "code": code} for code in codes)
        return out
