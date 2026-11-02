"""Running a workflow: order and values, condition branches, tools that ask permission (a denial ends its branch), the
stop button, records with measured timings, and the user's file contents staying private on the way."""

import asyncio
from dataclasses import replace

from spike.core.types import StreamEvent
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.providers.guard import GuardedProvider
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker, ToolRegistry
from spike.tools.builtin import Workspace, WriteFile
from spike.workflows.model import bind_inputs, clean
from spike.workflows.runner import Host, LiveRun, execute, new_record
from tests.helpers import ScriptedProvider, text
from tests.helpers_workflows import Broken, Danger, Echo, Secret, branching, chain, doc, edge, node

CATALOG = load_catalog()


class Hanging(ScriptedProvider):
    """A model that never answers: the stop button has something to interrupt."""

    async def stream(self, request):
        self.requests.append(request)
        await asyncio.Event().wait()
        yield StreamEvent(kind="done")  # pragma: no cover


def make_host(provider, tools, policies=None, **kw) -> Host:
    broker = PermissionBroker(policies or {}, timeout_s=5)
    registry = ToolRegistry(tools)
    orchestrator = Orchestrator(CATALOG, lambda spec: Backend(provider=provider, model=None, adapter=None), registry, broker)
    return Host(orchestrator=orchestrator, options=lambda mode: OrchestratorOptions(mode=mode, skill_mode="off"),
                broker=broker, **kw)


def start(d, host, given=None):
    """The run as a task, with its live log."""
    d = clean(d)
    values, problems = bind_inputs(d, given or {})
    assert problems == []
    live = LiveRun(new_record({**d, "id": "wf-test", "revision": 1}, values))
    return asyncio.ensure_future(execute(d, values, host, live)), live


async def run(d, host, given=None):
    task, live = start(d, host, given)
    return await task, live


def starts(live) -> list[str]:
    return [e["node"] for e in live.events if e["type"] == "node_start"]


def statuses(record) -> dict[str, str]:
    return {nid: n["status"] for nid, n in record["nodes"].items()}


async def pending(host, count=1):
    for _ in range(500):
        if len(host.broker.pending) >= count:
            return list(host.broker.pending.values())
        await asyncio.sleep(0.01)
    raise AssertionError("no permission question was asked")


# ---------------------------------------------------------------- order and values
async def test_nodes_run_in_order_and_each_value_reaches_the_next_node():
    provider, echo = ScriptedProvider([text("borrador sobre gatos")]), Echo()
    record, live = await run(chain(), make_host(provider, [echo]))
    assert starts(live) == ["in", "ask", "say", "out"] and record["status"] == "completed"
    assert provider.requests[0].messages[-1].content == "Escribe sobre gatos"  # {{topic}} from the input node
    assert echo.calls == [{"text": "borrador sobre gatos"}]  # {{input}} is what arrived on the edge
    assert record["nodes"]["say"]["output"] == "echo:borrador sobre gatos"
    assert record["nodes"]["out"]["artifact"] == {"title": "out", "format": "text", "content": "echo:borrador sobre gatos"}
    assert [e["type"] for e in live.events][0] == "run_start" and live.events[-1]["type"] == "run_end"
    assert record["inputs"] == {"topic": "gatos"} and all(n["status"] == "ok" for n in record["nodes"].values())


async def test_a_template_can_name_any_earlier_node_and_the_inputs_not_only_the_neighbour():
    d = doc([node("i", "input", name="topic", default="mar"),
             node("a", "specialist", name="first", prompt="1 {{topic}}"),
             node("b", "specialist", name="second", prompt="2 {{first}} {{topic}}"),
             node("c", "specialist", name="third", prompt="3 {{first}} {{second}} {{input}}")],
            [edge("i", "a"), edge("a", "b"), edge("b", "c")])
    provider = ScriptedProvider([text("uno"), text("dos"), text("tres")])
    record, _ = await run(d, make_host(provider, []))
    assert [r.messages[-1].content for r in provider.requests] == ["1 mar", "2 uno mar", "3 uno dos dos"]
    assert record["status"] == "completed"


