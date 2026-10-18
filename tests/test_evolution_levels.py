"""Evolution levels 2 and 3 (D2): learned instructions and skills found by search against the user's own eval and
kept only if they pass it, and corrections turned into training examples only with consent, only from SPIKE's own
local model and only once approved; a retrained adapter stays only if it passes the same eval."""

import asyncio
import json

import pytest

from spike.evolution import adapters, dataset, prompts
from spike.evolution.prompts import Variant
from spike.evolution.store import EvolutionStore
from tests.helpers import text
from tests.test_evolution import GOOD, ROOT, _eval_run, _gguf, chat, conv_of
from tests.test_evolution import env as evolution_env

env = pytest.fixture(evolution_env.__wrapped__) if hasattr(evolution_env, "__wrapped__") else evolution_env

RULE = "Para el IVA de España usa siempre el tipo general del 21 %."
QUESTIONS = [("¿Qué IVA lleva una factura de diseño en Madrid?", {"include": ["21 %"], "exclude": []}),
             ("¿Qué IVA cobro por una consultoría en Valencia?", {"include": ["21 %"], "exclude": []}),
             ("¿Cuánto IVA tiene un portátil comprado en Sevilla?", {"include": ["21 %"], "exclude": ["18 %"]}),
             ("Dame el IVA de un servicio de traducción en Bilbao", {"include": ["21 %"], "exclude": ["English"]})]


def accept(store: EvolutionStore, specialist="finance", questions=QUESTIONS):
    return [store.add("candidate", {"question": q, "specialist": specialist, "checks": checks, "from": "correction"},
                      status="accepted") for q, checks in questions]


def fake_answer(rules: dict[str, set[int]], base: set[int], flaky: bool = False):
    """Passes question i if i is in `base`, or in the set of an instruction the variant has; an instruction mapped to
    a negative index makes that question fail. `flaky`: every second scoring of a variant answers like the base."""
    calls: dict[Variant, int] = {}

    async def answer(q, variant):
        i = next(n for n, (question, _) in enumerate(QUESTIONS) if question == q["question"])
        calls[variant] = calls.get(variant, 0) + 1
        second = (calls[variant] - 1) // len(QUESTIONS) % 2 == 1  # this variant's 2nd, 4th... scoring
        lines = set() if flaky and second else set(variant.instructions)
        passed = (i in base or any(i in rules.get(line, set()) for line in lines)) and not any(
            -i - 1 in rules.get(line, set()) for line in lines)
        if variant.skill_modes().get("financial-ratio-analysis") == "off":
            passed = False
        return ("El tipo es del 21 %." if passed else "Depende del caso."), None

    return answer


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- level 2: the search
def test_moves_try_each_one_step_change():
    current = Variant.of(["a"], {"s1": "off"})
    labels = [label for label, _ in prompts.moves(current, ["a", "b"], ["s1", "s2"])]
    assert labels == ["add: b", "remove: a", "skill s1: always", "skill s1: auto", "skill s2: always", "skill s2: off"]
    assert dict(prompts.moves(current, ["b"], [])) == {"add: b": Variant.of(["a", "b"], {"s1": "off"}),
                                                       "remove: a": Variant.of([], {"s1": "off"})}
    assert Variant.from_dict(current.to_dict()) == current and Variant.of([], {"x": "maybe"}).skills == ()


def test_the_search_keeps_only_a_change_that_passes_more_and_loses_nothing(tmp_path):
    store = EvolutionStore(tmp_path / "evo.db")
    accept(store)
    english = "Responde siempre en English."
    answer = fake_answer({RULE: {0, 1, 2}, english: {0, 1, 2, -4}}, base={3})
    report = run(prompts.optimize(store, "finance", prompts.eval_set(store, "finance"), answer,
                                  [english, RULE], ["financial-ratio-analysis"]))
    assert report["accepted"] and report["baseline"]["passed"] == 1 and report["confirmed"]["passed"] == 4
    assert report["changes"] == [f"add: {RULE}"]  # the English line passed 3 too but lost question 4
    fourth = next(c["id"] for c in store.items("candidate") if c["question"] == QUESTIONS[3][0])
    assert {t["change"]: t["lost"] for t in report["tried"]}[f"add: {english}"] == [fourth]
    assert prompts.active(store, "finance") == Variant.of([RULE])
    version = store.active(prompts.component("finance"))
    assert version["reason"].startswith("1→4/4 eval questions") and version["report"]["measured_without_memory"]

    again = run(prompts.optimize(store, "finance", prompts.eval_set(store, "finance"), answer, [english, RULE],
                                 ["financial-ratio-analysis"]))
    assert not again["accepted"] and again["version"] is None and "no change passed more" in again["reasons"][0]
    assert store.rollback(prompts.component("finance")) is None and prompts.active(store, "finance") == Variant()


