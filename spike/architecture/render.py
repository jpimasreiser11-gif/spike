"""The module graph as one SVG picture: plain markup, no scripts, no external files, drawn by this module.

Layout (layered, left to right): modules in an import cycle are one block, the blocks are ordered so that a module is
always to the left of what it imports (the longest import chain decides the column), and inside a column modules are
grouped by folder and then moved towards the middle of their neighbours (three fixed sweeps). Imports are curves with
an arrow; the ones that close a cycle are red and thick, those inside a function or only for types are dashed, and
modules in a cycle have a red outline. A blue stripe marks Python, an amber one JavaScript or TypeScript. At most
`max_nodes` modules are drawn (every module of a cycle first, then the most connected) and the picture says how many.
Colours come from the stylesheet inside the picture and follow the viewer's light or dark setting. The same graph
always draws the same."""

from __future__ import annotations

import posixpath
from collections import Counter, defaultdict
from xml.sax.saxutils import escape

from spike.architecture.cycles import Cycle, strongly_connected
from spike.architecture.scan import Graph
from spike.memory.graph_svg import clean, short

NODE_W, NODE_H, COL_GAP, ROW_H = 220, 20, 96, 26
MARGIN_X, TOP, FOOT = 28, 78, 64
MIN_WIDTH = 760
MIN_NODES, MAX_NODES, DEFAULT_NODES = 10, 200, 80
LABEL_CHARS = 34
LETTER_W, KEY_STEP, ARROW_STEP = 6.2, 24, 52  # the legend is laid out at about 6.2 px a letter of its 11 px text

TEXT = {
    "es": {"title": "Arquitectura del proyecto", "empty": "No se encontraron archivos de Python ni de JavaScript en esta carpeta.",
           "py": "Python", "js": "JavaScript / TypeScript", "imp": "importación", "lazy": "dentro de una función o solo de tipos",
           "cyc": "ciclo de importaciones", "showing": "Se muestran {n} de {m} módulos (primero los de ciclos, luego los más conectados).",
           "cycles": "{n} ciclos con {k} módulos.", "nocycles": "No hay ciclos de importaciones.", "imports": "importa", "by": "importado por",
           "files": "Solo se leyeron los primeros {n} de {m} archivos de código.", "large": "{n} archivos superan el tamaño máximo y no se leyeron.",
           "time": "La lectura se detuvo al agotar el tiempo: {n} archivos sin leer.", "desc": "{n} módulos y {e} importaciones"},
    "en": {"title": "Project architecture", "empty": "No Python or JavaScript source files were found in this folder.",
           "py": "Python", "js": "JavaScript / TypeScript", "imp": "import", "lazy": "inside a function or types only",
           "cyc": "import cycle", "showing": "Showing {n} of {m} modules (those in cycles first, then the most connected).",
           "cycles": "{n} cycles with {k} modules.", "nocycles": "No import cycles.", "imports": "imports", "by": "imported by",
           "files": "Only the first {n} of {m} source files were read.", "large": "{n} files over the size limit were not read.",
           "time": "Reading stopped at the time limit: {n} files were not read.", "desc": "{n} modules and {e} imports"},
}
STYLE = """
:root{--bg:#ffffff;--fg:#1b1f23;--muted:#5d6672;--line:#8b95a3;--node:#f1f4f8;--edge:#8b95a3;--cyc:#c0262d;
--cycbg:#fdecec;--py:#2f6fdd;--js:#b76e00}
@media (prefers-color-scheme:dark){:root{--bg:#14181d;--fg:#e8ebee;--muted:#a3adb8;--line:#566170;--node:#202830;
--edge:#7b8796;--cyc:#ff7b7f;--cycbg:#3a2226;--py:#7fb0ff;--js:#f0b44c}}
.bg{fill:var(--bg)}.h{font:600 15px system-ui,sans-serif;fill:var(--fg)}.m{font:11px system-ui,sans-serif;fill:var(--muted)}
.t{font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:var(--fg)}
.node rect.box{fill:var(--node);stroke:var(--line);stroke-width:1}.node.cyc rect.box{fill:var(--cycbg);stroke:var(--cyc);stroke-width:2}
.node rect.py{fill:var(--py)}.node rect.js{fill:var(--js)}.key rect.py{fill:var(--py)}.key rect.js{fill:var(--js)}
.edge{fill:none;stroke:var(--edge);stroke-width:1.2;opacity:.8}.edge.lazy{stroke-dasharray:5 4}
.edge.cycle{stroke:var(--cyc);stroke-width:2.4;opacity:1;stroke-dasharray:none}
.ah{fill:var(--edge)}.ah.cyc{fill:var(--cyc)}
"""


