"""The architecture_graph tool: the module graph of a workspace folder (Python and JavaScript/TypeScript imports) with
its import cycles, drawn as an SVG for the artifacts panel. It reads source files as text and never runs them."""

from __future__ import annotations

import asyncio
from typing import Any

from spike.architecture.cycles import find_cycles
from spike.architecture.render import DEFAULT_NODES, MAX_NODES, MIN_NODES, render_graph
from spike.architecture.scan import scan
from spike.tools.base import Tool, ToolResult
from spike.tools.builtin import Workspace

MAX_CYCLES = 50  # cycles listed in the table and for the model
MAX_MEMBERS = 30  # modules named per cycle
MAX_PATH = 20


class ArchitectureError(ValueError):
    """A bad argument; the message is safe to show."""


class ArchitectureGraph(Tool):
    name = "architecture_graph"
    description = ("Map a project folder's modules: which Python and JavaScript/TypeScript files import which (found by "
                   "reading the code, nothing is run), the import cycles (Tarjan's strongly connected components) and a "
                   "diagram with the cycles in red. The user sees the diagram and a table of the cycles; you get the "
                   "counts and each cycle's path. By default only imports that run when a module loads make a cycle; "
                   "`lazy` also counts imports inside functions and type-only imports.")
    parameters = {"type": "object", "properties": {
        "path": {"type": "string", "description": "folder in the workspace; default is the workspace itself"},
        "lazy": {"type": "boolean", "description": "also count imports inside functions and under TYPE_CHECKING / "
                                                   "`import type` when looking for cycles"},
        "max_nodes": {"type": "integer", "minimum": MIN_NODES, "maximum": MAX_NODES,
                      "description": f"modules drawn at most (cycles first); default {DEFAULT_NODES}"},
        "title": {"type": "string"},
        "lang": {"type": "string", "enum": ["es", "en"], "description": "language of the diagram's own text; default es"}}}
    risk = "read"
    default_policy = "allow"  # reads source files as text on this computer; nothing leaves it

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            return await asyncio.to_thread(self.act, args)
        except (ArchitectureError, PermissionError, OSError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")

    def act(self, args: dict[str, Any]) -> ToolResult:
        lang, lazy, nodes = args.get("lang", "es"), args.get("lazy", False), args.get("max_nodes", DEFAULT_NODES)
        if lang not in ("es", "en"):
            raise ArchitectureError("lang must be es or en")
        if not isinstance(lazy, bool):
            raise ArchitectureError("lazy must be true or false")
        if isinstance(nodes, bool) or not isinstance(nodes, int) or not MIN_NODES <= nodes <= MAX_NODES:
            raise ArchitectureError(f"max_nodes must be a whole number from {MIN_NODES} to {MAX_NODES}")
        given = str(args.get("path") or ".")
        folder = self.workspace.resolve(given)
        if not folder.is_dir():
            raise ArchitectureError(f"{given} is not a folder in the workspace")
        graph = scan(folder)
        cycles = find_cycles(graph.nodes, graph.edges, lazy)
        title = str(args.get("title") or "").strip()[:120] or folder.name
        svg = render_graph(graph, cycles, title=title, lang=lang, max_nodes=nodes, lazy=lazy)
        summary = graph.summary()
        in_cycles = sum(len(c.members) for c in cycles)
        stats = {"modules": summary["modules"], "python": summary["python"], "javascript": summary["javascript"],
                 "edges": summary["edges"], "static": summary["static"], "lazy": summary["lazy"], "type": summary["type"],
                 "external": graph.external, "unresolved": graph.unresolved, "cycles": len(cycles),
                 "in_cycles": in_cycles, "shown": min(len(graph.nodes), nodes)}
        table = [{"size": len(c.members), "members": c.members[:MAX_MEMBERS], "more": max(0, len(c.members) - MAX_MEMBERS),
                  "path": c.path[:MAX_PATH]} for c in cycles[:MAX_CYCLES]]
        lines = [f"Module graph of {title}: {stats['modules']} modules ({stats['python']} Python, {stats['javascript']} "
                 f"JavaScript/TypeScript) and {stats['edges']} imports ({stats['static']} at import time, {stats['lazy']} "
                 f"inside functions or dynamic, {stats['type']} type-only); {graph.external} imports of packages or the "
                 f"standard library and {graph.unresolved} relative imports that match no file were left out.",
                 ("Cycles counted over all imports." if lazy else "Cycles counted over imports that run at import time.")
                 + (f" {len(cycles)} cycles, {in_cycles} modules:" if cycles else " No import cycles.")]
        for i, c in enumerate(table, 1):
            more = f" (+{c['more']} more modules)" if c["more"] else ""
            lines.append(f"{i}. {c['size']} modules: {' -> '.join(c['path'])}{more}")
        if len(cycles) > MAX_CYCLES:
            lines.append(f"[only the first {MAX_CYCLES} of {len(cycles)} cycles are listed]")
        if stats["shown"] < stats["modules"]:
            lines.append(f"[the diagram shows {stats['shown']} of {stats['modules']} modules: cycles first, then the "
                         "most connected]")
        notes = {"files": "only the first source files were read ({} files found)", "large": "{} files over the size limit "
                 "were not read", "time": "reading hit the time limit: {} files were not read"}
        lines += [f"[{notes[k].format(v)}]" for k, v in graph.truncated.items()]
        lines += [f"[could not parse: {e}]" for e in graph.errors[:5]]
        content = "\n".join(lines)
        ui = {"kind": "architecture", "title": title, "svg": svg, "stats": stats, "cycles": table,
              "cycles_total": len(cycles), "lazy": lazy, "truncated": graph.truncated, "errors": graph.errors[:10]}
        return ToolResult(ok=True, content=content, private=[content], data={"ui": ui})


def architecture_tools(workspace: Workspace) -> list[Tool]:
    return [ArchitectureGraph(workspace)]
