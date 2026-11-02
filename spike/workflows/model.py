"""The workflow document: nodes and edges, the {{variable}} templates, the checks made before a save or a run, and the
condition tests. Nothing here runs a model or a tool (runner.py does) and nothing here touches the disk (store.py does).

A workflow is a graph of five node types. `input` names a value the run starts with (text, number or a file path).
`specialist` asks a specialist (or auto) a prompt. `tool` calls one tool with arguments. `condition` tests the value it
receives and sends it down its `true` or its `false` port. `output` saves the value to a file or shows it as an
artifact. An edge carries a node's output to another node's `in` port; the node can read it as {{input}}, and any
input node, or any node upstream of it, by its name: {{topic}}, {{draft}}.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from spike.orchestrator.planner import Subtask, topological_levels

FORMAT, VERSION = "spike-workflow", 1
NODE_TYPES = ("input", "specialist", "tool", "condition", "output")
INPUT_KINDS = ("text", "number", "file")
CONDITION_OPS = ("contains", "regex", "number")
COMPARES = ("<", "<=", ">", ">=", "==", "!=")
OUTPUT_MODES = ("file", "artifact")
OUTPUT_FORMATS = ("text", "html")
OUT_PORTS = {"input": ("out",), "specialist": ("out",), "tool": ("out",), "condition": ("true", "false"), "output": ()}
IN_PORTS = {"input": (), "specialist": ("in",), "tool": ("in",), "condition": ("in",), "output": ("in",)}
RESERVED = ("input",)  # {{input}} is what arrives on the node's `in` port, never a node's name
RESERVED_FOLDER = "workflows"  # where the workflows and their runs are stored: an output node may not write there

MAX_NODES, MAX_EDGES = 60, 200
MAX_NAME, MAX_TEXT = 80, 20_000
MAX_VALUE = 2_000  # an input's value
MAX_REGEX = 300
MAX_SUBJECT = 100_000  # what a regular expression is run on
NODE_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,39}")
_TEMPLATE = re.compile(r"\\\{\{|\{\{([^{}]*)\}\}")
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)(?:[+*]|\{\d)")  # (a+)+ : exponential backtracking
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_DECIMAL_COMMA = re.compile(r"[-+]?\d+,\d+")


@dataclass
class Problem:
    """One thing wrong with a workflow, for one node when `node` is set. `code` is stable (the app shows it in the
    user's language, with `params`); `message` is the English text."""

    code: str
    message: str
    node: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "node": self.node, "params": self.params}


class WorkflowError(ValueError):
    """A document that cannot be read as a workflow, or a workflow that failed its checks (`problems`)."""

    def __init__(self, message: str, problems: list[Problem] | None = None):
        super().__init__(message)
        self.problems = problems or [Problem("format", message)]


@dataclass
class Environment:
    """What a workflow may name: the specialists and the tools (name -> JSON schema of its arguments) that exist now.
    `unavailable` are tools that exist but cannot be used in a workflow (they need someone to answer)."""

    specialists: Collection[str]
    tools: Mapping[str, Mapping[str, Any]]
    unavailable: Collection[str] = ()


# --------------------------------------------------------------------------- reading the document
def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _number(value: Any, low: float = -10_000, high: float = 10_000) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return 0
    return round(min(max(value, low), high), 1)


def _json(value: Any, depth: int = 0) -> Any:
    """A JSON value kept as it is (strings capped); anything else, or nesting past 5 levels, becomes an empty string."""
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value if not isinstance(value, float) or math.isfinite(value) else 0
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if depth < 5 and isinstance(value, list):
        return [_json(v, depth + 1) for v in value[:100]]
    if depth < 5 and isinstance(value, dict):
        return {str(k)[:80]: _json(v, depth + 1) for k, v in list(value.items())[:100]}
    return ""