async def test_timings_are_measured_per_node_and_for_the_run():
    d = doc([node("t", "tool", tool="echo", arguments={"text": "x", "delay": 0.05})], [])
    echo = Echo()
    echo.parameters = {**echo.parameters, "properties": {**echo.parameters["properties"], "delay": {"type": "number"}}}
    record, live = await run(d, make_host(ScriptedProvider([]), [echo]))
    node_ = record["nodes"]["t"]
    assert node_["elapsed_s"] >= 0.05 and node_["finished"] >= node_["started"]
    assert record["elapsed_s"] >= node_["elapsed_s"] and record["finished"] >= record["started"]
    end = next(e for e in live.events if e["type"] == "node_end" and e["node"] == "t")
    assert end["elapsed_s"] == node_["elapsed_s"] and all("t" in e for e in live.events)


async def test_tool_arguments_are_converted_to_the_type_the_tool_asks_for():
    echo = Echo()
    d = doc([node("n", "input", name="n", kind="number", default="3"),
             node("t", "tool", tool="echo", arguments={"text": "x", "times": "{{n}}"})], [])
    record, _ = await run(d, make_host(ScriptedProvider([]), [echo]))
    assert record["status"] == "completed" and echo.calls == [{"text": "x", "times": 3}]
    d["nodes"][1]["arguments"]["times"] = "{{n}}.5"
    record, _ = await run(d, make_host(ScriptedProvider([]), [echo]))
    assert record["nodes"]["t"]["status"] == "failed" and "whole number" in record["nodes"]["t"]["error"] or \
        "integer" in record["nodes"]["t"]["error"]


# ---------------------------------------------------------------- conditions
async def test_a_condition_sends_the_value_down_one_branch_and_the_other_is_skipped():
    big, _ = await run(branching(), make_host(ScriptedProvider([]), [Echo()]), {"n": "50"})
    assert statuses(big) == {"n": "ok", "c": "ok", "big": "ok", "small": "skipped", "end": "ok"}
    assert big["nodes"]["c"]["branch"] == "true" and big["nodes"]["small"]["skip"] == "branch"
    assert big["nodes"]["end"]["output"] == "echo:big 50"  # the node after the join ran with the side that ran
    small, live = await run(branching(), make_host(ScriptedProvider([]), [Echo()]), {"n": "5"})
    assert statuses(small)["big"] == "skipped" and small["nodes"]["c"]["branch"] == "false"
    assert small["nodes"]["end"]["output"] == "echo:small 5" and "big" not in starts(live)
    assert small["status"] == "completed"  # a branch that did not run is not a failure


async def test_contains_and_regex_conditions_test_what_the_previous_step_wrote():
    def flow(op, value):
        return doc([node("a", "specialist", name="a", prompt="dime"),
                    node("c", "condition", op=op, value=value),
                    node("yes", "tool", tool="echo", arguments={"text": "yes"}),
                    node("no", "tool", tool="echo", arguments={"text": "no"})],
                   [edge("a", "c"), edge("c", "yes", "true"), edge("c", "no", "false")])

    for op, value, answer, expected in (("contains", "ÉXITO", "Fue un éxito total", "true"),
                                        ("regex", r"^pedido \d{3}$", "pedido 123", "true"),
                                        ("regex", r"^pedido \d{3}$", "pedido 12", "false"),
                                        ("contains", "{{a}}", "texto", "true")):  # a template: tested against itself
        record, _ = await run(flow(op, value), make_host(ScriptedProvider([text(answer)]), [Echo()]))
        assert record["nodes"]["c"]["branch"] == expected, (op, value)
    record, _ = await run(flow("number", "1"), make_host(ScriptedProvider([text("sin cifras")]), [Echo()]))
    assert record["nodes"]["c"]["status"] == "failed" and "no number" in record["nodes"]["c"]["error"]
    assert statuses(record)["yes"] == statuses(record)["no"] == "skipped"  # a failed test sends nothing down either branch


