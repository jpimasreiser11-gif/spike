"""Tool strategy learning (EV3): which tool or skill worked for which task type, kept as counts on this computer, and
used only to break ties between skills that score the same, behind `spike evolve check`."""

import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from spike.evolution import strategy
from spike.evolution.checks import run_checks, strategy_check
from spike.evolution.store import EvolutionStore
from spike.server.app import create_app
from spike.server.state import AppState
from spike.skills.engine import BUNDLED, SkillLibrary
from tests.helpers import ScriptedProvider, call, text
from tests.test_skills import write_skill

TIE = "arregla el bug y escribe tests"  # scores systematic-debugging and test-driven-development the same


def tied_library(tmp_path) -> SkillLibrary:
    """Two skills that score the same on "informe": the router puts `alfa` first by name."""
    write_skill(tmp_path, "alfa", "Use for reports.", extra="metadata:\n  spike-keywords: informe\n")
    write_skill(tmp_path, "beta", "Use for reports.", extra="metadata:\n  spike-keywords: informe\n")
    return SkillLibrary([(tmp_path, "user")])


def uses(store: EvolutionStore, kind, name, task, good, bad, message="m"):
    store.add_runs([{"message": message, "call": "", "kind": kind, "name": name, "task_type": task, "ok": i < good}
                    for i in range(good + bad)])


# ---------------------------------------------------------------- task types
@pytest.mark.parametrize("request_text, intent", [
    ("Traduce este texto al inglés", "translate"),
    ("Resume este artículo, por favor", "summarize"),
    ("Tengo un bug en mi función de Python", "code"),
    ("Haz un gráfico de ventas con el CSV", "data"),
    ("Calcula el IVA de 120 euros al 21 %", "calculate"),
    ("What is 12 * 7?", "calculate"),
    ("Crea una presentación en PowerPoint sobre mi empresa", "document"),
    ("Busca las últimas noticias sobre el euro", "lookup"),
    ("Prepara un plan de lanzamiento", "plan"),
    ("Escribe un correo a mi casero", "write"),
    ("¿Qué es la inflación?", "explain"),
    ("Hola", "other"),
])
def test_the_intent_comes_from_fixed_patterns_not_a_model(request_text, intent):
    assert strategy.intent_of(request_text) == intent
    assert strategy.task_type("finance", request_text) == f"finance:{intent}"
    assert strategy.task_type("", request_text).startswith("core:")


# ---------------------------------------------------------------- what is recorded
def meta_of(**kw):
    base = {"route": {"specialists": [{"id": "data"}]}, "error": None, "cancelled": False, "tools": [], "events": []}
    return {**base, **kw}


def test_every_tool_and_skill_use_is_recorded_for_its_task_type_except_what_the_user_refused():
    meta = meta_of(tools=[
        {"type": "tool_call", "id": "c1", "name": "python", "arguments": {}, "specialist": "data"},
        {"type": "tool_result", "id": "c1", "name": "python", "ok": True, "content": "42", "specialist": "data"},
        {"type": "tool_call", "id": "c2", "name": "data_sql", "arguments": {}, "specialist": "data"},
        {"type": "tool_result", "id": "c2", "name": "data_sql", "ok": False, "content": "error: OperationalError: x",
         "specialist": "data"},
        {"type": "tool_result", "id": "c3", "name": "write_file", "ok": False,
         "content": "error: the user denied this tool call", "specialist": "data"},
        {"type": "tool_result", "id": "c4", "name": "python", "ok": False, "content": "error: refused: no network",
         "specialist": "data"},
        {"type": "tool_result", "id": "c5", "name": "web_fetch", "ok": False,
         "content": "error: 'web_fetch' needs the user's approval, which can only be given in the SPIKE app",
         "specialist": "data"},
        {"type": "tool_result", "id": "c6", "name": "x", "ok": False,
         "content": "error: tool 'x' is not available to this specialist", "specialist": "data"},
        {"type": "tool_call", "id": "c7", "name": "load_skill", "arguments": {"name": "systematic-debugging"}},
        {"type": "tool_result", "id": "c7", "name": "load_skill", "ok": True, "content": "# skill", "specialist": "data"}],
        events=[{"type": "skill", "names": ["campaign-brief"], "mode": "router", "specialist": "data"}])
    rows = strategy.observations(meta, "Haz un gráfico del CSV", "a1")
    assert {(r["kind"], r["name"], r["task_type"], r["ok"]) for r in rows} == {
        ("tool", "python", "data:data", True), ("tool", "data_sql", "data:data", False),
        ("skill", "systematic-debugging", "data:data", True), ("skill", "campaign-brief", "data:data", True)}
    assert all(r["message"] == "a1" for r in rows) and {r["call"] for r in rows} == {"c1", "c2", "c7", ""}


