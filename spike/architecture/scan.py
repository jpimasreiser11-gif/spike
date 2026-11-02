"""Read a folder's Python and JavaScript/TypeScript files and build its module graph. Nothing is run or imported.

Nodes are source files (paths relative to the folder, with `/`); an edge importer -> imported has a kind, `static`
(runs at import time), `lazy` (inside a function, or a dynamic `import()`) or `type` (under `TYPE_CHECKING`, or
`import type`); if a pair has several, the strongest wins. Only files inside the folder become nodes: standard
library modules and packages are counted in `external`, relative imports that match no file in `unresolved`.

Python (`ast`): `import a.b`, `from a import b` (a submodule `a/b.py` if there is one, else the package `a`),
relative imports by level. Absolute names are looked up from the folder, from each source root (the folder that
holds a top-level package, such as `src`), and from the importer's own folder when that is not a package (a script
run from there) and the name is not a standard library module; when the folder is itself a package (it holds an
`__init__.py`), its own name leads to it. The parent packages that `import a.b.c` also runs
are not edges. JavaScript and TypeScript (`jsimports.py`): relative specifiers only, tried as written, with each
extension, as `dir/index.*`, and with `.js` read as `.ts` (TypeScript's style); `tsconfig` paths, aliases and
`package.json` exports are not read, and `.vue`/`.svelte` files are not parsed.

Limits keep a huge repository from freezing the app: at most MAX_FILES files (the first ones in path order), no file
over MAX_FILE_BYTES (JavaScript over MAX_JS_BYTES, which is mostly minified code), and MAX_SECONDS to read them;
`Graph.truncated` says what was left out. node_modules, virtual environments, VCS and build folders, hidden folders
and symbolic links that leave the folder are never read."""

from __future__ import annotations

import ast
import os
import posixpath
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spike.architecture.jsimports import js_imports

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "env", "site-packages", "dist", "build", "out", "target", "coverage",
             "htmlcov", "vendor", "bower_components", "__pypackages__"}
PY_EXT = {".py"}
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
SWAP = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
ASSET_EXT = {".css", ".scss", ".sass", ".less", ".json", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
             ".html", ".txt", ".md", ".wasm", ".vue", ".svelte", ".yml", ".yaml", ".csv", ".woff", ".woff2"}
MAX_FILES = 2500
MAX_FILE_BYTES = 1_000_000
MAX_JS_BYTES = 400_000
MAX_SECONDS = 20.0
RANK = {"static": 2, "lazy": 1, "type": 0}
Edges = dict[tuple[str, str], str]


@dataclass
class Graph:
    nodes: list[str] = field(default_factory=list)  # relative paths, sorted
    edges: Edges = field(default_factory=dict)
    languages: dict[str, str] = field(default_factory=dict)  # path -> "py" | "js"
    external: int = 0  # imports of packages and the standard library
    unresolved: int = 0  # relative imports that match no file in the folder
    errors: list[str] = field(default_factory=list)  # files that could not be read or parsed
    truncated: dict[str, int] = field(default_factory=dict)  # files / large / time: how many were left out

    def summary(self) -> dict[str, Any]:
        kinds = {k: sum(1 for v in self.edges.values() if v == k) for k in RANK}
        return {"modules": len(self.nodes), "python": sum(1 for v in self.languages.values() if v == "py"),
                "javascript": sum(1 for v in self.languages.values() if v == "js"), "edges": len(self.edges), **kinds,
                "external": self.external, "unresolved": self.unresolved, "errors": len(self.errors),
                "truncated": dict(self.truncated)}


def source_files(root: Path) -> list[tuple[str, Path, str]]:
    """(relative path, absolute path, language) of every source file, in path order, skipping what is never read."""
    found: list[tuple[str, Path, str]] = []
    top = root.resolve()
    for folder, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".") and not d.endswith(".egg-info"))
        for name in sorted(files):
            suffix = os.path.splitext(name)[1].lower()
            lang = "py" if suffix in PY_EXT else "js" if suffix in JS_EXT else ""
            if not lang or name.startswith("."):
                continue
            path = Path(folder) / name
            if path.is_symlink():
                try:
                    inside = top in path.resolve().parents
                except (OSError, RuntimeError):
                    inside = False
                if not inside:
                    continue
            found.append((path.relative_to(top).as_posix(), path, lang))
    return sorted(found)


class PyImports(ast.NodeVisitor):
    """Imports of one module with their kind: `type` under TYPE_CHECKING, `lazy` inside a function, else `static`."""

    def __init__(self) -> None:
        self.found: list[tuple[int, list[str], list[str], str]] = []  # (level, module parts, names, kind)
        self.depth = 0
        self.typing = 0

    def kind(self) -> str:
        return "type" if self.typing else "lazy" if self.depth else "static"

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.found.append((0, alias.name.split("."), [], self.kind()))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.found.append((node.level, node.module.split(".") if node.module else [],
                           [a.name for a in node.names], self.kind()))

    def function(self, node: ast.AST) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = function  # noqa: N815

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        test = node.test
        guard = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        if not guard:
            self.generic_visit(node)
            return
        self.typing += 1
        for child in node.body:
            self.visit(child)
        self.typing -= 1
        for child in node.orelse:
            self.visit(child)


def stronger(edges: Edges, edge: tuple[str, str], kind: str) -> None:
    """Record an edge unless it is a module importing itself; keep the strongest kind of a pair."""
    if edge[0] != edge[1] and (edge not in edges or RANK[kind] > RANK[edges[edge]]):
        edges[edge] = kind


