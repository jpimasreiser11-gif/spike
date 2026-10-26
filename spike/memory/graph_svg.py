"""The knowledge graph as one SVG picture: plain markup, no scripts, no external files, drawn by this module.

Entities are shapes by kind (circle name, diamond e-mail, square date, hexagon quantity, triangle link) and notes are
rounded rectangles; size grows with how often something is mentioned. Solid lines are notes mentioning entities and
confirmed relations (with their label), dotted lines are entities that appear in the same notes and links between
notes, dashed lines are relations a model proposed and the user has not confirmed. The layout is a small
force-directed one with fixed starting points and a fixed number of steps, so the same graph always draws the same.
Colours come from the stylesheet inside the picture and follow the viewer's light or dark setting.
"""

from __future__ import annotations

import math
import re
from typing import Any
from xml.sax.saxutils import escape

WIDTH, HEIGHT, MARGIN = 960, 640, 70
STEPS = 220
LABEL_CHARS = 26
XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

TEXT = {
    "es": {"title": "Grafo de la memoria", "empty": "Todavía no hay entidades en la memoria.", "name": "Nombre",
           "email": "Correo", "date": "Fecha", "quantity": "Cantidad", "link": "Enlace", "note": "Nota",
           "relation": "relación confirmada", "proposed": "relación propuesta, sin confirmar",
           "cooccur": "aparecen en las mismas notas", "shared": "notas con entidades en común",
           "mentions": "la nota menciona", "mentioned": "veces", "desc": "{n} elementos y {e} conexiones"},
    "en": {"title": "Memory graph", "empty": "There are no entities in memory yet.", "name": "Name",
           "email": "E-mail", "date": "Date", "quantity": "Quantity", "link": "Link", "note": "Note",
           "relation": "confirmed relation", "proposed": "proposed relation, not confirmed",
           "cooccur": "appear in the same notes", "shared": "notes sharing entities",
           "mentions": "the note mentions", "mentioned": "times", "desc": "{n} items and {e} connections"},
}
STYLE = """
:root{--bg:#ffffff;--fg:#1b1f23;--muted:#5d6672;--line:#9aa4b0;--name:#2f6fdd;--email:#0f8f82;--date:#b76e00;
--quantity:#7a4fd8;--link:#5f6b7a;--note:#445063;--rel:#1b1f23;--prop:#c2410c}
@media (prefers-color-scheme:dark){:root{--bg:#14181d;--fg:#e8ebee;--muted:#a3adb8;--line:#566170;--name:#7fb0ff;
--email:#4fd1c5;--date:#f0b44c;--quantity:#b9a2f7;--link:#a7b1be;--note:#b5c0cf;--rel:#e8ebee;--prop:#fb923c}}
.bg{fill:var(--bg)}.t{font:12px system-ui,sans-serif;fill:var(--fg);paint-order:stroke;stroke:var(--bg);stroke-width:3px}
.m{fill:var(--muted)}.h{font:600 15px system-ui,sans-serif;fill:var(--fg)}
.k-name{fill:var(--name)}.k-email{fill:var(--email)}.k-date{fill:var(--date)}.k-quantity{fill:var(--quantity)}
.k-link{fill:var(--link)}.note{fill:var(--bg);stroke:var(--note);stroke-width:1.5}.focus{stroke:var(--fg);stroke-width:3}
.e{stroke:var(--line);stroke-width:1.2;fill:none}.e-cooccur{stroke-dasharray:1 4;stroke-linecap:round}
.e-shared{stroke-dasharray:1 4;stroke-linecap:round}.e-relation{stroke:var(--rel);stroke-width:2}
.e-proposed{stroke:var(--prop);stroke-width:2;stroke-dasharray:7 5}
"""


def clean(text: str) -> str:
    return XML_BAD.sub("", text)