def clean(raw: Any) -> dict[str, Any]:
    """The workflow as the app stores it: known fields only, texts capped. Unknown fields are dropped; a missing node
    name is filled in. Raises WorkflowError for what is not a workflow at all; whether it is a *good* workflow is
    `validate`'s question."""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise WorkflowError("this is not a SPIKE workflow (format)")
    if raw.get("version") != VERSION:
        raise WorkflowError(f"unsupported workflow version {raw.get('version')!r}")
    raw_nodes, raw_edges = raw.get("nodes"), raw.get("edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise WorkflowError("a workflow has a list of nodes and a list of edges")
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        raise WorkflowError(f"a workflow has at most {MAX_NODES} nodes and {MAX_EDGES} edges", [Problem(
            "too_big", f"a workflow has at most {MAX_NODES} nodes and {MAX_EDGES} edges",
            params={"nodes": MAX_NODES, "edges": MAX_EDGES})])
    nodes, taken = [], set()
    for i, item in enumerate(n for n in raw_nodes if isinstance(n, dict)):
        kind = _text(item.get("type"), 20)
        node: dict[str, Any] = {"id": _text(item.get("id"), 60), "type": kind, "x": _number(item.get("x")),
                                "y": _number(item.get("y")), "label": _text(item.get("label"), MAX_NAME)}
        name = _text(item.get("name"), 60) or f"{kind or 'node'}{i + 1}"
        while name in taken:
            name += "_"
        taken.add(name)
        node["name"] = name
        if kind == "input":
            node.update(kind=_text(item.get("kind"), 10) or "text", default=_text(item.get("default"), MAX_VALUE))
        elif kind == "specialist":
            node.update(specialist=_text(item.get("specialist"), 60) or "auto", prompt=_text(item.get("prompt")))
        elif kind == "tool":
            args = item.get("arguments")
            node.update(tool=_text(item.get("tool"), 120), arguments=_json(args) if isinstance(args, dict) else {})
        elif kind == "condition":
            node.update(op=_text(item.get("op"), 20) or "contains", value=_text(item.get("value"), MAX_TEXT),
                        compare=_text(item.get("compare"), 3) or ">", case_sensitive=item.get("case_sensitive") is True)
        elif kind == "output":
            node.update(mode=_text(item.get("mode"), 20) or "artifact", path=_text(item.get("path"), 300),
                        content=_text(item.get("content")) or "{{input}}", title=_text(item.get("title"), MAX_NAME),
                        format=_text(item.get("format"), 10) or "text")
        nodes.append(node)
    edges = []
    for i, item in enumerate(e for e in raw_edges if isinstance(e, dict)):
        edges.append({"id": _text(item.get("id"), 60) or f"e{i + 1}", "from": _text(item.get("from"), 60),
                      "fromPort": _text(item.get("fromPort"), 10) or "out", "to": _text(item.get("to"), 60),
                      "toPort": _text(item.get("toPort"), 10) or "in"})
    doc: dict[str, Any] = {"format": FORMAT, "version": VERSION, "name": _text(raw.get("name"), MAX_NAME).strip(),
                           "nodes": nodes, "edges": edges}
    if isinstance(raw.get("id"), str):
        doc["id"] = raw["id"][:60]
    return doc


# --------------------------------------------------------------------------- templates
def pieces(template: str) -> list[tuple[str, str]]:
    """A template as ("text", s), ("var", name) and ("bad", content) pieces. `\\{{` is a literal `{{`."""
    out: list[tuple[str, str]] = []
    last = 0
    for m in _TEMPLATE.finditer(template):
        if m.start() > last:
            out.append(("text", template[last:m.start()]))
        if m.group(0).startswith("\\"):
            out.append(("text", "{{"))
        else:
            name = m.group(1).strip()
            out.append(("var", name) if VAR_NAME.fullmatch(name) else ("bad", m.group(1)))
        last = m.end()
    if last < len(template):
        out.append(("text", template[last:]))
    return out


def references(template: str) -> list[str]:
    """The variable names a template uses, in order, each once."""
    return list(dict.fromkeys(name for kind, name in pieces(template) if kind == "var"))


def render(template: str, lookup: Mapping[str, str]) -> str:
    """The template with each {{name}} replaced by lookup[name]; KeyError(name) for one that has no value."""
    return "".join(value if kind == "text" else lookup[value] for kind, value in pieces(template) if kind != "bad")


def node_templates(node: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(field, template) of every text in the node that may use {{variables}}."""
    kind = node.get("type")
    if kind == "specialist":
        return [("prompt", str(node.get("prompt", "")))]
    if kind == "tool":
        return [(f"arguments.{path}", text) for path, text in _leaves(node.get("arguments"), "")]
    if kind == "condition":
        return [("value", str(node.get("value", "")))] if node.get("op") == "contains" else []
    if kind == "output":
        return [("content", str(node.get("content", ""))), *(
            [("path", str(node.get("path", "")))] if node.get("mode") == "file" else
            [("title", str(node.get("title", "")))])]
    return []


def _leaves(value: Any, path: str) -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        return [leaf for i, v in enumerate(value) for leaf in _leaves(v, f"{path}[{i}]")]
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in _leaves(v, f"{path}.{k}" if path else str(k))]
    return []


def render_value(value: Any, lookup: Mapping[str, str]) -> Any:
    """A JSON value with every string in it rendered as a template."""
    if isinstance(value, str):
        return render(value, lookup)
    if isinstance(value, list):
        return [render_value(v, lookup) for v in value]
    if isinstance(value, dict):
        return {k: render_value(v, lookup) for k, v in value.items()}
    return value


def used_names(node: Mapping[str, Any]) -> list[str]:
    return list(dict.fromkeys(name for _, text in node_templates(node) for name in references(text)))


# --------------------------------------------------------------------------- graph
def incoming(doc: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """node id -> the edges that end at it, in document order."""
    found: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in doc["edges"]:
        found[edge["to"]].append(edge)
    return found


def find_cycle(doc: Mapping[str, Any]) -> list[str]:
    """The ids of the nodes of one cycle, or [] when the graph has none (an edge to an unknown node, or from a node to
    itself, is reported as its own problem)."""
    ids = {n["id"] for n in doc["nodes"]}
    after: dict[str, list[str]] = defaultdict(list)
    for edge in doc["edges"]:
        if edge["from"] in ids and edge["to"] in ids and edge["from"] != edge["to"]:
            after[edge["from"]].append(edge["to"])
    state: dict[str, int] = {}  # 1 on the current path, 2 finished
    for start in [n["id"] for n in doc["nodes"]]:
        if start in state:
            continue
        path, todo = [], [(start, iter(after[start]))]
        state[start] = 1
        path.append(start)
        while todo:
            node, children = todo[-1]
            for child in children:
                if state.get(child) == 1:
                    return path[path.index(child):]
                if child not in state:
                    state[child] = 1
                    path.append(child)
                    todo.append((child, iter(after[child])))
                    break
            else:
                state[node] = 2
                path.pop()
                todo.pop()
    return []


def ancestors(doc: Mapping[str, Any], node_id: str) -> set[str]:
    """Every node that has a path to `node_id`."""
    sources = incoming(doc)
    seen: set[str] = set()
    todo = [node_id]
    while todo:
        for edge in sources.get(todo.pop(), []):
            if edge["from"] not in seen:
                seen.add(edge["from"])
                todo.append(edge["from"])
    return seen


def levels(doc: Mapping[str, Any]) -> list[list[str]]:
    """Node ids in the order a run takes them: each level only needs earlier ones (the planner's topological levels).
    The graph must be acyclic: `validate` finds cycles first, the planner would only break them silently."""
    sources = incoming(doc)
    ids = {n["id"] for n in doc["nodes"]}
    tasks = [Subtask(id=n["id"], specialist=n["type"], instruction="",
                     depends_on=list(dict.fromkeys(e["from"] for e in sources.get(n["id"], []) if e["from"] in ids)))
             for n in doc["nodes"]]
    return [[t.id for t in level] for level in topological_levels(tasks)]


def port_type(doc: Mapping[str, Any], node_id: str, _seen: tuple[str, ...] = ()) -> str:
    """What flows out of a node: text, number or file. A condition passes on the type of what it receives."""
    node = next((n for n in doc["nodes"] if n["id"] == node_id), None)
    if node is None or node_id in _seen:
        return "text"
    if node["type"] == "input":
        return node.get("kind") if node.get("kind") in INPUT_KINDS else "text"
    if node["type"] == "condition":
        first = incoming(doc).get(node_id)
        return port_type(doc, first[0]["from"], (*_seen, node_id)) if first else "text"
    return "text"


# --------------------------------------------------------------------------- validation
def path_problem(path: str) -> str | None:
    """Why a file path is not a relative path inside the project or workspace, or None."""
    text = path.strip().replace("\\", "/")
    parts = PurePosixPath(text).parts
    if not text or text.startswith("/") or any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
        return "must be a relative path inside the project"
    return None


def safe_output_path(path: str) -> str | None:
    """Why a file path an output node writes is not acceptable, or None."""
    if (why := path_problem(path)) is not None:
        return why
    if PurePosixPath(path.strip().replace("\\", "/")).parts[0].lower() == RESERVED_FOLDER:
        return f"cannot be in the folder '{RESERVED_FOLDER}', where workflows are stored"
    return None


def _type_error(value: Any, schema: Mapping[str, Any]) -> str | None:
    """Why a constant argument does not fit its JSON-schema type, or None. Strings that read as the type are fine
    (the run converts them), the way a model's loosely typed call would be."""
    want = schema.get("type")
    if want in ("integer", "number"):
        try:
            number = float(value) if isinstance(value, str) else value
        except ValueError:
            return f"must be a {want}"
        if isinstance(number, bool) or not isinstance(number, int | float) or not math.isfinite(number):
            return f"must be a {want}"
        return "must be a whole number" if want == "integer" and number != int(number) else None
    if want == "boolean" and not (isinstance(value, bool) or value in ("true", "false")):
        return "must be true or false"
    if want == "array" and not isinstance(value, list) and not (isinstance(value, str) and value.lstrip().startswith("[")):
        return "must be a list"
    if want == "object" and not isinstance(value, dict) and not (isinstance(value, str) and value.lstrip().startswith("{")):
        return "must be an object"
    if want == "string" and isinstance(value, dict | list):
        return "must be text"
    return None


def risky_regex(pattern: str) -> bool:
    """A pattern with a quantified group that holds a quantifier, such as (a+)+: it can take exponential time."""
    return bool(_NESTED_QUANTIFIER.search(pattern))


def validate(doc: Mapping[str, Any], env: Environment) -> list[Problem]:
    """Every problem that stops the workflow from being saved or run; [] when it is sound. The checks: unique ids and
    names; known specialists and tools; required and well-typed tool arguments; condition settings; output settings;
    edges that join an existing output port to an existing input port of a compatible type; no cycle; every
    {{variable}} naming an input node or a node upstream."""
    problems: list[Problem] = []

    def bad(code: str, message: str, node: str | None = None, **params: Any) -> None:
        problems.append(Problem(code, message, node, params))

    nodes = doc["nodes"]
    if not nodes:
        bad("no_nodes", "the workflow has no nodes")
    ids: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}
    for node in nodes:
        nid = node["id"]
        if not NODE_ID.fullmatch(nid):
            bad("node_id", "a node needs an id of letters, digits, - or _", nid or None)
        elif nid in ids:
            bad("node_id", f"two nodes share the id '{nid}'", nid, id=nid)
        ids.setdefault(nid, node)
        if node["type"] not in NODE_TYPES:
            bad("node_type", f"unknown node type '{node['type']}'", nid, type=node["type"])
            continue
        name = node["name"]
        if not VAR_NAME.fullmatch(name) or name in RESERVED:
            bad("node_name", f"'{name}' cannot be a variable name: use letters, digits and _, not starting with a digit"
                "; 'input' is reserved", nid, name=name)
        elif name in names and names[name] != nid:
            bad("node_name", f"two nodes are called '{name}'", nid, name=name)
        names.setdefault(name, nid)
        _check_node(node, env, bad)

    # edges
    seen_edges: set[tuple[str, str, str, str]] = set()
    for edge in doc["edges"]:
        src, dst = ids.get(edge["from"]), ids.get(edge["to"])
        eid = edge["id"]
        if src is None or dst is None:
            bad("edge_node", f"edge {eid} joins a node that does not exist", dst["id"] if dst else src["id"] if src else None,
                edge=eid)
            continue
        if src["id"] == dst["id"]:
            bad("edge_self", "a node cannot be joined to itself", src["id"], edge=eid)
            continue
        if src["type"] not in OUT_PORTS or dst["type"] not in IN_PORTS:
            continue
        if edge["fromPort"] not in OUT_PORTS[src["type"]]:
            bad("edge_port", f"a {src['type']} node has no output '{edge['fromPort']}'", src["id"], edge=eid,
                type=src["type"], port=edge["fromPort"])
            continue
        if edge["toPort"] not in IN_PORTS[dst["type"]]:
            bad("edge_port", f"a {dst['type']} node has no input '{edge['toPort']}'", dst["id"], edge=eid,
                type=dst["type"], port=edge["toPort"])
            continue
        key = (edge["from"], edge["fromPort"], edge["to"], edge["toPort"])
        if key in seen_edges:
            bad("edge_duplicate", "the same two ports are joined twice", dst["id"], edge=eid)
        seen_edges.add(key)
        if dst["type"] == "condition" and port_type(doc, src["id"]) == "file":
            bad("edge_type", "a file cannot be tested by a condition: read it with a tool first", dst["id"], edge=eid)
    for nid, node in ids.items():
        if node["type"] == "condition" and len(incoming(doc).get(nid, [])) != 1:
            bad("edge_condition_inputs", "a condition tests one value: join exactly one edge to it", nid)

    cycle = find_cycle(doc)
    if cycle:
        bad("cycle", "the workflow has a cycle: " + " → ".join(cycle), cycle[0], nodes=cycle)

    # variables
    by_name = {n["name"]: n for n in ids.values()}
    for nid, node in ids.items():
        if node["type"] not in NODE_TYPES:
            continue
        upstream = ancestors(doc, nid)
        has_input = bool(incoming(doc).get(nid))
        for label, text in node_templates(node):
            for kind, name in pieces(text):
                if kind == "bad":
                    bad("var_syntax", f"{label}: '{{{{{name}}}}}' is not a variable name", nid, field=label, text=name)
                elif kind == "var" and name == "input":
                    if not has_input:
                        bad("var_input", f"{label}: {{{{input}}}} needs an edge into this node", nid, field=label)
                elif kind == "var":
                    target = by_name.get(name)
                    if target is None:
                        bad("var_unknown", f"{label}: no input or node is called '{name}'", nid, field=label, name=name)
                    elif target["type"] != "input" and target["id"] not in upstream:
                        bad("var_upstream", f"{label}: '{name}' is not upstream of this node, so it has no value "
                            "yet", nid, field=label, name=name)
    return problems


def _check_node(node: dict[str, Any], env: Environment, bad: Callable[..., None]) -> None:
    nid, kind = node["id"], node["type"]
    if kind == "input":
        if node["kind"] not in INPUT_KINDS:
            bad("input_kind", f"an input is text, number or file, not '{node['kind']}'", nid, kind=node["kind"])
        elif node["default"] and node["kind"] == "number" and parse_number(node["default"]) is None:
            bad("input_default", "the default of a number input must be a number", nid)
        elif node["default"] and node["kind"] == "file" and (why := path_problem(node["default"])):
            bad("input_default", f"the default file path {why}", nid)
    elif kind == "specialist":
        if node["specialist"] != "auto" and node["specialist"] not in env.specialists:
            bad("specialist_unknown", f"unknown specialist '{node['specialist']}'", nid, specialist=node["specialist"])
        if not node["prompt"].strip():
            bad("prompt_empty", "the prompt is empty", nid)
    elif kind == "tool":
        _check_tool(node, env, bad)
    elif kind == "condition":
        _check_condition(node, bad)
    elif kind == "output":
        if node["mode"] not in OUTPUT_MODES:
            bad("output_mode", f"an output saves a file or shows an artifact, not '{node['mode']}'", nid, mode=node["mode"])
        elif node["mode"] == "file":
            path = node["path"]
            why = safe_output_path(path) if path.strip() and "{{" not in path else None
            if not path.strip():
                bad("output_path", "the file path is empty", nid)
            elif why:
                bad("output_path", f"the file path {why}", nid)
        elif node["format"] not in OUTPUT_FORMATS:
            bad("output_format", f"an artifact is text or html, not '{node['format']}'", nid, format=node["format"])
        if not node["content"].strip():
            bad("output_content", "the content is empty", nid)


def _check_tool(node: dict[str, Any], env: Environment, bad: Callable[..., None]) -> None:
    nid, name = node["id"], node["tool"]
    if name in env.unavailable:
        bad("tool_unavailable", f"'{name}' needs someone to answer and cannot be used in a workflow", nid, tool=name)
        return
    if name not in env.tools:
        bad("tool_unknown", f"unknown tool '{name}'", nid, tool=name)
        return
    schema = env.tools[name]
    props = schema.get("properties") or {}
    args = node["arguments"]
    for key in args:
        if props and key not in props:
            bad("arg_unknown", f"{name} has no argument '{key}'", nid, tool=name, arg=key)
    for key in schema.get("required") or []:
        value = args.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            bad("arg_missing", f"{name} needs the argument '{key}'", nid, tool=name, arg=key)
    for key, value in args.items():
        constant = not (isinstance(value, str) and "{{" in value)
        if key in props and constant and value is not None and (why := _type_error(value, props[key])):
            bad("arg_type", f"{name}: '{key}' {why}", nid, tool=name, arg=key)


def _check_condition(node: dict[str, Any], bad: Callable[..., None]) -> None:
    nid, op, value = node["id"], node["op"], node["value"]
    if op not in CONDITION_OPS:
        bad("condition_op", f"a condition tests contains, regex or number, not '{op}'", nid, op=op)
    elif not value.strip():
        bad("condition_value", "the condition has nothing to compare with", nid)
    elif op == "regex":
        if len(value) > MAX_REGEX:
            bad("condition_regex", f"the pattern is longer than {MAX_REGEX} characters", nid)
        elif risky_regex(value):
            bad("condition_regex", "the pattern repeats a repeated group, which can take exponential time", nid)
        else:
            try:
                re.compile(value)
            except re.error as exc:
                bad("condition_regex", f"the pattern is not a valid regular expression: {exc}", nid)
    elif op == "number":
        if parse_number(value) is None:
            bad("condition_number", "the value to compare with must be a number", nid)
        if node["compare"] not in COMPARES:
            bad("condition_compare", f"compare with one of {' '.join(COMPARES)}", nid, compare=node["compare"])


# --------------------------------------------------------------------------- values and conditions
def parse_number(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", ".")) if _DECIMAL_COMMA.fullmatch(text.strip()) else float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def first_number(text: str) -> float | None:
    """The number a text is (1,5 reads as 1.5), or the first one in it ("Total: 42 EUR" is 42)."""
    whole = parse_number(text)
    if whole is not None:
        return whole
    found = _NUMBER.search(text)
    return float(found.group(0)) if found else None


def show_number(value: float) -> str:
    return str(int(value)) if value == int(value) and abs(value) < 1e15 else repr(value)


def evaluate(node: Mapping[str, Any], subject: str, needle: str) -> bool:
    """Whether the condition holds for `subject`. `needle` is the node's value after its {{variables}} are filled in
    (the pattern of a regex is not a template). Raises ValueError for a number test on a text with no number."""
    op = node["op"]
    sensitive = bool(node.get("case_sensitive"))
    if op == "contains":
        return needle in subject if sensitive else needle.lower() in subject.lower()
    if op == "regex":
        return re.search(needle, subject[:MAX_SUBJECT], 0 if sensitive else re.IGNORECASE) is not None
    number, limit = first_number(subject), parse_number(needle)
    if number is None or limit is None:
        raise ValueError("the value has no number to compare")
    return {"<": number < limit, "<=": number <= limit, ">": number > limit, ">=": number >= limit,
            "==": number == limit, "!=": number != limit}[node.get("compare") or ">"]


def bind_inputs(doc: Mapping[str, Any], given: Mapping[str, Any],
                check_file: Callable[[str], str | None] | None = None) -> tuple[dict[str, str], list[Problem]]:
    """The value of every input node for a run (name -> text), from what the user gave or the node's default, and what
    is wrong with them. `check_file(path)` returns why a file path cannot be used, or None."""
    values: dict[str, str] = {}
    problems: list[Problem] = []
    for node in doc["nodes"]:
        if node["type"] != "input":
            continue
        name, raw = node["name"], given.get(node["name"])
        text = raw if isinstance(raw, str) else "" if raw is None else str(raw)
        text = (text if text.strip() else node["default"])[:MAX_VALUE]
        if not text.strip():
            problems.append(Problem("input_missing", f"'{name}' needs a value", node["id"], {"name": name}))
        elif node["kind"] == "number":
            number = parse_number(text)
            if number is None:
                problems.append(Problem("input_number", f"'{name}' must be a number", node["id"], {"name": name}))
            else:
                text = show_number(number)
        elif node["kind"] == "file":
            why = check_file(text.strip()) if check_file else None
            if why:
                problems.append(Problem("input_file", f"'{name}': {why}", node["id"], {"name": name, "why": why}))
            text = text.strip()
        values[name] = text
    return values, problems