# ---------------------------------------------------------------- permission
async def test_a_tool_step_asks_permission_and_a_denial_ends_that_branch_only():
    danger, echo = Danger(), Echo()
    d = doc([node("i", "input", name="i", default="x"),
             node("risky", "tool", name="risky", tool="danger", arguments={"text": "{{i}}"}),
             node("after", "tool", name="after", tool="echo", arguments={"text": "{{input}}"}),
             node("other", "tool", name="other", tool="echo", arguments={"text": "independent"})],
            [edge("i", "risky"), edge("risky", "after"), edge("i", "other")])
    host = make_host(ScriptedProvider([]), [danger, echo])
    task, live = start(d, host)
    (request,) = await pending(host)
    assert request.tool == "danger" and danger.calls == []  # it asked first; nothing ran yet
    asked = next(e for e in live.events if e["type"] == "permission_request")
    assert asked["node"] == "risky" and asked["id"] == request.id and asked["arguments"] == {"text": "x"}
    assert host.broker.resolve(request.id, "deny")
    record = await task
    assert statuses(record) == {"i": "ok", "risky": "denied", "after": "skipped", "other": "ok"}
    assert record["nodes"]["after"]["skip"] == "upstream" and danger.calls == [] and record["status"] == "failed"
    assert "denied" in record["nodes"]["risky"]["error"]
    assert record["nodes"]["risky"]["log"] == [{"type": "tool_call", "name": "danger", "arguments": '{"text": "x"}'},
                                               {"type": "permission", "decision": "deny"},
                                               {"type": "tool_result", "name": "danger", "ok": False}]


async def test_allowing_a_tool_step_runs_it_and_the_run_goes_on():
    danger = Danger()
    d = doc([node("t", "tool", name="t", tool="danger", arguments={"text": "go"}),
             node("o", "output", mode="artifact", content="{{input}}")], [edge("t", "o")])
    host = make_host(ScriptedProvider([]), [danger])
    task, live = start(d, host)
    (request,) = await pending(host)
    host.broker.resolve(request.id, "allow_once")
    record = await task
    assert danger.calls == [{"text": "go"}] and statuses(record) == {"t": "ok", "o": "ok"}
    assert [e["decision"] for e in live.events if e["type"] == "permission_resolved"] == ["allow_once"]


async def test_a_policy_that_denies_a_tool_ends_its_branch_without_asking():
    danger = Danger()
    d = doc([node("t", "tool", tool="danger", arguments={"text": "go"}), node("o", "output", content="{{input}}")],
            [edge("t", "o")])
    record, live = await run(d, make_host(ScriptedProvider([]), [danger], {"danger": "deny"}))
    assert statuses(record) == {"t": "denied", "o": "skipped"} and danger.calls == []
    assert not [e for e in live.events if e["type"] == "permission_request"]


async def test_saving_a_file_goes_through_write_file_and_its_permission(tmp_path):
    host = make_host(ScriptedProvider([]), [WriteFile(Workspace(tmp_path))])
    d = doc([node("i", "input", name="who", default="Ana"),
             node("o", "output", mode="file", path="salida/{{who}}.txt", content="Hola {{who}}")], [edge("i", "o")])
    task, live = start(d, host)
    (request,) = await pending(host)
    assert request.tool == "write_file" and request.arguments == {"path": "salida/Ana.txt", "content": "Hola Ana"}
    host.broker.resolve(request.id, "deny")
    record = await task
    assert record["nodes"]["o"]["status"] == "denied" and not (tmp_path / "salida").exists()
    task, live = start(d, host)
    (request,) = await pending(host)
    host.broker.resolve(request.id, "allow_once")
    record = await task
    assert (tmp_path / "salida" / "Ana.txt").read_text(encoding="utf-8") == "Hola Ana"
    assert record["nodes"]["o"]["file"] == "salida/Ana.txt" and record["status"] == "completed"
    escape = doc([node("o", "output", mode="file", path="{{p}}", content="x"), node("p", "input", name="p")],
                 [edge("p", "o")])
    record, _ = await run(escape, make_host(ScriptedProvider([]), [WriteFile(Workspace(tmp_path))]), {"p": "../fuera.txt"})
    assert record["nodes"]["o"]["status"] == "failed" and not (tmp_path.parent / "fuera.txt").exists()


