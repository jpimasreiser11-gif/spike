"""The Forge test tasks (`spike forge eval`): ten fixed tasks whose results SPIKE checks itself, on the files the team
saved; no model judges them. Each task runs in a new empty folder: Forge drafts the blueprint and runs it as drafted
(nobody reviews it here), and with `--baseline` the core model alone (one model, the same file tools, no plan and no
checker) answers the same task. The report gives each mode's success rate with a 95 % Wilson interval.

The checks run Python on the saved files, and some import the module the model wrote: they run in a subprocess in
that task's folder with CPU and memory limits, like the `python` tool. Numbers only mean something from real runs
with real weights; a scripted provider only tests this harness.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import platform
import re
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spike import __version__
from spike.forge.blueprint import make_blueprint
from spike.orchestrator.orchestrator import Orchestrator, OrchestratorOptions
from spike.tools.base import HeadlessBroker, PermissionBroker
from spike.tools.builtin import default_registry

TASKS = Path(__file__).with_name("tasks.jsonl")
CHECK_TIMEOUT_S = 20
# nobody answers questions during the eval: file tools and python run, the web does not
POLICIES = {"write_file": "allow", "create_docx": "allow", "create_xlsx": "allow", "create_pptx": "allow",
            "create_pdf": "allow", "python": "allow", "web_fetch": "deny"}
PRELUDE = r'''
import csv, io, json, re, sys
sys.path.insert(0, ".")

def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

NUM = re.compile(r"\d+(?:[.,  ]\d+)*")

def _value(token, style):
    t = token.replace(" ", "").replace(" ", "")
    t = t.replace(".", "").replace(",", ".") if style == "es" else t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return float("nan")

def numbers(text):
    """Every number in the text, read with a decimal comma (1.234,56) and with a decimal point (1,234.56)."""
    return [_value(m.group(), s) for m in NUM.finditer(text) for s in ("es", "en")]

def near(text, value, tol):
    return any(abs(n - value) <= tol for n in numbers(text))

def amount(text, style):
    """The first number in the text, read in one style; NaN when there is none."""
    m = NUM.search(text)
    return _value(m.group(), style) if m else float("nan")
'''


def load_tasks(path: Path = TASKS) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _limits() -> None:  # in the child, before exec (POSIX)
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (CHECK_TIMEOUT_S, CHECK_TIMEOUT_S))
    with contextlib.suppress(ValueError, OSError):  # macOS does not enforce RLIMIT_AS
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
    os.setsid()


def _python(code: str, root: Path) -> tuple[bool, str]:
    import subprocess

    script = Path(tempfile.mkdtemp(prefix="spike-check-")) / "check.py"
    script.write_text(PRELUDE + "\n" + code + "\n", encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, "-I", str(script)], cwd=root, capture_output=True, text=True,
                              timeout=CHECK_TIMEOUT_S * 2, env={"PATH": os.environ.get("PATH", ""),
                                                                "PYTHONIOENCODING": "utf-8", "HOME": str(root)},
                              preexec_fn=_limits if os.name == "posix" else None)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    finally:
        script.unlink(missing_ok=True)
        script.parent.rmdir()
    if proc.returncode == 0:
        return True, ""
    lines = [line for line in proc.stderr.strip().splitlines() if line.strip()]
    return False, (lines[-1] if lines else f"exit {proc.returncode}")[:300]


def _text(root: Path, path: str) -> str | None:
    target = (root / path).resolve()
    if root.resolve() not in target.parents or not target.is_file():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


def run_check(check: dict[str, Any], root: Path) -> tuple[bool, str]:
    """(passed, why not) for one check on the files in `root`."""
    kind = check["kind"]
    if kind == "python":
        return _python(check["code"], root)
    content = _text(root, check["path"])
    if content is None:
        return False, f"{check['path']} not found"
    if kind == "contains":
        low = content.lower()
        missing = [s for s in check.get("all", []) if s.lower() not in low]
        if missing:
            return False, f"{check['path']} lacks {', '.join(missing)}"
        if check.get("any") and not any(s.lower() in low for s in check["any"]):
            return False, f"{check['path']} has none of {', '.join(check['any'])}"
        return True, ""
    if kind == "words_max":
        words = len(re.findall(r"\w+", content))
        return (words <= check["max"], "" if words <= check["max"] else f"{words} words > {check['max']}")
    raise ValueError(f"unknown check kind '{kind}'")


def check_name(check: dict[str, Any]) -> str:
    if check.get("name"):
        return check["name"]
    if check["kind"] == "contains":
        return f"{check['path']} contains {', '.join(check.get('all') or check.get('any') or [])}"
    return f"{check['path']}: at most {check['max']} words"


def check_task(task: dict[str, Any], root: Path) -> dict[str, Any]:
    failed = []
    for check in task["checks"]:
        ok, why = run_check(check, root)
        if not ok:
            failed.append({"check": check_name(check), "why": why})
    return {"passed": not failed, "failed": failed}


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


async def run_task(base: Orchestrator, task: dict[str, Any], mode: str, folder: Path) -> dict[str, Any]:
    """One task in one mode ("forge" or "baseline") in an empty folder; its checks decide."""
    tools = default_registry(folder)
    orch = Orchestrator(base.catalog, base.resolve, tools, HeadlessBroker(PermissionBroker(POLICIES)),
                        skills=base.skills)
    started = time.perf_counter()
    error, extra = None, {}
    try:
        if mode == "forge":
            core = base.resolve(base.catalog.core)
            candidates = [c for c in base.router.route(task["prompt"]).specialists if c != "core"]
            bp = await make_blueprint(core.provider, base.catalog, task["prompt"], candidates, model=core.model)
            extra = {"blueprint": bp.method, "steps": len(bp.steps)}
            opts = OrchestratorOptions(forge=bp)
        else:
            opts = OrchestratorOptions(mode="core", use_planner=False)
        async for ev in orch.run([], task["prompt"], opts):
            if ev["type"] == "done":
                error = ev.get("error")
            elif ev["type"] == "forge_report":
                extra["rounds"] = ev["rounds"]
    except Exception as exc:  # a crash is a failed task, not a failed eval
        error = f"{exc.__class__.__name__}: {exc}"
    result = check_task(task, folder)
    return {"id": task["id"], "mode": mode, **result, "error": error,
            "elapsed_s": round(time.perf_counter() - started, 1), **extra}


async def evaluate(base: Orchestrator, tasks: list[dict[str, Any]], modes: list[str], meta: dict[str, Any],
                   progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    results = []
    for task in tasks:
        for mode in modes:
            with tempfile.TemporaryDirectory(prefix=f"spike-forge-{task['id']}-") as tmp:
                result = await run_task(base, task, mode, Path(tmp))
            results.append(result)
            if progress:
                progress(result)
    summary = {}
    for mode in modes:
        rows = [r for r in results if r["mode"] == mode]
        passed = sum(r["passed"] for r in rows)
        summary[mode] = {"passed": passed, "n": len(rows), "rate": round(passed / len(rows), 4) if rows else 0.0,
                         "ci95": wilson(passed, len(rows))}
    return {"date_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "spike_version": __version__,
            "platform": f"{platform.system()} {platform.machine()}", **meta, "summary": summary, "results": results}


def run(base: Orchestrator, tasks: list[dict[str, Any]], modes: list[str], meta: dict[str, Any],
        progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    return asyncio.run(evaluate(base, tasks, modes, meta, progress))
