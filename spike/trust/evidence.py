"""The evidence of one run: what the answer can be checked against. Sources are collected from the run's own events
(tool results, files the model wrote, pages it fetched), from the memory recalled for the message and from what the
user said; nothing is fetched again. A source is cited by a name (a file, a URL, a tool, a memory id), so every
source has the keys a citation can use."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any
from urllib.parse import urlparse

from spike.memory.service import Recall
from spike.trust.match import Doc, fold

MAX_TEXT = 300_000  # characters kept of one source
COMMAND_TOOLS = {"python", "data_python", "run_command"}  # what these print is a run's own output, not a lookup
PAGE_TOOLS = {"web_fetch"}
READ_TOOLS = {"read_file"}
MEMORY_KINDS = ("memory", "document")
GENERIC_MEMORY = {"memoria", "memory", "nota", "notas", "note", "notes", "recuerdo", "recuerdos", "memorias"}
PREFIX = re.compile(r"^(?:mem|memoria|memory|file|archivo|fichero|doc|documento|document|url|source|fuente|src|"
                    r"page|pagina|web)\s*[:=]\s*")
ANCHOR = re.compile(r"(?:#l?\d+(?:-l?\d+)?|,?\s*(?:p\.?|pag\.?|pagina|page|line|linea|l\.)\s*\d+.*)$")


def key(ref: str) -> str:
    """What two spellings of a source name share: lower case, no accents, no `file:` prefix, scheme, `www.`, line
    or page anchor or trailing slash."""
    k = PREFIX.sub("", fold(ref).strip().strip("\"'`<>()[] "))
    k = re.sub(r"^(?:https?://)?(?:www\.)?", "", k)
    k = ANCHOR.sub("", k)
    if "." in k.rsplit("/", 1)[-1]:
        k = re.sub(r":\d+(?:-\d+)?$", "", k)
    return k.removeprefix("./").rstrip("/.,;:").strip()


@dataclass
class Source:
    """Something an answer can be checked against. `kind`: tool (a tool's result), command (what code or a command
    printed), file (a file read or written), page (a fetched web page), memory (a recalled note), document (a
    recalled passage of a project file) or user (what the user said)."""

    id: str
    kind: str
    label: str  # shown to the user: the tool, the path, the URL
    text: str
    names: list[str] = field(default_factory=list)  # the names a citation uses, as written
    context: str = ""  # the tool and its arguments: counts for words and numbers, never as the anchor
    authored: bool = False  # written by the model itself (write_file): it backs only a sentence that names it
    memory: str | None = None
    chunk: int | None = None

    @cached_property
    def aliases(self) -> set[str]:
        keys = {key(n) for n in self.names}
        for n in self.names:
            if n.startswith(("http://", "https://")) and (host := urlparse(n).hostname):
                keys.add(key(host))
            if "/" in n and not n.startswith("http"):
                keys.add(key(n.rsplit("/", 1)[-1]))
        if self.memory:
            keys |= {self.memory, self.memory[:8]}
        return {k for k in keys if k}

    @cached_property
    def doc(self) -> Doc:
        return Doc(self.text)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label,
                **({"memory": self.memory} if self.memory else {}), **({"chunk": self.chunk} if self.chunk else {})}


class SourceSet:
    """The sources of a run, found by the names citations use."""

    def __init__(self) -> None:
        self.items: list[Source] = []

    def add(self, kind: str, label: str, text: str, **kw: Any) -> Source | None:
        text = text[:MAX_TEXT]
        if not text.strip():
            return None
        source = Source(id=f"s{len(self.items) + 1}", kind=kind, label=label[:200], text=text, **kw)
        self.items.append(source)
        return source

    def resolve(self, ref: str) -> list[Source]:
        """The sources a written reference names: by exact name, by the end of a path or the start of a memory id;
        'memoria' or 'notas' alone names every recalled note."""
        k = key(ref)
        if not k:
            return []
        hit = [s for s in self.items if k in s.aliases]
        if not hit:
            hit = [s for s in self.items if any(a.endswith("/" + k) or k.endswith("/" + a) for a in s.aliases)]
        if not hit and len(k) >= 6 and re.fullmatch(r"[0-9a-f]+", k):
            hit = [s for s in self.items if s.memory and s.memory.startswith(k)]
        if not hit and k in GENERIC_MEMORY:
            hit = [s for s in self.items if s.kind in MEMORY_KINDS]
        return hit

    def mentioned(self, sentence: str) -> list[Source]:
        """The sources whose name the sentence writes (a file, a page, a note id), tools' names excluded."""
        folded = fold(sentence)
        out = []
        for s in self.items:
            if s.kind in ("tool", "command", "user"):
                continue
            for a in s.aliases:
                if len(a) >= 3 and re.search(rf"(?<![\w/.-]){re.escape(a)}(?![\w-])", folded):
                    out.append(s)
                    break
        return out


