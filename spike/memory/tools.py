"""Tools that let a model save to and search SPIKE's memory. Saving asks the user by default: a note stays and
shapes later chats, so a page the model read must not be able to plant one silently."""

from __future__ import annotations

import time
from typing import Any

from spike.memory.service import MemoryService, scopes_for
from spike.memory.tutor import TutorError
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


class StudyTopics(Tool):
    name = "study_topics"
    description = ("List the learner's study topics with their mastery (0 to 5) and when each is due for review "
                   "(spaced repetition), most overdue first.")
    parameters = {"type": "object", "properties": {"due_only": {"type": "boolean"}}}
    risk = "read"
    default_policy = "allow"

    def __init__(self, memory: MemoryService, project_id: str | None):
        self.memory = memory
        self.project_id = project_id

    async def run(self, args: dict[str, Any]) -> ToolResult:
        now = time.time()
        topics = self.memory.tutor.list(scopes_for(self.project_id), due_only=bool(args.get("due_only")), limit=40)
        if not topics:
            return ToolResult(ok=True, content="nothing is due" if args.get("due_only") else "no topics yet")
        lines = []
        for t in topics:
            days = max(1, round((t.next_review - now) / 86400))
            lines.append(f"- {t.name}: mastery {t.mastery}/5, "
                         + ("due now" if t.due(now) else f"next review in {days} day{'s' if days != 1 else ''}"))
        return ToolResult(ok=True, content="\n".join(lines))


class StudyReview(Tool):
    name = "study_review"
    description = ("Record how a review of one topic went and schedule the next one: grade 0 (blank) to 5 (perfect "
                   "recall); below 3 counts as forgotten. A topic that is not listed yet is added. Use it after "
                   "quizzing the learner.")
    parameters = {"type": "object", "properties": {
        "topic": {"type": "string", "description": "the topic's name, as in the study list"},
        "grade": {"type": "integer", "minimum": 0, "maximum": 5}}, "required": ["topic", "grade"]}
    risk = "write"
    default_policy = "ask"  # it changes the learner's schedule, like a note changes memory

    def __init__(self, memory: MemoryService, project_id: str | None):
        self.memory = memory
        self.project_id = project_id

    async def run(self, args: dict[str, Any]) -> ToolResult:
        tutor, scopes = self.memory.tutor, scopes_for(self.project_id)
        name, grade = str(args.get("topic", "")).strip(), args.get("grade")
        if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 5:
            return ToolResult(ok=False, content="error: 'grade' must be a whole number from 0 to 5")
        try:
            topic = tutor.find(name, scopes) or tutor.add(name, scopes[0])
            done = tutor.review(topic.id, grade)
        except TutorError as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        if done is None:
            return ToolResult(ok=False, content="error: the topic is gone")
        days = done.interval_days
        return ToolResult(ok=True, content=f"{done.name}: mastery {done.mastery}/5, next review in {days} "
                                           f"day{'s' if days != 1 else ''}", data={"topic": done.id})


def memory_tools(memory: MemoryService, project_id: str | None) -> list[Tool]:
    return [Remember(memory, project_id), Recall(memory, project_id), StudyTopics(memory, project_id),
            StudyReview(memory, project_id)]
