"""Evolution: corrections, route corrections and failures recorded locally, the router learned behind its gate,
eval candidates, the regression check and versioned adapters with rollback."""

import asyncio
import json
import struct
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.cli import main
from spike.core.types import StreamEvent
from spike.evolution import adapters
from spike.evolution.acceptance import check_acceptance
from spike.evolution.candidates import contamination, judge, references, suggested_checks
from spike.evolution.checks import run_checks
from spike.evolution.router_learning import apply_overlay, evaluate, gate, learn_overlay, load_labeled
from spike.evolution.service import Evolution
from spike.evolution.store import EvolutionStore
from spike.orchestrator.router import LexicalRouter
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from tests.helpers import ScriptedProvider, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from spike_train import evaluation as training_eval  # noqa: E402

CATALOG = load_catalog()
PET = "Mi perro tiene diarrea desde ayer, ¿qué le doy?"
CAT = "Mi gato vomita pelo cada semana"
JOB = "Escribe una oferta de empleo para un puesto de camarero"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")
    return client, state, local, tmp_path


def chat(client, local, body, script):
    local._script = [script] if isinstance(script, list) else [text(script)]
    return [json.loads(line[6:]) for line in client.post("/api/chat", json={"mode": "auto", **body}).text.splitlines()
            if line.startswith("data: ")]


def conv_of(events):
    return next(e for e in events if e["type"] == "conversation")


