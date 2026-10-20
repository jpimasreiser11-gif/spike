"""Collective (roles, the checker that sends work back) and Forge (blueprint, deliverables, report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.forge import evaluate
from spike.forge.blueprint import clean_path, from_user, make_blueprint, validate_blueprint
from spike.orchestrator import verify
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.orchestrator.planner import Subtask, validate_plan
from spike.orchestrator.verify import MAX_ROUNDS, dependents, format_check, parse_verdict, run_outcome
from spike.providers.guard import GuardedProvider
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from spike.store.db import Store
from spike.tools.base import HeadlessBroker, PermissionBroker
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


def orchestrator(provider, tmp_path, broker=None):
    broker = broker or PermissionBroker({"write_file": "allow"})
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
    # the checker reads the saved file itself, once there is one
    assert "Saved file" not in provider.requests[2].messages[-1].content
    assert "## Saved file informe.md (t2)\n<<<\n# Informe\n370 €\n\n>>>" in provider.requests[5].messages[-1].content
    report = next(e for e in events if e["type"] == "forge_report")
    assert report["verified"] and report["rounds"] == 2 and report["unresolved"] == []
    assert report["criteria"] == [{"text": "El informe tiene un título", "ok": True, "note": ""}]
    assert (tmp_path / "informe.md").read_text(encoding="utf-8") == "# Informe\n370 €\n"
    assert events[-1]["type"] == "done" and events[-1]["text"] == "FINAL"


def test_the_checker_gets_the_saved_text_files_clipped(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "FILE_CHARS", 10)
    monkeypatch.setattr(verify, "FILES_CHARS", 15)
    (tmp_path / "a.md").write_text("0123456789abc", encoding="utf-8")
    (tmp_path / "b.docx").write_bytes(b"PK\x03\x04")
    (tmp_path / "c.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    checks = [{"subtask": "t1", "path": p, "ok": True, "bytes": 1} for p in ("a.md", "b.docx", "c.csv")]
    checks.append({"subtask": "t2", "path": "d.md", "ok": False, "bytes": 0})
    assert verify.saved_texts(checks, tmp_path) == [  # binary and missing files left out, 15 characters in all
        {"subtask": "t1", "path": "a.md", "text": "0123456789", "clipped": True},
        {"subtask": "t1", "path": "c.csv", "text": "x,y\n1", "clipped": True}]


async def test_a_one_step_plan_answers_with_its_own_summary(tmp_path):
    bp = blueprint([{"id": "t1", "specialist": "writing", "instruction": "Escribe nota.md", "deliverables": ["nota.md"]}],
                   ["La nota existe"])
    provider = ScriptedProvider([call("write_file", {"path": "nota.md", "content": "Hola"}),
                                 text("Guardé nota.md con un saludo."), text(checker(criteria=[True]))])
    events = await run(orchestrator(provider, tmp_path), "Escribe una nota", OrchestratorOptions(forge=bp))
    assert len(provider.requests) == 3 and not any(e["type"] == "synthesis_start" for e in events)  # no integrator
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Guardé nota.md con un saludo."
    assert next(e for e in events if e["type"] == "forge_report")["criteria"][0]["ok"] is True


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


# ---------------------------------------------------------------- checks SPIKE runs on the saved files
ALL_MET = checker(criteria=[True])
SLUG = ("ACENTOS = {'á': 'a', 'ñ': 'n'}\n\n\ndef slugify(texto):\n    texto = texto.lower()\n"
        "    for a, b in NAMES.items():\n        texto = texto.replace(a, b)\n    return texto\n")


def code_step(*paths, instruction="Guarda el archivo"):
    return blueprint([{"id": "t1", "specialist": "code", "instruction": instruction, "deliverables": list(paths)}],
                     ["El archivo existe"])


def write(path, content):
    return call("write_file", {"path": path, "content": content})


def allowed(**policies):
    return PermissionBroker({"write_file": "allow", "python": "allow", **policies})


async def test_a_name_nothing_defines_goes_back_with_the_error_and_is_fixed_in_round_2(tmp_path):
    # the typo is inside the function: importing or running the file never reaches it, so SPIKE reads the names
    provider = ScriptedProvider([
        write("slug.py", SLUG.replace("NAMES", "ACCENTOS")), text("Guardé slug.py"), text(ALL_MET),  # the checker passes it
        write("slug.py", SLUG.replace("NAMES", "ACENTOS")), text("Corregido"), text(ALL_MET),
    ])
    events = await run(orchestrator(provider, tmp_path, allowed()), "Escribe slug.py", OrchestratorOptions(forge=code_step("slug.py")))
    assert [e["subtask"] for e in events if e["type"] == "subtask_start"] == ["t1", "t1.r2"]
    first, second = [e for e in events if e["type"] == "verify"]
    assert first["checks"][0]["program"] == {
        "ok": False, "note": "would raise NameError: name 'ACCENTOS' is not defined at line 6: "
                             "`for a, b in ACCENTOS.items():`"}
    fix = first["returned"][0]["fix"]  # the checker had no complaint: this is SPIKE's
    assert "slug.py would raise NameError: name 'ACCENTOS' is not defined at line 6" in fix
    assert "save it again at exactly that path" in fix
    # the checker is told as a fact, the specialist gets it as the reason to redo the file
    asked = provider.requests[2].messages[-1].content
    assert "# Checks SPIKE ran on the saved files" in asked
    assert "- slug.py (t1), FAILED: would raise NameError: name 'ACCENTOS' is not defined at line 6" in asked
    assert "NameError: name 'ACCENTOS' is not defined" in provider.requests[3].messages[-1].content
    assert second["returned"] == [] and second["checks"][0]["program"]["ok"] is True
    assert second["checks"][0]["program"]["note"] == "compiles, uses no name that is not defined, imports without an error"
    assert "- slug.py (t1), passed: compiles" in provider.requests[5].messages[-1].content
    report = next(e for e in events if e["type"] == "forge_report")
    assert report["rounds"] == 2 and report["unresolved"] == [] and report["verified"]
    assert "ACENTOS.items()" in (tmp_path / "slug.py").read_text(encoding="utf-8")


async def test_a_file_that_fails_when_imported_goes_back_with_the_last_lines_of_the_traceback(tmp_path):
    bad = "import json\nLIMITE = int('diez')\n"
    provider = ScriptedProvider([write("util.py", bad), text("Guardé"), text(ALL_MET),
                                 write("util.py", "LIMITE = 10\n"), text("Corregido"), text(ALL_MET)])
    events = await run(orchestrator(provider, tmp_path, allowed()), "util.py", OrchestratorOptions(forge=code_step("util.py")))
    first = next(e for e in events if e["type"] == "verify")
    assert first["checks"][0]["program"] == {
        "ok": False, "note": "raised ValueError: invalid literal for int() with base 10: 'diez' at line 2: `LIMITE = int('diez')`"}
    assert "util.py raised ValueError" in first["returned"][0]["fix"]
    assert next(e for e in events if e["type"] == "forge_report")["rounds"] == 2


async def test_a_json_file_that_does_not_parse_goes_back_and_is_fixed(tmp_path):
    provider = ScriptedProvider([write("campana.json", '{"publico": "x", "canales": ["a", "b",]}'), text("Guardé"),
                                 text(ALL_MET), write("campana.json", '{"publico": "x", "canales": ["a", "b"]}'),
                                 text("Corregido"), text(ALL_MET)])
    events = await run(orchestrator(provider, tmp_path), "campana.json", OrchestratorOptions(forge=code_step("campana.json")))
    first, second = [e for e in events if e["type"] == "verify"]
    assert first["checks"][0]["program"]["ok"] is False
    assert "campana.json is not valid JSON: " in first["returned"][0]["fix"] and "line 1 column 38" in first["returned"][0]["fix"]
    assert second["returned"] == [] and second["checks"][0]["program"] == {"ok": True, "note": "is valid JSON"}
    assert next(e for e in events if e["type"] == "forge_report")["rounds"] == 2


async def test_files_that_pass_are_reported_as_passed_and_not_sent_back(tmp_path):
    work = tmp_path / "ws"
    work.mkdir()
    imported, started = tmp_path / "imported", tmp_path / "started"
    program = (f"open({str(imported)!r}, 'w').close()\nopen('scratch.txt', 'w').close()\n\n\ndef main():\n"
               f"    input('nombre? ')\n    open({str(started)!r}, 'w').close()\n\n\n"
               "if __name__ == '__main__':\n    main()\n")
    files = {"app.py": program, "datos.json": '{"a": [1, 2]}', "ventas.csv": "mes,ventas\nene,100\nfeb,200\n",
             "nota.md": "# Nota\nHola\n"}
    provider = ScriptedProvider([*(write(p, c) for p, c in files.items()), text("Guardé todo"), text(ALL_MET)])
    events = await run(orchestrator(provider, work, allowed()), "Guarda cuatro archivos",
                       OrchestratorOptions(forge=code_step(*files)))
    (verify_event,) = [e for e in events if e["type"] == "verify"]
    assert verify_event["returned"] == [] and [c["program"]["ok"] for c in verify_event["checks"]] == [True] * 4
    assert next(e for e in events if e["type"] == "forge_report")["rounds"] == 1
    asked = provider.requests[-1].messages[-1].content
    assert asked.count(", passed: ") == 4 and "FAILED" not in asked and "not fully checked" not in asked
    assert imported.exists() and not started.exists()  # imported, not started: the __main__ block did not run
    assert sorted(p.name for p in work.iterdir()) == sorted(files)  # it ran in a copy: no scratch.txt here


@pytest.mark.parametrize("setup, answer, ran, why", [
    ("ask", "allow_once", True, ""),
    ("ask", "deny", False, "the user denied this tool call"),
    ("deny", None, False, "the user has disabled the 'python' tool"),
    ("headless", None, False, "'python' needs the user's approval"),
])
async def test_nothing_is_imported_without_the_permission_the_python_tool_needs(tmp_path, setup, answer, ran, why):
    work = tmp_path / "ws"
    work.mkdir()
    marker = tmp_path / "imported"
    provider = ScriptedProvider([write("hola.py", f"open({str(marker)!r}, 'w').close()\n"), text("Guardé"),
                                 text(ALL_MET)])
    policies = {"write_file": "allow", **({"python": "deny"} if setup == "deny" else {})}
    broker = HeadlessBroker(PermissionBroker(policies)) if setup == "headless" else PermissionBroker(policies)
    orch = orchestrator(provider, work, broker)
    events = []
    async for ev in orch.run([], "hola.py", OrchestratorOptions(forge=code_step("hola.py"))):
        events.append(ev)
        if ev["type"] == "permission_request":
            assert ev["tool"] == "python" and ev["risk"] == "execute" and "hola.py" in ev["arguments"]["code"]
            assert broker.resolve(ev["id"], answer)
    asked = [e for e in events if e["type"] == "permission_request"]
    assert len(asked) == (1 if setup == "ask" else 0)
    program = next(e for e in events if e["type"] == "verify")["checks"][0]["program"]
    assert marker.exists() is ran
    if ran:
        assert program["ok"] is True
    else:  # not run is not a failure: nothing goes back, and the checker is told what was not checked
        assert program["ok"] is None and f"not imported: {why}" in program["note"]
        assert "not fully checked" in provider.requests[-1].messages[-1].content
    assert next(e for e in events if e["type"] == "forge_report")["rounds"] == 1


async def test_a_remote_checker_does_not_get_what_the_checks_quote_of_the_users_file(tmp_path):
    secret = "ZX-ALBATROS-9931"
    (tmp_path / "notas.txt").write_text(f"El código de acceso es {secret}.\n", encoding="utf-8")
    store = Store(tmp_path / "s.db")
    local = ScriptedProvider([call("read_file", {"path": "notas.txt"}),
                              write("codigo.py", f"CODIGO = int('{secret}')\n"), text("Guardé codigo.py"),
                              write("codigo.py", "CODIGO = 1\n"), text("Corregido")], name="local")
    local.config.local = True
    remote = ScriptedProvider([text(ALL_MET), text(ALL_MET)], name="remote")
    guarded_local, guarded_remote = GuardedProvider(local, store), GuardedProvider(remote, store)

    def resolve(spec):
        return Backend(provider=guarded_local if spec.id == "code" else guarded_remote, model=None, adapter=None)

    orch = Orchestrator(CATALOG, resolve, default_registry(tmp_path),
                        PermissionBroker({"read_file": "allow", "write_file": "allow", "python": "allow"}))
    events = await run(orch, "Guarda un código a partir de mis notas", OrchestratorOptions(forge=code_step("codigo.py")))
    first = next(e for e in events if e["type"] == "verify")
    assert secret in first["checks"][0]["program"]["note"]  # the check found the error and quoted the file
    redo = next(r.messages[-1].content for r in local.requests if "sent your work back" in r.messages[-1].content)
    assert secret in redo  # the local specialist that read the file is told what is wrong
    sent = [m.content for r in remote.requests for m in r.messages]
    assert all(secret not in c for c in sent)  # the remote checker is not
    assert "- codigo.py (t1), FAILED: [file content withheld" in remote.requests[0].messages[-1].content
    assert "- codigo.py (t1), passed: compiles" in remote.requests[1].messages[-1].content  # a pass says nothing private
    assert next(e for e in events if e["type"] == "forge_report")["rounds"] == 2


@pytest.mark.parametrize("path, content, note", [
    ("a.py", "def f(:\n    pass\n", "does not compile: SyntaxError: invalid syntax at line 1: `def f(:`"),
    ("a.py", "def f():\n    return y\n", "would raise NameError: name 'y' is not defined at line 2: `return y`"),
    ("a.json", '{"a": 1', "is not valid JSON: Expecting ',' delimiter: line 1 column 8 (char 7)"),
    ("a.csv", "mes,ventas\nene,100\nfeb,200,9\n", "has 3 columns on line 3 but the header has 2"),
    ("a.csv", 'mes,ventas\n"ene,100\n', "is not valid CSV: unexpected end of data (line 2)"),
    ("a.tsv", "a\tb\n1\n", "has 1 columns on line 2 but the header has 2"),
    ("a.md", " \n\n", "has no content"),
])
def test_files_that_are_wrong_are_found_without_running_them(path, content, note):
    assert format_check(path, content) == {"ok": False, "note": note}


def test_valid_python_is_never_flagged_for_a_name_it_does_define():
    code = (
        "import os.path\nimport numpy as np\nfrom typing import List\n\nTOTAL: int = 0\n\n\n"
        "class A(List):\n    def f(self, *args, **kw):\n        global TOTAL\n        TOTAL = len(args)\n"
        "        return [x for x in range(3)] + [__class__, __file__, __name__]\n\n\n"
        "def g(n, k=os.path.sep):\n    try:\n        return n.real\n    except (OSError, ValueError) as exc:\n"
        "        return str(exc)\n    finally:\n        pass\n\n\n"
        "with open('x') as fh:\n    h = lambda z: z + len(fh.name)\nmatch h(1):\n    case [first, *rest]:\n"
        "        print(first, rest)\n    case {'k': v, **others}:\n        print(v, others)\n"
        "if (n := np.zeros(1)) is not None:\n    print(n)\n"
    )
    assert format_check("ok.py", code)["ok"] is True
    assert format_check("star.py", "from math import *\nprint(sqrt(4), nada)\n")["ok"] is True  # names we cannot see
    assert format_check("dyn.py", "globals()['x'] = 1\nprint(x)\n")["ok"] is True


def test_an_import_that_cannot_be_judged_does_not_send_work_back():
    trace = ('Traceback (most recent call last):\n  File "main.py", line 1, in <module>\n    nombre = input()\n'
             "EOFError: EOF when reading a line")
    missing = trace.replace("EOFError: EOF when reading a line", "ModuleNotFoundError: No module named 'pandas'")
    static = "compiles"
    for content in (f"[stderr]\n{trace}", f"[stderr]\n{missing}", "error: timed out after 30s",
                    "error: the user denied this tool call"):
        assert run_outcome("main.py", ["main.py"], content, False, static)["ok"] is None, content
    assert run_outcome("main.py", ["main.py"], f"[stderr]\n{missing}", False, static)["note"].endswith(
        "No module named 'pandas'")
    assert run_outcome("main.py", ["main.py"], "(no output)", True, static) == {
        "ok": True, "note": "compiles, imports without an error"}


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
    trace = json.loads((kept / "primos-forge" / "_forge-trace.json").read_text(encoding="utf-8"))
    assert trace["blueprint"]["steps"][0]["deliverables"] == ["primos.txt"] and trace["verify"][0]["round"] == 1
    assert trace["verify"][0]["checks"][0]["program"] == {"ok": True, "note": "has content"}  # what SPIKE's checks found
    assert not (kept / "primos-baseline" / "_forge-trace.json").exists() and "trace" not in forge