def labels(paths: list[str]) -> dict[str, str]:
    """The shortest tail of each path that is unique among them (an `__init__.py` keeps its folder)."""
    out: dict[str, str] = {}
    for depth in range(1, 40):
        tails = {p: "/".join(p.split("/")[-max(depth, 2 if posixpath.basename(p).startswith("__init__") else 1):])
                 for p in paths if p not in out}
        count = Counter(tails.values())
        for p, tail in tails.items():
            if count[tail] == 1 or depth >= p.count("/") + 1:
                out[p] = tail
        if len(out) == len(paths):
            break
    return out


def cycle_edges(edges: dict[tuple[str, str], str], cycles: list[Cycle], lazy: bool) -> set[tuple[str, str]]:
    group = {m: i for i, c in enumerate(cycles) for m in c.members}
    return {(a, b) for (a, b), kind in edges.items()
            if a != b and a in group and group[a] == group.get(b) and (lazy or kind == "static")}


def choose(graph: Graph, cycles: list[Cycle], max_nodes: int) -> list[str]:
    """The modules to draw: cycle members first (biggest cycle first), then by how connected they are."""
    where = {m: i for i, c in enumerate(cycles) for m in c.members}
    degree: Counter[str] = Counter()
    for a, b in graph.edges:
        degree[a] += 1
        degree[b] += 1
    ranked = sorted(graph.nodes, key=lambda n: (n not in where, where.get(n, 0), -degree[n], n))
    return sorted(ranked[:max_nodes])