# ---------------------------------------------------------------- store
def test_versions_roll_back_to_what_they_replaced(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    v1 = store.add_version("router", {"n": 1})
    v2 = store.add_version("router", {"n": 2})
    assert store.active("router")["id"] == v2["id"] and v2["replaces"] == v1["id"]
    assert store.rollback("router")["id"] == v1["id"]
    v3 = store.add_version("router", {"n": 3})
    assert v3["replaces"] == v1["id"]  # not the rolled-back v2
    assert store.rollback("router")["id"] == v1["id"]
    assert store.rollback("router") is None and store.active("router") is None  # built-in
    with pytest.raises(LookupError):
        store.rollback("router")
    rejected = store.add_version("router", {"n": 4}, activate=False)
    assert not rejected["active"] and store.active("router") is None
    assert [v["data"]["n"] for v in store.versions("router")] == [4, 3, 2, 1]


def test_items_are_stored_found_updated_and_deleted(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    item = store.add("route", {"query": "q", "message": "m1"})
    assert store.find("route", message="m1")["id"] == item["id"]
    assert store.update(item["id"], status="ignored", query="q2")["query"] == "q2"
    assert store.items("route", "ignored")[0]["status"] == "ignored"
    assert store.delete(item["id"]) and store.get(item["id"]) is None
    with pytest.raises(ValueError):
        store.add("nonsense", {})


# ---------------------------------------------------------------- acceptance parity with the training copy
def _summary(gain_tuned, general_tuned):
    def preds(variant, results, suite):
        return [{"suite": suite, "task": suite[0], "item": f"{suite}/{i}", "variant": variant, "correct": c,
                 "parsed": "A", "finish_reason": "stop"} for i, c in enumerate(results)]
    base = [True] * 50 + [False] * 50
    general = [True] * 60 + [False] * 40
    return training_eval.summarize(preds("base", base, "medicine") + preds("spike-medicine", gain_tuned, "medicine")
                                   + preds("base", general, "general") + preds("spike-medicine", general_tuned, "general"))


@pytest.mark.parametrize("acceptance", [
    {"primary": {"suite": "medicine", "min_gain_points": 3.0, "max_p_value": 0.05},
     "regression": {"suite": "general", "max_drop_points": 1.5}},
    {"primary": {"suite": "medicine", "min_gain_points": 3.0, "max_p_value": 0.05},
     "regression": {"suite": "general", "max_drop_points": 0.5}},
    {"primary": {"suite": "medicine", "min_gain_points": 20.0}},
    {"primary": {"suite": "finance", "min_gain_points": 3.0}},
    {"regression": {"suite": "law", "max_drop_points": 1.0}},
])
@pytest.mark.parametrize("tuned", [
    ([True] * 62 + [False] * 38, [True] * 59 + [False] * 41),
    ([True] * 51 + [False] * 49, [True] * 60 + [False] * 40),
    ([True] * 45 + [False] * 55, [True] * 50 + [False] * 50),
])
def test_acceptance_copy_gives_the_training_verdicts(acceptance, tuned):
    summary = _summary(*tuned)
    assert check_acceptance(summary, acceptance, "spike-medicine") == \
        training_eval.check_acceptance(summary, acceptance, "spike-medicine")


# ---------------------------------------------------------------- router learning
def test_router_learns_route_corrections_without_hurting_the_router_set():
    corrections = [{"query": PET, "specialist": "medicine"}, {"query": CAT, "specialist": "medicine"},
                   {"query": JOB, "specialist": "business"}]
    assert [LexicalRouter(CATALOG).route(c["query"]).specialists[0] for c in corrections] == ["core"] * 3
    overlay = learn_overlay(CATALOG, corrections, load_labeled("dev"))
    report = gate(CATALOG, overlay, corrections)
    assert report["accepted"], report["reasons"]
    assert report["before"]["corrections"]["primary"] == 0 and report["after"]["corrections"]["primary"] == 1
    for split in ("dev", "test"):
        assert report["after"][split] == report["before"][split] == evaluate(CATALOG, load_labeled(split))
    learned = LexicalRouter(apply_overlay(CATALOG, overlay))
    assert learned.route(PET).specialists[0] == "medicine" and learned.route(JOB).specialists[0] == "business"
    assert not any(w in overlay.get("medicine", {}) for w in ("semana", "desde", "tiene"))  # no filler words
    assert CATALOG.specialists["medicine"].keywords == load_catalog().specialists["medicine"].keywords  # a copy


def test_router_does_not_learn_what_the_router_set_contradicts():
    dev = load_labeled("dev")
    row = next(r for r in dev if r["labels"] == ["finance"])
    corrections = [{"query": row["query"], "specialist": "law"}]
    overlay = learn_overlay(CATALOG, corrections, dev)
    report = gate(CATALOG, overlay, corrections)
    assert not report["accepted"] and overlay == {}


# ---------------------------------------------------------------- candidates
def test_suggested_checks_and_judging():
    assert suggested_checks("No, el IVA general es del 21 %, no del 18%.") == {"include": ["21%"], "exclude": ["18%"]}
    assert suggested_checks("No, son 21%.") == {"include": ["21%"], "exclude": []}  # the opener negates the answer
    assert suggested_checks("It is 3 days, never 5") == {"include": ["3"], "exclude": ["5"]}
    assert judge("El IVA general es del 21%.", None, {"include": ["21%"], "exclude": ["18%"]}) == (True, [])
    ok, problems = judge("Es del 18%.", None, {"include": ["21%"], "exclude": ["18%"]})
    assert not ok and problems == ["missing '21%'", "contains '18%'"]
    assert judge("", "boom", {}) == (False, ["error: boom"])
    assert judge("Es del **21\u00a0%**.", None, {"include": ["21%"], "exclude": ["18 %"]}) == (True, [])  # "21 %" is 21%
    assert judge("Es del 18%.", None, {"exclude": ["18 %"]}) == (False, ["contains '18 %'"])


def test_contamination_flags_known_questions_only():
    refs = references([])
    known = load_labeled("test")[0]["query"]
    assert contamination(known, refs)["with"] == "router set"
    assert contamination("¿Qué tipo de IVA se aplica a las bicicletas eléctricas en Portugal?", refs) is None


# ---------------------------------------------------------------- the app
def test_a_route_correction_teaches_the_router_and_can_be_rolled_back(env):
    client, state, local, _ = env
    events = chat(client, local, {"message": PET}, "Dale agua.")
    route = next(e for e in events if e["type"] == "route")
    assert [s["id"] for s in route["specialists"]] == ["core"]
    uid = conv_of(events)["user_message_id"]
    assert client.post(f"/api/messages/{uid}/route", json={"specialist": "core"}).json() == {"recorded": False}
    out = client.post(f"/api/messages/{uid}/route", json={"specialist": "medicine"}).json()
    assert out["recorded"] and out["router"]["accepted"], out
    assert LexicalRouter(state.catalog).route(PET).specialists[0] == "medicine"
    overview = client.get("/api/evolution").json()
    assert overview["router"]["active"]["data"]["overlay"]["medicine"]
    assert overview["router"]["current"]["test"] == overview["router"]["built_in"]["test"]
    events = chat(client, local, {"message": PET}, "Llévalo al veterinario.")
    assert [s["id"] for s in next(e for e in events if e["type"] == "route")["specialists"]] == ["medicine"]

    assert client.post("/api/evolution/rollback", json={"component": "router"}).json()["active"] is None
    assert LexicalRouter(state.catalog).route(PET).specialists[0] == "core"
    assert client.post("/api/evolution/rollback", json={"component": "router"}).status_code == 404
    assert client.post(f"/api/messages/{uid}/route", json={"specialist": "astrology"}).status_code == 400

    restarted = AppState(home=state.home)  # the learned router is kept across restarts until rolled back
    assert LexicalRouter(restarted.catalog).route(PET).specialists[0] == "core"


def test_a_saved_correction_becomes_an_eval_candidate(env):
    client, state, local, _ = env
    first = chat(client, local, {"message": "¿Cuál es el tipo general de IVA en España?"}, "Es del 18%.")
    cid = conv_of(first)["id"]
    events = chat(client, local, {"message": "No, el tipo general es del 21%, no del 18%.", "conversation_id": cid},
                  "Tienes razón: es del 21%.")
    uid = conv_of(events)["user_message_id"]
    assert any(e["type"] == "correction" for e in events)
    client.post(f"/api/messages/{uid}/learn", json={"action": "save", "text": "El IVA general en España es del 21%."})
    [correction] = client.get("/api/evolution/items?kind=correction").json()
    assert correction["question"] == "¿Cuál es el tipo general de IVA en España?"
    assert correction["wrong_answer"] == "Es del 18%." and correction["rule"].endswith("21%.")
    [candidate] = client.get("/api/evolution/items?kind=candidate").json()
    assert candidate["status"] == "proposed" and candidate["checks"] == {"include": ["21%"], "exclude": ["18%"]}
    assert candidate["contamination"] is None

    accepted = client.patch(f"/api/evolution/items/{candidate['id']}",
                            json={"status": "accepted", "checks": {"include": ["21%"], "exclude": ["18%"]}}).json()
    assert accepted["status"] == "accepted"
    exported = [json.loads(line) for line in client.get("/api/evolution/candidates.jsonl").text.splitlines()]
    assert exported == [{"id": candidate["id"], "prompt": candidate["question"], "specialist": "core",
                         "checks": {"include": ["21%"], "exclude": ["18%"]},
                         "reference": "No, el tipo general es del 21%, no del 18%.", "from": "correction",
                         "source": "spike-evolution"}]
    memory_id = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["meta"]["learn"]["correction"]["memory"]
    client.post(f"/api/messages/{uid}/learn", json={"action": "undo", "memory": memory_id})
    assert client.get("/api/evolution/items?kind=correction").json() == []
    assert client.get("/api/evolution/items?kind=candidate").json()[0]["status"] == "accepted"  # the user decided

    dup = state.evolution.store.add("candidate", {"question": load_labeled("dev")[0]["query"], "checks": {}},
                                    status="proposed")
    refused = client.patch(f"/api/evolution/items/{dup['id']}", json={"status": "accepted"})
    assert refused.status_code == 400 and "router set" in refused.json()["detail"]


def test_failures_are_recorded_with_cause_and_fix_but_not_in_temporary_chats(env):
    client, state, local, _ = env
    boom = [StreamEvent(kind="error", text="llama-server stopped")]
    chat(client, local, {"message": "Resume este contrato confidencial", "mode": "core"}, boom)
    [failure] = client.get("/api/evolution/items?kind=failure").json()
    assert failure["what"] == "run" and "llama-server stopped" in failure["error"] and failure["status"] == "open"
    issue = client.get(f"/api/evolution/items/{failure['id']}/issue").text
    assert "llama-server stopped" in issue and "contrato confidencial" not in issue

    fixed = client.patch(f"/api/evolution/items/{failure['id']}",
                         json={"cause": "the engine ran out of memory", "fix": "context 8192", "verified": True}).json()
    assert fixed["status"] == "fixed"
    assert "**Fix (verified)**" in client.get(f"/api/evolution/items/{failure['id']}/issue").text
    [candidate] = client.get("/api/evolution/items?kind=candidate").json()
    assert candidate["from"] == "failure" and candidate["question"] == "Resume este contrato confidencial"

    chat(client, local, {"message": "Otra cosa", "temporary": True, "mode": "core"}, boom)
    client.put("/api/settings", json={"evolution": {"enabled": False, "auto_router": True}})
    chat(client, local, {"message": "Y otra", "mode": "core"}, boom)
    assert len(client.get("/api/evolution/items?kind=failure").json()) == 1


def test_tool_crashes_are_failures_and_denials_are_not(tmp_path):
    evo = Evolution(EvolutionStore(tmp_path / "e.db"))
    meta = {"route": {"specialists": [{"id": "data"}]}, "tools": [
        {"type": "tool_result", "name": "python", "ok": False, "content": "error: ZeroDivisionError: division by zero"},
        {"type": "tool_result", "name": "write_file", "ok": False, "content": "error: the user denied this tool call"},
        {"type": "tool_result", "name": "calculator", "ok": True, "content": "4"}]}
    [found] = evo.record_failures("divide", meta, "c1", "m1")
    assert found["what"] == "tool" and found["tool"] == "python" and found["specialists"] == ["data"]


# ---------------------------------------------------------------- the regression check
def test_check_runs_the_gate_and_replays_accepted_candidates(env):
    client, state, local, _ = env
    report = client.post("/api/evolution/check", json={}).json()
    assert report["ok"] and [c["name"] for c in report["checks"]] == ["router", "catalog", "skills", "adapters"]
    state.evolution.store.add("candidate", {"question": "¿IVA general?", "checks": {"include": ["21%"]}},
                              status="accepted")

    async def answer(candidate):
        return "Es del 18%.", None

    replayed = asyncio.run(run_checks(state, replay=True, answer=answer))
    assert not replayed["ok"] and replayed["checks"][-1]["results"][0]["problems"] == ["missing '21%'"]
    local._script = [text("El IVA general es del 21%.")]
    report = client.post("/api/evolution/check", json={"replay": True}).json()  # through SPIKE itself
    assert report["ok"] and report["checks"][-1]["detail"] == "1/1 candidates pass their checks"


# ---------------------------------------------------------------- versioned adapters
def _gguf(path: Path, **meta: str) -> Path:
    data = b"GGUF" + struct.pack("<IQQ", 3, 0, len(meta))
    for key, value in meta.items():
        k, v = key.encode(), value.encode()
        data += struct.pack("<Q", len(k)) + k + struct.pack("<I", 8) + struct.pack("<Q", len(v)) + v
    path.write_bytes(data)
    return path


def _eval_run(folder: Path, tuned) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(json.dumps(_summary(*tuned)))
    return folder


GOOD = ([True] * 62 + [False] * 38, [True] * 59 + [False] * 41)
BAD = ([True] * 51 + [False] * 49, [True] * 60 + [False] * 40)


def test_adapters_install_only_when_accepted_and_roll_back(env, tmp_path):
    client, state, _, home = env
    spec, store, folder = state.catalog.get("medicine"), state.evolution.store, state.adapters_path()
    config = ROOT / "training" / "configs" / "medicine.yaml"
    lora = {"general.type": "adapter", "adapter.type": "lora"}
    first = _gguf(tmp_path / "a1.gguf", **lora, **{"general.name": "one"})
    second = _gguf(tmp_path / "a2.gguf", **lora, **{"general.name": "two"})
    dest = folder / "spike-medicine.gguf"

    with pytest.raises(ValueError, match="refused"):
        adapters.install(store, folder, spec, first, _eval_run(tmp_path / "bad", BAD), config)
    with pytest.raises(ValueError, match="not a LoRA"):
        adapters.install(store, folder, spec, _gguf(tmp_path / "m.gguf", **{"general.type": "model"}),
                         _eval_run(tmp_path / "good", GOOD), config)
    with pytest.raises(ValueError, match="recipe of 'finance'"):
        adapters.install(store, folder, spec, first, tmp_path / "good", ROOT / "training" / "configs" / "finance.yaml")
    assert not dest.exists() and store.versions() == []

    _gguf(dest, **lora, **{"general.name": "by hand"})  # installed before versioning
    v = adapters.install(store, folder, spec, first, tmp_path / "good", config)["version"]
    assert v["report"]["accepted"] and dest.read_bytes() == first.read_bytes()
    assert [x["reason"] for x in store.versions()][-1] == "installed before versioning"
    adapters.install(store, folder, spec, second, tmp_path / "good" / "summary.json", config)
    assert dest.read_bytes() == second.read_bytes()
    assert adapters.install(store, folder, spec, second, tmp_path / "good", config).get("unchanged")
    assert client.post("/api/evolution/check", json={}).json()["checks"][3]["ok"]

    dest.write_bytes(b"GGUF tampered")
    check = client.post("/api/evolution/check", json={}).json()["checks"][3]
    assert not check["ok"] and "checksum differs" in check["detail"]

    assert client.post("/api/evolution/rollback", json={"component": "adapter:medicine"}).json()["active"]["id"] == v["id"]
    assert dest.read_bytes() == first.read_bytes()
    state.rollback("adapter:medicine")
    assert b"by hand" in dest.read_bytes()
    assert state.rollback("adapter:medicine") is None and not dest.exists()  # prompt profile again
    assert not any((folder).glob("*.gguf.tmp")) and len(list((folder / "history").glob("*.gguf"))) == 3


def test_an_adapter_exported_in_place_is_versioned_with_its_verdict(env, tmp_path):
    _, state, _, _ = env
    spec, store, folder = state.catalog.get("medicine"), state.evolution.store, state.adapters_path()
    dest = _gguf(folder / "spike-medicine.gguf", **{"general.type": "adapter", "adapter.type": "lora"})
    v = adapters.install(store, folder, spec, dest, _eval_run(tmp_path / "run", GOOD),
                         ROOT / "training" / "configs" / "medicine.yaml")["version"]
    assert [x["id"] for x in store.versions()] == [v["id"]] and v["report"]["accepted"] and dest.is_file()
    assert state.rollback("adapter:medicine") is None and not dest.exists()


def test_cli_check_history_and_rollback(env, capsys):
    _, state, _, _ = env
    assert main(["evolve", "check"]) == 0
    assert "ok   router" in capsys.readouterr().out
    assert main(["models", "history"]) == 0 and "built-in" in capsys.readouterr().out
    state.evolution.store.add("route", {"query": PET, "specialist": "medicine", "routed": ["core"]})
    assert main(["evolve", "router"]) == 0 and "Accepted" in capsys.readouterr().out
    assert main(["models", "history", "router"]) == 0 and "* router" in capsys.readouterr().out
    assert main(["evolve", "rollback", "router"]) == 0 and "built-in" in capsys.readouterr().out
    assert main(["evolve", "rollback", "router"]) == 1