class Evidence:
    """Collects the sources of a run from its events, the memory recalled for the message and what the user said."""

    def __init__(self, user_text: str = "", recall: Recall | None = None):
        self.sources = SourceSet()
        self.calls: dict[tuple[Any, str], tuple[str, dict[str, Any]]] = {}  # (subtask, call id) -> (tool, arguments)
        self.verify: dict[str, Any] | None = None
        self.forge: dict[str, Any] | None = None
        self.sources.add("user", "your message", user_text)
        for hit in recall.hits if recall else []:
            m = hit.memory
            if m.kind == "document" and m.source.startswith("file:"):
                name = m.source[5:]
                self.sources.add("document", name, hit.text, names=[name], memory=m.id, chunk=hit.chunk or None)
            else:
                self.sources.add("memory", f"{m.kind} · {m.id[:8]}", hit.text, memory=m.id, chunk=hit.chunk or None)

    @property
    def verifier_failed(self) -> bool:
        """The checker of a multi-step run could not check, or work it sent back was still wrong at the end."""
        if self.forge is not None:
            return not self.forge.get("verified", True) or bool(self.forge.get("unresolved"))
        if self.verify is not None:
            return self.verify.get("method") == "unavailable" or bool(self.verify.get("returned"))
        return False

    def see(self, ev: dict[str, Any]) -> None:
        """Take what an event adds. A `tool_result` may carry the whole result as `full` (the event's `content` is
        cut at 4000 characters); that key is taken out so it never reaches the client."""
        kind = ev.get("type")
        if kind == "tool_call":
            self.calls[(ev.get("subtask"), ev["id"])] = (ev["name"], ev.get("arguments") or {})
        elif kind == "tool_result":
            full = ev.pop("full", None)
            if ev.get("ok"):
                self._tool(ev, full if isinstance(full, str) else str(ev.get("content") or ""))
        elif kind == "verify":
            self.verify = ev
        elif kind == "forge_report":
            self.forge = ev

    def _tool(self, ev: dict[str, Any], content: str) -> None:
        name, args = self.calls.get((ev.get("subtask"), ev.get("id")), (str(ev.get("name") or ""), {}))
        path, url = str(args.get("path") or ""), str(args.get("url") or "")
        if name == "ask_user":
            self.sources.add("user", "your answer", content)
        elif name in READ_TOOLS and path:
            self.sources.add("file", path, content, names=[path])
        elif name in PAGE_TOOLS or name.startswith("mcp__playwright__"):
            self.sources.add("page", url or name, re.sub(r"^\[HTTP \d+\][^\n]*\n\n", "", content), names=[url] if url else [])
        elif path and isinstance(args.get("content"), str):  # write_file and the document tools: the model's own text
            self.sources.add("file", path, args["content"], names=[path], authored=True)
        else:
            context = f"{name} " + " ".join(str(v) for v in args.values() if isinstance(v, str | int | float))
            self.sources.add("command" if name in COMMAND_TOOLS else "tool", name, content, names=[name],
                             context=context[:2000])