def layers(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Column of each module: the length of the longest import chain that reaches it (a cycle is one block)."""
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    comps = strongly_connected(nodes, adj)  # Tarjan emits a block after everything it imports
    block = {m: i for i, c in enumerate(comps) for m in c}
    preds: dict[int, set[int]] = defaultdict(set)
    for a, b in edges:
        if block[a] != block[b]:
            preds[block[b]].add(block[a])
    column: dict[int, int] = {}
    for i in range(len(comps) - 1, -1, -1):  # importers before what they import
        column[i] = 1 + max(column[p] for p in preds[i]) if preds[i] else 0
    return {m: column[block[m]] for m in nodes}


def order(nodes: list[str], column: dict[str, int], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Row of each module inside its column: by folder first, then three sweeps towards the neighbours' middle."""
    cols: dict[int, list[str]] = defaultdict(list)
    for n in sorted(nodes, key=lambda p: (posixpath.dirname(p), p)):
        cols[column[n]].append(n)
    row = {n: i for c in cols.values() for i, n in enumerate(c)}
    before: dict[str, list[str]] = defaultdict(list)
    after: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        if column[a] < column[b]:
            before[b].append(a)
            after[a].append(b)
    top = max(cols, default=0)
    for sweep in ("forward", "backward", "forward"):
        for c in range(top + 1) if sweep == "forward" else range(top, -1, -1):
            use = before if sweep == "forward" else after
            home = {n: i for i, n in enumerate(cols[c])}
            cols[c].sort(key=lambda n: (sum(row[m] for m in use[n]) / len(use[n]) if use[n] else row[n], home[n]))
            row.update({n: i for i, n in enumerate(cols[c])})
    return row


def legend_width(words: dict[str, str]) -> int:
    """How far the one-line legend reaches, so that a small graph's picture is at least that wide (it would be cut off)."""
    return (MARGIN_X + sum(KEY_STEP + int(LETTER_W * len(words[k])) for k in ("py", "js"))
            + sum(ARROW_STEP + int(LETTER_W * len(words[k])) for k in ("imp", "lazy", "cyc")))


def render_graph(graph: Graph, cycles: list[Cycle], title: str = "", lang: str = "en", max_nodes: int = DEFAULT_NODES,
                 lazy: bool = False) -> str:
    """The graph as an SVG document string; `cycles` are what `find_cycles` found (with the same `lazy`)."""
    words = TEXT["es" if lang == "es" else "en"]
    heading = short(title or words["title"], 80)
    head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" style="display:block;max-width:{w}px" '
            'role="img" aria-labelledby="a-title a-desc">')
    if not graph.nodes:
        w, h = MIN_WIDTH, 200
        return (head.format(w=w, h=h) + f'<title id="a-title">{escape(heading)}</title><desc id="a-desc">{escape(words["empty"])}</desc>'
                f'<style>{STYLE}</style><rect class="bg" width="{w}" height="{h}"/>'
                f'<text class="h" x="{MARGIN_X}" y="40">{escape(heading)}</text>'
                f'<text class="m" x="{MARGIN_X}" y="80">{escape(words["empty"])}</text></svg>')
    max_nodes = max(MIN_NODES, min(MAX_NODES, int(max_nodes)))
    shown = choose(graph, cycles, max_nodes)
    keep = set(shown)
    edges = sorted((a, b) for a, b in graph.edges if a in keep and b in keep and a != b)
    column = layers(shown, edges)
    row = order(shown, column, edges)
    name = labels(shown)
    hot = cycle_edges(graph.edges, cycles, lazy)
    in_cycle = {m for c in cycles for m in c.members}
    depth = max(column.values()) + 1
    rows = max(Counter(column.values()).values())
    legend_x = MARGIN_X
    members = sum(len(c.members) for c in cycles)
    notes = [words["cycles"].format(n=len(cycles), k=members) if cycles else words["nocycles"]]
    if len(shown) < len(graph.nodes):
        notes.append(words["showing"].format(n=len(shown), m=len(graph.nodes)))
    for key in ("files", "large", "time"):
        if graph.truncated.get(key):
            notes.append(words[key].format(n=len(graph.nodes) if key == "files" else graph.truncated[key],
                                           m=graph.truncated[key]))
    width = max(MIN_WIDTH, 2 * MARGIN_X + depth * (NODE_W + COL_GAP) - COL_GAP + 60, legend_width(words))
    height = TOP + rows * ROW_H + FOOT + 16 * len(notes)

    def x_of(n: str) -> int:
        return MARGIN_X + column[n] * (NODE_W + COL_GAP)

    def y_of(n: str) -> int:
        return TOP + row[n] * ROW_H

    total_in, total_by = Counter(a for a, _ in graph.edges), Counter(b for _, b in graph.edges)
    out = ['<defs><marker id="a-n" viewBox="0 0 8 6" refX="7" refY="3" markerUnits="userSpaceOnUse" markerWidth="8" '
           'markerHeight="6" orient="auto"><path class="ah" d="M0,0L8,3L0,6z"/></marker>'
           '<marker id="a-c" viewBox="0 0 8 6" refX="7" refY="3" markerUnits="userSpaceOnUse" markerWidth="9" '
           'markerHeight="7" orient="auto"><path class="ah cyc" d="M0,0L8,3L0,6z"/></marker></defs>',
           f'<text class="h" x="{MARGIN_X}" y="28">{escape(heading)}</text>']
    # legend
    for kind, text in (("py", words["py"]), ("js", words["js"])):
        out.append(f'<g class="key"><rect class="{kind}" x="{legend_x}" y="42" width="4" height="14"/></g>'
                   f'<text class="m" x="{legend_x + 10}" y="53">{escape(text)}</text>')
        legend_x += KEY_STEP + int(LETTER_W * len(text))
    for klass, marker, text in (("edge", "a-n", words["imp"]), ("edge lazy", "a-n", words["lazy"]),
                                ("edge cycle", "a-c", words["cyc"])):
        out.append(f'<path class="{klass}" d="M{legend_x},49H{legend_x + 28}" marker-end="url(#{marker})"/>'
                   f'<text class="m" x="{legend_x + 36}" y="53">{escape(text)}</text>')
        legend_x += ARROW_STEP + int(LETTER_W * len(text))
    # edges first, so that the modules cover their ends
    for a, b in edges:
        kind = graph.edges[(a, b)]
        klass = "edge cycle" if (a, b) in hot else "edge lazy" if kind != "static" else "edge"
        marker = "a-c" if (a, b) in hot else "a-n"
        x1, y1, y2 = x_of(a) + NODE_W, y_of(a) + NODE_H // 2, y_of(b) + NODE_H // 2
        if column[a] == column[b]:  # inside a cycle: a loop on the right, coming back to the right edge of the target
            bulge = 34 + 5 * min(abs(row[a] - row[b]), 12)
            d = f"M{x1},{y1}C{x1 + bulge},{y1} {x1 + bulge},{y2} {x1},{y2}"
        else:
            x2 = x_of(b)
            dx = max(40, (x2 - x1) // 2)
            d = f"M{x1},{y1}C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}"
        out.append(f'<path class="{klass}" d="{d}" marker-end="url(#{marker})">'
                   f'<title>{escape(clean(a))} → {escape(clean(b))} ({kind})</title></path>')
    for n in shown:
        klass = "node cyc" if n in in_cycle else "node"
        tip = f"{clean(n)}\n{words['imports']}: {total_in[n]} · {words['by']}: {total_by[n]}"
        out.append(f'<g class="{klass}"><title>{escape(tip)}</title>'
                   f'<rect class="box" x="{x_of(n)}" y="{y_of(n)}" width="{NODE_W}" height="{NODE_H}" rx="4"/>'
                   f'<rect class="{graph.languages.get(n, "js")}" x="{x_of(n)}" y="{y_of(n)}" width="4" height="{NODE_H}"/>'
                   f'<text class="t" x="{x_of(n) + 10}" y="{y_of(n) + 14}">{escape(short(name[n], LABEL_CHARS))}</text></g>')
    foot = TOP + rows * ROW_H + 20
    for i, line in enumerate(notes):
        out.append(f'<text class="m" x="{MARGIN_X}" y="{foot + 16 * i}">{escape(line)}</text>')
    desc = words["desc"].format(n=len(graph.nodes), e=len(graph.edges))
    return (head.format(w=width, h=height) + f'<title id="a-title">{escape(heading)}</title><desc id="a-desc">{escape(desc)}</desc>'
            f'<style>{STYLE}</style><rect class="bg" width="{width}" height="{height}"/>' + "".join(out) + "</svg>")
