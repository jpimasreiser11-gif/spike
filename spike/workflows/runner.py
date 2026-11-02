"""Running a workflow: the nodes in topological order, a live log of events per node, and a record of the run.

Every model call goes through the orchestrator and every tool call (a tool node, an output node that saves a file, and
whatever a specialist asks for) goes through `call_tool`, the same permission-gated path the chat uses: a tool whose
policy is `ask` waits for the user's answer, a denial ends that branch (a `denied` node; its descendants are skipped)
and the others go on. Nothing in here can reach a tool another way.

A node runs when none of its incoming edges is dead and at least one is live (or it has none). An edge is live when
its source finished `ok` (for a condition: and went down that edge's port), neutral when its source was skipped
because a condition went the other way, and dead when its source failed, was denied or was skipped for a dead edge.
That makes the two branches of a condition able to join again: the node after them runs with whichever side ran.

What the user's files said stays marked private on its way through the nodes: a prompt that holds such text goes to the
orchestrator with those passages declared (`OrchestratorOptions.private_text`), so a provider that may not receive
files gets them withheld, exactly as in a chat.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from spike.agent.loop import call_tool
from spike.core.types import ToolCall
from spike.orchestrator.orchestrator import Orchestrator, OrchestratorOptions
from spike.tools.base import PermissionBroker, ToolRegistry
from spike.workflows.model import (
    evaluate,
    incoming,
    levels,
    parse_number,
    references,
    render,
    render_value,
    safe_output_path,
    used_names,
)

RECORD_FORMAT = "spike-workflow-run"
MAX_OUTPUT = 100_000  # characters a node passes on and stores
MAX_PROMPT = 200_000
MAX_EVENTS = 20_000
MAX_LOG = 40  # entries of a node's compact log in the record
FAILED, DENIED, CANCELLED = "failed", "denied", "cancelled"
REFUSAL_PREFIXES = ("error: the user denied", "error: the user has disabled", "error: refused:")


class NodeFailure(Exception):
    """A node that cannot do its job; the message is shown on the node. `denied`: the user (or the user's policy for
    the tool) refused the call."""

    def __init__(self, message: str, denied: bool = False):
        super().__init__(message)
        self.denied = denied


@dataclass
class Value:
    """What a node produced and which passages of it are the user's file contents."""

    text: str
    private: list[str] = field(default_factory=list)


@dataclass
class Host:
    """What a run uses: the orchestrator (specialists and tools), the options for a specialist's mode, and the broker
    that asks the user. `parallel` runs the nodes of one level together (the user's setting for remote models)."""

    orchestrator: Orchestrator
    options: Callable[[str], OrchestratorOptions]
    broker: PermissionBroker
    tools_enabled: bool = True
    parallel: bool = False

    @property
    def tools(self) -> ToolRegistry:
        return self.orchestrator.tools


