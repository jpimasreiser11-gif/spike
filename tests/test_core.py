import asyncio
import json
from pathlib import Path

import pytest

from spike.agent.loop import AgentRun, run_agent
from spike.core.context import fit_messages
from spike.core.types import Message, StreamEvent
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.orchestrator.planner import Subtask, extract_json, topological_levels, validate_plan
from spike.orchestrator.router import LexicalRouter, normalize
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker
from spike.tools.builtin import Calculator, PythonRunner, ReadFile, WebFetch, Workspace, default_registry, safe_eval
from tests.helpers import ScriptedProvider, call, text

CATALOG = load_catalog()


# ---------------------------------------------------------------- catalog & router
def test_catalog_loads_all_specialists():
    assert {"core", "finance", "medicine", "marketing", "law", "code", "science", "data"} <= set(CATALOG.specialists)
    assert all(s.adapter_status in {"none", "planned"} for s in CATALOG.specialists.values())


def test_normalize_strips_accents():
    assert normalize("Diagnóstico MÉDICO") == "diagnostico medico"


def test_router_single_multi_direct():
    router = LexicalRouter(CATALOG)
    assert router.route("¿Cuál es la dosis de ibuprofeno para la fiebre?").specialists == ["medicine"]
    multi = router.route("Plan a marketing campaign for an ETF and compute the expected ROI of the investment")
    assert multi.mode == "multi" and set(multi.specialists) == {"marketing", "finance"}
    assert router.route("hello there").mode == "direct"


