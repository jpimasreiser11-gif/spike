"""The Godot 4 side: a model's plan becomes the files of a minimal project (`project.godot`, a main scene written as
Godot 4's text format, GDScript files), and `godot --headless` is run on it to check it. Every name, type, path and
property in a plan is checked before a file is written, so a plan cannot write outside its project folder or break the
scene file. The commands below use Godot 4's documented command-line options; they were only exercised with a fake
`godot` in the tests, never with a real one."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
CLASS = re.compile(r"[A-Z][A-Za-z0-9]{0,63}")
PROPERTY = re.compile(r"[A-Za-z_][A-Za-z0-9_/]{0,63}")
SCRIPT_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*\.gd")
MAX_NODES = 200
MAX_SCRIPTS = 40
MAX_CODE = 100_000
MAX_EXPRESSION = 200
MAIN_SCENE = "main.tscn"
CHECKED_SCRIPTS = 40  # a check runs Godot once per script; more than this are left out and the result says so
SKIP_DIRS = {".godot", ".git", ".import"}
DEFAULT_SCRIPT = "extends {root}\n\n\nfunc _ready() -> void:\n\tprint(\"Hello from SPIKE\")\n"


class PlanError(ValueError):
    pass


@dataclass
class Node:
    name: str
    type: str
    parent: str  # "." for a child of the root, else the path of its parent below the root; "" for the root itself
    script: str = ""
    properties: dict[str, str] = field(default_factory=dict)  # values already written the way Godot reads them


@dataclass
class Plan:
    name: str
    width: int
    height: int
    root: Node
    nodes: list[Node]
    scripts: dict[str, str]


def value(raw: Any) -> str:
    """A property value as the scene file writes it: numbers and booleans as they are, text quoted, and text that
    starts with "=" as a Godot expression on one line (`=Vector2(100, 50)`, `=Color(1, 0, 0)`)."""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, int | float):
        if not math.isfinite(raw):
            raise PlanError("a property value must be a finite number")
        return repr(raw)
    if isinstance(raw, str):
        if not raw.startswith("="):
            return json.dumps(raw, ensure_ascii=False)
        expression = raw[1:].strip()
        if not expression or len(expression) > MAX_EXPRESSION or any(c in expression for c in "\r\n\x00"):
            raise PlanError(f"a Godot expression after = must be one line of at most {MAX_EXPRESSION} characters")
        return expression
    raise PlanError("a property value must be a number, true/false, text, or text starting with = for an expression")


def parse(args: dict[str, Any]) -> Plan:
    """Check a model's plan and turn it into a `Plan`. Raises `PlanError` saying what to fix."""
    raw_scripts = args.get("scripts") or []
    if not isinstance(raw_scripts, list) or len(raw_scripts) > MAX_SCRIPTS:
        raise PlanError(f"scripts must be a list of at most {MAX_SCRIPTS} items like {{\"path\": \"player.gd\", "
                        "\"code\": \"extends Node2D\"}")
    scripts: dict[str, str] = {}
    for item in raw_scripts:
        path, code = (item.get("path"), item.get("code")) if isinstance(item, dict) else (None, None)
        if not isinstance(path, str) or not SCRIPT_PATH.fullmatch(path):
            raise PlanError(f"a script path must be a relative .gd path such as player.gd or scripts/enemy.gd, "
                            f"not {path!r}")
        if not isinstance(code, str) or len(code) > MAX_CODE:
            raise PlanError(f"{path}: `code` must be text of at most {MAX_CODE} characters")
        if path in scripts:
            raise PlanError(f"the script {path} is listed twice")
        scripts[path] = code if code.endswith("\n") else code + "\n"

    def need(script: str, where: str) -> str:
        if script and script not in scripts:
            raise PlanError(f"{where} uses the script {script!r}, which is not in `scripts`")
        return script

    root_name, root_type = str(args.get("root_name") or "Main"), str(args.get("root_type") or "Node2D")
    if not NAME.fullmatch(root_name) or not CLASS.fullmatch(root_type):
        raise PlanError("root_name must be a plain name (Main) and root_type a Godot class (Node2D, Node3D, Control)")
    root_script = need(str(args.get("root_script") or ""), "the root")
    if not scripts and not root_script:  # a project that does something when it starts
        root_script, scripts["main.gd"] = "main.gd", DEFAULT_SCRIPT.format(root=root_type)
    root = Node(root_name, root_type, "", root_script)

    raw_nodes = args.get("nodes") or []
    if not isinstance(raw_nodes, list) or len(raw_nodes) > MAX_NODES:
        raise PlanError(f"nodes must be a list of at most {MAX_NODES} items like {{\"name\": \"Player\", \"type\": "
                        "\"Sprite2D\", \"parent\": \".\"}")
    below = {"."}  # the paths a node can be placed under: the root, then every node declared so far
    nodes: list[Node] = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            raise PlanError("each node must be an object with a name, a type and (optionally) a parent")
        name, kind = str(item.get("name") or ""), str(item.get("type") or "Node")
        if not NAME.fullmatch(name) or not CLASS.fullmatch(kind):
            raise PlanError(f"node {name!r}: the name must be a plain name (Player) and the type a Godot class "
                            f"(Sprite2D), not {kind!r}")
        parent = str(item.get("parent") or ".")
        parent = "." if parent == root_name else parent
        if parent not in below:
            raise PlanError(f"node {name}: its parent {parent!r} is not the root (\".\") or a node listed before it")
        path = name if parent == "." else f"{parent}/{name}"
        if path in below:
            raise PlanError(f"two nodes would have the path {path}")
        below.add(path)
        props = item.get("properties") or {}
        if not isinstance(props, dict) or any(not isinstance(k, str) or not PROPERTY.fullmatch(k) for k in props):
            raise PlanError(f"node {name}: properties must be an object whose names are Godot properties "
                            "(position, scale, text, ...)")
        try:
            written = {k: value(v) for k, v in props.items()}
        except PlanError as exc:
            raise PlanError(f"node {name}: {exc}") from exc
        nodes.append(Node(name, kind, parent, need(str(item.get("script") or ""), f"node {name}"), written))

    title = re.sub(r"[\x00-\x1f]", " ", str(args.get("name") or Path(str(args.get("folder") or "")).name or "Game"))
    return Plan(title.strip()[:80] or "Game", size(args, "width", 1152), size(args, "height", 648), root, nodes,
                scripts)