class Resolver:
    """Finds the file an import means, among the files read."""

    def __init__(self, nodes: set[str], package: str = ""):
        self.files = nodes
        self.package = package if "__init__.py" in nodes else ""  # the folder is itself a package, named like this
        py = {n for n in nodes if n.endswith(".py")}
        self.packages = {posixpath.dirname(n) for n in py if posixpath.basename(n) == "__init__.py"}
        self.roots = sorted({""} | {posixpath.dirname(p) for p in self.packages if posixpath.dirname(p) not in self.packages},
                            key=lambda r: (r.count("/") + bool(r), r))

    def module(self, base: str) -> str | None:
        """The file for a module path without extension: base.py or base/__init__.py."""
        for candidate in (f"{base}.py", posixpath.join(base, "__init__.py")):
            if candidate in self.files:
                return candidate
        return None

    def absolute(self, parts: list[str], importer: str) -> str | None:
        folder = posixpath.dirname(importer)
        roots = list(self.roots)
        if folder not in self.packages and parts[0] not in sys.stdlib_module_names:
            roots.insert(0, folder)  # a script finds its neighbours
        for root in roots:
            found = self.module(posixpath.join(root, *parts))
            if found:
                return found
        if self.package and parts[0] == self.package:  # the scanned folder is the package: `import spike.x` inside spike/
            return self.module(posixpath.join(*parts[1:])) if len(parts) > 1 else self.init("")
        return None

    def init(self, folder: str) -> str | None:
        path = posixpath.join(folder, "__init__.py")
        return path if path in self.files else None

    @staticmethod
    def package_dir(base: str | None) -> str | None:
        """The folder of a package's `__init__.py` (where its submodules are), None for a plain module or no file."""
        return posixpath.dirname(base) if base and posixpath.basename(base) == "__init__.py" else None

    def python(self, importer: str, level: int, parts: list[str], names: list[str]) -> tuple[list[str], str]:
        """(files imported, "ok" | "external" | "unresolved") for one import statement."""
        if level:
            folder = posixpath.dirname(importer)
            for _ in range(level - 1):
                if not folder:
                    return [], "unresolved"  # above the folder
                folder = posixpath.dirname(folder)
            base = self.module(posixpath.join(folder, *parts)) if parts else self.init(folder)
            package_dir = self.package_dir(base) if parts else folder
            missing = "unresolved"
        else:
            base = self.absolute(parts, importer)
            package_dir = self.package_dir(base)
            missing = "external"
        hits = set()
        for name in names:  # `from pkg import name`: the submodule if there is one, else the package itself
            sub = self.module(posixpath.join(package_dir, name)) if package_dir is not None and name != "*" else None
            if sub or base:
                hits.add(sub or base)
        if not names and base:
            hits.add(base)
        return sorted(hits), ("ok" if hits else missing)

    def javascript(self, importer: str, spec: str) -> tuple[str | None, str]:
        if not (spec.startswith(("./", "../")) or spec in (".", "..")):
            return None, "external"
        base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
        if base == ".." or base.startswith("../"):
            return None, "unresolved"
        base = "" if base == "." else base
        ext = posixpath.splitext(base)[1].lower()
        candidates = [base] if ext in JS_EXT else []
        if ext in SWAP:
            candidates += [base[:-len(ext)] + e for e in SWAP[ext]]
        candidates += [base + e for e in JS_EXT] + [posixpath.join(base, "index" + e) for e in JS_EXT]
        for candidate in candidates:
            if candidate in self.files:
                return candidate, "ok"
        return None, "ignored" if ext in ASSET_EXT else "unresolved"


def scan(root: Path) -> Graph:
    """The module graph of the folder `root`."""
    graph = Graph()
    files = source_files(root)
    if len(files) > MAX_FILES:
        graph.truncated["files"] = len(files)
        files = files[:MAX_FILES]
    deadline = time.monotonic() + MAX_SECONDS
    parsed: list[tuple[str, str, Any]] = []  # (path, language, raw imports)
    large = late = 0
    for rel, path, lang in files:
        try:
            size = path.stat().st_size
        except OSError:
            graph.errors.append(f"{rel}: cannot be read")
            continue
        if size > MAX_FILE_BYTES or (lang == "js" and size > MAX_JS_BYTES):
            large += 1
            continue
        if time.monotonic() > deadline:
            late += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            graph.errors.append(f"{rel}: cannot be read")
            continue
        if lang == "py":
            try:
                visitor = PyImports()
                visitor.visit(ast.parse(text, rel))
                raw: Any = visitor.found
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                graph.errors.append(f"{rel}: {exc.__class__.__name__}: {str(exc)[:80]}")
                raw = []
        else:
            raw = js_imports(text)
        parsed.append((rel, lang, raw))
    if large:
        graph.truncated["large"] = large
    if late:
        graph.truncated["time"] = late
    graph.nodes = sorted(rel for rel, _, _ in parsed)
    graph.languages = {rel: lang for rel, lang, _ in parsed}
    resolver = Resolver(set(graph.nodes), root.resolve().name)
    for rel, lang, raw in parsed:
        if lang == "py":
            for level, parts, names, kind in raw:
                hits, status = resolver.python(rel, level, parts, names)
                for hit in hits:
                    stronger(graph.edges, (rel, hit), kind)
                if status == "external":
                    graph.external += 1
                elif status == "unresolved":
                    graph.unresolved += 1
        else:
            for spec, kind in raw:
                hit, status = resolver.javascript(rel, spec)
                if hit:
                    stronger(graph.edges, (rel, hit), kind)
                elif status == "external":
                    graph.external += 1
                elif status == "unresolved":
                    graph.unresolved += 1
    return graph
