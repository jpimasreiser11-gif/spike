"""Architecture Explorer (A16): the module graph of a folder from its Python and JavaScript/TypeScript imports, cycles
found with Tarjan's strongly connected components, and a deterministic SVG with the cycles highlighted. Offline."""

import json
import os
import re
from pathlib import Path
from xml.dom import minidom

import pytest

from spike.architecture import scan as scanmod
from spike.architecture.cycles import find_cycles, strongly_connected
from spike.architecture.jsimports import js_imports
from spike.architecture.render import render_graph
from spike.architecture.scan import scan
from spike.architecture.tools import ArchitectureGraph
from spike.tools.base import PermissionBroker
from spike.tools.builtin import Workspace


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def edges(graph, kind=None):
    return sorted(e for e, k in graph.edges.items() if kind in (None, k))


# ---------------------------------------------------------------- Tarjan
def test_tarjan_finds_every_strongly_connected_component():
    nodes = list("abcdefgh")
    adj = {"a": ["b"], "b": ["c"], "c": ["a", "d"], "d": ["e"], "e": ["f"], "f": ["d"], "g": ["g"], "h": []}
    comps = strongly_connected(nodes, adj)
    assert sorted(map(tuple, comps)) == [("a", "b", "c"), ("d", "e", "f"), ("g",), ("h",)]
    assert comps == strongly_connected(nodes, adj)  # the same graph gives the same order


def test_tarjan_does_not_recurse_so_a_long_chain_is_fine():
    n = 20_000
    nodes = [f"n{i}" for i in range(n)]
    adj = {f"n{i}": [f"n{i + 1}"] for i in range(n - 1)} | {f"n{n - 1}": ["n0"]}  # one huge cycle
    comps = strongly_connected(nodes, adj)
    assert len(comps) == 1 and len(comps[0]) == n


def test_cycles_are_the_components_with_more_than_one_module_or_a_self_import():
    nodes = ["a", "b", "c", "d", "e"]
    graph_edges = {("a", "b"): "static", ("b", "c"): "static", ("c", "a"): "static", ("c", "d"): "static",
                   ("e", "e"): "static"}
    cycles = find_cycles(nodes, graph_edges)
    assert [c.members for c in cycles] == [["a", "b", "c"], ["e"]]
    assert cycles[0].path == ["a", "b", "c", "a"]  # a real way round, in the direction of the imports
    assert cycles[1].path == ["e", "e"]


def test_the_cycle_path_is_the_shortest_way_back_to_the_first_module():
    graph_edges = {(a, b): "static" for a, b in [("a", "b"), ("b", "c"), ("c", "d"), ("d", "a"), ("b", "a")]}
    (cycle,) = find_cycles(list("abcd"), graph_edges)
    assert cycle.members == ["a", "b", "c", "d"] and cycle.path == ["a", "b", "a"]


def test_lazy_and_type_only_imports_do_not_make_a_cycle_unless_asked():
    graph_edges = {("a", "b"): "static", ("b", "a"): "lazy", ("b", "c"): "static", ("c", "b"): "type"}
    assert find_cycles(["a", "b", "c"], graph_edges) == []
    cycles = find_cycles(["a", "b", "c"], graph_edges, lazy=True)
    assert [c.members for c in cycles] == [["a", "b", "c"]]


