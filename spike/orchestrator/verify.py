"""The verifier of a multi-step plan (Collective).

After the team's subtasks run, one more model call checks each result against its instruction, the user's request
and, in Forge, the acceptance criteria the user approved. A result with a concrete problem goes back to its
specialist with the verifier's note (and the subtasks that used it run again too), at most MAX_ROUNDS times; the
integrator then merges the results. Whether a deliverable file was saved is checked by SPIKE itself, not by the
model, and a missing one always sends its subtask back; the verifier reads the saved text files themselves (clipped),
not only their authors' summaries. SPIKE also checks the files' format with a program (Python compiles and uses no
name nothing defines, JSON parses, CSV rows have the same number of columns, text is not empty) and imports each
Python file through the `python` tool; a failure is shown to the verifier as a fact and sends its subtask back with
the error, so a typo the verifier would read past does not get through. When the verifier's answer is not valid
JSON nothing is sent back and the run says the results could not be verified.
"""

from __future__ import annotations

import ast
import builtins
import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spike.orchestrator.planner import Subtask, extract_json

MAX_ROUNDS = 2  # times work can be sent back
RESULT_CHARS = 3000  # of each result shown to the verifier
MIN_FIX = 8  # a "not ok" without a usable note is not sent back: there would be nothing to fix
FILE_CHARS = 2000  # of each saved text file shown to the verifier
FILES_CHARS = 8000  # of all of them
TEXT_FILES = {".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".py", ".js", ".ts", ".html", ".css", ".svg", ".xml",
              ".yaml", ".yml", ".toml", ".sql", ".sh"}
CHECK_BYTES = 1_000_000  # a saved file larger than this is not checked by program
MODULE_NAMES = {"__name__", "__file__", "__doc__", "__package__", "__spec__", "__loader__", "__builtins__", "__path__",
                "__cached__", "__annotations__", "__class__", "__module__", "__qualname__"}
DYNAMIC_NAMES = {"globals", "vars", "exec", "eval"}  # a file that uses them may define names we cannot see
NOT_JUDGED = ("EOFError", "ModuleNotFoundError")  # waiting for a keyboard, a package that is not installed here
# What the `python` tool runs for a saved Python file: the file is imported as a module (its __name__ is not
# "__main__", so the block that starts the program, reads input() or serves does not run) in a temporary copy of the
# saved files, with nothing to read from the keyboard.
RUN_CODE = """\
import os, runpy, shutil, sys
sys.stdin = open(os.devnull)
for name in {files!r}:
    if os.path.isfile(os.path.join({root!r}, name)):
        os.makedirs(os.path.dirname(name) or ".", exist_ok=True)
        shutil.copyfile(os.path.join({root!r}, name), name)
sys.path.insert(0, os.getcwd())
runpy.run_path({target!r}, run_name="spike_check")
"""

VERIFIER_PROMPT = (
    "You are the checker of SPIKE, a team of specialist models. Check each subtask result against its instruction "
    "and the user's request{criteria}. Mark a result not ok only for a concrete problem its author can fix: a part "
    "of the instruction that is missing, a calculation or fact that is wrong (say which and why), a contradiction "
    "with another result, or a file it had to save that is missing. Style is not a problem. When the saved files "
    "are shown, judge the files themselves. Do not redo calculations in your head: call a number wrong only when "
    "you show the exact calculation that gives another value; a value you only estimate is never a reason. For each "
    "problem write in `fix` exactly what to change. Reply with JSON only."
)


@dataclass
class Verdict:
    method: str  # "llm" | "unavailable"
    returned: dict[str, str] = field(default_factory=dict)  # subtask id -> what to fix
    criteria: list[dict[str, Any]] = field(default_factory=list)  # Forge: {"text", "ok" (None: not checked), "note"}
    note: str = ""

    def event(self, round_: int, checks: list[dict[str, Any]]) -> dict[str, Any]:
        return {"type": "verify", "round": round_, "method": self.method, "note": self.note,
                "returned": [{"subtask": k, "fix": v} for k, v in self.returned.items()],
                "criteria": self.criteria, "checks": checks}


