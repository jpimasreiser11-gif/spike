"""The task board SPIKE's two builders share: Claude (the lead, in the cloud) and Codex (a worker on the owner's Mac).

    python scripts/team/board.py check                      # validate docs/team/tasks.json; exit 1 on any problem
    python scripts/team/board.py render [--check]           # write docs/team/BOARD.md; --check: exit 1 when it is stale
    python scripts/team/board.py next --owner codex         # the owner's next task as JSON; nothing and exit 3 if none
    python scripts/team/board.py show X1                    # one task as JSON

docs/team/tasks.json is the only source of truth; BOARD.md is generated from it (Spanish, for people) and never edited by
hand. A task is {id, owner, status, phase, title, depends, paths, spec, accept}; see validate() for the rules. The
functions load_board / parse_board / validate / render / next_task are imported by scripts/team/codex_worker.py and the
tests. Standard library only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "docs" / "team" / "tasks.json"
NONE_FOUND = 3   # exit code of `next` when the owner has nothing to do

OWNERS = ("claude", "codex", "mac", "joan")
STATUSES = ("todo", "doing", "review", "changes", "done", "blocked")
OWNER_ES = {"claude": "Claude", "codex": "Codex", "mac": "Mac", "joan": "joan"}
STATUS_ES = {"todo": "pendiente", "doing": "en curso", "review": "en revisión", "changes": "cambios pedidos",
             "done": "hecha", "blocked": "bloqueada"}
ID_RE = re.compile(r"[A-Z]{1,2}\d{1,3}")
NO_PHASE = "sin fase"


class BoardError(ValueError):
    """The board file cannot be read or is not JSON."""


def parse_board(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise BoardError(f"not valid JSON: {e}") from None


def load_board(path: str | Path = BOARD) -> dict:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise BoardError(f"cannot read {path}: {e.strerror or e}") from None
    return parse_board(text)


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate(board) -> list[str]:
    """Every problem with the board, one line each (empty list: valid)."""
    if not isinstance(board, dict):
        return ["the board must be a JSON object"]
    problems: list[str] = []
    if board.get("version") != 1:
        problems.append(f"version must be 1, got {board.get('version')!r}")
    tasks = board.get("tasks")
    if not isinstance(tasks, list):
        return problems + ['"tasks" must be a list']
    seen: dict[str, dict] = {}
    for n, t in enumerate(tasks, 1):
        who = f"task #{n}"
        if not isinstance(t, dict):
            problems.append(f"{who}: must be an object")
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not ID_RE.fullmatch(tid):
            problems.append(f"{who}: id {tid!r} must match ^[A-Z]{{1,2}}\\d{{1,3}}$")
        else:
            who = f"task {tid}"
            if tid in seen:
                problems.append(f"{who}: duplicate id")
            seen.setdefault(tid, t)
        if t.get("owner") not in OWNERS:
            problems.append(f"{who}: owner {t.get('owner')!r} must be one of {', '.join(OWNERS)}")
        if t.get("status") not in STATUSES:
            problems.append(f"{who}: status {t.get('status')!r} must be one of {', '.join(STATUSES)}")
        if "phase" in t and not isinstance(t["phase"], str):
            problems.append(f"{who}: phase must be a string")
        if not _is_text(t.get("title")):
            problems.append(f"{who}: title must be a non-empty string")
        if not _is_text(t.get("spec")):
            problems.append(f"{who}: spec must be a non-empty string")
        accept = t.get("accept")
        if not isinstance(accept, list) or not accept or not all(_is_text(a) for a in accept):
            problems.append(f"{who}: accept must be a non-empty list of non-empty strings")
        for key in ("depends", "paths"):
            value = t.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                problems.append(f"{who}: {key} must be a list of strings")
    graph: dict[str, list[str]] = {}
    for t in tasks:   # every task, a duplicate too
        deps = t.get("depends", []) if isinstance(t, dict) else None
        if not isinstance(deps, list) or not isinstance(t.get("id"), str):
            continue
        graph.setdefault(t["id"], []).extend(d for d in deps if isinstance(d, str) and d in seen)
        problems.extend(f"task {t['id']}: depends on unknown task {d!r}" for d in deps if isinstance(d, str) and d not in seen)
    problems.extend(f"dependency cycle: {' -> '.join(c)}" for c in _cycles(graph))
    return problems


def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """One path per cycle found (depth-first; a self-dependency is a cycle of one)."""
    found: list[list[str]] = []
    state: dict[str, int] = {}   # 1: on the current path, 2: finished
    for root in graph:
        if state.get(root):
            continue
        path = [root]
        state[root] = 1
        stack = [iter(graph[root])]
        while stack:
            for dep in stack[-1]:
                if state.get(dep) == 1:
                    found.append(path[path.index(dep):] + [dep])
                elif not state.get(dep):
                    state[dep] = 1
                    path.append(dep)
                    stack.append(iter(graph.get(dep, ())))
                    break
            else:
                state[path.pop()] = 2
                stack.pop()
    return found


def next_task(board: dict, owner: str, skip=()) -> dict | None:
    """The owner's next task: a `changes` one first, then a `todo` one, in file order; its dependencies must all be done."""
    tasks = [t for t in board.get("tasks", []) if isinstance(t, dict)]
    done = {t.get("id") for t in tasks if t.get("status") == "done"}
    skip = set(skip)
    for wanted in ("changes", "todo"):
        for t in tasks:
            if (t.get("owner") == owner and t.get("status") == wanted and t.get("id") not in skip
                    and all(d in done for d in t.get("depends", []))):
                return t
    return None


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def render(board: dict) -> str:
    """BOARD.md for a valid board: the same board gives the same bytes (no timestamps)."""
    tasks = board["tasks"]
    lines = ["# Tablero SPIKE", "",
             "Generado desde `docs/team/tasks.json` con `python scripts/team/board.py render`; no se edita a mano.", "",
             "## Resumen", "",
             "| Quién | " + " | ".join(STATUS_ES[s] for s in STATUSES) + " | total |",
             "|---|" + "---:|" * (len(STATUSES) + 1)]
    for owner in OWNERS:
        counts = [sum(1 for t in tasks if t["owner"] == owner and t["status"] == s) for s in STATUSES]
        lines.append(f"| {OWNER_ES[owner]} | " + " | ".join(map(str, counts)) + f" | {sum(counts)} |")
    totals = [sum(1 for t in tasks if t["status"] == s) for s in STATUSES]
    lines.append("| **Total** | " + " | ".join(f"**{n}**" for n in totals) + f" | **{len(tasks)}** |")
    phases: dict[str, list[dict]] = {}
    for t in tasks:
        phases.setdefault(t.get("phase") or NO_PHASE, []).append(t)
    for phase, group in phases.items():
        lines += ["", f"## Fase: {_cell(phase)}", "", "| ID | Quién | Estado | Tarea | Depende de |", "|---|---|---|---|---|"]
        for t in group:
            deps = ", ".join(t.get("depends", [])) or "-"
            lines.append(f"| {t['id']} | {OWNER_ES[t['owner']]} | {STATUS_ES[t['status']]} | {_cell(t['title'])} | {deps} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="board.py", description="SPIKE team task board (docs/team/tasks.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_board(p):
        p.add_argument("--board", type=Path, default=BOARD, help="the task file (default docs/team/tasks.json)")

    p = sub.add_parser("check", help="validate the board")
    add_board(p)
    p = sub.add_parser("render", help="write BOARD.md (Spanish view)")
    add_board(p)
    p.add_argument("--out", type=Path, help="default: BOARD.md next to the board file")
    p.add_argument("--check", action="store_true", help="write nothing; exit 1 if the file on disk is not what render gives")
    p = sub.add_parser("next", help="the owner's next task, as JSON (exit 3 when there is none)")
    add_board(p)
    p.add_argument("--owner", required=True, choices=OWNERS)
    p.add_argument("--skip", default="", help="comma-separated task ids to pass over")
    p = sub.add_parser("show", help="one task, as JSON")
    add_board(p)
    p.add_argument("id")
    args = ap.parse_args(argv)

    try:
        board = load_board(args.board)
    except BoardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    problems = validate(board)
    if problems:
        print(*problems, sep="\n", file=sys.stdout if args.cmd == "check" else sys.stderr)
        return 1
    if args.cmd == "check":
        print(f"ok: {len(board['tasks'])} tasks")
        return 0
    if args.cmd == "render":
        out = args.out or args.board.with_name("BOARD.md")
        text = render(board)
        if args.check:
            # compared as the LF text it is written as: a CRLF checkout of the same file is not a difference
            current = out.read_bytes().replace(b"\r\n", b"\n") if out.is_file() else None
            if current == text.encode("utf-8"):
                return 0
            print(f"{out} is out of date: run python scripts/team/board.py render", file=sys.stderr)
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"wrote {out}")
        return 0
    if args.cmd == "next":
        task = next_task(board, args.owner, [s.strip() for s in args.skip.split(",") if s.strip()])
        if task is None:
            return NONE_FOUND
        print(json.dumps(task, ensure_ascii=False, indent=2))
        return 0
    for task in board["tasks"]:
        if task["id"] == args.id:
            print(json.dumps(task, ensure_ascii=False, indent=2))
            return 0
    print(f"error: no task {args.id!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):   # Spanish text on a console that is not UTF-8 (Windows)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