# ---------------------------------------------------------------- Python imports
def test_python_imports_are_resolved_to_files_inside_the_folder(tmp_path):
    write(tmp_path, {
        "app/__init__.py": "",
        "app/main.py": "import os\nimport json\nfrom app import util\nfrom .models import User\nimport requests\n",
        "app/util.py": "import app.models\nfrom app.models import helper as h\n",
        "app/models.py": "from . import util\nfrom .. import outside\n",
        "app/sub/__init__.py": "from .leaf import thing\n",
        "app/sub/leaf.py": "from ..util import x\n",
        "tool.py": "import app.sub.leaf\nfrom app.sub import leaf\nfrom app import *\n",
    })
    graph = scan(tmp_path)
    assert graph.nodes == sorted(["app/__init__.py", "app/main.py", "app/util.py", "app/models.py",
                                  "app/sub/__init__.py", "app/sub/leaf.py", "tool.py"])
    got = set(graph.edges)
    assert ("app/main.py", "app/util.py") in got  # from app import util: a submodule, not the package
    assert ("app/main.py", "app/models.py") in got  # relative
    assert ("app/util.py", "app/models.py") in got and ("app/models.py", "app/util.py") in got
    assert ("app/sub/__init__.py", "app/sub/leaf.py") in got and ("app/sub/leaf.py", "app/util.py") in got
    assert ("tool.py", "app/sub/leaf.py") in got and ("tool.py", "app/__init__.py") in got  # import * -> the package
    assert not any(dst.startswith(("os", "json", "requests")) for _, dst in got)  # stdlib and packages are outside
    assert graph.external >= 3 and graph.unresolved == 1  # `from .. import outside` leaves the folder


def test_a_src_layout_and_scripts_resolve_like_python_does(tmp_path):
    write(tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "from pkg import b\n",
        "src/pkg/b.py": "from . import a\n",
        "scripts/run.py": "import helper\nimport json\n",
        "scripts/helper.py": "",
        "scripts/json.py": "",  # a script directory shadows the standard library: Python would not use it from a package
    })
    graph = scan(tmp_path)
    assert ("src/pkg/a.py", "src/pkg/b.py") in graph.edges and ("src/pkg/b.py", "src/pkg/a.py") in graph.edges
    assert ("scripts/run.py", "scripts/helper.py") in graph.edges
    assert ("scripts/run.py", "scripts/json.py") not in graph.edges  # a standard library name is not local


def test_scanning_a_package_folder_itself_resolves_its_own_name(tmp_path):
    pkg = tmp_path / "mypkg"
    write(pkg, {"__init__.py": "", "a.py": "import mypkg.b\nfrom mypkg import c\nimport mypkg\n", "b.py": "from mypkg.a import x\n",
                "c.py": "", "sub/__init__.py": "", "sub/d.py": "from mypkg.sub import d\nfrom mypkg.c import y\n"})
    got = set(scan(pkg).edges)
    assert {("a.py", "b.py"), ("b.py", "a.py"), ("a.py", "c.py"), ("a.py", "__init__.py"), ("sub/d.py", "c.py")} <= got
    assert find_cycles(scan(pkg).nodes, scan(pkg).edges)[0].members == ["a.py", "b.py"]


def test_python_import_kinds_runtime_lazy_and_type_checking(tmp_path):
    write(tmp_path, {
        "a.py": ("from __future__ import annotations\nimport typing\nfrom typing import TYPE_CHECKING\n"
                 "import b\nif TYPE_CHECKING:\n    import c\nif typing.TYPE_CHECKING:\n    import d\n"
                 "def f():\n    import e\n    return e\nclass K:\n    import f2\n"),
        "b.py": "", "c.py": "", "d.py": "", "e.py": "", "f2.py": "",
    })
    graph = scan(tmp_path)
    assert graph.edges == {("a.py", "b.py"): "static", ("a.py", "c.py"): "type", ("a.py", "d.py"): "type",
                           ("a.py", "e.py"): "lazy", ("a.py", "f2.py"): "static"}  # a class body runs at import time


def test_a_file_that_does_not_parse_is_reported_and_the_rest_still_works(tmp_path):
    write(tmp_path, {"good.py": "import other\n", "other.py": "", "bad.py": "def (:\n"})
    graph = scan(tmp_path)
    assert ("good.py", "other.py") in graph.edges and "bad.py" in graph.nodes
    assert len(graph.errors) == 1 and "bad.py" in graph.errors[0]