def short(text: str, n: int = LABEL_CHARS) -> str:
    text = " ".join(clean(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def layout(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], focus: str | None) -> dict[str, tuple[float, float]]:
    """Positions in the picture: fixed start on a circle, then STEPS rounds of repulsion, attraction and cooling."""
    order = sorted(nodes, key=lambda n: (n["id"] != focus, n["type"], -n.get("weight", 0), n["id"]))
    ids = [n["id"] for n in order]
    if len(ids) == 1:
        return {ids[0]: (WIDTH / 2, HEIGHT / 2)}
    cx, cy = WIDTH / 2, HEIGHT / 2
    radius = min(WIDTH, HEIGHT) * 0.32
    pos: dict[str, list[float]] = {}
    ring = [i for i in ids if i != focus]
    for i, node_id in enumerate(ring):
        angle = 2 * math.pi * i / max(1, len(ring))
        pos[node_id] = [cx + radius * math.cos(angle), cy + radius * math.sin(angle)]
    if focus in ids:
        pos[focus] = [cx, cy]
    k = math.sqrt(WIDTH * HEIGHT / len(ids)) * 0.55
    links = [(e["source"], e["target"], 1 + math.log2(1 + e.get("weight", 1))) for e in edges
             if e["source"] in pos and e["target"] in pos]
    for step in range(STEPS):
        heat = (WIDTH / 8) * (1 - step / STEPS) + 0.5
        move = {i: [0.0, 0.0] for i in ids}
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                dx, dy = pos[ids[a]][0] - pos[ids[b]][0], pos[ids[a]][1] - pos[ids[b]][1]
                dist = math.hypot(dx, dy) or 0.01
                push = k * k / dist
                move[ids[a]][0] += dx / dist * push
                move[ids[a]][1] += dy / dist * push
                move[ids[b]][0] -= dx / dist * push
                move[ids[b]][1] -= dy / dist * push
        for s, t, w in links:
            dx, dy = pos[s][0] - pos[t][0], pos[s][1] - pos[t][1]
            dist = math.hypot(dx, dy) or 0.01
            pull = dist * dist / k * w * 0.5
            move[s][0] -= dx / dist * pull
            move[s][1] -= dy / dist * pull
            move[t][0] += dx / dist * pull
            move[t][1] += dy / dist * pull
        for i in ids:
            if i == focus:
                continue
            move[i][0] += (cx - pos[i][0]) * 0.02  # a little gravity keeps loose pieces near
            move[i][1] += (cy - pos[i][1]) * 0.02
            size = math.hypot(*move[i]) or 0.01
            pos[i][0] += move[i][0] / size * min(size, heat)
            pos[i][1] += move[i][1] / size * min(size, heat)
    xs, ys = [p[0] for p in pos.values()], [p[1] for p in pos.values()]
    span_x, span_y = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
    scale = min((WIDTH - 2 * MARGIN) / span_x, (HEIGHT - 2 * MARGIN - 40) / span_y)
    mid_x, mid_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return {i: (round(WIDTH / 2 + (p[0] - mid_x) * scale, 1), round(HEIGHT / 2 - 15 + (p[1] - mid_y) * scale, 1))
            for i, p in pos.items()}


def shape(kind: str, node_type: str, x: float, y: float, r: float, css: str, tip: str) -> str:
    title = f"<title>{escape(tip)}</title>"
    if node_type == "note":
        return (f'<rect class="note {css}" x="{x - r * 1.5:.1f}" y="{y - r * 0.8:.1f}" width="{r * 3:.1f}" '
                f'height="{r * 1.6:.1f}" rx="5">{title}</rect>')
    if kind == "email":
        return (f'<polygon class="k-email {css}" points="{x:.1f},{y - r * 1.2:.1f} {x + r * 1.2:.1f},{y:.1f} '
                f'{x:.1f},{y + r * 1.2:.1f} {x - r * 1.2:.1f},{y:.1f}">{title}</polygon>')
    if kind == "date":
        return (f'<rect class="k-date {css}" x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" '
                f'rx="2">{title}</rect>')
    if kind == "quantity":
        pts = " ".join(f"{x + r * 1.15 * math.cos(math.pi / 3 * i):.1f},{y + r * 1.15 * math.sin(math.pi / 3 * i):.1f}"
                       for i in range(6))
        return f'<polygon class="k-quantity {css}" points="{pts}">{title}</polygon>'
    if kind == "link":
        return (f'<polygon class="k-link {css}" points="{x:.1f},{y - r * 1.2:.1f} {x + r * 1.1:.1f},{y + r:.1f} '
                f'{x - r * 1.1:.1f},{y + r:.1f}">{title}</polygon>')
    return f'<circle class="k-name {css}" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}">{title}</circle>'


def render_svg(data: dict[str, Any], lang: str = "en", title: str | None = None) -> str:
    """The graph (`Graph.graph` output) as an SVG document string."""
    words = TEXT["es" if lang == "es" else "en"]
    nodes, edges, focus = data.get("nodes", []), data.get("edges", []), data.get("focus")
    heading = short(title or words["title"], 80)
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" '
            f'style="display:block;max-width:{WIDTH}px" role="img" aria-labelledby="g-title g-desc">')
    if not nodes:
        return (f'{head}<title id="g-title">{escape(heading)}</title><desc id="g-desc">{escape(words["empty"])}</desc>'
                f'<style>{STYLE}</style><rect class="bg" width="{WIDTH}" height="{HEIGHT}"/>'
                f'<text class="h" x="{WIDTH / 2}" y="{HEIGHT / 2}" text-anchor="middle">{escape(words["empty"])}</text></svg>')
    pos = layout(nodes, edges, focus)
    out = [head, f'<title id="g-title">{escape(heading)}</title>',
           f'<desc id="g-desc">{escape(words["desc"].format(n=len(nodes), e=len(edges)))}</desc>',
           f"<style>{STYLE}</style>", f'<rect class="bg" width="{WIDTH}" height="{HEIGHT}"/>',
           f'<text class="h" x="16" y="26">{escape(heading)}</text>']
    for e in sorted(edges, key=lambda e: e["type"] != "relation"):
        if e["source"] not in pos or e["target"] not in pos:
            continue
        (x1, y1), (x2, y2) = pos[e["source"]], pos[e["target"]]
        kind = "proposed" if e.get("status") == "proposed" else e["type"]
        out.append(f'<line class="e e-{kind}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
        if e["type"] == "relation" and e.get("label"):
            out.append(f'<text class="t m" x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 4:.1f}" text-anchor="middle">'
                       f"{escape(short(e['label'], 30))}</text>")
    for n in nodes:
        x, y = pos[n["id"]]
        r = 7 + min(9.0, 2.2 * math.log2(1 + n.get("weight", 1)))
        label = clean(n["label"])
        tip = f"{label}\n{words.get(n['kind'], n['kind']) if n['type'] == 'entity' else words['note']}"
        if n["type"] == "entity" and n.get("weight"):
            tip += f" · {n['weight']} {words['mentioned']}"
        out.append(shape(n["kind"], n["type"], x, y, r, "focus" if n["id"] == focus else "", tip))
        out.append(f'<text class="t" x="{x:.1f}" y="{y + r + 14:.1f}" text-anchor="middle">{escape(short(label))}</text>')
    kinds = [k for k in ("name", "email", "date", "quantity", "link") if any(n["kind"] == k for n in nodes)]
    if any(n["type"] == "note" for n in nodes):
        kinds.append("note")
    x = 16
    for k in kinds:
        out.append(shape("name" if k == "note" else k, "note" if k == "note" else "entity", x + 8, HEIGHT - 34, 6, "",
                         words[k]))
        out.append(f'<text class="t m" x="{x + 22}" y="{HEIGHT - 30}">{escape(words[k])}</text>')
        x += 40 + 7 * len(words[k])
    used = {("proposed" if e.get("status") == "proposed" else e["type"]) for e in edges}
    x = 16
    for k in ("mentions", "relation", "proposed", "cooccur", "shared"):
        if k in used:
            out.append(f'<line class="e e-{k}" x1="{x}" y1="{HEIGHT - 14}" x2="{x + 24}" y2="{HEIGHT - 14}"/>')
            out.append(f'<text class="t m" x="{x + 30}" y="{HEIGHT - 10}">{escape(words[k])}</text>')
            x += 50 + 6 * len(words[k])
    out.append("</svg>")
    return "".join(out)