def test_a_gain_that_does_not_hold_or_fails_the_gate_is_stored_but_not_used(tmp_path):
    store = EvolutionStore(tmp_path / "evo.db")
    accept(store)
    flaky = run(prompts.optimize(store, "finance", prompts.eval_set(store, "finance"),
                                 fake_answer({RULE: {0, 1, 2}}, {3}, flaky=True), [RULE], []))
    assert not flaky["accepted"] and "did not hold on a second run" in flaky["reasons"][0]
    gated = run(prompts.optimize(store, "finance", prompts.eval_set(store, "finance"),
                                 fake_answer({RULE: {0, 1, 2}}, {3}), [RULE], [], gate=lambda: (False, "router 0.70")))
    assert not gated["accepted"] and gated["reasons"] == ["regression checks failed: router 0.70"]
    versions = store.versions(prompts.component("finance"))
    assert len(versions) == 2 and not any(v["active"] for v in versions)
    assert prompts.active(store, "finance") == Variant()


def test_too_few_questions_or_budget_stop_the_search(tmp_path):
    store = EvolutionStore(tmp_path / "evo.db")
    accept(store, questions=QUESTIONS[:2])
    accept(store, specialist="medicine", questions=QUESTIONS[2:])  # other specialists' questions don't count
    store.add("candidate", {"question": "sin checks", "specialist": "finance", "checks": {}}, status="accepted")
    few = run(prompts.optimize(store, "finance", prompts.eval_set(store, "finance"), fake_answer({}, set()), [RULE], []))
    assert few["version"] is None and "only 2 accepted eval questions" in few["reasons"][0]
    store2 = EvolutionStore(tmp_path / "evo2.db")
    accept(store2)
    capped = run(prompts.optimize(store2, "finance", prompts.eval_set(store2, "finance"),
                                  fake_answer({RULE: {0, 1, 2}}, {3}), ["x", "y", RULE], [], max_calls=8))
    assert capped["calls"] == 8 and capped["notes"] == ["stopped at the budget of 8 answers"]
    assert not capped["accepted"] and capped["version"] is None  # the rule was never reached within the budget


def test_ideas_come_from_the_user_and_the_specialists_saved_rules(tmp_path):
    store = EvolutionStore(tmp_path / "evo.db")
    store.add("correction", {"rule": RULE, "specialists": ["finance"]}, status="saved")
    store.add("correction", {"rule": "Otra regla de medicina", "specialists": ["medicine"]}, status="saved")
    store.add("correction", {"rule": "  para el IVA de España usa siempre el tipo general del 21 %. ",
                             "specialists": ["finance"]}, status="saved")
    assert prompts.ideas_for(store, "finance", ["Cita la ley", "", "x" * 400]) == ["Cita la ley", "x" * 300, RULE]


# ---------------------------------------------------------------- level 2: in the app
def test_the_app_optimises_a_specialist_and_its_chats_use_what_was_learned(env):
    client, state, local, _ = env
    accept(state.evolution.store)
    state.evolution.store.add("correction", {"rule": RULE, "specialists": ["finance"]}, status="saved")

    def script(request):
        system = request.messages[0].content
        assert request.temperature == 0.0 and "# Relevant memory" not in system
        return text("El tipo es del 21 %." if RULE in system else "Depende del caso.")

    local._script = script
    assert client.post("/api/evolution/prompts/nope/optimize", json={}).status_code == 404
    events = [json.loads(line[6:]) for line in client.post("/api/evolution/prompts/finance/optimize", json={
        "instructions": ["Responde con una tabla"]}).text.splitlines() if line.startswith("data: ")]
    assert [e["label"] for e in events if e["type"] == "try"][:2] == ["in use", "add: Responde con una tabla"]
    report = events[-1]["report"]
    assert events[-1]["type"] == "done" and report["accepted"] and report["changes"] == [f"add: {RULE}"]
    assert not state.optimizing
    status = {s["specialist"]: s for s in client.get("/api/evolution/prompts").json()}
    assert status["finance"]["questions"] == 4 and status["finance"]["active"]["data"]["instructions"] == [RULE]
    assert status["finance"]["skills"] == ["financial-ratio-analysis"] and status["medicine"]["active"] is None

    local._script = [text("Hecho.")]
    chat(client, local, {"message": "¿Qué IVA aplico?", "mode": "finance"}, [text("Hecho.")])
    system = local.requests[-1].messages[0].content
    assert f"# Learned instructions (kept because they passed the user's eval)\n- {RULE}" in system

    state.optimizing = True
    assert client.post("/api/evolution/prompts/finance/optimize", json={}).status_code == 409
    state.optimizing = False
    assert client.post("/api/evolution/rollback", json={"component": "prompt:finance"}).json()["active"] is None
    chat(client, local, {"message": "¿Qué IVA aplico?", "mode": "finance"}, [text("Hecho.")])
    assert "# Learned instructions" not in local.requests[-1].messages[0].content