# ---------------------------------------------------------------- JavaScript and TypeScript imports
@pytest.mark.parametrize("source,expected", [
    ('import a from "./a";', [("./a", "static")]),
    ("import { a, b as c } from './b'", [("./b", "static")]),
    ('import * as ns from "./c"', [("./c", "static")]),
    ('import d, { e } from "./d"', [("./d", "static")]),
    ('import "./side-effect";', [("./side-effect", "static")]),
    ('import {\n  a,\n  b,\n} from "./multi";', [("./multi", "static")]),
    ('export * from "./re";', [("./re", "static")]),
    ('export * as x from "./re2";', [("./re2", "static")]),
    ('export { a, b } from "./re3";', [("./re3", "static")]),
    ('export { a, b };\nconst x = 1;', []),  # a local export has no module
    ('import type { T } from "./types";', [("./types", "type")]),
    ('export type { T } from "./types2";', [("./types2", "type")]),
    ('import type from "./named-type";', [("./named-type", "static")]),  # a default import called `type`
    ('const m = await import("./lazy");', [("./lazy", "lazy")]),
    ('import("./lazy2").then(f)', [("./lazy2", "lazy")]),
    ('const name = "x"; import(name)', []),  # not a string literal: cannot be followed
    ('const a = require("./cjs");', [("./cjs", "static")]),
    ("const a = require('./cjs2'), b = require('./cjs3')", [("./cjs2", "static"), ("./cjs3", "static")]),
    ('import fs = require("./ts-style");', [("./ts-style", "static")]),
    ('obj.require("./no"); obj.import("./no2"); require.resolve("./no3"); require(name)', []),
    ('import.meta.url; import x from "pkg"', [("pkg", "static")]),
])
def test_js_import_forms(source, expected):
    assert js_imports(source) == expected


def test_js_imports_ignore_comments_strings_templates_and_regexes():
    source = '''
// import a from "./commented"
/* import b from "./block"; require("./block2") */
const s = 'import c from "./in-string"';
const t = `import d from "./in-template" ${ require("./not-code-we-follow-but-fine") }`;
const r = /import e from "\\/x"/.test(s);
const q = a / b; const u = "it's";
import real from "./real";
const msg = "don't" + require("./after-apostrophe");
'''
    found = [spec for spec, _ in js_imports(source)]
    assert "./real" in found and "./after-apostrophe" in found
    for ghost in ("./commented", "./block", "./block2", "./in-string", "./in-template"):
        assert ghost not in found


def test_js_files_are_resolved_with_extensions_index_files_and_the_ts_js_swap(tmp_path):
    write(tmp_path, {
        "web/index.js": ('import { x } from "./lib/x.js";\nconst y = require("./lib/y");\nimport("./lib/z");\n'
                         'import dir from "./dir";\nimport "react";\nimport q from "../../escape";\n'),
        "web/lib/x.ts": "export const x = 1;\n",  # TS projects import ./x.js and mean ./x.ts
        "web/lib/y.cjs": "",
        "web/lib/z.tsx": "import type { A } from '../index'\n",
        "web/dir/index.ts": "",
        "node_modules/dep/index.js": 'import "../../web/index.js";\n',
        ".venv/lib/mod.py": "import web\n",
        ".git/hooks.js": "",
        "build/out.js": "",
        "dist/bundle.js": "",
        "web/__pycache__/x.py": "",
    })
    graph = scan(tmp_path)
    assert graph.nodes == ["web/dir/index.ts", "web/index.js", "web/lib/x.ts", "web/lib/y.cjs", "web/lib/z.tsx"]
    assert graph.edges == {("web/index.js", "web/lib/x.ts"): "static", ("web/index.js", "web/lib/y.cjs"): "static",
                           ("web/index.js", "web/lib/z.tsx"): "lazy", ("web/index.js", "web/dir/index.ts"): "static",
                           ("web/lib/z.tsx", "web/index.js"): "type"}
    assert graph.external == 1 and graph.unresolved == 1  # "react", and a path that leaves the folder


def test_a_js_cycle_is_found_and_python_and_js_graphs_live_side_by_side(tmp_path):
    write(tmp_path, {"a.js": 'import "./b"', "b.js": 'import "./c"', "c.js": 'import "./a"', "p.py": "import q",
                     "q.py": ""})
    graph = scan(tmp_path)
    cycles = find_cycles(graph.nodes, graph.edges)
    assert [c.members for c in cycles] == [["a.js", "b.js", "c.js"]]