def verify_schema(ids: list[str], n_criteria: int) -> dict[str, Any]:
    props: dict[str, Any] = {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string", "enum": ids}, "ok": {"type": "boolean"}, "fix": {"type": "string"}},
        "required": ["id", "ok", "fix"], "additionalProperties": False}}}
    if n_criteria:
        props["criteria"] = {"type": "array", "items": {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1, "maximum": n_criteria}, "ok": {"type": "boolean"},
                           "note": {"type": "string"}},
            "required": ["n", "ok", "note"], "additionalProperties": False}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def verifier_prompt(criteria: list[str]) -> str:
    extra = (" and the acceptance criteria; for each criterion say in `criteria` whether the results meet it"
             if criteria else "")
    shape = ('{"results": [{"id": "t1", "ok": true, "fix": ""}]' +
             (', "criteria": [{"n": 1, "ok": true, "note": ""}]}' if criteria else "}"))
    return VERIFIER_PROMPT.format(criteria=extra) + "\n" + shape


def verify_message(user_text: str, subtasks: list[Subtask], results: dict[str, str], names: dict[str, str],
                   criteria: list[str], checks: list[dict[str, Any]], saved: list[dict[str, Any]] | None = None) -> str:
    parts = [f"# User request\n{user_text}"]
    if criteria:
        parts.append("# Acceptance criteria\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, 1)))
    for t in subtasks:
        text = results.get(t.id, "")
        clipped = text[:RESULT_CHARS] + (" […]" if len(text) > RESULT_CHARS else "")
        files = f"\nFiles it had to save: {', '.join(t.deliverables)}" if t.deliverables else ""
        parts.append(f"## {t.id} · {names.get(t.specialist, t.specialist)} · {t.role}\nInstruction: "
                     f"{t.instruction}{files}\nResult:\n{clipped}")
    if checks:
        parts.append("# Files checked by SPIKE\n" + "\n".join(
            f"- {c['path']} ({c['subtask']}): {'saved, ' + str(c['bytes']) + ' bytes' if c['ok'] else 'NOT FOUND'}"
            for c in checks))
    ran = [c for c in checks if c.get("program")]
    if ran:
        parts.append("# Checks SPIKE ran on the saved files (by program, not by a model)\n" + "\n".join(
            f"- {c['path']} ({c['subtask']}), "
            f"{'passed' if c['program']['ok'] else 'FAILED' if c['program']['ok'] is False else 'not fully checked'}: "
            f"{c['program']['note']}" for c in ran))
    for f in saved or []:
        parts.append(f"## Saved file {f['path']} ({f['subtask']}){', first part' if f['clipped'] else ''}\n"
                     f"<<<\n{f['text']}\n>>>")
    return "\n\n".join(parts)


def parse_verdict(text: str, ids: list[str], criteria: list[str]) -> Verdict | None:
    obj = extract_json(text)
    if not obj or not isinstance(obj.get("results"), list):
        return None
    returned: dict[str, str] = {}
    for row in obj["results"]:
        if not isinstance(row, dict) or row.get("id") not in ids:
            continue
        fix = str(row.get("fix") or "").strip()
        if row.get("ok") is False and len(fix) >= MIN_FIX:
            returned[str(row["id"])] = fix[:1000]
    judged: dict[int, dict[str, Any]] = {}
    for row in obj.get("criteria") or []:
        if isinstance(row, dict) and isinstance(row.get("n"), int) and 1 <= row["n"] <= len(criteria) \
                and isinstance(row.get("ok"), bool):
            judged[row["n"]] = {"ok": row["ok"], "note": str(row.get("note") or "")[:500]}
    rows = [{"text": c, **judged.get(i, {"ok": None, "note": ""})} for i, c in enumerate(criteria, 1)]
    return Verdict(method="llm", returned=returned, criteria=rows)


def file_checks(subtasks: list[Subtask], root: Path | None) -> list[dict[str, Any]]:
    """Whether each deliverable was saved (and is not empty) in the folder the file tools write to."""
    if root is None:
        return []
    out = []
    for t in subtasks:
        for path in t.deliverables:
            target = (root / path).resolve()
            size = target.stat().st_size if target.is_file() and root in target.parents else 0
            out.append({"subtask": t.id, "path": path, "ok": size > 0, "bytes": size})
    return out


def saved_texts(checks: list[dict[str, Any]], root: Path | None) -> list[dict[str, Any]]:
    """The saved text deliverables, clipped, for the verifier to read; binary files (docx, xlsx...) are left out."""
    out, left = [], FILES_CHARS
    for c in checks:
        if root is None or not c["ok"] or Path(c["path"]).suffix.lower() not in TEXT_FILES or left <= 0:
            continue
        with (root / c["path"]).open(encoding="utf-8", errors="replace") as fh:
            text = fh.read(min(FILE_CHARS, left) + 1)
        clipped = len(text) > min(FILE_CHARS, left)
        text = text[:min(FILE_CHARS, left)]
        left -= len(text)
        out.append({"subtask": c["subtask"], "path": c["path"], "text": text, "clipped": clipped})
    return out


def dependents(subtasks: list[Subtask], ids: set[str]) -> set[str]:
    """These subtasks and every subtask that used their results, directly or not."""
    out = set(ids)
    changed = True
    while changed:
        changed = False
        for t in subtasks:
            if t.id not in out and any(d in out for d in t.depends_on):
                out.add(t.id)
                changed = True
    return out


# ---------------------------------------------------------------- checks by program
def source_line(text: str, line: int | None) -> str:
    lines = text.splitlines()
    return f": `{lines[line - 1].strip()[:120]}`" if line and 0 < line <= len(lines) else ""


def undefined_names(tree: ast.AST) -> list[ast.Name]:
    """The first read of each name that nothing in the file binds, in any scope, and that is not a builtin. Scopes
    are ignored on purpose: a name bound anywhere is never flagged, so valid code is never sent back, and a typo
    that happens to equal a name bound elsewhere is missed."""
    bound = set(dir(builtins)) | MODULE_NAMES
    reads: list[ast.Name] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                reads.append(node)
            else:
                bound.add(node.id)
        elif isinstance(node, ast.alias):
            if node.name == "*":
                return []  # `from x import *` brings names we cannot see
            bound.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            bound.update(node.names)
        else:  # def, class, `except ... as`, match captures, type parameters
            bound.update(v for a in ("name", "rest") if isinstance(v := getattr(node, a, None), str))
    if any(n.id in DYNAMIC_NAMES for n in reads):
        return []
    first = {n.id: n for n in sorted(reads, key=lambda n: (n.lineno, n.col_offset)) if n.id not in bound}
    return list(first.values())


def python_problem(text: str, path: str) -> str:
    """Why a Python file cannot work, found without running it; '' when nothing is wrong. A typo inside a function
    only fails when the function is called, which importing the file never does, so names are checked here."""
    try:
        tree = ast.parse(text, path)
        compile(tree, path, "exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        line = getattr(exc, "lineno", None)
        return (f"does not compile: {exc.__class__.__name__}: {getattr(exc, 'msg', None) or exc}"
                + (f" at line {line}{source_line(text, line)}" if line else ""))
    names = undefined_names(tree)[:3]
    return "; ".join(f"would raise NameError: name '{n.id}' is not defined at line {n.lineno}"
                     f"{source_line(text, n.lineno)}" for n in names)


def csv_problem(text: str, delimiter: str) -> str:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    width = 0
    try:
        for row in reader:
            if row and not width:
                width = len(row)
            elif row and len(row) != width:
                return f"has {len(row)} columns on line {reader.line_num} but the header has {width}"
    except csv.Error as exc:
        return f"is not valid CSV: {exc} (line {reader.line_num})"
    return ""


def format_check(path: str, text: str) -> dict[str, Any]:
    """{"ok", "note"} for one saved text file: its note is a phrase that follows the path."""
    suffix = Path(path).suffix.lower()
    problem, passed = "", "has content"
    if not text.strip():
        problem = "has no content"
    elif suffix == ".py":
        problem, passed = python_problem(text, path), "compiles, uses no name that is not defined"
    elif suffix == ".json":
        try:
            json.loads(text)
        except (ValueError, RecursionError) as exc:
            problem = f"is not valid JSON: {exc}"
        passed = "is valid JSON"
    elif suffix in (".csv", ".tsv"):
        problem, passed = csv_problem(text, "\t" if suffix == ".tsv" else ","), "is valid CSV, the same columns in every row"
    return {"ok": not problem, "note": problem or passed}


def check_files(checks: list[dict[str, Any]], root: Path | None) -> None:
    """Give each saved text file a `program` entry: SPIKE's own check of its format (a Python file also gets
    its import run, see `run_outcome`). Nothing here runs the files."""
    for c in checks:
        if root is None or not c["ok"] or c["bytes"] > CHECK_BYTES or Path(c["path"]).suffix.lower() not in TEXT_FILES:
            continue
        text = (root / c["path"]).read_text(encoding="utf-8", errors="replace")
        c["program"] = format_check(c["path"], text)


def run_code(root: Path, files: list[str], target: str) -> str:
    return RUN_CODE.format(root=str(root), files=files, target=target)


def run_outcome(path: str, files: list[str], content: str, ok: bool, static: str) -> dict[str, Any]:
    """The `program` entry for a Python file after the `python` tool imported it: passed, failed with the
    traceback's last lines, or not judged (it could not run, ran out of time, waits for a keyboard or needs a
    package that is not installed here: none of these sends work back)."""
    if ok:
        return {"ok": True, "note": f"{static}, imports without an error"}
    parts = content.rsplit("Traceback (most recent call last):", 1)
    if len(parts) == 1:
        why = re.sub(r"^error: ", "", content.strip().splitlines()[0] if content.strip() else "no output")
        return {"ok": None, "note": f"{static}; not imported: {why[:200]}"}
    lines = parts[1].strip("\n").splitlines()
    last = lines[-1].strip()
    if last.startswith(NOT_JUDGED):
        return {"ok": None, "note": f"{static}; not imported to the end: {last[:200]}"}
    where = ""
    for i, line in enumerate(lines):  # the innermost frame in the saved files (not runpy's or the stdlib's)
        frame = re.match(r'\s*File "(.+)", line (\d+)', line)
        if frame and Path(frame[1]).name in {Path(f).name for f in files}:
            src = lines[i + 1].strip() if i + 2 < len(lines) and not lines[i + 1].lstrip().startswith("File ") else ""
            src = "" if set(src) <= set("^~ ") else f": `{src[:120]}`"  # a caret line is not source
            of = "" if Path(frame[1]).name == Path(path).name else f" of {Path(frame[1]).name}"
            where = f" at line {frame[2]}{of}{src}"
    return {"ok": False, "note": f"raised {last[:300]}{where}"}


def private_notes(checks: list[dict[str, Any]], tainted: set[str]) -> list[str]:
    """The program checks' notes that quote a tainted subtask's file or its error (a pass only says what was checked)."""
    return [c["program"]["note"] for c in checks
            if c["subtask"] in tainted and c.get("program") and c["program"]["ok"] is not True]


def problems(checks: list[dict[str, Any]]) -> dict[str, str]:
    """What to tell each subtask whose files are missing or failed SPIKE's checks, by subtask id."""
    out: dict[str, str] = {}
    for c in checks:
        if not c["ok"]:
            note = f"The file {c['path']} was not saved: save it with your file tool at exactly that path."
        elif c.get("program", {}).get("ok") is False:
            note = (f"Checks SPIKE ran on the saved file: {c['path']} {c['program']['note']}. Fix it and save it "
                    "again at exactly that path.")
        else:
            continue
        out[c["subtask"]] = " ".join(x for x in (out.get(c["subtask"]), note) if x)
    return out