def test_learned_skill_modes_turn_a_skill_on_or_off_for_a_specialist(env):
    client, state, local, _ = env
    store = state.evolution.store
    ratios = "Calcula el margen EBITDA y el ROE de este balance"
    chat(client, local, {"message": ratios, "mode": "finance"}, [text("ok")])
    assert "# Skill: financial-ratio-analysis" in local.requests[-1].messages[0].content
    store.add_version(prompts.component("finance"), Variant.of([], {"financial-ratio-analysis": "off"}).to_dict())
    chat(client, local, {"message": ratios, "mode": "finance"}, [text("ok")])
    assert "# Skill:" not in local.requests[-1].messages[0].content
    store.add_version(prompts.component("finance"), Variant.of([], {"financial-ratio-analysis": "always"}).to_dict())
    chat(client, local, {"message": "Hola, ¿qué tal?", "mode": "finance"}, [text("ok")])
    assert "# Skill: financial-ratio-analysis" in local.requests[-1].messages[0].content
    chat(client, local, {"message": "Hola, ¿qué tal?", "mode": "marketing"}, [text("ok")])
    assert "financial-ratio-analysis" not in local.requests[-1].messages[0].content  # only for finance


def same_app(monkeypatch, local, home):
    """The CLI builds its own AppState: give it the scripted model too."""
    from spike.server.state import AppState

    def factory(cfg):
        local.config = cfg
        return local

    monkeypatch.setattr("spike.server.state.AppState", lambda: AppState(home=home, provider_factory=factory))


def test_cli_optimize(env, capsys, monkeypatch):
    from spike.cli import main

    client, state, local, home = env
    accept(state.evolution.store)
    same_app(monkeypatch, local, home)
    local._script = lambda request: text("El tipo es del 21 %." if "21 %" in request.messages[0].content else "No sé.")
    assert main(["evolve", "optimize", "finance", "--try", RULE]) == 0
    out = capsys.readouterr().out
    assert "In use: 0/4" in out and "Best: 4/4 on its second run" in out and "Accepted: now in use." in out
    assert main(["evolve", "optimize", "finance"]) == 1 and "Nothing changed" in capsys.readouterr().out


# ---------------------------------------------------------------- level 3: corrections as training data
def corrected_chat(client, local, question="¿Cuál es el tipo general de IVA en España?", wrong="Es del 18%.",
                   correction="No, el tipo general es del 21%, no del 18%.", right="Tienes razón: es del 21%."):
    first = chat(client, local, {"message": question}, wrong)
    cid = conv_of(first)["id"]
    events = chat(client, local, {"message": correction, "conversation_id": cid}, right)
    uid = conv_of(events)["user_message_id"]
    client.post(f"/api/messages/{uid}/learn", json={"action": "save", "text": "El IVA general en España es del 21%."})
    return cid


