"""A knowledge graph over Neural Memory: entities, the notes that mention them, and relations between entities.

Everything is derived from the memories already stored, in the same SQLite file, and forgotten with them:

- `entities` and `mentions` come from `extract_entities` (names, e-mails, dates, quantities, links), a fixed set of
  patterns with no model. `sync()` reads the memories that are new or changed since the last time; deleting a memory
  deletes its mentions, and an entity nobody mentions or relates is removed with them (a trigger), so no name stays
  behind in the file.
- Links between notes are not stored: two notes that share an entity are linked at query time (entities that appear
  in more than `HUB_NOTES` notes are ignored for this, they would link everything).
- `relations` are the only stored edges: between two entities, with a label. A local model may *propose* them from
  one note (status `proposed`); nothing reaches the graph the user sees until they confirm it (`confirmed`); a
  rejected one is kept so it is not proposed again. The user can also add one by hand. A proposal belongs to the note
  it came from and goes when that note goes.

Queries take the memory scopes to look in (a project and the global scope), like search does.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from spike.memory.extract_entities import extract, fold
from spike.memory.store import MemoryStore

HUB_NOTES = 25  # an entity in more notes than this does not link notes together
MAX_EDGES = 160  # of one picture; stored relations are never the ones left out
MAX_LABEL = 60
STATUSES = ("proposed", "confirmed", "rejected")
SYNC_BATCH = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL, UNIQUE (kind, key)
);
CREATE TABLE IF NOT EXISTS mentions (
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  count INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (entity_id, memory_id)
);
CREATE INDEX IF NOT EXISTS mentions_memory ON mentions(memory_id);
CREATE TABLE IF NOT EXISTS relations (
  id TEXT PRIMARY KEY, src INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  dst INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, label TEXT NOT NULL, status TEXT NOT NULL,
  origin TEXT NOT NULL, scope TEXT NOT NULL, memory_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
  created REAL NOT NULL, UNIQUE (src, dst, label, scope)
);
CREATE TABLE IF NOT EXISTS graph_seen (
  memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE, updated REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS mentions_ad AFTER DELETE ON mentions BEGIN
  DELETE FROM entities WHERE id = old.entity_id AND NOT EXISTS (SELECT 1 FROM mentions WHERE entity_id = old.entity_id)
    AND NOT EXISTS (SELECT 1 FROM relations WHERE src = old.entity_id OR dst = old.entity_id);
END;
CREATE TRIGGER IF NOT EXISTS relations_ad AFTER DELETE ON relations BEGIN
  DELETE FROM entities WHERE id IN (old.src, old.dst) AND NOT EXISTS (SELECT 1 FROM mentions WHERE entity_id = entities.id)
    AND NOT EXISTS (SELECT 1 FROM relations WHERE src = entities.id OR dst = entities.id);
END;
"""


class GraphError(ValueError):
    """A request about the graph that cannot be honoured; the message is safe to show."""


def entity_node(r: sqlite3.Row, weight: int = 0) -> dict[str, Any]:
    return {"id": f"e:{r['id']}", "type": "entity", "kind": r["kind"], "label": r["name"], "weight": weight}


def note_node(r: sqlite3.Row) -> dict[str, Any]:
    first = " ".join(r["text"].split())
    return {"id": f"m:{r['id']}", "type": "note", "kind": r["kind"], "scope": r["scope"], "weight": 1,
            "label": first[:MAX_LABEL] + ("…" if len(first) > MAX_LABEL else ""), "source": r["source"]}


def _marks(values: list[Any]) -> str:
    return ",".join("?" * len(values))