def _router_accuracy(split: str) -> tuple[float, float, int]:
    router = LexicalRouter(CATALOG)
    rows = [json.loads(line) for line in Path("evals/router/labeled.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["split"] == split]
    primary = exact = 0
    for r in rows:
        got = router.route(r["query"]).specialists
        primary += got[0] in r["labels"]
        exact += set(got) == set(r["labels"])
    return primary / len(rows), exact / len(rows), len(rows)


def test_router_eval_dev_split():
    primary, exact, n = _router_accuracy("dev")
    print(f"router dev n={n} primary={primary:.2f} exact={exact:.2f}")
    assert primary >= 0.85


def test_router_eval_test_split_reported():
    # The test split is never used for tuning; this guards against regressions only.
    primary, exact, n = _router_accuracy("test")
    print(f"router test n={n} primary={primary:.2f} exact={exact:.2f}")
    assert primary >= 0.6


# ---------------------------------------------------------------- planner
def test_extract_json_handles_fences_and_think():
    assert extract_json('<think>x</think>```json\n{"subtasks": []}\n```') == {"subtasks": []}
    assert extract_json("nonsense") is None


def test_validate_plan_rejects_unknown_and_drops_forward_deps():
    ok = validate_plan({"subtasks": [
        {"id": "a", "specialist": "finance", "instruction": "x", "depends_on": ["b"]},
        {"id": "b", "specialist": "law", "instruction": "y", "depends_on": ["a"]},
    ]}, CATALOG, 4)
    assert ok is not None and ok[0].depends_on == [] and ok[1].depends_on == ["a"]
    assert validate_plan({"subtasks": [{"id": "a", "specialist": "astrology", "instruction": "x"}]}, CATALOG, 4) is None


def test_topological_levels():
    tasks = [Subtask("a", "finance", "x"), Subtask("b", "law", "y"), Subtask("c", "core", "z", ["a", "b"])]
    assert [[t.id for t in lvl] for lvl in topological_levels(tasks)] == [["a", "b"], ["c"]]


# ---------------------------------------------------------------- context
def test_fit_messages_keeps_system_and_latest_and_marks_drop():
    msgs = [Message(role="system", content="S")] + [Message(role="user", content="x" * 300) for _ in range(10)]
    fitted, dropped = fit_messages(msgs, budget_tokens=350)
    assert fitted[0].content == "S" and dropped > 0
    assert "omitted" in fitted[1].content
    assert fitted[-1] is msgs[-1]


# ---------------------------------------------------------------- tools
def test_safe_eval():
    assert safe_eval("2^10 + sqrt(16)") == 1028
    for bad in ["__import__('os')", "open('x')", "(1).__class__", "9**999999"]:
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval(bad)


async def test_calculator_reports_errors():
    assert (await Calculator().run({"expression": "1/0"})).ok is False


async def test_workspace_blocks_traversal(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    tool = ReadFile(Workspace(tmp_path))
    assert (await tool.run({"path": "a.txt"})).content == "hello"
    assert (await tool.run({"path": "../../etc/passwd"})).ok is False


async def test_python_runner_executes_and_times_out():
    out = await PythonRunner().run({"code": "print(sum(range(10)))"})
    assert out.ok and out.content == "45"
    slow = await PythonRunner(timeout_s=1).run({"code": "while True: pass"})
    assert slow.ok is False


async def test_web_fetch_blocks_private_addresses():
    for url in ["http://127.0.0.1:8080/", "http://localhost/", "file:///etc/passwd", "http://169.254.169.254/"]:
        assert (await WebFetch().run({"url": url})).ok is False


# ---------------------------------------------------------------- agent loop
async def test_agent_runs_tool_then_answers(tmp_path):
    provider = ScriptedProvider([call("calculator", {"expression": "6*7"}), text("The answer is ", "42.")])
    broker = PermissionBroker()
    run = AgentRun()
    events = [e async for e in run_agent(provider, [Message(role="user", content="6*7?")],
                                         tools=default_registry(tmp_path).subset(["calculator"]), broker=broker, run=run)]
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result", "delta", "delta"]
    assert events[1]["content"] == "6*7 = 42"
    assert run.text == "The answer is 42."
    # the second request carries the tool result back to the model
    assert provider.requests[1].messages[-1].role == "tool"


async def test_agent_permission_ask_allow_and_deny(tmp_path):
    reg = default_registry(tmp_path)
    for decision, expect_file in [("allow_once", True), ("deny", False)]:
        provider = ScriptedProvider([call("write_file", {"path": f"{decision}.txt", "content": "x"}), text("done")])
        broker = PermissionBroker()
        events = []
        async for ev in run_agent(provider, [Message(role="user", content="write")], tools=reg.subset(["write_file"]),
                                  broker=broker, run=AgentRun()):
            events.append(ev)
            if ev["type"] == "permission_request":
                asyncio.get_running_loop().call_soon(broker.resolve, ev["id"], decision)
        assert (tmp_path / f"{decision}.txt").exists() is expect_file
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["ok"] is expect_file


async def test_agent_stops_on_provider_error():
    provider = ScriptedProvider([[StreamEvent(kind="error", text="boom")]])
    run = AgentRun()
    events = [e async for e in run_agent(provider, [Message(role="user", content="x")], tools=[],
                                         broker=PermissionBroker(), run=run)]
    assert events == [{"type": "error", "message": "boom"}] and run.error == "boom"


# ---------------------------------------------------------------- orchestrator
def make_orchestrator(provider, tmp_path, adapters=True):
    def resolve(spec):
        return Backend(provider=provider, model=None, adapter=spec.adapter if adapters else None)

    return Orchestrator(CATALOG, resolve, default_registry(tmp_path), PermissionBroker())


async def test_orchestrator_single_specialist_uses_adapter_and_custom_instructions(tmp_path):
    provider = ScriptedProvider([text("Take 500 mg.")])
    orch = make_orchestrator(provider, tmp_path)
    opts = OrchestratorOptions(custom_instructions="Answer in Spanish.")
    events = [e async for e in orch.run([], "What dose of paracetamol for fever in adults?", opts)]
    route = next(e for e in events if e["type"] == "route")
    assert route["mode"] == "single" and route["specialists"][0]["id"] == "medicine"
    req = provider.requests[0]
    assert req.adapter == "spike-medicine"
    assert "Spike Medicine" in req.messages[0].content and "Answer in Spanish." in req.messages[0].content
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Take 500 mg."


async def test_orchestrator_multi_with_llm_plan_and_synthesis(tmp_path):
    plan = {"subtasks": [
        {"id": "t1", "specialist": "marketing", "instruction": "Campaign plan", "depends_on": []},
        {"id": "t2", "specialist": "finance", "instruction": "ROI estimate", "depends_on": ["t1"]},
    ]}
    provider = ScriptedProvider([text(json.dumps(plan)), text("CAMPAIGN"), text("ROI 12%"), text("FINAL")])
    orch = make_orchestrator(provider, tmp_path)
    events = [e async for e in orch.run([], "Plan a marketing campaign for our ETF and estimate the ROI of the investment",
                                        OrchestratorOptions())]
    types = [e["type"] for e in events]
    assert "plan" in types and types.count("subtask_start") == 2 and "synthesis_start" in types
    assert provider.requests[0].json_schema is not None  # planner uses constrained output
    assert provider.requests[2].adapter == "spike-finance"
    assert "CAMPAIGN" in provider.requests[2].messages[1].content  # dependency output passed on
    assert "ROI 12%" in provider.requests[3].messages[-1].content  # synthesis sees reports
    assert events[-1]["text"] == "FINAL"


async def test_orchestrator_planner_fallback_on_invalid_json(tmp_path):
    provider = ScriptedProvider([text("I cannot do JSON"), text("A"), text("B"), text("MERGED")])
    orch = make_orchestrator(provider, tmp_path)
    events = [e async for e in orch.run([], "Draft the terms of service contract and the marketing landing page copy",
                                        OrchestratorOptions())]
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["method"] == "fallback" and plan["note"] == "planner output was invalid"
    assert events[-1]["text"] == "MERGED"


async def test_orchestrator_reports_prompt_profile_when_no_adapter(tmp_path):
    provider = ScriptedProvider([text("ok")])
    orch = make_orchestrator(provider, tmp_path, adapters=False)
    events = [e async for e in orch.run([], "Explain EBITDA vs cash flow", OrchestratorOptions())]
    info = next(e for e in events if e["type"] == "route")["specialists"][0]
    assert info["id"] == "finance" and info["profile_only"] is True and provider.requests[0].adapter is None


async def test_orchestrator_parallel_merges_events(tmp_path):
    plan = {"subtasks": [
        {"id": "t1", "specialist": "law", "instruction": "a", "depends_on": []},
        {"id": "t2", "specialist": "marketing", "instruction": "b", "depends_on": []},
    ]}
    provider = ScriptedProvider([text(json.dumps(plan)), text("L"), text("M"), text("F")])
    orch = make_orchestrator(provider, tmp_path)
    events = [e async for e in orch.run([], "contract clause and marketing campaign", OrchestratorOptions(parallel=True))]
    ends = [e for e in events if e["type"] == "subtask_end"]
    assert len(ends) == 2 and all(e["ok"] for e in ends)
