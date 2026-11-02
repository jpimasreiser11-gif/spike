"""Import cycles: Tarjan's strongly connected components (iterative, so a 20,000-module chain does not hit Python's
recursion limit), the components that are cycles, and one real way round each.

An edge has a kind: `static` (runs when the module is imported), `lazy` (inside a function, or a dynamic `import()`)
or `type` (only under `TYPE_CHECKING` or `import type`, erased at run time). A cycle that exists only through lazy or
type edges is how projects break a real cycle on purpose, so by default only static edges count; `lazy=True` counts all."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

Edges = dict[tuple[str, str], str]


@dataclass
class Cycle:
    members: list[str]  # every module of the component, sorted
    path: list[str]  # the shortest way round through the first member: a -> b -> a


def strongly_connected(nodes: Iterable[str], adj: dict[str, list[str]]) -> list[list[str]]:
    """Every strongly connected component (single modules too), members sorted, in the order Tarjan finishes them."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for start in sorted(nodes):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(sorted(adj.get(start, ()))))]
        while work:
            v, neighbours = work[-1]
            descended = False
            for w in neighbours:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(adj.get(w, ())))))
                    descended = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                component = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == v:
                        break
                out.append(sorted(component))
    return out


def adjacency(nodes: Iterable[str], edges: Edges, lazy: bool = True) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for (src, dst), kind in edges.items():
        if lazy or kind == "static":
            adj.setdefault(src, []).append(dst)
    return {k: sorted(v) for k, v in adj.items()}


def way_round(start: str, members: set[str], adj: dict[str, list[str]]) -> list[str]:
    """The shortest path start -> ... -> start inside a component (breadth first, neighbours in name order)."""
    parent: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        v = queue.popleft()
        for w in adj.get(v, ()):
            if w == start:
                path = [v]
                while parent[path[-1]] is not None:
                    path.append(parent[path[-1]])  # type: ignore[arg-type]
                return [*reversed(path), start] if v != start else [start, start]
            if w in members and w not in parent:
                parent[w] = v
                queue.append(w)
    return [start, start]


def find_cycles(nodes: Iterable[str], edges: Edges, lazy: bool = False) -> list[Cycle]:
    """The import cycles, biggest first (then by name): components of two or more modules, and modules that import
    themselves. `lazy` also follows lazy and type-only imports."""
    nodes = list(nodes)
    adj = adjacency(nodes, edges, lazy)
    cycles = []
    for component in strongly_connected(nodes, adj):
        if len(component) > 1 or component[0] in adj.get(component[0], ()):
            cycles.append(Cycle(component, way_round(component[0], set(component), adj)))
    return sorted(cycles, key=lambda c: (-len(c.members), c.members[0]))
