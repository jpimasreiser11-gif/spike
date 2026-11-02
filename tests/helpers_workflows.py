"""Builders for workflow documents and fake tools, shared by the workflow tests."""

from __future__ import annotations

import asyncio
from typing import Any

from spike.tools.base import Tool, ToolResult
from spike.workflows.model import FORMAT, VERSION, Environment

ECHO = {"type": "object", "properties": {"text": {"type": "string"}, "times": {"type": "integer"}}, "required": ["text"]}
FILE = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"]}
ENV = Environment(specialists={"core", "finance"}, tools={"echo": ECHO, "danger": ECHO, "write_file": FILE},
                  unavailable={"ask_user"})


def node(nid: str, type_: str, /, **fields: Any) -> dict[str, Any]:
    return {"id": nid, "type": type_, "name": fields.pop("name", nid), **fields}


def edge(src: str, dst: str, port: str = "out") -> dict[str, Any]:
    return {"id": f"{src}.{port}-{dst}", "from": src, "fromPort": port, "to": dst, "toPort": "in"}


def doc(nodes: list[dict], edges: list[dict], name: str = "Test") -> dict[str, Any]:
    return {"format": FORMAT, "version": VERSION, "name": name, "nodes": nodes, "edges": edges}


def chain() -> dict[str, Any]:
    """input -> specialist -> tool -> output(artifact): the smallest workflow that uses every kind but a condition."""
    return doc([node("in", "input", name="topic", default="gatos"),
                node("ask", "specialist", name="draft", prompt="Escribe sobre {{topic}}"),
                node("say", "tool", name="said", tool="echo", arguments={"text": "{{input}}"}),
                node("out", "output", mode="artifact", content="{{input}}")],
               [edge("in", "ask"), edge("ask", "say"), edge("say", "out")])


def branching() -> dict[str, Any]:
    """input(number) -> condition(> 10) -> true: echo "big"; false: echo "small"; both -> output."""
    return doc([node("n", "input", name="n", kind="number", default="5"),
                node("c", "condition", op="number", compare=">", value="10"),
                node("big", "tool", name="big", tool="echo", arguments={"text": "big {{input}}"}),
                node("small", "tool", name="small", tool="echo", arguments={"text": "small {{input}}"}),
                node("end", "output", mode="artifact", content="{{input}}")],
               [edge("n", "c"), edge("c", "big", "true"), edge("c", "small", "false"), edge("big", "end"),
                edge("small", "end")])


class Echo(Tool):
    name = "echo"
    description = "repeats its text"
    parameters = ECHO

    def __init__(self):
        self.calls: list[dict] = []

    async def run(self, args: dict[str, Any]) -> ToolResult:
        self.calls.append(args)
        await asyncio.sleep(float(args.get("delay", 0)))
        return ToolResult(ok=True, content=f"echo:{args['text']}")


class Danger(Echo):
    """A tool that asks first, like every tool that writes or runs code."""

    name = "danger"
    risk = "execute"
    default_policy = "ask"


class Secret(Tool):
    """A tool that returns the user's file contents, marked private the way read_file does."""

    name = "secret"
    description = "reads a file"
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, content="CONFIDENTIAL-4471", private=["CONFIDENTIAL-4471"])


class Broken(Tool):
    name = "broken"
    description = "always fails"
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict[str, Any]) -> ToolResult:
        raise RuntimeError("boom")
