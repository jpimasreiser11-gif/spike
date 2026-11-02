"""G3: Forge blueprint validation reliability against non-list/non-string payloads and loose model JSON drafts."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from spike.forge.blueprint import clean_path, from_user, make_blueprint
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker
from spike.tools.builtin import default_registry
from tests.helpers import ScriptedProvider, text

CATALOG = load_catalog()


@pytest.mark.parametrize("raw", [None, True, 123, ["informe.md"], {"path": "informe.md"}])
def test_clean_path_refuses_non_string_values(raw):
    with pytest.raises(ValueError, match="relative file path"):
        clean_path(raw)  # type: ignore[arg-type]


@pytest.mark.parametrize("payload, error", [
    ({"steps": [{"id": "t1", "specialist": "code", "instruction": "Escribe main", "deliverables": "main"}]},
     "deliverables"),
    ({"steps": [{"id": "t1", "specialist": "code", "instruction": "a", "deliverables": 123}]}, "deliverables"),
    ({"steps": [{"id": "t1", "specialist": "code", "instruction": "a", "deliverables": {"path": "a.py"}}]},
     "deliverables"),
    ({"steps": [{"id": "t1", "specialist": "code", "instruction": "a", "deliverables": [None]}]},
     "relative file path"),
    ({"steps": [{"id": "t", "specialist": "data", "instruction": "a"},
                {"id": "t2", "specialist": "writing", "instruction": "b", "depends_on": "t"}]}, "depends_on"),
    ({"steps": [{"id": "t1", "specialist": "data", "instruction": "a", "depends_on": 1}]}, "depends_on"),
    ({"steps": [{"id": "t1", "specialist": "data", "instruction": "a"},
                {"id": "t2", "specialist": "data", "instruction": "b", "depends_on": [1]}]}, "depends_on"),
    ({"steps": [{"id": 123, "specialist": "data", "instruction": "a"}]}, "unique id"),
    ({"steps": [{"id": "t1", "specialist": 123, "instruction": "a"}]}, "unknown specialist"),
    ({"steps": [{"id": "t1", "specialist": "data", "instruction": True}]}, "no instruction"),
    ({"steps": [{"id": "t1", "specialist": "data", "instruction": ["a"]}]}, "no instruction"),
    ({"goal": 123, "steps": [{"id": "t1", "specialist": "data", "instruction": "a"}]}, "goal"),
    ({"note": ["x"], "steps": [{"id": "t1", "specialist": "data", "instruction": "a"}]}, "note"),
    ({"requirements": [None], "steps": [{"id": "t1", "specialist": "data", "instruction": "a"}]}, "requirements"),
    ({"criteria": [123], "steps": [{"id": "t1", "specialist": "data", "instruction": "a"}]}, "criteria"),
])
def test_from_user_rejects_non_list_or_non_string_fields_with_value_error(payload, error):
    with pytest.raises(ValueError, match=error):
        from_user({"goal": "g", "requirements": [], "criteria": [], **payload}, CATALOG)


def test_from_user_deduplicates_repeated_step_dependencies():
    bp = from_user({"goal": "g", "requirements": [], "criteria": [], "steps": [
        {"id": "t1", "specialist": "data", "instruction": "lee"},
        {"id": "t2", "specialist": "writing", "instruction": "redacta", "depends_on": ["t1", "t1"]},
    ]}, CATALOG)
    assert bp.steps[1].depends_on == ["t1"]


async def test_make_blueprint_and_forge_run_survive_malformed_model_drafts(tmp_path):
    # Models without strict JSON-schema support may emit scalar/object fields instead of arrays.
    loose = {
        "goal": ["Resumen"],
        "requirements": ["Claro", None, 99],
        "criteria": ["Breve", False],
        "steps": [
            {"id": "t1", "specialist": "data", "role": "research", "instruction": "Obtén cifras",
             "depends_on": 1, "deliverables": {"path": "cifras.csv"}},
            {"id": "t2", "specialist": "writing", "role": "execute", "instruction": "Resume las cifras",
             "depends_on": "t1", "deliverables": "nota.md"},
        ],
    }
    draft_provider = ScriptedProvider([
        text(json.dumps(loose)),
        text(json.dumps({"goal": "x", "requirements": [], "criteria": [],
                         "steps": [{"id": "t1", "specialist": "code", "instruction": ["lista"]}]})),
    ])
    bp = await make_blueprint(draft_provider, CATALOG, "Resume las ventas", ["writing"])
    assert bp.method == "llm"
    assert bp.goal == "" and bp.requirements == ["Claro"] and bp.criteria == ["Breve"]
    # Neither {"path": ...} nor "nota.md" may crash or split into single-letter files ["n", "o", "t", "a"].
    assert [s.deliverables for s in bp.steps] == [[], []]
    assert [s.depends_on for s in bp.steps] == [[], []]

    fallback = await make_blueprint(draft_provider, CATALOG, "Escribe código", ["code"])
    assert fallback.method == "fallback" and fallback.note == "planner output was invalid"

    run_provider = ScriptedProvider([
        text("Ventas: 370 €"),
        text("Resumen: 370 €"),
        text(json.dumps({"results": [], "criteria": [{"n": 1, "ok": True, "note": ""}]})),
        text("Resumen final: 370 €"),
    ])
    orch = Orchestrator(CATALOG, lambda spec: Backend(provider=run_provider, model=None, adapter=None),
                        default_registry(tmp_path), PermissionBroker({"write_file": "allow"}))
    events = [e async for e in orch.run([], "Resume las ventas", OrchestratorOptions(forge=bp))]
    report = next(e for e in events if e["type"] == "forge_report")
    assert report["verified"] and report["rounds"] == 1 and report["unresolved"] == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad_step", [
    {"id": "t1", "specialist": "code", "instruction": "a", "deliverables": "main"},
    {"id": "t1", "specialist": "code", "instruction": "a", "deliverables": 123},
    {"id": "t1", "specialist": "code", "instruction": "a", "deliverables": {"path": "a.py"}},
    {"id": "t1", "specialist": "code", "instruction": "a", "depends_on": 123},
])
def test_chat_and_prototypes_endpoints_return_400_on_malformed_blueprint_types(tmp_path, monkeypatch, bad_step):
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state), raise_server_exceptions=True)
    forge = {"goal": "g", "requirements": [], "criteria": [], "steps": [bad_step]}
    res_chat = client.post("/api/chat", json={"message": "x", "forge": forge})
    assert res_chat.status_code == 400 and res_chat.json()["detail"].startswith("blueprint:")
    res_proto = client.post("/api/forge/prototypes", json={"task": "x", "blueprints": [forge, forge]})
    assert res_proto.status_code == 400 and res_proto.json()["detail"].startswith("prototypes:")
    assert local.requests == []
