"""Held-out evaluation files written for SPIKE (evals/data/*.jsonl). Evaluation only: never training data.

The files are written by hand for this repository, never by a distillation teacher, and removed from training by
13-gram decontamination (prepare.py `decontaminate_files`). A file starts with a header record,
{"kind": "header", "written_by": ..., "purpose": "evaluation only", ...}, and the loaders refuse a file without one.

    science_eval.jsonl   {id, category, level, topic, question, options, answer}: four-option questions
    data_eval.jsonl      {"kind": "database", id, domain, schema} records, then {"kind": "item", id, db, question,
                         gold_sql} records: each question is asked about one small database and scored by executing
                         the answer on it (sqlsandbox.py)

Every loader returns plain rows with the `prompt` the model is shown, which is also the text decontamination indexes.
"""

from __future__ import annotations

import json
from pathlib import Path

from spike_train import sqlsandbox
from spike_train.data import LETTERS, SQL_EXEC_INSTRUCTION, mcq_prompt, sql_block


def read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_header(path: Path) -> tuple[dict, list[dict]]:
    """(header, the other records) of an evaluation file; ValueError when it has no header saying it is evaluation-only."""
    records = read_records(path)
    head = records[0] if records and records[0].get("kind") == "header" else None
    if not head or head.get("purpose") != "evaluation only" or not str(head.get("written_by") or "").strip():
        raise ValueError(f"{path.name}: the first record must be a header with `written_by` and "
                         '`purpose: "evaluation only"`')
    return head, records[1:]


def science_rows(path: Path) -> list[dict]:
    """Questions with their `prompt` (the question and options with the usual answer instruction)."""
    _, records = split_header(path)
    rows = []
    for r in records:
        options = r.get("options")
        if not (isinstance(options, list) and len(options) == 4 and r.get("answer") in LETTERS[:4]
                and all(isinstance(o, str) and o.strip() for o in options) and str(r.get("question") or "").strip()):
            raise ValueError(f"{path.name}: record {r.get('id')!r} is not a four-option question with a lettered answer")
        rows.append({**r, "prompt": mcq_prompt(r["question"], options)})
    return rows


def data_rows(path: Path) -> list[dict]:
    """Items joined with their database: each row has `schema`, `question`, `gold_sql` and the `prompt`. Every gold query
    must run on its database and return rows, otherwise ValueError (a broken gold answer would mark right answers wrong)."""
    _, records = split_header(path)
    databases = {r["id"]: r for r in records if r.get("kind") == "database"}
    rows = []
    for r in (r for r in records if r.get("kind") == "item"):
        db = databases.get(r.get("db"))
        if db is None:
            raise ValueError(f"{path.name}: item {r.get('id')!r} names an unknown database {r.get('db')!r}")
        gold = sqlsandbox.run(db["schema"], r["gold_sql"])
        if not gold.ok or not gold.rows:
            raise ValueError(f"{path.name}: item {r['id']!r}: the gold query "
                             + (f"fails ({gold.stage}: {gold.error})" if not gold.ok else "returns no rows"))
        rows.append({**r, "schema": db["schema"], "domain": db.get("domain", ""),
                     "prompt": f"{sql_block(db['schema'], r['question'])}\n\n{SQL_EXEC_INSTRUCTION}"})
    return rows


FORMATS = {"science_local": science_rows, "sql_exec": data_rows}


def prompts(path: Path) -> list[str]:
    """The prompts of any evaluation file, for decontamination: a `prompt` field (the pairwise marketing prompts), or
    the rendered question of a science or data file."""
    records = read_records(path)
    if any(r.get("kind") == "item" for r in records):
        return [r["prompt"] for r in data_rows(path)]
    if any("options" in r for r in records):
        return [r["prompt"] for r in science_rows(path)]
    return [r["prompt"] for r in records if "prompt" in r]