class Graph:
    def __init__(self, store: MemoryStore):
        self.store = store
        with store.write() as db:
            db.executescript(SCHEMA)

    # ---------------------------------------------------------------- building it from memory
    def sync(self, limit: int | None = None) -> int:
        """Read the memories added or changed since the last time. Returns how many were read."""
        done = 0
        while limit is None or done < limit:
            with self.store.read() as db:
                rows = db.execute("SELECT m.id, m.text, m.updated FROM memories m LEFT JOIN graph_seen g "
                                  "ON g.memory_id = m.id WHERE g.memory_id IS NULL OR g.updated < m.updated "
                                  "LIMIT ?", (SYNC_BATCH,)).fetchall()
            if not rows:
                break
            for r in rows:
                self._read(r["id"], r["text"], r["updated"])
            done += len(rows)
        return done

    def _read(self, memory_id: str, text: str, updated: float) -> None:
        found = extract(text)
        with self.store.write() as db:
            db.execute("DELETE FROM mentions WHERE memory_id = ?", (memory_id,))
            for entity, count in found:
                db.execute("INSERT OR IGNORE INTO entities (kind, key, name) VALUES (?,?,?)",
                           (entity.kind, entity.key, entity.name))
                eid = db.execute("SELECT id FROM entities WHERE kind = ? AND key = ?",
                                 (entity.kind, entity.key)).fetchone()[0]
                db.execute("INSERT INTO mentions VALUES (?,?,?)", (eid, memory_id, count))
            db.execute("INSERT OR REPLACE INTO graph_seen VALUES (?,?)", (memory_id, updated))

    def stats(self, scopes: list[str]) -> dict[str, int]:
        with self.store.read() as db:
            ents = db.execute(f"SELECT COUNT(DISTINCT x.entity_id) FROM mentions x JOIN memories m ON m.id = x.memory_id "
                              f"WHERE m.scope IN ({_marks(scopes)})", scopes).fetchone()[0]
            rels = db.execute(f"SELECT COUNT(*) FROM relations WHERE status = 'confirmed' AND scope IN ({_marks(scopes)})",
                              scopes).fetchone()[0]
            props = db.execute(f"SELECT COUNT(*) FROM relations WHERE status = 'proposed' AND scope IN ({_marks(scopes)})",
                               scopes).fetchone()[0]
        return {"entities": ents, "relations": rels, "proposed": props}

    # ---------------------------------------------------------------- looking things up
    def entities(self, scopes: list[str], q: str | None = None, kind: str | None = None,
                 limit: int = 50) -> list[dict[str, Any]]:
        """The entities mentioned in these scopes, most mentioned (in most notes) first."""
        where, args = [f"m.scope IN ({_marks(scopes)})"], list(scopes)
        if q and fold(q):
            where.append("e.key LIKE ? ESCAPE '\\'")
            args.append("%" + fold(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if kind:
            where.append("e.kind = ?")
            args.append(kind)
        with self.store.read() as db:
            rows = db.execute(f"SELECT e.*, COUNT(DISTINCT x.memory_id) AS notes FROM entities e "
                              f"JOIN mentions x ON x.entity_id = e.id JOIN memories m ON m.id = x.memory_id "
                              f"WHERE {' AND '.join(where)} GROUP BY e.id ORDER BY notes DESC, e.key LIMIT ?",
                              (*args, limit)).fetchall()
        return [entity_node(r, r["notes"]) for r in rows]

    def graph(self, scopes: list[str], node: str | None = None, depth: int = 1, limit: int = 30,
              notes: bool = True, proposed: bool = False) -> dict[str, Any]:
        """Nodes and edges around `node` ("e:12" or "m:abc"), or the most mentioned entities when it is None."""
        if depth < 1 or depth > 3:
            raise GraphError("depth is 1 to 3")
        limit = max(2, min(limit, 80))
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[tuple, dict[str, Any]] = {}
        with self.store.read() as db:
            ctx = _Query(db, scopes, proposed)
            if node is None:
                for e in ctx.top_entities(limit):
                    nodes[e["id"]] = e
                ctx.link_entities(nodes, edges)
                if notes:
                    ctx.add_notes(nodes, edges, limit)
            else:
                if node not in ctx.known(node):
                    raise GraphError("that node is not in the graph")
                frontier = [node]
                nodes.update(ctx.nodes_of([node]))
                for _ in range(depth):
                    reached: list[str] = []
                    for current in frontier:
                        for other, edge in ctx.around(current, notes, limit):
                            if len(nodes) >= limit and other["id"] not in nodes:
                                continue
                            if other["id"] not in nodes:
                                reached.append(other["id"])
                            nodes.setdefault(other["id"], other)
                            edges.setdefault(_edge_key(edge), edge)
                    frontier = reached
                ctx.link_entities(nodes, edges)  # edges between the entities that ended up in the picture
        kept = sorted(edges.values(), key=lambda e: (e["type"] != "relation", -e["weight"], e["id"]))[:MAX_EDGES]
        return {"focus": node, "nodes": list(nodes.values()), "edges": kept}

    # ---------------------------------------------------------------- relations
    def relations(self, scopes: list[str], status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        where, args = [f"r.scope IN ({_marks(scopes)})"], list(scopes)
        if status:
            if status not in STATUSES:
                raise GraphError(f"status is one of {', '.join(STATUSES)}")
            where.append("r.status = ?")
            args.append(status)
        with self.store.read() as db:
            rows = db.execute(f"SELECT r.*, a.name AS a_name, a.kind AS a_kind, b.name AS b_name, b.kind AS b_kind "
                              f"FROM relations r JOIN entities a ON a.id = r.src JOIN entities b ON b.id = r.dst "
                              f"WHERE {' AND '.join(where)} ORDER BY r.created DESC LIMIT ?", (*args, limit)).fetchall()
        return [{"id": r["id"], "source": f"e:{r['src']}", "target": f"e:{r['dst']}", "from": r["a_name"],
                 "to": r["b_name"], "label": r["label"], "status": r["status"], "origin": r["origin"],
                 "scope": r["scope"], "memory": r["memory_id"]} for r in rows]

    def _entity_id(self, db: sqlite3.Connection, name: str, memory_id: str | None = None) -> int | None:
        """The entity called `name` (any kind), among the ones the note mentions when given."""
        sql = "SELECT e.id FROM entities e"
        args: list[Any] = [fold(name)]
        if memory_id:
            sql += " JOIN mentions x ON x.entity_id = e.id AND x.memory_id = ?"
            args.insert(0, memory_id)
        row = db.execute(sql + " WHERE e.key = ? ORDER BY (e.kind = 'name') DESC LIMIT 1", args).fetchone()
        return row[0] if row else None

    def propose(self, memory_id: str, items: list[tuple[str, str, str]], origin: str = "model") -> list[dict[str, Any]]:
        """Store relations `(entity, label, entity)` suggested for a note. Names must be entities the note mentions;
        anything else is dropped. A relation already there (in any status) is left as it is."""
        with self.store.read() as db:
            m = db.execute("SELECT scope FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if m is None:
            raise GraphError("memory not found")
        self.sync()
        saved: list[str] = []
        with self.store.write() as db:
            for a, label, b in items:
                label = " ".join(str(label).split())[:MAX_LABEL]
                src, dst = self._entity_id(db, str(a), memory_id), self._entity_id(db, str(b), memory_id)
                if not label or src is None or dst is None or src == dst:
                    continue
                rid = uuid.uuid4().hex[:12]
                cur = db.execute("INSERT OR IGNORE INTO relations VALUES (?,?,?,?,?,?,?,?,?)",
                                 (rid, src, dst, label, "proposed", origin, m["scope"], memory_id, time.time()))
                if cur.rowcount:
                    saved.append(rid)
        listed = {r["id"]: r for r in self.relations([m["scope"]], "proposed")}
        return [listed[rid] for rid in saved if rid in listed]  # in the order the model gave them

    def add_relation(self, scope: str, a: str, label: str, b: str) -> dict[str, Any]:
        """A relation the user writes by hand, between two entities by id (`e:12`) or name; confirmed at once."""
        label = " ".join(str(label).split())[:MAX_LABEL]
        if not label:
            raise GraphError("a relation needs a label")
        self.sync()
        with self.store.write() as db:
            ids = []
            for ref in (a, b):
                if ref.startswith("e:") and ref[2:].isdigit():
                    row = db.execute("SELECT id FROM entities WHERE id = ?", (int(ref[2:]),)).fetchone()
                    ids.append(row[0] if row else None)
                else:
                    ids.append(self._entity_id(db, ref))
            if None in ids or ids[0] == ids[1]:
                raise GraphError("both ends must be different entities that appear in memory")
            rid = uuid.uuid4().hex[:12]
            db.execute("INSERT INTO relations VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (src, dst, label, scope) "
                       "DO UPDATE SET status = 'confirmed' WHERE status != 'confirmed'",
                       (rid, ids[0], ids[1], label, "confirmed", "user", scope, None, time.time()))
            row = db.execute("SELECT id FROM relations WHERE src = ? AND dst = ? AND label = ? AND scope = ?",
                             (ids[0], ids[1], label, scope)).fetchone()
        return next(r for r in self.relations([scope]) if r["id"] == row[0])

    def set_status(self, relation_id: str, status: str) -> dict[str, Any] | None:
        if status not in STATUSES:
            raise GraphError(f"status is one of {', '.join(STATUSES)}")
        with self.store.write() as db:
            changed = db.execute("UPDATE relations SET status = ? WHERE id = ?", (status, relation_id)).rowcount
            row = db.execute("SELECT scope FROM relations WHERE id = ?", (relation_id,)).fetchone()
        if not changed or row is None:
            return None
        return next(r for r in self.relations([row["scope"]]) if r["id"] == relation_id)

    def delete_relation(self, relation_id: str) -> bool:
        with self.store.write() as db:
            return db.execute("DELETE FROM relations WHERE id = ?", (relation_id,)).rowcount > 0

    def delete_scope(self, scope: str | None) -> int:
        """Drop the relations of one scope (all for None); entities nobody mentions any more go with them."""
        with self.store.write() as db:
            if scope is None:
                return db.execute("DELETE FROM relations").rowcount
            return db.execute("DELETE FROM relations WHERE scope = ?", (scope,)).rowcount

    def note_entities(self, memory_id: str) -> list[str]:
        """Names of the entities a note mentions, most frequent first (what a model may relate)."""
        self.sync()
        with self.store.read() as db:
            rows = db.execute("SELECT e.name FROM mentions x JOIN entities e ON e.id = x.entity_id "
                              "WHERE x.memory_id = ? ORDER BY x.count DESC, e.key", (memory_id,)).fetchall()
        return [r[0] for r in rows]


def _edge_key(edge: dict[str, Any]) -> tuple:
    return (edge["type"], *sorted((edge["source"], edge["target"])), edge.get("label", ""))


class _Query:
    """The reads behind `Graph.graph`, on one connection and one set of scopes."""

    def __init__(self, db: sqlite3.Connection, scopes: list[str], proposed: bool):
        self.db, self.scopes, self.proposed = db, scopes, proposed
        self.statuses = ("confirmed", "proposed") if proposed else ("confirmed",)

    @property
    def in_scope(self) -> str:
        return f"m.scope IN ({_marks(self.scopes)})"

    def known(self, node: str) -> set[str]:
        kind, _, raw = node.partition(":")
        if kind == "e" and raw.isdigit():
            row = self.db.execute(f"SELECT 1 FROM entities e WHERE e.id = ? AND (EXISTS (SELECT 1 FROM mentions x "
                                  f"JOIN memories m ON m.id = x.memory_id WHERE x.entity_id = e.id AND {self.in_scope})"
                                  f" OR EXISTS (SELECT 1 FROM relations r WHERE (r.src = e.id OR r.dst = e.id) "
                                  f"AND r.scope IN ({_marks(self.scopes)})))", (int(raw), *self.scopes, *self.scopes)
                                  ).fetchone()
        elif kind == "m":
            row = self.db.execute(f"SELECT 1 FROM memories m WHERE m.id = ? AND {self.in_scope}",
                                  (raw, *self.scopes)).fetchone()
        else:
            row = None
        return {node} if row else set()

    def nodes_of(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for node in ids:
            kind, _, raw = node.partition(":")
            if kind == "e":
                r = self.db.execute(f"SELECT e.*, (SELECT COUNT(DISTINCT x.memory_id) FROM mentions x JOIN memories m "
                                    f"ON m.id = x.memory_id WHERE x.entity_id = e.id AND {self.in_scope}) AS notes "
                                    f"FROM entities e WHERE e.id = ?", (*self.scopes, int(raw))).fetchone()
                out[node] = entity_node(r, r["notes"])
            else:
                r = self.db.execute("SELECT * FROM memories WHERE id = ?", (raw,)).fetchone()
                out[node] = note_node(r)
        return out

    def top_entities(self, limit: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            f"SELECT e.*, COUNT(DISTINCT x.memory_id) AS notes FROM entities e JOIN mentions x ON x.entity_id = e.id "
            f"JOIN memories m ON m.id = x.memory_id WHERE {self.in_scope} GROUP BY e.id "
            f"ORDER BY notes DESC, e.key LIMIT ?", (*self.scopes, limit)).fetchall()
        return [entity_node(r, r["notes"]) for r in rows]

    def link_entities(self, nodes: dict[str, dict[str, Any]], edges: dict[tuple, dict[str, Any]]) -> None:
        """Edges among the entities already in the picture: stored relations and co-occurrence in a note."""
        ids = [int(n["id"][2:]) for n in nodes.values() if n["type"] == "entity"]
        if len(ids) < 2:
            return
        marks = _marks(ids)
        for r in self.db.execute(
                f"SELECT * FROM relations r WHERE r.src IN ({marks}) AND r.dst IN ({marks}) "
                f"AND r.status IN ({_marks(list(self.statuses))}) AND r.scope IN ({_marks(self.scopes)})",
                (*ids, *ids, *self.statuses, *self.scopes)).fetchall():
            edge = {"id": r["id"], "source": f"e:{r['src']}", "target": f"e:{r['dst']}", "type": "relation",
                    "label": r["label"], "status": r["status"], "weight": 1}
            edges.setdefault(_edge_key(edge), edge)
        for r in self.db.execute(
                f"SELECT a.entity_id AS a, b.entity_id AS b, COUNT(DISTINCT a.memory_id) AS n FROM mentions a "
                f"JOIN mentions b ON b.memory_id = a.memory_id AND a.entity_id < b.entity_id "
                f"JOIN memories m ON m.id = a.memory_id WHERE a.entity_id IN ({marks}) AND b.entity_id IN ({marks}) "
                f"AND {self.in_scope} GROUP BY a.entity_id, b.entity_id", (*ids, *ids, *self.scopes)).fetchall():
            edge = {"id": f"c:{r['a']}-{r['b']}", "source": f"e:{r['a']}", "target": f"e:{r['b']}", "type": "cooccur",
                    "label": "", "status": "confirmed", "weight": r["n"]}
            edges.setdefault(_edge_key(edge), edge)

    def add_notes(self, nodes: dict[str, dict[str, Any]], edges: dict[tuple, dict[str, Any]], limit: int) -> None:
        """The notes that mention several of the entities in the picture."""
        ids = [int(n["id"][2:]) for n in nodes.values() if n["type"] == "entity"]
        if not ids:
            return
        rows = self.db.execute(
            f"SELECT m.*, COUNT(*) AS n FROM mentions x JOIN memories m ON m.id = x.memory_id "
            f"WHERE x.entity_id IN ({_marks(ids)}) AND {self.in_scope} GROUP BY m.id HAVING n >= 2 "
            f"ORDER BY n DESC, m.updated DESC LIMIT ?", (*ids, *self.scopes, max(3, limit // 3))).fetchall()
        for r in rows:
            node = note_node(r)
            nodes[node["id"]] = node
            for x in self.db.execute(f"SELECT entity_id FROM mentions WHERE memory_id = ? AND entity_id IN "
                                     f"({_marks(ids)})", (r["id"], *ids)).fetchall():
                edge = {"id": f"n:{r['id']}-{x[0]}", "source": node["id"], "target": f"e:{x[0]}", "type": "mentions",
                        "label": "", "status": "confirmed", "weight": 1}
                edges.setdefault(_edge_key(edge), edge)

    def around(self, node: str, notes: bool, limit: int) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """(neighbour, edge) pairs of one node, the strongest ties first."""
        kind, _, raw = node.partition(":")
        out: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if kind == "e":
            eid = int(raw)
            share = max(3, limit // 2)
            for r in self.db.execute(
                    f"SELECT r.*, e.id AS other, e.kind AS okind, e.name AS oname FROM relations r "
                    f"JOIN entities e ON e.id = CASE WHEN r.src = ? THEN r.dst ELSE r.src END "
                    f"WHERE (r.src = ? OR r.dst = ?) AND r.status IN ({_marks(list(self.statuses))}) "
                    f"AND r.scope IN ({_marks(self.scopes)})", (eid, eid, eid, *self.statuses, *self.scopes)).fetchall():
                other = {"id": f"e:{r['other']}", "type": "entity", "kind": r["okind"], "label": r["oname"], "weight": 0}
                out.append((other, {"id": r["id"], "source": f"e:{r['src']}", "target": f"e:{r['dst']}",
                                    "type": "relation", "label": r["label"], "status": r["status"], "weight": 1}))
            for r in self.db.execute(  # entities that share notes with it
                    f"SELECT e.*, COUNT(DISTINCT b.memory_id) AS n, "
                    f"(SELECT COUNT(DISTINCT y.memory_id) FROM mentions y JOIN memories m2 ON m2.id = y.memory_id "
                    f"WHERE y.entity_id = e.id AND m2.scope IN ({_marks(self.scopes)})) AS notes "
                    f"FROM mentions a JOIN mentions b ON b.memory_id = a.memory_id AND b.entity_id != a.entity_id "
                    f"JOIN entities e ON e.id = b.entity_id JOIN memories m ON m.id = a.memory_id "
                    f"WHERE a.entity_id = ? AND {self.in_scope} GROUP BY e.id ORDER BY n DESC, e.key LIMIT ?",
                    (*self.scopes, eid, *self.scopes, share)).fetchall():
                a, b = sorted((eid, r["id"]))
                out.append((entity_node(r, r["notes"]), {"id": f"c:{a}-{b}", "source": node, "target": f"e:{r['id']}",
                                                         "type": "cooccur", "label": "", "status": "confirmed",
                                                         "weight": r["n"]}))
            if notes:  # the notes that mention it
                for r in self.db.execute(
                        f"SELECT m.*, x.count AS n FROM mentions x JOIN memories m ON m.id = x.memory_id "
                        f"WHERE x.entity_id = ? AND {self.in_scope} ORDER BY x.count DESC, m.updated DESC LIMIT ?",
                        (eid, *self.scopes, share)).fetchall():
                    out.append((note_node(r), {"id": f"n:{r['id']}-{eid}", "source": f"m:{r['id']}", "target": node,
                                               "type": "mentions", "label": "", "status": "confirmed",
                                               "weight": r["n"]}))
        else:
            for r in self.db.execute(  # the entities it mentions
                    "SELECT e.*, x.count AS n FROM mentions x JOIN entities e ON e.id = x.entity_id "
                    "WHERE x.memory_id = ? ORDER BY x.count DESC, e.key LIMIT ?", (raw, limit)).fetchall():
                out.append((entity_node(r), {"id": f"n:{raw}-{r['id']}", "source": node, "target": f"e:{r['id']}",
                                             "type": "mentions", "label": "", "status": "confirmed", "weight": r["n"]}))
            if notes:  # notes that share entities with it (hubs aside)
                for r in self.db.execute(
                        f"SELECT m.*, COUNT(*) AS n, GROUP_CONCAT(e.name, ' · ') AS via FROM mentions a "
                        f"JOIN mentions b ON b.entity_id = a.entity_id AND b.memory_id != a.memory_id "
                        f"JOIN memories m ON m.id = b.memory_id JOIN entities e ON e.id = a.entity_id "
                        f"WHERE a.memory_id = ? AND {self.in_scope} AND (SELECT COUNT(*) FROM mentions h "
                        f"WHERE h.entity_id = a.entity_id) <= ? GROUP BY m.id ORDER BY n DESC, m.updated DESC LIMIT ?",
                        (raw, *self.scopes, HUB_NOTES, limit)).fetchall():
                    a, b = sorted((raw, r["id"]))
                    out.append((note_node(r), {"id": f"s:{a}-{b}", "source": node, "target": f"m:{r['id']}",
                                               "type": "shared", "label": r["via"][:MAX_LABEL], "status": "confirmed",
                                               "weight": r["n"]}))
        return out[:limit * 2]