def size(args: dict[str, Any], key: str, default: int) -> int:
    got = args.get(key, default)
    if isinstance(got, bool) or not isinstance(got, int) or not 128 <= got <= 7680:
        raise PlanError(f"{key} must be a whole number of pixels between 128 and 7680")
    return got


def project_text(plan: Plan) -> str:
    return "\n".join([
        "; Engine configuration file, written by SPIKE. Edit it in Godot (Project > Project Settings) or by hand.",
        "", "config_version=5", "", "[application]", "",
        f"config/name={json.dumps(plan.name, ensure_ascii=False)}", f'run/main_scene="res://{MAIN_SCENE}"',
        'config/features=PackedStringArray("4.0")', "", "[display]", "",
        f"window/size/viewport_width={plan.width}", f"window/size/viewport_height={plan.height}", ""])


def scene_text(plan: Plan) -> str:
    """The main scene in Godot 4's text format (`format=3`): the scripts it uses as external resources, then the root
    and the nodes in the order the plan gave them (a parent always comes before its children)."""
    used = list(dict.fromkeys(n.script for n in [plan.root, *plan.nodes] if n.script))
    ids = {path: str(i) for i, path in enumerate(used, 1)}
    lines = [f"[gd_scene load_steps={len(ids) + 1} format=3]" if ids else "[gd_scene format=3]", ""]
    lines += [f'[ext_resource type="Script" path="res://{path}" id="{ids[path]}"]' for path in used]
    lines += [""] if used else []
    for node in [plan.root, *plan.nodes]:
        parent = f' parent="{node.parent}"' if node.parent else ""
        lines.append(f'[node name="{node.name}" type="{node.type}"{parent}]')
        if node.script:
            lines.append(f'script = ExtResource("{ids[node.script]}")')
        lines += [f"{key} = {text}" for key, text in node.properties.items()]
        lines.append("")
    return "\n".join(lines)


def files(plan: Plan) -> dict[str, str]:
    """Every file of the project by its path inside the project folder."""
    return {"project.godot": project_text(plan), MAIN_SCENE: scene_text(plan), **dict(sorted(plan.scripts.items()))}


# --------------------------------------------------------------------------- the headless check
def version_command(exe: str) -> list[str]:
    return [exe, "--version"]


def check_command(exe: str, project: Path, script: str) -> list[str]:
    """Parse one script and quit: `--check-only` is meant to be used with `--script`."""
    return [exe, "--headless", "--path", str(project), "--check-only", "--script", f"res://{script}"]


def load_command(exe: str, project: Path) -> list[str]:
    """Start the project without a window, load its main scene, run one frame and quit."""
    return [exe, "--headless", "--path", str(project), "--quit"]


def scripts_in(project: Path) -> list[str]:
    """The .gd files of a project (relative, with /), without Godot's own cache folder."""
    found: list[str] = []
    for folder, dirs, names in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        found += [(Path(folder) / n).relative_to(project).as_posix() for n in sorted(names) if n.endswith(".gd")]
    return sorted(found)


def major_version(output: str) -> tuple[int, str] | None:
    """(major, full version text) from what `godot --version` printed ("4.2.1.stable.official.b09f793f5"), or None."""
    line = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
    found = re.match(r"(\d+)\.\d+", line)
    return (int(found[1]), line) if found else None


ERROR_LINE = re.compile(r"(?:SCRIPT ERROR|ERROR|Parse Error):")
HARMLESS = re.compile(r"leaked at exit|still in use at exit", re.IGNORECASE)  # engine bookkeeping at shutdown


def problems(output: str, limit: int = 8) -> list[str]:
    """The lines of Godot's output that report an error (`SCRIPT ERROR: ...`, `ERROR: ...`, `Parse Error: ...`)."""
    lines = [ln.strip()[:300] for ln in output.splitlines() if ERROR_LINE.match(ln.strip()) and not HARMLESS.search(ln)]
    return lines[:limit]