# ---------------------------------------------------------------- limits
def test_size_limits_are_reported(tmp_path, monkeypatch):
    write(tmp_path, {f"m{i}.py": "" for i in range(5)} | {"big.py": "x = 1\n" + "# pad\n" * 50})
    monkeypatch.setattr(scanmod, "MAX_FILES", 4)
    graph = scan(tmp_path)
    assert len(graph.nodes) == 4 and graph.truncated["files"] == 6  # the first 4 in path order, of 6
    monkeypatch.setattr(scanmod, "MAX_FILES", 100)
    monkeypatch.setattr(scanmod, "MAX_FILE_BYTES", 100)
    graph = scan(tmp_path)
    assert "big.py" not in graph.nodes and graph.truncated == {"large": 1}
    monkeypatch.setattr(scanmod, "MAX_FILE_BYTES", 1_000_000)
    monkeypatch.setattr(scanmod, "MAX_SECONDS", -1)
    graph = scan(tmp_path)
    assert graph.truncated.get("time") and len(graph.nodes) < 6


def test_a_symlink_that_leaves_the_folder_is_not_read(tmp_path):
    outside = tmp_path / "outside"
    inside = tmp_path / "inside"
    write(outside, {"secret.py": "import os\n"})
    write(inside, {"ok.py": ""})
    try:
        (inside / "link.py").symlink_to(outside / "secret.py")
        (inside / "dirlink").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert scan(inside).nodes == ["ok.py"]


# ---------------------------------------------------------------- the picture
def project(tmp_path):
    return write(tmp_path, {
        "app/__init__.py": "", "app/main.py": "from app import util\nfrom app import solo\nfrom app import lazy\n",
        "app/util.py": "from app import models\n", "app/models.py": "from app import util\n",
        "app/lazy.py": "def f():\n    from app import main\n", "app/solo.py": "",
        "web/a.js": 'import "./b"', "web/b.js": 'import "./a"',
    })


def test_the_svg_is_deterministic_well_formed_and_highlights_the_cycles(tmp_path):
    graph = scan(project(tmp_path))
    cycles = find_cycles(graph.nodes, graph.edges)
    assert [c.members for c in cycles] == [["app/models.py", "app/util.py"], ["web/a.js", "web/b.js"]]
    svg = render_graph(graph, cycles, title="demo", lang="en")
    assert svg == render_graph(graph, cycles, title="demo", lang="en")
    minidom.parseString(svg)
    assert len(re.findall(r'<path class="edge cycle"[^>]*><title>', svg)) == 4  # util<->models, a<->b (not the key)
    assert svg.count('class="node cyc"') == 4 and svg.count('class="node"') == 4
    assert "app/util.py" in svg and "cycle" in svg.lower() and "<script" not in svg
    assert re.search(r'<path class="edge lazy"[^>]*><title>app/lazy.py', svg)  # lazy.py -> main: drawn, not a cycle
    assert "prefers-color-scheme:dark" in svg.replace(" ", "")
    es = render_graph(graph, cycles, title="demo", lang="es")
    assert "ciclo" in es.lower() and es != svg


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_legend_fits_inside_a_small_picture(tmp_path, lang):
    # found in the browser: a two-module graph is as narrow as the minimum width, and the legend ran past its right edge
    graph = scan(write(tmp_path, {"a.py": "import b\n", "b.py": ""}))
    svg = render_graph(graph, [], lang=lang)
    width = int(re.search(r'viewBox="0 0 (\d+) ', svg).group(1))
    legend = re.findall(r'<text class="m" x="(\d+)" y="53">([^<]*)</text>', svg)
    assert len(legend) == 5
    assert all(int(x) + 6 * len(text) <= width for x, text in legend), (width, legend)


