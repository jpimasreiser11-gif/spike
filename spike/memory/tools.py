"""Tools that let a model save to and search SPIKE's memory. Saving asks the user by default: a note stays and
shapes later chats, so a page the model read must not be able to plant one silently."""

from __future__ import annotations

from typing import Any

from spike.memory.service import MemoryService, scopes_for
from spike.tools.base import Tool, ToolResult

SAVABLE = ("fact", "decision", "preference")


class Remember(Tool):
    name = "remember"
    description = ("Save a short note to long-term memory so later chats can use it: a fact about the user or "
                   "their work, a decision taken, or a preference. One self-contained sentence.")
    parameters = {"type": "object", "properties": {
        "text": {"type": "string", "description": "the note, self-contained"},
        "kind": {"type": "string", "enum": list(SAVABLE)},
    }, "required": ["text"]}
    risk = "write"
    default_policy = "ask"

    def __init__(self, memory: MemoryService, project_id: str | None):
        self.memory = memory
        self.project_id = project_id

    async def run(self, args: dict[str, Any]) -> ToolResult:
        kind = str(args.get("kind") or "fact")
        text = str(args.get("text", "")).strip()
        if kind not in SAVABLE:
            return ToolResult(ok=False, content=f"error: kind must be one of {', '.join(SAVABLE)}")
        if not text or len(text) > 2000:
            return ToolResult(ok=False, content="error: the note must be between 1 and 2000 characters")
        scope = scopes_for(self.project_id)[0]
        m = self.memory.store.add(text, kind, scope, meta={"by": "model"})
        return ToolResult(ok=True, content=f"saved to memory ({kind})", data={"memory": m.id})


class Recall(Tool):
    name = "recall"
    description = "Search long-term memory (earlier chats, saved notes, project files) for something specific."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    risk = "read"
    default_policy = "allow"

    def __init__(self, memory: MemoryService, project_id: str | None):
        self.memory = memory
        self.project_id = project_id

    async def run(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, content="error: 'query' is required")
        found = await self.memory.recall(query, self.project_id, k=8)
        if not found.hits:
            return ToolResult(ok=True, content="nothing found in memory")
        lines = [f"- [{h.memory.kind}{' ' + h.memory.source if h.memory.source else ''}] {h.text.strip()[:1200]}"
                 for h in found.hits]
        files = [line for line, h in zip(lines, found.hits, strict=True) if h.memory.kind == "document"]
        return ToolResult(ok=True, content="\n".join(lines), private=files)


def memory_tools(memory: MemoryService, project_id: str | None) -> list[Tool]:
    return [Remember(memory, project_id), Recall(memory, project_id)]