async def test_turned_off_or_missing_tools_fail_the_node_and_a_broken_tool_does_not_stop_other_branches():
    d = doc([node("t", "tool", tool="echo", arguments={"text": "x"}), node("b", "tool", tool="broken", arguments={}),
             node("after", "output", content="{{input}}"), node("fine", "output", content="ok")],
            [edge("b", "after")])
    record, _ = await run(d, make_host(ScriptedProvider([]), [Echo(), Broken()]))
    assert statuses(record) == {"t": "ok", "b": "failed", "after": "skipped", "fine": "ok"}
    assert record["nodes"]["b"]["error"] == "RuntimeError: boom" or "boom" in record["nodes"]["b"]["error"]
    record, _ = await run(d, make_host(ScriptedProvider([]), [Echo(), Broken()], tools_enabled=False))
    assert "turned off" in record["nodes"]["t"]["error"]
    record, _ = await run(d, make_host(ScriptedProvider([]), [Echo()]))
    assert "not available" in record["nodes"]["b"]["error"]


# ---------------------------------------------------------------- stop
async def test_stop_cancels_the_running_node_skips_the_rest_and_leaves_a_clean_record():
    provider = Hanging([])
    d = doc([node("i", "input", name="i", default="x"), node("a", "specialist", name="a", prompt="{{i}}"),
             node("t", "tool", tool="echo", arguments={"text": "{{input}}"})], [edge("i", "a"), edge("a", "t")])
    echo = Echo()
    task, live = start(d, make_host(provider, [echo]))
    while not provider.requests:
        await asyncio.sleep(0.01)
    task.cancel()
    record = await task  # the cancellation ends in a record, not in an exception
    assert record["status"] == "cancelled" and statuses(record) == {"i": "ok", "a": "cancelled", "t": "skipped"}
    assert record["nodes"]["t"]["skip"] == "stopped" and echo.calls == []
    assert live.events[-1] == {**live.events[-1], "type": "run_end", "status": "cancelled"}
    assert record["finished"] and record["elapsed_s"] is not None and not task.cancelled()


async def test_stop_while_a_permission_question_is_open_withdraws_the_question():
    danger = Danger()
    d = doc([node("t", "tool", tool="danger", arguments={"text": "x"}), node("o", "output", content="{{input}}")],
            [edge("t", "o")])
    host = make_host(ScriptedProvider([]), [danger])
    task, _ = start(d, host)
    await pending(host)
    task.cancel()
    record = await task
    assert record["status"] == "cancelled" and statuses(record) == {"t": "cancelled", "o": "skipped"}
    assert host.broker.pending == {} and danger.calls == []  # the question is gone and the tool never ran


async def test_nodes_of_one_level_run_together_only_when_the_parallel_setting_is_on():
    d = doc([node("a", "tool", tool="echo", arguments={"text": "a", "delay": 0.2}),
             node("b", "tool", tool="echo", arguments={"text": "b", "delay": 0.2})], [])
    echo = Echo()
    echo.parameters = {**echo.parameters, "properties": {**echo.parameters["properties"], "delay": {"type": "number"}}}
    record, _ = await run(d, make_host(ScriptedProvider([]), [echo], parallel=True))
    assert record["elapsed_s"] < 0.39 and record["status"] == "completed"
    record, _ = await run(d, make_host(ScriptedProvider([]), [echo]))
    assert record["elapsed_s"] >= 0.39


# ---------------------------------------------------------------- privacy
def guarded(inner: ScriptedProvider, share_files: bool, local: bool = False) -> GuardedProvider:
    class Log:
        def log_call(self, **row): ...

        def usage_since(self, provider_id, since):
            return {"tokens_in": 0, "tokens_out": 0, "cost": 0.0}

    inner.config = replace(inner.config, local=local, share_files=share_files)
    return GuardedProvider(inner, Log())