def test_module_names_cannot_break_out_of_the_picture(tmp_path):
    if os.name == "nt":  # < > are not allowed in Windows file names; & is, and must still be escaped
        write(tmp_path, {"&a&.js": 'import "./&b&.js"', "&b&.js": ""})
    else:
        write(tmp_path, {"<script>alert(1)</script>.js": 'import "./&b&.js"', "&b&.js": ""})
    graph = scan(tmp_path)
    assert len(graph.nodes) == 2
    svg = render_graph(graph, find_cycles(graph.nodes, graph.edges))
    assert "&amp;b&amp;.js" in svg and "&b&" not in svg
    if os.name != "nt":
        assert "<script" not in svg and "&lt;script&gt;" in svg
    minidom.parseString(svg)


def test_a_big_graph_draws_the_cycles_first_and_says_what_it_left_out(tmp_path):
    files = {f"m{i:03d}.py": f"import m{i + 1:03d}\n" for i in range(150)} | {"m150.py": ""}
    files["z1.py"], files["z2.py"] = "import z2\n", "import z1\n"  # the cycle sorts last by name
    write(tmp_path, files)
    graph = scan(tmp_path)
    cycles = find_cycles(graph.nodes, graph.edges)
    svg = render_graph(graph, cycles, max_nodes=30, lang="en")
    assert "z1.py" in svg and "z2.py" in svg  # cycle members are drawn before anything else
    assert svg.count('class="node') == 30
    assert "Showing 30 of 153 modules" in svg
    minidom.parseString(svg)


def test_an_empty_folder_draws_a_message(tmp_path):
    graph = scan(tmp_path)
    assert graph.nodes == []
    svg = render_graph(graph, [], lang="en")
    assert "No Python or JavaScript" in svg
    minidom.parseString(svg)


# ---------------------------------------------------------------- the tool
@pytest.fixture
def ws(tmp_path):
    project(tmp_path / "proyecto")
    write(tmp_path, {"plain.py": ""})
    return Workspace(tmp_path)


async def test_the_tool_hands_the_picture_and_the_cycle_table_to_the_app(ws):
    tool = ArchitectureGraph(ws)
    assert tool.risk == "read" and tool.default_policy == "allow"
    assert PermissionBroker({}).policy_for_call(tool, {"path": "proyecto"})[0] == "allow"
    result = await tool.run({"path": "proyecto", "lang": "en"})
    assert result.ok and result.private
    ui = result.data["ui"]
    assert ui["kind"] == "architecture" and ui["svg"].startswith("<svg") and ui["title"] == "proyecto"
    assert ui["stats"]["modules"] == 8 and ui["stats"]["cycles"] == 2 and ui["stats"]["in_cycles"] == 4
    assert [c["members"] for c in ui["cycles"]] == [["app/models.py", "app/util.py"], ["web/a.js", "web/b.js"]]
    assert ui["cycles"][0]["path"] == ["app/models.py", "app/util.py", "app/models.py"]
    assert "app/models.py -> app/util.py -> app/models.py" in result.content
    assert "<svg" not in result.content
    lazy = await tool.run({"path": "proyecto", "lazy": True})
    assert lazy.data["ui"]["stats"]["cycles"] == 3  # main -> ... -> lazy.py -> main closes a third


async def test_the_tool_stays_in_the_workspace_and_reports_errors(ws):
    tool = ArchitectureGraph(ws)
    for args in ({"path": "../outside"}, {"path": "nope"}, {"path": "plain.py"}, {"path": "proyecto", "lang": "fr"},
                 {"path": "proyecto", "max_nodes": 5}, {"path": "proyecto", "lazy": "yes"}):
        result = await tool.run(args)
        assert not result.ok and result.content.startswith("error:"), args
    default = await tool.run({})  # the workspace itself
    assert default.ok and default.data["ui"]["stats"]["modules"] == 9


def test_the_graph_serialises_for_the_app(tmp_path):
    graph = scan(project(tmp_path))
    json.dumps(graph.summary())
    assert re.fullmatch(r"[\w./ -]+", graph.nodes[0])