class LiveRun:
    """A run in progress: its record, every event so far (late readers replay them) and the task that executes it."""

    def __init__(self, record: dict[str, Any]):
        self.record = record
        self.events: list[dict[str, Any]] = []
        self.finished = False
        self.task: asyncio.Future | None = None
        self.owner: tuple[str | None, str] | None = None  # (project id, workflow id)
        self._clock = time.perf_counter()
        self._waiters: list[asyncio.Future] = []

    def emit(self, event: dict[str, Any]) -> None:
        if len(self.events) >= MAX_EVENTS and event["type"] == "delta":
            return  # a very long answer keeps its record, not every piece
        self.events.append({**event, "t": round(time.perf_counter() - self._clock, 3)})
        self._wake()

    def finish(self) -> None:
        self.finished = True
        self._wake()

    def _wake(self) -> None:
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    async def wait_finished(self) -> None:
        async for _ in self.follow(len(self.events)):
            pass

    async def follow(self, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """The events from index `after` on, waiting for new ones until the run has finished."""
        index = max(0, after)
        while True:
            while index < len(self.events):
                yield self.events[index]
                index += 1
            if self.finished:
                return
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            await waiter


def new_record(doc: dict[str, Any], inputs: dict[str, str], provider_id: str | None = None) -> dict[str, Any]:
    now = time.time()
    return {"format": RECORD_FORMAT, "version": 1, "id": f"{int(now * 1000):013d}-{uuid.uuid4().hex[:6]}",
            "workflow": doc.get("id"), "workflow_name": doc["name"], "workflow_revision": doc.get("revision"),
            "status": "running", "started": round(now, 3), "finished": None, "elapsed_s": None,
            "provider_id": provider_id, "inputs": inputs, "order": levels(doc),
            "nodes": {n["id"]: {"id": n["id"], "name": n["name"], "type": n["type"], "status": "pending"}
                      for n in doc["nodes"]}}


def _cap(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + f"\n[truncated {len(text) - MAX_OUTPUT} characters]"


def _short(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _coerce(args: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Arguments typed as the tool's schema says: text a template produced becomes the number, flag or list wanted."""
    props = schema.get("properties") or {}
    out = dict(args)
    for key, value in args.items():
        want = (props.get(key) or {}).get("type")
        if not isinstance(value, str) or want in (None, "string"):
            continue
        try:
            if want in ("integer", "number"):
                number = parse_number(value)
                if number is None or (want == "integer" and number != int(number)):
                    raise ValueError
                out[key] = int(number) if want == "integer" else number
            elif want == "boolean":
                if value.strip().lower() not in ("true", "false"):
                    raise ValueError
                out[key] = value.strip().lower() == "true"
            elif want in ("array", "object"):
                parsed = json.loads(value)
                if not isinstance(parsed, list if want == "array" else dict):
                    raise ValueError
                out[key] = parsed
        except ValueError as exc:
            raise NodeFailure(f"the argument '{key}' must be {'a ' + want}, not '{_short(value, 60)}'") from exc
    return out


class _Run:
    """The state of one execution (see `execute`)."""

    def __init__(self, doc: dict[str, Any], values: dict[str, str], host: Host, live: LiveRun):
        self.doc, self.host, self.live = doc, host, live
        self.nodes = {n["id"]: n for n in doc["nodes"]}
        self.sources = incoming(doc)
        self.records = live.record["nodes"]
        self.scope = {name: Value(text) for name, text in values.items()}  # names of input nodes, then finished nodes
        self.values = values

    def emit(self, event: dict[str, Any]) -> None:
        self.live.emit(event)

    # ------------------------------------------------------------------ edges
    def edge_state(self, edge: dict[str, Any]) -> str:
        source = self.records[edge["from"]]
        if source["status"] == "ok":
            if self.nodes[edge["from"]]["type"] == "condition":
                return "live" if source.get("branch") == edge["fromPort"] else "neutral"
            return "live"
        return "neutral" if source["status"] == "skipped" and source.get("skip") == "branch" else "dead"

    # ------------------------------------------------------------------ one node
    async def run_node(self, nid: str) -> None:
        node, rec = self.nodes[nid], self.records[nid]
        edges = self.sources.get(nid, [])
        states = [self.edge_state(e) for e in edges]
        if "dead" in states or (edges and "live" not in states):
            reason = "upstream" if "dead" in states else "branch"
            rec.update(status="skipped", skip=reason)
            self.emit({"type": "node_end", "node": nid, "status": "skipped", "skip": reason})
            return
        live_edges = [e for e, s in zip(edges, states, strict=True) if s == "live"]
        subject = None
        if live_edges:
            parts = [self.scope_of(e["from"]) for e in live_edges]
            subject = Value("\n\n".join(p.text for p in parts), [x for p in parts for x in p.private])
        rec.update(status="running", started=round(time.time(), 3))
        self.emit({"type": "node_start", "node": nid, "kind": node["type"], "name": node["name"]})
        began = time.perf_counter()
        try:
            outcome = await getattr(self, f"do_{node['type']}")(node, rec, subject)
        except asyncio.CancelledError:
            self.finish_node(nid, began, CANCELLED, error="stopped")
            raise
        except NodeFailure as exc:
            self.finish_node(nid, began, DENIED if exc.denied else FAILED, error=str(exc))
            return
        except Exception as exc:  # a bug in a tool or a provider must not take the other branches down
            self.finish_node(nid, began, FAILED, error=f"{exc.__class__.__name__}: {exc}")
            return
        self.finish_node(nid, began, "ok", value=outcome)

    def scope_of(self, nid: str) -> Value:
        """What a finished node passed on: a condition passes on what it tested."""
        return self.scope[self.nodes[nid]["name"]]

    def finish_node(self, nid: str, began: float, status: str, value: Value | None = None,
                    error: str | None = None) -> None:
        node, rec = self.nodes[nid], self.records[nid]
        rec.update(status=status, finished=round(time.time(), 3), elapsed_s=round(time.perf_counter() - began, 3))
        if error:
            rec["error"] = error
        if value is not None:
            rec["output"] = value.text
            rec["private"] = bool(value.private)
            self.scope[node["name"]] = value
        event = {"type": "node_end", "node": nid, "status": status, "elapsed_s": rec["elapsed_s"],
                 **{k: rec[k] for k in ("error", "branch", "file", "artifact", "private") if rec.get(k)}}
        if value is not None:
            event["output"] = value.text[:4000]
        self.emit(event)

    # ------------------------------------------------------------------ templates
    def lookup(self, names: list[str], subject: Value | None) -> tuple[dict[str, str], list[str]]:
        found: dict[str, str] = {}
        private: list[str] = []
        for name in names:
            value = subject if name == "input" else self.scope.get(name)
            if value is None:
                raise NodeFailure(f"'{name}' has no value: the step that makes it did not run")
            found[name] = value.text
            private.extend(value.private)
        return found, private

    def fill(self, template: str, subject: Value | None) -> tuple[str, list[str]]:
        found, private = self.lookup(references(template), subject)
        return render(template, found), private

    def log(self, rec: dict[str, Any], entry: dict[str, Any]) -> None:
        log = rec.setdefault("log", [])
        if len(log) < MAX_LOG:
            log.append(entry)

    # ------------------------------------------------------------------ the five kinds
    async def do_input(self, node: dict[str, Any], rec: dict[str, Any], subject: Value | None) -> Value:
        return Value(self.values[node["name"]])

    async def do_specialist(self, node: dict[str, Any], rec: dict[str, Any], subject: Value | None) -> Value:
        prompt, private = self.fill(node["prompt"], subject)
        if len(prompt) > MAX_PROMPT:
            raise NodeFailure("the prompt is too long once its variables are filled in")
        options = self.host.options(node["specialist"])
        options.use_planner = False  # one specialist answers: the graph is the plan
        options.private_text = list(dict.fromkeys(private))
        options.checkpoints = None
        text, saw_private = "", False
        async with aclosing(self.host.orchestrator.run([], prompt, options)) as events:
            async for event in events:
                kind = event["type"]
                if kind == "done":
                    text, saw_private = event.get("text") or "", bool(event.get("private"))
                    if event.get("error"):
                        raise NodeFailure(str(event["error"]))
                elif kind == "route":
                    rec["specialists"] = [s["id"] for s in event.get("specialists") or []]
                    self.emit({"type": "route", "node": node["id"], "specialists": rec["specialists"]})
                elif kind in ("delta", "tool_call", "tool_result", "permission_request", "permission_resolved",
                              "question", "answered", "privacy", "error", "skill"):
                    self.emit({**event, "node": node["id"]})
                    self.note(rec, event)
        text = _cap(text)
        return Value(text, [text] if saw_private and text else [])

    def note(self, rec: dict[str, Any], event: dict[str, Any]) -> None:
        """The compact log of a node in the record: tool calls and what the user decided, not every word."""
        kind = event["type"]
        if kind == "tool_call":
            self.log(rec, {"type": "tool_call", "name": event.get("name"), "arguments": _short(event.get("arguments"))})
        elif kind == "tool_result":
            self.log(rec, {"type": "tool_result", "name": event.get("name"), "ok": event.get("ok")})
        elif kind == "permission_resolved":
            self.log(rec, {"type": "permission", "decision": event.get("decision")})

    async def call(self, node: dict[str, Any], rec: dict[str, Any], name: str, args: dict[str, Any],
                   tainted: bool) -> Value:
        """One tool call through the permission flow. Returns the result; raises NodeFailure when it fails or is
        refused (a refusal is marked `denied`)."""
        if not self.host.tools_enabled:
            raise NodeFailure("tools are turned off in Settings")
        tool = self.host.tools.get(name)
        if tool is None:
            raise NodeFailure(f"the tool '{name}' is not available now")
        args = _coerce(args, tool.parameters)
        call = ToolCall(id=f"wf-{node['id']}", name=name, arguments=args)
        tag = {"node": node["id"]}
        self.emit({"type": "tool_call", "id": call.id, "name": name, "arguments": args, **tag})
        self.note(rec, {"type": "tool_call", "name": name, "arguments": args})
        outcome: list[Any] = []
        async with aclosing(call_tool(tool, call, self.host.broker, None, tag, outcome)) as events:
            async for event in events:
                self.emit(event)
                self.note(rec, event)
        text, ok, file, private, _, _ = outcome
        self.emit({"type": "tool_result", "id": call.id, "name": name, "ok": ok, "content": text[:4000], **tag,
                   **({"file": file} if file else {})})
        self.note(rec, {"type": "tool_result", "name": name, "ok": ok})
        if not ok:
            raise NodeFailure(text.removeprefix("error: "),
                              denied=text.startswith(REFUSAL_PREFIXES) or "needs the user's approval" in text[:120])
        if file:
            rec["file"] = file
        text = _cap(text)
        return Value(text, [text] if tainted and text else [p for p in private if p and p in text])

    async def do_tool(self, node: dict[str, Any], rec: dict[str, Any], subject: Value | None) -> Value:
        found, private = self.lookup(used_names(node), subject)
        args = render_value(node["arguments"], found)
        return await self.call(node, rec, node["tool"], args, bool(private))

    async def do_condition(self, node: dict[str, Any], rec: dict[str, Any], subject: Value | None) -> Value:
        if subject is None:
            raise NodeFailure("the condition received no value")
        needle = self.fill(node["value"], subject)[0] if node["op"] == "contains" else node["value"]
        try:
            holds = evaluate(node, subject.text, needle)
        except ValueError as exc:
            raise NodeFailure(str(exc)) from exc
        rec["branch"] = "true" if holds else "false"
        return subject

    async def do_output(self, node: dict[str, Any], rec: dict[str, Any], subject: Value | None) -> Value:
        content, private = self.fill(node["content"], subject)
        if node["mode"] == "file":
            path, _ = self.fill(node["path"], subject)
            if (why := safe_output_path(path)) is not None:
                raise NodeFailure(f"the file path '{_short(path, 80)}' {why}")
            result = await self.call(node, rec, "write_file", {"path": path.strip(), "content": content}, False)
            return Value(result.text)
        title, _ = self.fill(node["title"], subject) if node["title"] else (node["name"], [])
        rec["artifact"] = {"title": title.strip()[:80] or node["name"], "format": node["format"], "content": _cap(content)}
        return Value(_cap(content), private)


async def execute(doc: dict[str, Any], values: dict[str, str], host: Host, live: LiveRun) -> dict[str, Any]:
    """Run the workflow to the end, or until the task is cancelled (the stop button), and return its record. Cancelling
    marks the node that was running `cancelled` and the rest stopped; it never leaves a half-written record."""
    record, run = live.record, _Run(doc, values, host, live)
    began = time.perf_counter()
    live.emit({"type": "run_start", "run": record["id"], "order": record["order"],
               "nodes": [{"id": n["id"], "name": n["name"], "type": n["type"]} for n in doc["nodes"]]})
    cancelled = False
    try:
        for level in record["order"]:
            if host.parallel and len(level) > 1:
                await asyncio.gather(*(run.run_node(nid) for nid in level))
            else:
                for nid in level:
                    await run.run_node(nid)
    except asyncio.CancelledError:
        cancelled = True  # the work is stopped; the record below is the answer, so the cancellation ends here
    for nid, rec in run.records.items():
        if rec["status"] in ("pending", "running"):
            rec.update(status="skipped", skip="stopped")
            live.emit({"type": "node_end", "node": nid, "status": "skipped", "skip": "stopped"})
    statuses = {r["status"] for r in run.records.values()}
    record["status"] = CANCELLED if cancelled else FAILED if statuses & {FAILED, DENIED} else "completed"
    record["finished"] = round(time.time(), 3)
    record["elapsed_s"] = round(time.perf_counter() - began, 3)
    live.emit({"type": "run_end", "status": record["status"], "elapsed_s": record["elapsed_s"]})
    return record