def reading_workflow():
    return doc([node("r", "tool", name="file", tool="secret", arguments={}),
                node("s", "specialist", name="summary", prompt="Resume esto: {{input}}"),
                node("t", "specialist", name="again", prompt="Mejora: {{summary}}")], [edge("r", "s"), edge("s", "t")])


async def test_file_contents_stay_private_so_a_provider_that_may_not_receive_files_never_gets_them():
    inner = ScriptedProvider([text("un resumen sin datos"), text("mejor")], name="remote")
    record, _ = await run(reading_workflow(), make_host(guarded(inner, share_files=False), [Secret()]))
    seen = " ".join(m.content for r in inner.requests for m in r.messages)
    assert "CONFIDENTIAL-4471" not in seen and "withheld" in seen and record["status"] == "completed"
    assert record["nodes"]["r"]["private"] is True
    assert record["nodes"]["s"]["private"] is False  # the model never saw the file, so its answer cannot quote it


async def test_private_text_is_sent_when_the_provider_may_receive_files_and_the_answer_is_marked_private():
    inner = ScriptedProvider([text("resumen de CONFIDENTIAL-4471"), text("mejor")], name="remote")
    record, _ = await run(reading_workflow(), make_host(guarded(inner, share_files=True), [Secret()]))
    assert "CONFIDENTIAL-4471" in inner.requests[0].messages[-1].content
    assert inner.requests[0].messages[-1].private == ["CONFIDENTIAL-4471"]
    assert record["nodes"]["s"]["private"] is True  # what it wrote may quote the file ...
    assert inner.requests[1].messages[-1].private == ["resumen de CONFIDENTIAL-4471"]  # ... so the next step withholds it too


async def test_a_local_model_gets_file_contents_and_an_untainted_prompt_declares_nothing():
    inner = ScriptedProvider([text("a"), text("b")], name="local")
    await run(reading_workflow(), make_host(guarded(inner, share_files=False, local=True), [Secret()]))
    assert "CONFIDENTIAL-4471" in inner.requests[0].messages[-1].content
    plain = ScriptedProvider([text("a")], name="plain")
    await run(doc([node("s", "specialist", prompt="hola")], []), make_host(plain, []))
    assert plain.requests[0].messages[-1].private == []


async def test_the_workflow_arguments_that_carry_file_contents_make_the_tool_output_private():
    d = doc([node("r", "tool", name="file", tool="secret", arguments={}),
             node("e", "tool", name="e", tool="echo", arguments={"text": "{{input}}"})], [edge("r", "e")])
    record, _ = await run(d, make_host(ScriptedProvider([]), [Secret(), Echo()]))
    assert record["nodes"]["e"]["private"] is True and record["nodes"]["e"]["output"] == "echo:CONFIDENTIAL-4471"


async def test_a_specialist_failure_marks_the_node_failed_and_skips_what_depends_on_it():
    class Failing(ScriptedProvider):
        async def stream(self, request):
            yield StreamEvent(kind="error", text="model unavailable")

    d = doc([node("a", "specialist", prompt="x"), node("o", "output", content="{{input}}")], [edge("a", "o")])
    record, live = await run(d, make_host(Failing([]), []))
    assert statuses(record) == {"a": "failed", "o": "skipped"} and "model unavailable" in record["nodes"]["a"]["error"]
    assert record["status"] == "failed"


async def test_a_variable_of_a_step_that_did_not_run_is_an_error_not_an_empty_string():
    d = clean(branching())
    d["nodes"][-1]["content"] = "{{big}} / {{input}}"  # `big` is upstream of `end` but the false branch skipped it
    values, _ = bind_inputs(d, {"n": "5"})
    live = LiveRun(new_record(d, values))
    record = await execute(d, values, make_host(ScriptedProvider([]), [Echo()]), live)
    assert record["nodes"]["end"]["status"] == "failed" and "'big' has no value" in record["nodes"]["end"]["error"]