def test_corrections_become_training_examples_only_with_consent_and_approval(env):
    client, state, local, _ = env
    good = corrected_chat(client, local)
    external = corrected_chat(client, local, question="¿Y el IVA reducido en España?", wrong="Es del 4%.",
                              correction="No, el reducido es del 10%.", right="Cierto, el reducido es del 10%.")
    answer = state.store.messages(external)[-1]
    meta = answer["meta"]
    meta["route"]["specialists"][0]["provider_id"] = "anthropic"
    state.store.update_message_meta(answer["id"], meta)
    failing = corrected_chat(client, local, question="¿Y el superreducido?", wrong="Es del 2%.",
                             correction="No, es del 4%, no del 2%.", right="Vale, es del 2% o del 4%.")

    assert client.post("/api/evolution/examples/build").status_code == 409
    assert client.get("/api/evolution/training.jsonl").status_code == 409
    settings = client.get("/api/settings").json()
    client.put("/api/settings", json={"evolution": {**settings["evolution"], "training_data": True}})
    assert client.post("/api/evolution/examples/build").json() == {"proposed": 1, "skipped": 2, "unchanged": 0}
    examples = {e["conversation"]: e for e in client.get("/api/evolution/items?kind=example").json()}
    assert examples[good]["status"] == "proposed" and examples[good]["chosen"] == "Tienes razón: es del 21%."
    assert "anthropic" in examples[external]["reason"] and "only answers from SPIKE's own local model" in \
        examples[external]["reason"]
    assert "fails its checks" in examples[failing]["reason"] or "already passes" in examples[failing]["reason"]
    assert client.patch(f"/api/evolution/items/{examples[external]['id']}", json={"status": "approved"}).status_code == 400

    assert client.get("/api/evolution/training.jsonl").text == ""  # nothing approved yet
    client.patch(f"/api/evolution/items/{examples[good]['id']}", json={"status": "approved"})
    [line] = client.get("/api/evolution/training.jsonl").text.splitlines()
    exported = json.loads(line)
    assert [m["role"] for m in exported["messages"]] == ["system", "user", "assistant"]
    assert exported["messages"][0]["content"] == state.base_catalog().get("core").system_prompt
    assert exported["messages"][2]["content"] == "Tienes razón: es del 21%."
    assert exported["meta"] == {"id": examples[good]["id"], "specialist": "core", "source": "spike-correction",
                                "checks": {"include": ["21%"], "exclude": ["18%"]}}
    [pair] = [json.loads(x) for x in client.get("/api/evolution/preferences.jsonl").text.splitlines()]
    assert pair["chosen"][0]["content"] == "Tienes razón: es del 21%." and pair["rejected"][0]["content"] == "Es del 18%."
    assert pair["prompt"][-1] == {"role": "user", "content": "¿Cuál es el tipo general de IVA en España?"}

    meta["route"]["specialists"][0]["provider_id"] = "spike-local"  # a skipped example is looked at again
    state.store.update_message_meta(answer["id"], meta)
    assert state.build_examples() == {"proposed": 1, "skipped": 1, "unchanged": 1}


def test_cli_dataset_writes_the_approved_examples(env, tmp_path, capsys, monkeypatch):
    from spike.cli import main

    client, state, local, home = env
    corrected_chat(client, local)
    same_app(monkeypatch, local, home)
    assert main(["evolve", "dataset", str(tmp_path / "out")]) == 1  # not opted in
    state.store.set_setting("evolution", {"enabled": True, "auto_router": True, "training_data": True})
    assert main(["evolve", "dataset", str(tmp_path / "out")]) == 0
    assert "1 new examples to review" in capsys.readouterr().out
    [example] = state.evolution.store.items("example")
    state.evolution.store.update(example["id"], status="approved")
    assert main(["evolve", "dataset", str(tmp_path / "out")]) == 0
    assert len((tmp_path / "out" / "spike-training.jsonl").read_text().splitlines()) == 1
    assert dataset.LOCAL_ENGINE == "spike-local"


# ---------------------------------------------------------------- level 3: a retrained adapter meets the user's eval
@pytest.mark.parametrize("after, kept", [({0, 1, 2, 3}, True), ({1, 2, 3}, False)])
def test_a_retrained_adapter_stays_only_if_it_passes_the_users_eval(env, tmp_path, after, kept):
    _, state, _, _ = env
    spec, store, folder = state.catalog.get("medicine"), state.evolution.store, state.adapters_path()
    questions = accept(store, specialist="medicine")
    lora = {"general.type": "adapter", "adapter.type": "lora"}
    old = _gguf(tmp_path / "old.gguf", **lora, **{"general.name": "old"})
    new = _gguf(tmp_path / "new.gguf", **lora, **{"general.name": "new"})
    config, run_dir = ROOT / "training" / "configs" / "medicine.yaml", _eval_run(tmp_path / "good", GOOD)
    adapters.install(store, folder, spec, old, run_dir, config)
    loaded = {"name": "old"}
    reloads = []

    async def reload():
        reloads.append(1)
        loaded["name"] = "new" if b"new" in (folder / "spike-medicine.gguf").read_bytes() else "old"

    async def answer(q):
        i = next(n for n, c in enumerate(questions) if c["id"] == q["id"])
        passed = i in ({0, 1, 2} if loaded["name"] == "old" else after)
        return ("El tipo es del 21 %." if passed else "No sé."), None

    result = run(adapters.install_checked(store, folder, spec, new, run_dir, prompts.eval_set(store, "medicine"),
                                          answer, reload, config))
    assert result["local_eval"]["before"] == 3 and result["rolled_back"] is (not kept)
    assert (b"new" in (folder / "spike-medicine.gguf").read_bytes()) is kept
    assert len(reloads) == (1 if kept else 2)  # load the new one, and the old one again if it goes back
    if not kept:
        assert result["local_eval"]["lost"] == [questions[0]["id"]]
