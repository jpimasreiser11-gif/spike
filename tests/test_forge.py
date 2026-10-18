"""Collective (roles, the checker that sends work back) and Forge (blueprint, deliverables, report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.forge import evaluate
from spike.forge.blueprint import clean_path, from_user, make_blueprint, validate_blueprint
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.orchestrator.planner import Subtask, validate_plan
from spike.orchestrator.verify import MAX_ROUNDS, dependents, parse_verdict
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker
from spike.tools.builtin import default_registry
from tests.helpers import ScriptedProvider, call, text

CATALOG = load_catalog()
OK = '{"results": []}'


def checker(*returned: tuple[str, str], criteria: list[bool] | None = None) -> str:
    rows = [{"id": sid, "ok": False, "fix": fix} for sid, fix in returned]
    out: dict = {"results": rows}
    if criteria is not None:
        out["criteria"] = [{"n": i, "ok": ok, "note": "" if ok else "falta"} for i, ok in enumerate(criteria, 1)]
    return json.dumps(out)


def orchestrator(provider, tmp_path):
    broker = PermissionBroker({"write_file": "allow"})
    return Orchestrator(CATALOG, lambda spec: Backend(provider=provider, model=None, adapter=None),
                        default_registry(tmp_path), broker)


def blueprint(steps, criteria=()):
    return from_user({"goal": "g", "requirements": [], "steps": steps, "criteria": list(criteria)}, CATALOG)


async def run(orch, task, opts):
    return [e async for e in orch.run([], task, opts)]


# ---------------------------------------------------------------- planner roles and the checker's parsing
def test_planner_roles_default_to_execute():
    steps = validate_plan({"subtasks": [
        {"id": "t1", "specialist": "data", "role": "research", "instruction": "datos", "depends_on": []},
        {"id": "t2", "specialist": "writing", "role": "boss", "instruction": "texto", "depends_on": ["t1"]},
        {"id": "t3", "specialist": "math", "instruction": "cuenta", "depends_on": []},
    ]}, CATALOG, 4)
    assert [s.role for s in steps] == ["research", "execute", "execute"]


def test_checker_output_needs_a_usable_fix():
    verdict = parse_verdict(checker(("t1", "El total no suma 470,49 €; corrígelo"), ("t2", "mal"), ("zz", "otra cosa")),
                            ["t1", "t2"], [])
    assert verdict.returned == {"t1": "El total no suma 470,49 €; corrígelo"}  # "mal" says nothing to fix
    assert parse_verdict("no JSON here", ["t1"], []) is None
    judged = parse_verdict(checker(criteria=[True]), ["t1"], ["Incluye el total", "Tiene tres filas"])
    assert judged.criteria == [{"text": "Incluye el total", "ok": True, "note": ""},
                               {"text": "Tiene tres filas", "ok": None, "note": ""}]  # not judged: not checked


def test_dependents_are_sent_back_too():
    steps = [Subtask("t1", "data", "a"), Subtask("t2", "writing", "b", ["t1"]), Subtask("t3", "math", "c"),
             Subtask("t4", "core", "d", ["t2"])]
    assert dependents(steps, {"t1"}) == {"t1", "t2", "t4"}


# ---------------------------------------------------------------- blueprint
@pytest.mark.parametrize("path", ["informe.md", "datos/ventas.csv", "Informe final (v2).docx"])
def test_clean_paths(path):
    assert clean_path(path) == path
    assert clean_path("./datos//x.md") == "datos/x.md"


@pytest.mark.parametrize("path", ["", "/etc/passwd", "../fuera.md", "a/../../b", "C:/x.md", "dir/", "a\x00b",
                                  "a" * 201])
def test_paths_outside_the_folder_are_refused(path):
    with pytest.raises(ValueError):
        clean_path(path)


def test_the_models_draft_is_cleaned_up():
    bp = validate_blueprint({"goal": "Informe", "requirements": ["a", " ", "b"], "criteria": ["c"], "steps": [
        {"id": "t1", "specialist": "data", "role": "research", "instruction": "busca", "depends_on": ["t9"],
         "deliverables": ["../x.md", "datos.csv"]},
        {"id": "t2", "specialist": "nobody", "instruction": "x"},
    ]}, CATALOG)
    assert bp is None  # an unknown specialist makes the draft unusable: the fallback takes over
    bp = validate_blueprint({"goal": "Informe", "requirements": ["a", " ", "b"], "criteria": ["c"], "steps": [
        {"id": "t1", "specialist": "data", "role": "research", "instruction": "busca", "depends_on": ["t9"],
         "deliverables": ["../x.md", "datos.csv"]},
        {"id": "t2", "specialist": "writing", "instruction": "redacta", "depends_on": ["t1"],
         "deliverables": ["datos.csv", "informe.md"]},
    ]}, CATALOG)
    assert bp.requirements == ["a", "b"] and [s.deliverables for s in bp.steps] == [["datos.csv"], ["informe.md"]]
    assert bp.steps[0].depends_on == [] and bp.steps[1].depends_on == ["t1"] and bp.steps[1].role == "execute"


@pytest.mark.parametrize("steps, error", [
    ([], "at least one step"),
    ([{"id": "t1", "specialist": "x", "instruction": "a"}], "unknown specialist"),
    ([{"id": "t1", "specialist": "data", "instruction": ""}], "no instruction"),
    ([{"id": "t1", "specialist": "data", "instruction": "a", "depends_on": ["t2"]},
      {"id": "t2", "specialist": "data", "instruction": "b"}], "not an earlier step"),
    ([{"id": "t1", "specialist": "data", "instruction": "a", "deliverables": ["x.md"]},
      {"id": "t2", "specialist": "data", "instruction": "b", "deliverables": ["x.md"]}], "two steps save x.md"),
    ([{"id": "t1", "specialist": "data", "instruction": "a", "deliverables": ["/x.md"]}], "not a relative file"),
    ([{"id": "t1", "specialist": "data", "instruction": "a", "role": "boss"}], "role must be"),
    ([{"id": "t 1", "specialist": "data", "instruction": "a"}], "unique id"),
    ([{"id": f"t{i}", "specialist": "data", "instruction": "a"} for i in range(9)], "at most 8 steps"),
])
def test_the_users_blueprint_is_checked_strictly(steps, error):
    with pytest.raises(ValueError, match=error):
        blueprint(steps)


async def test_the_blueprint_is_drafted_with_constrained_output_or_falls_back():
    draft = {"goal": "Tabla de facturas", "requirements": ["IVA 21 %"], "criteria": ["Tres filas"], "steps": [
        {"id": "t1", "specialist": "data", "role": "execute", "instruction": "Crea facturas.csv", "depends_on": [],
         "deliverables": ["facturas.csv"]}]}
    provider = ScriptedProvider([text(json.dumps(draft))])
    bp = await make_blueprint(provider, CATALOG, "Calcula el IVA de tres facturas", ["data"])
    assert bp.method == "llm" and bp.deliverables == ["facturas.csv"] and bp.criteria == ["Tres filas"]
    assert provider.requests[0].json_schema["required"] == ["goal", "requirements", "steps", "criteria"]
    bp = await make_blueprint(ScriptedProvider([text("no sé")]), CATALOG, "Calcula el IVA", ["finance"])
    assert bp.method == "fallback" and bp.steps[0].specialist == "finance" and bp.note == "planner output was invalid"


# ---------------------------------------------------------------- Forge runs
async def test_a_missing_deliverable_goes_back_and_the_report_says_what_was_met(tmp_path):
    bp = blueprint([
        {"id": "t1", "specialist": "data", "role": "research", "instruction": "Reúne las cifras"},
        {"id": "t2", "specialist": "marketing", "instruction": "Escribe informe.md", "depends_on": ["t1"],
         "deliverables": ["informe.md"]},
    ], ["El informe tiene un título"])
    provider = ScriptedProvider([
        text("cifras: 120 y 250"), text("Hecho (sin guardar)"),  # round 1: t2 forgets the file
        text(checker(criteria=[False])),
        call("write_file", {"path": "informe.md", "content": "# Informe\n370 €\n"}), text("Guardado informe.md"),
        text(checker(criteria=[True])),
        text("FINAL"),
    ])
    events = await run(orchestrator(provider, tmp_path), "Haz el informe", OrchestratorOptions(forge=bp))
    route = next(e for e in events if e["type"] == "route")
    assert route["mode"] == "forge" and route["method"] == "blueprint"
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["method"] == "blueprint" and plan["subtasks"][1]["deliverables"] == ["informe.md"]
    starts = [(e["subtask"], e["role"], e["round"]) for e in events if e["type"] == "subtask_start"]
    assert starts == [("t1", "research", 1), ("t2", "execute", 1), ("t2.r2", "execute", 2)]
    first, second = [e for e in events if e["type"] == "verify"]
    assert first["checks"] == [{"subtask": "t2", "path": "informe.md", "ok": False, "bytes": 0}]
    assert "informe.md was not saved" in first["returned"][0]["fix"]
    assert second["returned"] == [] and second["checks"][0]["ok"]
    # marketing has no write_file of its own: the step got it for its deliverable
    assert "write_file" in [t.name for t in provider.requests[1].tools or []]
    retry = provider.requests[3].messages[-1].content
    assert "The checker sent your work back" in retry and "Hecho (sin guardar)" in retry
    assert "met" in provider.requests[-1].messages[-1].content  # the integrator sees the criteria verdict
    report = next(e for e in events if e["type"] == "forge_report")
    assert report["verified"] and report["rounds"] == 2 and report["unresolved"] == []
    assert report["criteria"] == [{"text": "El informe tiene un título", "ok": True, "note": ""}]
    assert (tmp_path / "informe.md").read_text(encoding="utf-8") == "# Informe\n370 €\n"
    assert events[-1]["type"] == "done" and events[-1]["text"] == "FINAL"


async def test_work_goes_back_at_most_twice(tmp_path):
    bp = blueprint([{"id": "t1", "specialist": "math", "instruction": "Suma 120 + 250,50 + 99,99"},
                    {"id": "t2", "specialist": "writing", "instruction": "Resume", "depends_on": ["t1"]}])
    wrong = checker(("t1", "La suma es 470,49, no 470"))
    provider = ScriptedProvider([text("470"), text("Total 470"), text(wrong),
                                 text("470,4"), text("Total 470,4"), text(wrong),
                                 text("470,5"), text("Total 470,5"), text(wrong), text("FINAL")])
    events = await run(orchestrator(provider, tmp_path), "Suma", OrchestratorOptions(forge=bp))
    starts = [e["subtask"] for e in events if e["type"] == "subtask_start"]
    assert starts == ["t1", "t2", "t1.r2", "t2.r2", "t1.r3", "t2.r3"]  # the summary used t1, so it runs again too
    assert len([e for e in events if e["type"] == "verify"]) == MAX_ROUNDS + 1
    feedback = next(e for e in events if e["type"] == "subtask_start" and e["subtask"] == "t2.r2")["feedback"]
    assert "revised" in feedback
    report = next(e for e in events if e["type"] == "forge_report")
    assert report["unresolved"] == [{"subtask": "t1", "fix": "La suma es 470,49, no 470"}] and report["rounds"] == 3
    assert events[-1]["text"] == "FINAL"


async def test_a_checker_that_cannot_answer_sends_nothing_back(tmp_path):
    plan = {"subtasks": [{"id": "t1", "specialist": "law", "instruction": "a", "depends_on": []},
                         {"id": "t2", "specialist": "marketing", "instruction": "b", "depends_on": []}]}
    provider = ScriptedProvider([text(json.dumps(plan)), text("L"), text("M"), text("no JSON"), text("F")])
    events = await run(orchestrator(provider, tmp_path), "contract clause and marketing campaign", OrchestratorOptions())
    verify = next(e for e in events if e["type"] == "verify")
    assert verify["method"] == "unavailable" and verify["note"] == "checker output was invalid"
    assert [e["subtask"] for e in events if e["type"] == "subtask_start"] == ["t1", "t2"]
    assert not any(e["type"] == "forge_report" for e in events) and events[-1]["text"] == "F"


async def test_the_checker_can_be_turned_off_for_chats_but_not_for_forge(tmp_path):
    plan = {"subtasks": [{"id": "t1", "specialist": "law", "instruction": "a", "depends_on": []},
                         {"id": "t2", "specialist": "marketing", "instruction": "b", "depends_on": []}]}
    provider = ScriptedProvider([text(json.dumps(plan)), text("L"), text("M"), text("F")])
    events = await run(orchestrator(provider, tmp_path), "contract clause and marketing campaign",
                       OrchestratorOptions(verify=False))
    assert not any(e["type"].startswith("verify") for e in events) and events[-1]["text"] == "F"
    bp = blueprint([{"id": "t1", "specialist": "law", "instruction": "a"}])
    provider = ScriptedProvider([text("L"), text(OK), text("F")])
    events = await run(orchestrator(provider, tmp_path), "x", OrchestratorOptions(verify=False, forge=bp))
    assert any(e["type"] == "verify" for e in events)  # one step, still checked: it is a Forge task


# ---------------------------------------------------------------- the app
@pytest.fixture
def app(tmp_path, monkeypatch):
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    state.broker.policies["write_file"] = "allow"
    client = TestClient(create_app(state))
    client.get("/api/providers")
    return client, state, local, tmp_path


def sse(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_forge_in_the_app_drafts_runs_and_keeps_the_report(app):
    client, state, local, home = app
    draft = {"goal": "Facturas", "requirements": ["IVA 21 %"], "criteria": ["Tres filas"], "steps": [
        {"id": "t1", "specialist": "data", "role": "execute", "instruction": "Crea facturas.csv", "depends_on": [],
         "deliverables": ["facturas.csv"]}]}
    local._script = [text(json.dumps(draft))]
    bp = client.post("/api/forge/blueprint", json={"task": "Calcula el IVA de tres facturas"}).json()
    assert bp["method"] == "llm" and bp["steps"][0]["deliverables"] == ["facturas.csv"]
    assert client.post("/api/chat", json={"message": "x", "forge": {"steps": [{"id": "t1", "specialist": "x",
                                                                               "instruction": "a"}]}}).status_code == 400
    assert client.post("/api/chat", json={"message": "x", "forge": bp, "response_schema": {"type": "object"}}
                       ).status_code == 400
    bp["criteria"].append("Los totales llevan dos decimales")  # the user edits before approving
    local._script = [call("write_file", {"path": "facturas.csv", "content": "base,iva,total\n120,25.20,145.20\n"}),
                     text("Guardé facturas.csv"), text(checker(criteria=[True, True])), text("Listo: facturas.csv")]
    events = sse(client.post("/api/chat", json={"message": "Calcula el IVA de tres facturas", "forge": bp}))
    report = next(e for e in events if e["type"] == "forge_report")
    assert report["verified"] and [c["ok"] for c in report["criteria"]] == [True, True]
    assert (home / "ws" / "facturas.csv").is_file()
    conv = next(e for e in events if e["type"] == "conversation")["id"]
    stored = client.get(f"/api/conversations/{conv}").json()["messages"][-1]["meta"]
    assert stored["forge"]["blueprint"]["method"] == "user" and stored["forge"]["report"]["rounds"] == 1
    assert stored["verify"][0]["returned"] == [] and stored["subtasks"]["t1"]["role"] == "execute"
    assert stored["route"]["mode"] == "forge"


# ---------------------------------------------------------------- the Forge test tasks
FIXTURES = Path(__file__).parent / "fixtures" / "forge"
TASKS = evaluate.load_tasks()


def test_there_are_ten_tasks_each_with_a_reference_that_passes(tmp_path):
    assert len(TASKS) == 10 and len({t["id"] for t in TASKS}) == 10
    for task in TASKS:
        assert evaluate.check_task(task, FIXTURES / task["id"]) == {"passed": True, "failed": []}, task["id"]
        empty = tmp_path / task["id"]
        empty.mkdir()
        result = evaluate.check_task(task, empty)
        assert not result["passed"] and len(result["failed"]) == len(task["checks"]), task["id"]


@pytest.mark.parametrize("task_id, files, why", [
    ("fizzbuzz", {"fizzbuzz.py": "def fizzbuzz(n):\n    return [str(i) for i in range(1, n + 1)]\n"}, "AssertionError"),
    ("facturas", {"facturas.csv": "base,iva,total\n120,25.20,145.20\n250.50,52.61,303.11\n99.99,21.00,120.99\n",
                  "informe.md": "Total: 569 €"}, "569,30"),
    ("prestamo", {"prestamo.md": "La cuota es de 300 €"}, "299,71"),
    ("email", {"email.md": "Laura, pedido 4512, llegará el 15 de noviembre. Disculpa. " + "palabra " * 150},
     "words"),
    ("cafeteria", {"plan.md": "## Objetivo\nx\n## Costes iniciales\n| Partida | € |\n|---|---|\n| A | 10 |\n"
                              "| B | 20 |\n| C | 30 |\n| Total | 70 |\n## Riesgos\nx\n## Próximos pasos\nx\n"}, "Total"),
    ("ventas", {"ventas.csv": "mes,ventas\n" + "".join(f"m{i},{100 * i}\n" for i in range(1, 13)),
                "resumen.md": "Total 7800, mejor mes m12, media 600"}, "media"),
    ("quiz", {"quiz.json": json.dumps([{"pregunta": "p", "opciones": ["a", "b", "c", "d"], "correcta": True}] * 5)},
     "correcta"),
])
def test_wrong_results_fail_their_checks(tmp_path, task_id, files, why):
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    result = evaluate.check_task(next(t for t in TASKS if t["id"] == task_id), tmp_path)
    assert not result["passed"] and why in json.dumps(result["failed"], ensure_ascii=False)


def test_the_cost_table_can_have_its_amounts_in_any_column(tmp_path):
    # the layout a real run wrote (Forge, Qwen3.5-4B): amounts in the middle, a description last, thousands with spaces
    table = ("| Partida | Coste (€) | Detalle |\n|---|---:|---|\n| Local y reformas | 45 000 | Arriendo inicial + reforma |\n"
             "| Equipo de cocina | 25 000 | Molinos, cafeteras |\n| Mobiliario | 8 000 | Mesas y sillas |\n")
    task = next(t for t in TASKS if t["id"] == "cafeteria")
    for total, passed in (("| **Total** | **78 000** | |", True), ("| **Total** | **80 000** | 3 partidas |", False)):
        (tmp_path / "plan.md").write_text(f"## Objetivo\nx\n## Costes iniciales\n{table}{total}\n## Riesgos\nx\n"
                                          "## Próximos pasos\nx\n", encoding="utf-8")
        assert evaluate.check_task(task, tmp_path)["passed"] is passed, total


def test_a_check_cannot_hang_the_eval(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "CHECK_TIMEOUT_S", 1)
    (tmp_path / "fizzbuzz.py").write_text("def fizzbuzz(n):\n    while True:\n        pass\n", encoding="utf-8")
    result = evaluate.check_task(next(t for t in TASKS if t["id"] == "fizzbuzz"), tmp_path)
    assert not result["passed"]


def test_wilson_interval():
    assert evaluate.wilson(7, 10) == (0.3968, 0.8922)
    assert evaluate.wilson(0, 0) == (0.0, 0.0) and evaluate.wilson(10, 10)[1] == 1.0


async def test_the_harness_runs_forge_and_the_baseline_in_fresh_folders(tmp_path):
    primes = "2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71"
    draft = {"goal": "primos", "requirements": [], "criteria": ["20 primos"], "steps": [
        {"id": "t1", "specialist": "math", "role": "execute", "instruction": "Guarda primos.txt", "depends_on": [],
         "deliverables": ["primos.txt"]}]}

    def script(request):
        system = request.messages[0].content
        last = request.messages[-1]
        if request.json_schema and "steps" in request.json_schema["properties"]:
            return text(json.dumps(draft))
        if request.json_schema:
            return text(checker(criteria=[True]))
        if last.role == "tool":
            return text("hecho")
        if "Spike Math" in system.split("\n")[0]:
            return call("write_file", {"path": "primos.txt", "content": primes})
        if "Specialist reports" in last.content:
            return text("Guardé primos.txt")
        return call("write_file", {"path": "primos.txt", "content": "2, 3, 5"})  # the core alone gets it wrong

    provider = ScriptedProvider(script)
    base = Orchestrator(CATALOG, lambda spec: Backend(provider=provider, model=None, adapter=None),
                        default_registry(tmp_path / "unused"), PermissionBroker())
    task = next(t for t in TASKS if t["id"] == "primos")
    report = await evaluate.evaluate(base, [task], ["forge", "baseline"], {"provider": "scripted"},
                                     keep=tmp_path / "kept")
    assert report["summary"]["forge"] == {"passed": 1, "n": 1, "rate": 1.0, "ci95": evaluate.wilson(1, 1)}
    assert report["summary"]["baseline"]["passed"] == 0
    forge, baseline = report["results"]
    assert forge["blueprint"] == "llm" and forge["rounds"] == 1 and baseline["failed"][0]["why"]
    assert not (tmp_path / "unused" / "primos.txt").exists()  # each task wrote in its own folder
    kept = tmp_path / "kept"  # --keep: each task's files, to see why it failed
    assert (kept / "primos-forge" / "primos.txt").read_text(encoding="utf-8") == primes
    assert (kept / "primos-baseline" / "primos.txt").read_text(encoding="utf-8") == "2, 3, 5"