def test_a_skill_is_a_success_only_if_its_run_ended_without_an_error():
    events = [{"type": "skill", "names": ["alfa"], "specialist": "core"}]
    assert strategy.observations(meta_of(events=events, error="boom"), "informe", "a")[0]["ok"] is False
    assert strategy.observations(meta_of(events=events, cancelled=True), "informe", "a")[0]["ok"] is False
    assert strategy.observations(meta_of(events=events), "informe", "a")[0]["ok"] is True
    # an answer stored without its events still names its skills
    assert strategy.observations(meta_of(skills=["alfa"]), "informe", "a")[0]["task_type"] == "data:document"
    assert strategy.observations(meta_of(skills=["alfa"]), "Hola", "a")[0]["task_type"] == "data:other"


def test_a_use_counts_only_if_it_worked_and_was_not_retried_undone_or_corrected(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    store.add_runs([{"message": f"a{i}", "call": f"c{i}", "kind": "tool", "name": "python", "task_type": "data:data",
                     "ok": ok} for i, ok in enumerate([True, True, True, True, False])])
    assert store.flag_runs(["a1"], "retried") == 1
    assert store.flag_runs(["a2"], "undone", call="c2") == 1
    assert store.flag_runs(["a3"], "undone", call="other") == 0  # another call of that answer is not the one undone
    assert store.flag_runs(["a3"], "corrected") == 1
    assert store.flag_runs(["a1"], "corrected") == 0  # only the first reason is kept
    assert store.flag_runs([], "retried") == 0
    with pytest.raises(ValueError):
        store.flag_runs(["a0"], "liked")
    [row] = store.run_stats()
    assert (row["n"], row["good"], row["retried"], row["undone"], row["corrected"]) == (5, 1, 1, 1, 1)
    assert store.clear_runs() == 5 and store.run_stats() == [] and store.count_runs() == 0


def test_counts_are_kept_in_the_local_evolution_database_without_any_text(tmp_path):
    path = tmp_path / "evolution.db"
    EvolutionStore(path).add_runs([{"message": "a1", "kind": "skill", "name": "alfa", "task_type": "core:write",
                                    "ok": True, "call": ""}])
    columns = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(tool_runs)")]
    assert columns == ["id", "message", "call", "kind", "name", "task_type", "ok", "flag", "created"]
    [row] = strategy.table(EvolutionStore(path))
    assert {k: v for k, v in row.items() if k != "last"} == {
        "kind": "skill", "name": "alfa", "task_type": "core:write", "n": 1, "good": 1, "retried": 0, "undone": 0,
        "corrected": 0, "rate": 1.0, "enough": False}


# ---------------------------------------------------------------- the tie-break
RANKED = [(4.0, "alfa"), (4.0, "beta"), (2.0, "gamma")]


def test_only_skills_that_tie_and_all_have_enough_samples_can_change_places():
    rates = {"alfa": [1, 8], "beta": [7, 8], "gamma": [8, 8]}
    assert strategy.reorder(RANKED, rates) == ["beta", "alfa", "gamma"]  # gamma scores less: never promoted
    assert strategy.reorder(RANKED, {**rates, "beta": [4, 4]}) == ["alfa", "beta", "gamma"]  # 4 uses < 5: no effect
    assert strategy.reorder(RANKED, {"beta": [7, 8]}) == ["alfa", "beta", "gamma"]  # alfa has no record at all
    assert strategy.reorder(RANKED, {"alfa": [4, 8], "beta": [4, 8]}) == ["alfa", "beta", "gamma"]  # equal rates
    assert strategy.reorder(RANKED, {"alfa": [4, 8], "beta": [4, 7]}) == ["alfa", "beta", "gamma"]  # same 10-point step
    assert strategy.reorder(RANKED, {"alfa": [4, 8], "beta": [5, 8]}) == ["beta", "alfa", "gamma"]  # a step apart
    assert strategy.reorder(RANKED[:1], rates) == ["alfa"]
    assert strategy.reorder([(4.0, "alfa"), (3.0, "beta")], rates) == ["alfa", "beta"]  # not tied: margin 0
    assert strategy.reorder([(4.0, "alfa"), (3.0, "beta")], rates, margin=1.0) == ["beta", "alfa"]  # a wider margin
    assert strategy.reorder(RANKED, {"alfa": [1, 2], "beta": [2, 2]}, min_samples=2) == ["beta", "alfa", "gamma"]


def test_the_skill_router_takes_the_tie_break_but_never_adds_a_skill(tmp_path):
    library = tied_library(tmp_path)
    assert [s.name for s in library.select("Prepara el informe", "core")] == ["alfa"]
    library.prefer = strategy.Preference({"core:write": {"alfa": [1, 9], "beta": [8, 9]}}).order
    assert [s.name for s in library.select("Prepara el informe", "core", k=2)] == ["alfa", "beta"]  # other task type
    library.prefer = strategy.Preference({"core:document": {"alfa": [1, 9], "beta": [8, 9]}}).order
    assert [s.name for s in library.select("Prepara el informe", "core", k=2)] == ["beta", "alfa"]
    assert [s.name for s in library.select("Hola, ¿qué tal?", "core")] == []  # nothing scores: nothing is added
    assert [s.name for s in library.select("Prepara el informe", "core", disabled={"beta"})] == ["alfa"]
    library.prefer = lambda ranked, specialist, request: ["zeta", "beta"]  # a name it does not know is ignored
    assert [s.name for s in library.select("Prepara el informe", "core", k=2)] == ["beta", "alfa"]


def test_the_rule_in_use_is_a_snapshot_that_passed_the_gate_and_rolls_back(tmp_path):
    library = tied_library(tmp_path)
    store = EvolutionStore(tmp_path / "e.db")
    tool = [{"n": 8, "good": 8, "kind": "tool", "name": "python", "task_type": "core:other"}]
    assert strategy.Preference.from_stats(tool) == strategy.Preference({})  # tools are shown, never used
    none = strategy.learn(store, library)
    assert not none["accepted"] and "no skill has 5 recorded uses" in none["reasons"][0] and none["version"] is None

    uses(store, "skill", "alfa", "core:other", 2, 6)
    uses(store, "skill", "beta", "core:other", 7, 1, message="n")
    gates = []
    report = strategy.learn(store, library, gate=lambda p: (gates.append(p) or True, ""))
    assert report["accepted"] and report["skills"] == 2 and report["routing"]["after"] == report["routing"]["before"]
    assert len(gates) == 1 and store.active("strategy")["id"] == report["version"]
    assert strategy.learn(store, library)["unchanged"]  # same counts: nothing new in the history
    assert len(store.versions("strategy")) == 1
    assert strategy.active_preference(store).skills == {"core:other": {"alfa": [2, 8], "beta": [7, 8]}}

    # a rejected snapshot is kept in the history, inactive, with its reason
    uses(store, "skill", "alfa", "core:other", 0, 6, message="o")
    bad = strategy.learn(store, library, gate=lambda p: (False, "router 0.50 < 0.85"))
    assert not bad["accepted"] and bad["reasons"] == ["regression checks fail with it applied: router 0.50 < 0.85"]
    assert store.active("strategy")["id"] == report["version"] and not store.version(bad["version"])["active"]
    assert strategy.reset(store) == 22 and store.active("strategy") is None and len(store.versions("strategy")) == 2


def test_a_snapshot_that_makes_skill_routing_worse_is_refused(tmp_path, monkeypatch):
    library = tied_library(tmp_path)
    store = EvolutionStore(tmp_path / "e.db")
    uses(store, "skill", "alfa", "core:document", 1, 7)
    uses(store, "skill", "beta", "core:document", 8, 0, message="n")
    monkeypatch.setattr(strategy, "load_skill_labeled", lambda: [
        {"specialist": "core", "query": "Prepara el informe", "expected": "alfa"}])
    report = strategy.learn(store, library, gate=lambda p: (True, ""))
    assert not report["accepted"] and report["routing"] == {"before": 1, "after": 0, "n": 1,
                                                            "wrong_after": ["Prepara el informe"]}
    assert report["reasons"][0].startswith("skill routing gets worse with it (1/1 -> 0/1)")
    assert store.active("strategy") is None and library.prefer is None  # the library is left as it was


def test_the_bundled_skill_routing_set_is_answered_in_full_without_any_preference():
    library = SkillLibrary([(BUNDLED, "bundled")])
    assert strategy.skill_routing(library) == {"n": 12, "correct": 12, "wrong": []}


# ---------------------------------------------------------------- in the app
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
    client.put("/api/settings", json={"tool_policies": {"write_file": "allow"}})
    return client, state, local, tmp_path


def chat(client, local, message, script, **body):
    local._script = script
    out = client.post("/api/chat", json={"message": message, "mode": "core", **body})
    return [json.loads(line[6:]) for line in out.text.splitlines() if line.startswith("data: ")]


def counts(client, name="write_file"):
    [row] = [r for r in client.get("/api/evolution/strategy").json()["rows"] if r["name"] == name]
    return row


def test_a_chat_records_its_tools_and_retry_undo_and_correction_stop_them_counting(env):
    client, state, local, _ = env
    first = chat(client, local, "Escribe las notas", [call("write_file", {"path": "a.md", "content": "uno"}, "c1"),
                                                      text("Hecho")])
    cid = next(e for e in first if e["type"] == "conversation")["id"]
    row = counts(client)
    assert (row["task_type"], row["n"], row["good"]) == ("core:write", 1, 1)

    cp = next(e for e in first if e["type"] == "tool_result")["checkpoint"]
    assert client.post(f"/api/checkpoints/{cp}/undo", json={}).json()["ok"]
    assert (counts(client)["n"], counts(client)["good"], counts(client)["undone"]) == (1, 0, 1)

    # asking again for the same answer: the new run counts, the replaced one does not
    second = chat(client, local, "Escribe un correo", [call("write_file", {"path": "b.md", "content": "x"}, "c2"),
                                                       text("Listo")], conversation_id=cid)
    uid = next(e for e in second if e["type"] == "conversation")["user_message_id"]
    assert (counts(client)["n"], counts(client)["good"]) == (2, 1)
    chat(client, local, "Escribe un correo", [call("write_file", {"path": "b.md", "content": "y"}, "c3"), text("Otra")],
         conversation_id=cid, replace_from=uid)
    assert (counts(client)["n"], counts(client)["good"], counts(client)["retried"]) == (3, 1, 1)

    # the next message corrects the answer: it was not a success
    chat(client, local, "No, el tipo general es del 21%, no del 18%.", [text("Tienes razón.")], conversation_id=cid)
    assert (counts(client)["good"], counts(client)["corrected"]) == (0, 1)


def test_nothing_is_recorded_for_temporary_chats_or_when_evolution_is_off(env):
    client, state, local, _ = env
    chat(client, local, "Escribe las notas", [call("write_file", {"path": "a.md", "content": "uno"}), text("Hecho")],
         temporary=True)
    assert client.get("/api/evolution/strategy").json()["rows"] == []
    client.put("/api/settings", json={"evolution": {"enabled": False, "auto_router": True}})
    chat(client, local, "Escribe las notas", [call("write_file", {"path": "a.md", "content": "uno"}), text("Hecho")])
    assert client.get("/api/evolution/strategy").json()["rows"] == []


def test_the_table_can_be_learned_from_used_and_reset_from_the_app(env):
    client, state, local, _ = env
    store = state.evolution.store
    uses(store, "skill", "systematic-debugging", "code:code", 2, 6)
    uses(store, "skill", "test-driven-development", "code:code", 8, 0, message="n")
    uses(store, "tool", "python", "code:code", 1, 0, message="p")
    table = client.get("/api/evolution/strategy").json()
    assert table["uses"] == 17 and table["min_samples"] == 5 and table["margin"] == 0.0
    assert {(r["name"], r["enough"]) for r in table["rows"]} == {
        ("systematic-debugging", True), ("test-driven-development", True), ("python", False)}
    assert [s.name for s in state.skills.select(TIE, "code")] == ["systematic-debugging"]  # the router's own order
    learned = client.post("/api/evolution/strategy/learn").json()
    assert learned["accepted"] and learned["skills"] == 2
    assert [s.name for s in state.skills.select(TIE, "code")] == ["test-driven-development"]  # the one that worked
    assert client.get("/api/evolution/strategy").json()["active"]["id"] == learned["version"]
    client.put("/api/settings", json={"evolution": {"enabled": False, "auto_router": True}})
    assert [s.name for s in state.skills.select(TIE, "code")] == ["systematic-debugging"]  # Evolution off: not used
    client.put("/api/settings", json={"evolution": {"enabled": True, "auto_router": True}})
    assert [s.name for s in state.skills.select(TIE, "code")] == ["test-driven-development"]

    assert client.delete("/api/evolution/strategy").json() == {"deleted": 17}
    assert client.get("/api/evolution/strategy").json()["rows"] == []
    assert [s.name for s in state.skills.select(TIE, "code")] == ["systematic-debugging"]
    versions = client.get("/api/evolution").json()["versions"]
    assert [v["component"] for v in versions] == ["strategy"] and not versions[0]["active"]  # kept, not in use


def test_the_tie_break_refreshes_itself_every_few_uses_unless_turned_off(env):
    client, state, local, _ = env
    uses(state.evolution.store, "skill", "test-driven-development", "code:code", 8, 0)
    uses(state.evolution.store, "skill", "systematic-debugging", "code:code", 1, 7, message="n")
    meta = {"route": {"specialists": [{"id": "code"}]}, "error": None, "cancelled": False, "events": [], "tools": [
        {"type": "tool_call", "id": "c", "name": "python", "arguments": {}, "specialist": "code"},
        {"type": "tool_result", "id": "c", "name": "python", "ok": True, "content": "1", "specialist": "code"}]}
    client.put("/api/settings", json={"evolution": {"enabled": True, "auto_router": True, "auto_strategy": False}})
    for i in range(strategy.AUTO_EVERY):
        state.record_strategy("Escribe un correo", meta, f"x{i}")
    assert state.evolution.store.count_runs() == 36 and state.evolution.store.active("strategy") is None
    client.put("/api/settings", json={"evolution": {"enabled": True, "auto_router": True, "auto_strategy": True}})
    state.record_strategy("Escribe un correo", meta, "y1")
    assert state.evolution.store.active("strategy") is not None  # more than AUTO_EVERY uses since the last snapshot


def test_the_check_runs_the_routing_tests_with_the_tie_break_applied(env, monkeypatch):
    client, state, _, _ = env
    report = asyncio.run(run_checks(state))
    assert report["ok"] and [c["name"] for c in report["checks"]][-1] == "strategy"
    assert "no learned tie-break in use" in report["checks"][-1]["detail"]
    uses(state.evolution.store, "skill", "test-driven-development", "code:code", 8, 0)
    uses(state.evolution.store, "skill", "systematic-debugging", "code:code", 1, 7, message="n")
    assert state.learn_strategy()["accepted"]
    check = strategy_check(state)
    assert check["ok"] and check["detail"] == "skill routing 12/12 -> 12/12 with the learned tie-break"

    # routing on a labelled request that ties would now go the other way: the check fails, and a rollback fixes it
    monkeypatch.setattr(strategy, "load_skill_labeled", lambda: [
        {"specialist": "code", "query": TIE, "expected": "systematic-debugging"}])
    worse = strategy_check(state)
    assert not worse["ok"] and worse["detail"].startswith("skill routing 1/1 -> 0/1 with the learned tie-break")
    assert not asyncio.run(run_checks(state))["ok"]
    assert client.post("/api/evolution/rollback", json={"component": "strategy"}).status_code == 200
    assert strategy_check(state)["ok"] and asyncio.run(run_checks(state))["ok"]
