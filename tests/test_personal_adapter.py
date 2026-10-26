"""EV6: the personal adapter. Off by default, built only from the user's approved corrections and the chats they marked
(minus what they exclude), trained with the specialists' pipeline on Apple silicon and installed only if general knowledge
holds. The pipeline is stubbed here: nothing is trained and no model runs; each stubbed command writes what the real one
would, from numbers the test picks, so the dataset, the commands, the acceptance gate and the clean-up are what is tested."""

import json
import shutil
import sys
import types
from pathlib import Path

import pytest
import yaml

from spike.cli import main
from spike.evolution import adapters, personal
from spike.evolution.store import EvolutionStore
from spike.runtime.hardware import HardwareInfo
from tests.test_evolution import ROOT, _gguf, training_eval
from tests.test_evolution import env as evolution_env

env = pytest.fixture(evolution_env.__wrapped__) if hasattr(evolution_env, "__wrapped__") else evolution_env

LORA = {"general.type": "adapter", "adapter.type": "lora"}
LOCAL = {"route": {"specialists": [{"id": "core", "provider_id": "spike-local"}]}}
EXTERNAL = {"route": {"specialists": [{"id": "core", "provider_id": "anthropic"}]}}
RECIPE = ROOT / "training" / "configs" / "personal.yaml"


def hardware(apple=True, ram=32.0, os_name=None, arch=None) -> HardwareInfo:
    return HardwareInfo(os=os_name or ("Darwin" if apple else "Linux"), arch=arch or ("arm64" if apple else "x86_64"),
                        cpu_model="test", physical_cores=8, logical_cores=8, total_ram_gb=ram, available_ram_gb=ram - 4,
                        apple_silicon=apple)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("SPIKE_UNSUPERVISED", raising=False)
    monkeypatch.delenv("RESUME_FREE_GB", raising=False)


# ---------------------------------------------------------------- chats and corrections to build a set from
def make_chat(state, turns, meta=None, title="Mis cosas", start=1000.0) -> str:
    """A saved chat of (question, answer) turns; a turn's answer can carry its own meta as (question, answer, meta)."""
    chat = state.store.create_conversation(title)
    at = start
    for turn in turns:
        question, answer = turn[0], turn[1]
        state.store.add_message(chat["id"], "user", question, created=at)
        state.store.add_message(chat["id"], "assistant", answer, turn[2] if len(turn) > 2 else meta or LOCAL,
                                created=at + 0.5)
        at += 1
    return chat["id"]


def many(n, prefix="Pregunta"):
    return [(f"{prefix} número {i} sobre mi trabajo", f"Respuesta {i}, escrita como me gusta.") for i in range(n)]


def approve(state, question, chosen, conversation="c1", status="approved"):
    return state.evolution.store.add("example", {"question": question, "chosen": chosen, "rejected": "mal",
                                                 "conversation": conversation, "source": "x", "specialist": "core",
                                                 "system": ""}, status=status)["id"]


def turn_on(client, **extra):
    current = client.get("/api/settings").json()["evolution"]
    client.put("/api/settings", json={"evolution": {**current, "personal_adapter": True, **extra}})


# ---------------------------------------------------------------- what would be used
def test_the_set_holds_only_approved_corrections_and_marked_chats(env):
    _, state, _, _ = env
    evo, store = state.evolution.store, state.store
    approved = [approve(state, "¿Cómo firmo los correos?", "Firma siempre con «Un saludo, Ana»."),
                approve(state, "¿Cómo trato a Luis?", "De usted, siempre.")]
    approve(state, "¿Y esto?", "Aún sin revisar.", status="proposed")
    approve(state, "¿Y aquello?", "Rechazado por mí.", status="rejected")
    unmarked = make_chat(state, [("Algo de otro chat", "Respuesta de otro chat")])
    marked = make_chat(state, [
        ("¿Capital de Francia?", "París."),
        ("Dame un titular", "Titular de un servicio externo", EXTERNAL),
        ("¿IVA general?", "Es del 18%."),
        ("No, el IVA general es del 21%, no del 18%.", "Tienes razón: es del 21%."),
        ("Otra pregunta que falló", "…", {**LOCAL, "error": "boom"}),
        ("Una pregunta sin registro de modelo", "Respuesta sin meta", {}),
    ])
    assert personal.build_set(evo, store, False)["counts"]["used"] == 0  # nothing is marked yet
    personal.mark_chat(evo, store, marked)

    built = personal.build_set(evo, store, training_data=True)
    questions = [(e["source"], e["question"]) for e in built["entries"]]
    assert questions == [("correction", "¿Cómo firmo los correos?"), ("correction", "¿Cómo trato a Luis?"),
                         ("chat", "¿Capital de Francia?"), ("chat", "No, el IVA general es del 21%, no del 18%.")]
    assert built["chats"] == {"marked": 1, "missing": 0, "answers_not_used": {"origin": 3, "corrected": 1}}
    assert built["counts"] == {"approved_corrections": 2, "corrections": 2, "chat_answers": 2, "excluded": 0,
                               "duplicates": 0, "used": 4, "needed": 30, "corrections_need_consent": False}
    assert unmarked not in {e["conversation"] for e in built["entries"]}
    assert [e["id"] for e in built["entries"][:2]] == [approved[0], approved[1]]  # the oldest first, as approved

    # the corrections follow the same consent as their export: without "Use my corrections to retrain" they are out
    without = personal.build_set(evo, store, training_data=False)
    assert [e["source"] for e in without["entries"]] == ["chat", "chat"] and without["counts"]["used"] == 2
    assert without["counts"]["approved_corrections"] == 2 and without["counts"]["corrections_need_consent"]
    assert any("turn on 'Use my corrections to retrain'" in line for line in personal.summary(without))


def test_a_chat_example_has_the_turns_before_it_as_context(env):
    _, state, _, _ = env
    cid = make_chat(state, many(9))
    personal.mark_chat(state.evolution.store, state.store, cid)
    entries = personal.build_set(state.evolution.store, state.store, False)["entries"]
    assert len(entries) == 9 and entries[0]["messages"] == [
        {"role": "user", "content": "Pregunta número 0 sobre mi trabajo"},
        {"role": "assistant", "content": "Respuesta 0, escrita como me gusta."}]
    last = entries[8]["messages"]
    assert last[-2:] == [{"role": "user", "content": "Pregunta número 8 sobre mi trabajo"},
                         {"role": "assistant", "content": "Respuesta 8, escrita como me gusta."}]
    assert len(last) == personal.MAX_CONTEXT + 2 and last[0]["content"] == "Pregunta número 5 sobre mi trabajo"


def test_what_the_user_excludes_is_left_out_and_can_be_put_back(env):
    _, state, _, _ = env
    evo, store = state.evolution.store, state.store
    cid = make_chat(state, many(3))
    fixed = approve(state, "¿Cómo firmo?", "Con «Un saludo».")
    personal.mark_chat(evo, store, cid)
    entries = personal.build_set(evo, store, True)["entries"]
    chat_entry, correction = entries[1], entries[0]
    assert correction["id"] == fixed and chat_entry["id"].startswith(f"{cid}:")

    personal.set_excluded(evo, chat_entry["id"], True)
    personal.set_excluded(evo, chat_entry["id"], True)  # twice is the same as once
    personal.set_excluded(evo, fixed, True)
    built = personal.build_set(evo, store, True)
    assert [e["excluded"] for e in built["entries"]] == [True, True, False, False]
    assert built["counts"]["excluded"] == 2 and built["counts"]["used"] == 2
    assert chat_entry["question"] not in personal.export_chats(built["usable"])  # not even as context of the next turns
    assert [len(e["messages"]) for e in built["usable"]] == [2, 4]  # turn 1 lost its context; turn 2 keeps turn 1's
    assert built["usable"][1]["messages"][0]["content"] == "Pregunta número 1 sobre mi trabajo"
    assert len(evo.items("personal", "excluded")) == 2
    personal.set_excluded(evo, chat_entry["id"], False)
    personal.set_excluded(evo, "nothing-here", False)  # not there: nothing to put back
    assert personal.build_set(evo, store, True)["counts"]["used"] == 3
    assert personal.excluded(evo) == {fixed}


def test_the_same_example_from_two_places_counts_once_and_deleted_chats_are_noted(env):
    _, state, _, _ = env
    evo, store = state.evolution.store, state.store
    first = make_chat(state, [("¿Cómo firmo los correos?", "Con «Un saludo».")])
    second = make_chat(state, [("¿Cómo firmo los correos?", "Con «Un saludo».")], start=2000.0)
    gone = make_chat(state, many(2))
    for cid in (first, second, gone):
        personal.mark_chat(evo, store, cid)
    approve(state, "¿Cómo firmo los correos?", "Con «Un saludo».")
    store.delete_conversation(gone)
    built = personal.build_set(evo, store, True)
    assert built["counts"]["duplicates"] == 2 and built["counts"]["used"] == 1 and built["chats"]["missing"] == 1
    assert [e["duplicate"] for e in built["entries"]] == [False, True, True]
    assert any("1 marked chats were deleted" in line for line in personal.summary(built))


def test_marking_a_chat_needs_a_saved_chat_and_can_be_undone(env):
    _, state, _, _ = env
    evo, store = state.evolution.store, state.store
    with pytest.raises(LookupError, match="chat not found"):
        personal.mark_chat(evo, store, "does-not-exist")
    cid = make_chat(state, many(1))
    one = personal.mark_chat(evo, store, cid)
    assert personal.mark_chat(evo, store, cid)["id"] == one["id"] and len(personal.marked(evo)) == 1
    assert one["title"] == "Mis cosas" and personal.unmark_chat(evo, cid) and not personal.marked(evo)
    assert not personal.unmark_chat(evo, cid)


def test_the_training_file_is_chat_jsonl_tagged_for_the_personal_recipe(env):
    _, state, _, _ = env
    cid = make_chat(state, many(2))
    personal.mark_chat(state.evolution.store, state.store, cid)
    usable = personal.build_set(state.evolution.store, state.store, False)["usable"]
    lines = [json.loads(x) for x in personal.export_chats(usable).splitlines()]
    assert len(lines) == 2 and all(set(x) == {"messages", "meta"} for x in lines)
    assert lines[0]["meta"] == {"id": usable[0]["id"], "specialist": "personal", "source": "spike-personal"}
    assert [m["role"] for m in lines[0]["messages"]] == ["user", "assistant"]  # the system prompt is added by prepare.py
    assert personal.export_chats([]) == ""


# ---------------------------------------------------------------- whether it can run here
def test_it_says_why_it_cannot_run_on_a_computer_that_is_not_an_apple_silicon_mac(tmp_path):
    here = personal.availability(hardware(apple=False), ROOT, True)
    assert not here["available"] and "Not available on this computer (Linux x86_64)" in here["reason"]
    assert "needs a Mac with Apple silicon" in here["reason"] and "nothing was sent anywhere" in here["reason"]
    intel = personal.availability(hardware(apple=False, os_name="Darwin", arch="x86_64"), ROOT, True)
    assert "(Darwin x86_64)" in intel["reason"]
    windows = personal.availability(hardware(apple=False, os_name="Windows", arch="AMD64"), ROOT, True)
    assert "(Windows AMD64)" in windows["reason"]


def test_it_needs_the_source_checkout_mlx_and_enough_memory(tmp_path):
    no_scripts = personal.availability(hardware(), tmp_path, True)
    assert not no_scripts["available"] and "needs a source checkout of SPIKE" in no_scripts["reason"]
    no_mlx = personal.availability(hardware(), ROOT, False)
    assert not no_mlx["available"] and "mlx-lm is not installed" in no_mlx["reason"]
    small = personal.availability(hardware(ram=16.0), ROOT, True)
    assert not small["available"] and "16 GB of memory" in small["reason"] and "waits for 22 GB" in small["reason"]
    assert personal.availability(hardware(ram=16.0), ROOT, True, {"RESUME_FREE_GB": "8"})["available"]
    assert not personal.availability(hardware(ram=32.0), ROOT, True, {"RESUME_FREE_GB": "40"})["available"]
    assert personal.availability(hardware(), ROOT, True) == {"available": True, "reason": ""}


def test_the_ram_floor_is_the_one_the_ram_guard_uses():
    sys.path.insert(0, str(ROOT / "training"))
    from ramguard import Config

    for env in ({}, {"RESUME_FREE_GB": "30"}, {"RESUME_FREE_GB": "8.5"}):
        assert personal.ram_floor_gb(env) == Config.from_env(env).resume_free_gb
    assert personal.ram_floor_gb({}) == 22.0


def test_the_recipe_cannot_loosen_the_acceptance_rule(tmp_path):
    recipe = personal.load_recipe(ROOT)
    assert recipe["specialist"] == "personal" and recipe["system_from"] == "core" and recipe["domain_sources"] == []
    assert recipe["acceptance"] == {"regression": {"suite": "general", "max_drop_points": 1.5}}
    assert personal.MAX_DROP_POINTS == 1.5

    def with_acceptance(acceptance) -> Path:
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        (folder / "training" / "configs").mkdir(parents=True)
        (folder / RECIPE.relative_to(ROOT)).write_text(yaml.safe_dump({**recipe, "acceptance": acceptance}),
                                                       encoding="utf-8")
        return folder

    for loose in ({"regression": {"suite": "general", "max_drop_points": 5.0}}, {"regression": {"suite": "general-select",
                                                                                              "max_drop_points": 1.5}},
                  {"regression": {"suite": "general", "max_drop_points": -1}}, {}, {"primary": {"suite": "general"}}):
        with pytest.raises(ValueError, match="must require the general suite to drop by at most 1.5 points"):
            personal.load_recipe(with_acceptance(loose))
    assert personal.load_recipe(with_acceptance({"regression": {"suite": "general", "max_drop_points": 1.0}}))


def test_the_eval_arguments_are_the_trainings():
    sys.path.insert(0, str(ROOT / "training"))
    from spike_train.evaluation import eval_args

    recipe = yaml.safe_load(RECIPE.read_text(encoding="utf-8"))
    assert personal._eval_args(recipe) == eval_args(recipe) == ["--max-tokens", "2048"]
    assert personal._eval_args({}) == eval_args({}) == []
    assert personal._select_rule(recipe["acceptance"]) == {"regression": {"suite": "general-select",
                                                                         "max_drop_points": 1.5}}


# ---------------------------------------------------------------- the stubbed pipeline
def summary_of(suite, base_correct, tuned_correct, n=100, variant="spike-personal"):
    def preds(name, correct):
        return [{"suite": suite, "task": suite[0], "item": f"{suite}/{i}", "variant": name, "correct": i < correct,
                 "parsed": "A", "finish_reason": "stop"} for i in range(n)]

    return training_eval.summarize(preds("base", base_correct) + preds(variant, tuned_correct))


class Pipeline:
    """The five commands of the pipeline as one runner: each writes what the real one writes, and the runner notes
    what it was asked and what the disk looked like at that moment."""

    def __init__(self, root, adapters_dir, select=(60, 59), general=(60, 59), exits=None, tag="one"):
        self.root, self.adapters_dir, self.select, self.general, self.tag = root, adapters_dir, select, general, tag
        self.exits, self.commands, self.seen = exits or {}, [], {}

    @staticmethod
    def step_of(cmd) -> str:
        script = Path(cmd[1]).name
        return {"prepare.py": "prepare", "train_supervised.sh": "train", "train.sh": "train",
                "export_adapter.py": "export"}.get(script) or cmd[cmd.index("--suites") + 1]

    def __call__(self, cmd, env):
        step = self.step_of(cmd)
        self.commands.append((step, cmd))
        self.seen.setdefault("gguf_in_adapters_folder", []).append((self.adapters_dir / "spike-personal.gguf").exists())
        data, runs = self.root / "training" / "data" / "personal", self.root / "training" / "runs" / "personal"
        code = self.exits.get(step, 0)
        if step == "prepare":
            self.seen["examples"] = Path(cmd[cmd.index("--corrections") + 1]).read_text(encoding="utf-8")
            data.mkdir(parents=True, exist_ok=True)
            (data / "train.jsonl").write_text(self.seen["examples"], encoding="utf-8")
        elif step == "train":
            (runs / "adapter").mkdir(parents=True, exist_ok=True)
            (runs / "adapter" / "adapters.safetensors").write_bytes(b"weights")
        elif step == "export":
            stage = Path(cmd[cmd.index("--out") + 1])
            self.seen["stage"] = stage
            if code == 0:
                _gguf(stage / f"{cmd[cmd.index('--name') + 1]}.gguf", **LORA, **{"general.name": self.tag})
        else:
            out = Path(cmd[cmd.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            base, tuned = self.select if step == "general-select" else self.general
            (out / "summary.json").write_text(json.dumps(summary_of(step, base, tuned)), encoding="utf-8")
            if step == "general" and tuned - base < -1.5 and code == 0:
                code = 2  # run_eval.py --acceptance exits 2 when the rule is not met
        return code


@pytest.fixture
def bench(env, tmp_path):
    """A state with 40 usable chat examples, a fake source checkout and fake llama.cpp and model paths."""
    _, state, _, home = env
    cid = make_chat(state, many(40))
    personal.mark_chat(state.evolution.store, state.store, cid)
    root = tmp_path / "checkout"
    (root / "training" / "configs").mkdir(parents=True)
    (root / "training" / "prepare.py").write_text("", encoding="utf-8")
    shutil.copy(RECIPE, root / "training" / "configs" / "personal.yaml")
    llama = tmp_path / "llama.cpp"
    llama.mkdir()
    (llama / "convert_lora_to_gguf.py").write_text("", encoding="utf-8")
    model = tmp_path / "base.gguf"
    model.write_bytes(b"GGUF")
    folder = state.adapters_path()
    log: list[str] = []

    def job(pipeline=None, settings=None, **over) -> personal.Job:
        values = dict(evo=state.evolution.store, store=state.store,
                      settings={"personal_adapter": True, "training_data": True} if settings is None else settings, adapters_dir=folder,
                      work=home / "personal", llama_cpp=llama, model=model, root=root,
                      runner=pipeline or Pipeline(root, folder), hardware=hardware(), has_mlx=True, log=log.append)
        return personal.Job(**{**values, **over})

    return types.SimpleNamespace(state=state, root=root, llama=llama, model=model, folder=folder, job=job, log=log,
                                 pipeline=lambda **kw: Pipeline(root, folder, **kw), work=home / "personal")


def nothing_is_left(bench):
    return not any([(bench.work / "stage").exists(), (bench.work / "spike-personal.jsonl").exists(),
                    (bench.root / "training" / "data" / "personal").exists(),
                    (bench.root / "training" / "runs" / "personal").exists()])


def test_an_accepted_adapter_is_trained_on_the_users_set_installed_and_cleaned_up(bench):
    pipeline = bench.pipeline()
    result = personal.run(bench.job(pipeline))
    assert result["status"] == "accepted" and result["version"] is not None
    assert [s["name"] for s in result["steps"]] == ["prepare", "train", "export", "select", "evaluate"]
    assert all(s["exit"] == 0 for s in result["steps"])
    assert result["message"].startswith("Accepted and installed as adapter:personal v")
    assert "spike evolve rollback adapter:personal" in result["message"]

    # the examples are exactly the ones counted, tagged for the personal recipe
    sent = [json.loads(x) for x in pipeline.seen["examples"].splitlines()]
    assert len(sent) == 40 == result["counts"]["used"] and {x["meta"]["source"] for x in sent} == {"spike-personal"}
    assert {x["meta"]["specialist"] for x in sent} == {"personal"}

    commands = dict(pipeline.commands)
    prepare = commands["prepare"]
    assert prepare[1].endswith("prepare.py") and prepare[2] == str(bench.root / RECIPE.relative_to(ROOT))
    assert prepare[3] == "--corrections" and Path(prepare[4]) == bench.work / "spike-personal.jsonl"
    assert commands["train"][0] == "bash" and commands["train"][1].endswith("train_supervised.sh")
    assert commands["train"][2] == "personal"  # under the RAM guard
    export = commands["export"]
    assert export[export.index("--name") + 1] == "spike-personal" and export[export.index("--system-from") + 1] == "core"
    stage = bench.work / "stage"
    assert Path(export[export.index("--out") + 1]) == stage and Path(export[export.index("--work") + 1]) == stage / "work"
    assert export[export.index("--check-model") + 1] == str(bench.model)
    assert export[export.index("--llama-cpp") + 1] == str(bench.llama)
    select, general = commands["general-select"], commands["general"]
    for cmd in (select, general):
        assert cmd[1].endswith("run_eval.py") and cmd[cmd.index("--model") + 1] == str(bench.model)
        assert cmd[cmd.index("--adapter") + 1] == str(stage / "spike-personal.gguf")
        assert cmd[cmd.index("--max-tokens") + 1] == "2048"
    assert "--acceptance" in general and general[general.index("--acceptance") + 1].endswith("personal.yaml")
    assert "--acceptance" not in select
    assert [step for step, _ in pipeline.commands] == ["prepare", "train", "export", "general-select", "general"]

    # nothing reached the adapters folder before the verdict; afterwards the adapter is in use and versioned
    assert pipeline.seen["gguf_in_adapters_folder"] == [False] * 5
    version = bench.state.evolution.store.active("adapter:personal")
    assert version["id"] == result["version"] and version["report"]["accepted"] and "accepted" in version["reason"]
    assert (bench.folder / "spike-personal.gguf").is_file()
    assert nothing_is_left(bench)  # the user's text is not kept, nor the weights trained on it
    assert any(line.startswith("[prepare] ") for line in bench.log)


def test_the_unsupervised_variant_is_only_for_when_the_user_asks(bench, monkeypatch):
    monkeypatch.setenv("SPIKE_UNSUPERVISED", "1")
    pipeline = bench.pipeline()
    assert personal.run(bench.job(pipeline))["status"] == "accepted"
    assert dict(pipeline.commands)["train"][1].endswith("train.sh")


def test_a_drop_in_general_select_ends_the_run_before_the_long_general_suite(bench):
    pipeline = bench.pipeline(select=(60, 56))
    result = personal.run(bench.job(pipeline))
    assert result["status"] == "rejected" and result["message"].startswith("Rejected on general-select: ")
    assert "general-select: -4.00 pts (max drop 1.5)" in result["message"]
    assert [step for step, _ in pipeline.commands] == ["prepare", "train", "export", "general-select"]
    assert bench.state.evolution.store.active("adapter:personal") is None and bench.state.evolution.store.versions() == []
    assert not (bench.folder / "spike-personal.gguf").exists() and nothing_is_left(bench)


def test_a_drop_in_the_general_suite_refuses_the_adapter_and_nothing_is_activated(bench):
    pipeline = bench.pipeline(general=(60, 57))  # general-select held, the general suite did not
    result = personal.run(bench.job(pipeline))
    assert result["status"] == "rejected" and result["version"] is None
    assert result["message"].startswith("Rejected, not activated: general: -3.00 pts (max drop 1.5)")
    assert [s["name"] for s in result["steps"]][-1] == "evaluate" and result["steps"][-1]["exit"] == 2
    assert bench.state.evolution.store.versions() == [] and not (bench.folder / "spike-personal.gguf").exists()
    assert nothing_is_left(bench)


def test_the_gate_judges_the_measured_numbers_not_the_exit_code_of_the_eval(bench):
    class LyingEval(Pipeline):
        def __call__(self, cmd, env):
            code = super().__call__(cmd, env)
            return 0 if self.step_of(cmd) == "general" else code

    result = personal.run(bench.job(LyingEval(bench.root, bench.folder, general=(60, 50))))
    assert result["status"] == "rejected" and bench.state.evolution.store.versions() == []
    assert not (bench.folder / "spike-personal.gguf").exists()


def test_a_small_drop_within_the_limit_is_accepted(bench):
    result = personal.run(bench.job(bench.pipeline(select=(60, 59), general=(60, 59))))
    assert result["status"] == "accepted"
    assert result["reasons"] == ["general: -1.00 pts (max drop 1.5)"]


def test_a_second_accepted_adapter_replaces_the_first_and_rollback_puts_it_back(bench):
    state, evo = bench.state, bench.state.evolution.store
    first = personal.run(bench.job(bench.pipeline(tag="one")))
    second = personal.run(bench.job(bench.pipeline(tag="two")))
    assert first["status"] == second["status"] == "accepted" and first["version"] != second["version"]
    dest = bench.folder / "spike-personal.gguf"
    assert evo.active("adapter:personal")["id"] == second["version"] and b"two" in dest.read_bytes()
    assert state.rollback("adapter:personal")["id"] == first["version"] and b"one" in dest.read_bytes()
    assert state.rollback("adapter:personal") is None and not dest.exists()  # back to no personal adapter
    assert evo.active("adapter:personal") is None and len(evo.versions("adapter:personal")) == 2


def test_it_does_nothing_unless_the_user_turned_it_on(bench):
    pipeline = bench.pipeline()
    for settings in ({}, {"personal_adapter": False, "training_data": True}):
        result = personal.run(bench.job(pipeline, settings=settings))
        assert result["status"] == "off" and "The personal adapter is off" in result["message"]
    assert pipeline.commands == [] and nothing_is_left(bench) and not bench.work.exists()


def test_it_says_so_and_does_nothing_on_other_platforms(bench):
    pipeline = bench.pipeline()
    result = personal.run(bench.job(pipeline, hardware=hardware(apple=False)))
    assert result["status"] == "unavailable" and "needs a Mac with Apple silicon" in result["message"]
    assert pipeline.commands == [] and nothing_is_left(bench) and bench.state.evolution.store.versions() == []
    no_mlx = personal.run(bench.job(pipeline, has_mlx=False))
    assert no_mlx["status"] == "unavailable" and "mlx-lm is not installed" in no_mlx["message"]


def test_too_few_examples_are_not_trained_on(bench):
    pipeline = bench.pipeline()
    result = personal.run(bench.job(pipeline, settings={"personal_adapter": True, "training_data": False}))
    assert result["status"] == "accepted"  # 40 chat answers are enough without corrections
    pipeline = bench.pipeline()
    for entry in personal.build_set(bench.state.evolution.store, bench.state.store, False)["entries"][:11]:
        personal.set_excluded(bench.state.evolution.store, entry["id"], True)
    result = personal.run(bench.job(pipeline))
    assert result["status"] == "too_few" and result["counts"]["used"] == 29 and result["counts"]["excluded"] == 11
    assert "29 examples to train on; at least 30 are needed" in result["message"] and pipeline.commands == []


def test_a_missing_llama_cpp_or_model_stops_before_anything_is_written(bench):
    pipeline = bench.pipeline()
    wrong = bench.llama.parent / "nowhere"
    result = personal.run(bench.job(pipeline, llama_cpp=wrong))
    assert result["status"] == "failed" and result["message"].startswith("llama.cpp checkout not found: ")
    result = personal.run(bench.job(pipeline, model=wrong / "m.gguf"))
    assert result["status"] == "failed" and result["message"].startswith("base model not found: ")
    assert pipeline.commands == [] and not bench.work.exists()


def test_a_recipe_that_loosens_the_rule_stops_the_run(bench):
    path = bench.root / RECIPE.relative_to(ROOT)
    recipe = yaml.safe_load(path.read_text(encoding="utf-8"))
    recipe["acceptance"]["regression"]["max_drop_points"] = 10.0
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    pipeline = bench.pipeline()
    result = personal.run(bench.job(pipeline))
    assert result["status"] == "failed" and "must require the general suite to drop by at most 1.5 points" in result["message"]
    assert pipeline.commands == []


@pytest.mark.parametrize("step, kept", [("prepare", False), ("train", True), ("export", False), ("general-select", False),
                                        ("general", False)])
def test_a_failing_step_stops_the_run_and_only_a_stopped_training_keeps_the_files(bench, step, kept):
    pipeline = bench.pipeline(exits={step: 1})
    result = personal.run(bench.job(pipeline))
    assert result["status"] == "failed" and bench.state.evolution.store.versions() == []
    assert not (bench.folder / "spike-personal.gguf").exists()
    assert (nothing_is_left(bench)) is (not kept)
    assert result["steps"][-1] == {"name": step if step in ("prepare", "train", "export") else (
        "select" if step == "general-select" else "evaluate"), "exit": 1}
    assert result["message"].endswith("see its output above.")


def test_the_ram_guard_giving_up_keeps_the_prepared_data_so_that_the_command_can_resume(bench):
    pipeline = bench.pipeline(exits={"train": 75})
    result = personal.run(bench.job(pipeline))
    assert result["status"] == "failed" and "RAM guard gave up waiting" in result["message"]
    assert "run the command again: training resumes from its last checkpoint" in result["message"]
    assert (bench.root / "training" / "data" / "personal" / "train.jsonl").is_file()
    assert (bench.root / "training" / "runs" / "personal" / "adapter" / "adapters.safetensors").is_file()
    assert [step for step, _ in pipeline.commands] == ["prepare", "train"]
    assert personal.run(bench.job(bench.pipeline()))["status"] == "accepted" and nothing_is_left(bench)  # resumed


def test_the_user_text_is_deleted_whatever_the_verdict(bench):
    for pipeline in (bench.pipeline(select=(60, 50)), bench.pipeline(general=(60, 50)), bench.pipeline()):
        personal.run(bench.job(pipeline))
        assert nothing_is_left(bench)


def test_run_command_returns_the_exit_code_of_the_command():
    assert personal.run_command([sys.executable, "-c", "import sys; sys.exit(3)"], {}) == 3
    assert personal.run_command([sys.executable, "-c", "import os, sys; sys.exit(int(os.environ['X_EXIT']))"],
                                {"X_EXIT": "5"}) == 5


# ---------------------------------------------------------------- Spike Core uses it, only while it is on
def install_accepted(state, tmp_path):
    summary = tmp_path / "eval"
    summary.mkdir()
    (summary / "summary.json").write_text(json.dumps(summary_of("general", 60, 59)), encoding="utf-8")
    state.adapters_path().mkdir(parents=True, exist_ok=True)
    return adapters.install(state.evolution.store, state.adapters_path(), personal.PERSONAL,
                            _gguf(tmp_path / "p.gguf", **LORA), summary, RECIPE)["version"]


def test_spike_core_loads_the_personal_adapter_only_while_the_setting_is_on(env, tmp_path):
    client, state, _, _ = env
    assert state.evolution_settings()["personal_adapter"] is False  # off by default
    assert state.personal_adapter() is None
    install_accepted(state, tmp_path)
    state.installed_adapters = {"spike-local": {"spike-personal", "spike-medicine"}}

    def adapter_of(specialist):
        return state.orchestrator().resolve(state.catalog.get(specialist)).adapter

    assert adapter_of("core") is None  # installed, but the user has not turned it on
    turn_on(client)
    assert state.personal_adapter() == "spike-personal" and adapter_of("core") == "spike-personal"
    assert adapter_of("medicine") == "spike-medicine"  # the specialists keep their own adapters
    state.installed_adapters = {"spike-local": {"spike-medicine"}}  # the engine did not load it
    assert adapter_of("core") is None
    state.installed_adapters = {"spike-local": {"spike-personal"}}
    (state.adapters_path() / "spike-personal.gguf").unlink()
    assert state.personal_adapter() is None  # no file, no adapter
    state.rollback("adapter:personal")
    turn_on(client)
    assert state.personal_adapter() is None  # nothing accepted in use


def test_rolling_back_the_personal_adapter_removes_it(env, tmp_path):
    _, state, _, _ = env
    install_accepted(state, tmp_path)
    assert (state.adapters_path() / "spike-personal.gguf").is_file()
    assert state.rollback("adapter:personal") is None
    assert not (state.adapters_path() / "spike-personal.gguf").exists()
    assert state.evolution.store.active("adapter:personal") is None
    with pytest.raises(LookupError):
        state.rollback("adapter:personal")


# ---------------------------------------------------------------- the API
def test_the_api_shows_what_would_be_used_and_lets_the_user_mark_and_exclude(env):
    client, state, _, _ = env
    first = client.get("/api/evolution/personal").json()
    assert first["enabled"] is False and first["training_data"] is False and first["entries"] == []
    assert first["marked"] == [] and first["active"] is None and first["counts"]["needed"] == 30
    assert "available" in first and "reason" in first and first["command"].startswith("spike evolve personal-adapter")
    cid = make_chat(state, many(3))
    assert client.post("/api/evolution/personal/marks", json={"conversation": cid}).status_code == 409  # still off

    turn_on(client)
    assert client.post("/api/evolution/personal/marks", json={"conversation": "nope"}).status_code == 404
    assert client.post("/api/evolution/personal/marks", json={"conversation": cid}).status_code == 200
    overview = client.get("/api/evolution/personal").json()
    assert overview["enabled"] is True and overview["counts"]["used"] == 3 and overview["counts"]["chat_answers"] == 3
    assert overview["marked"][0]["conversation"] == cid and overview["marked"][0]["title"] == "Mis cosas"
    entry = overview["entries"][0]
    assert set(entry) == {"id", "source", "conversation", "question", "answer", "excluded", "duplicate"}

    assert client.put("/api/evolution/personal/exclusions", json={"ref": "unknown"}).status_code == 404
    assert client.put("/api/evolution/personal/exclusions", json={"ref": entry["id"]}).json() == {"ok": True}
    after = client.get("/api/evolution/personal").json()
    assert after["counts"]["used"] == 2 and after["counts"]["excluded"] == 1 and after["entries"][0]["excluded"]
    client.put("/api/evolution/personal/exclusions", json={"ref": entry["id"], "excluded": False})
    assert client.get("/api/evolution/personal").json()["counts"]["used"] == 3

    assert client.delete(f"/api/evolution/personal/marks/{cid}").json() == {"ok": True}
    assert client.delete(f"/api/evolution/personal/marks/{cid}").status_code == 404
    assert client.get("/api/evolution/personal").json()["counts"]["used"] == 0


def test_approved_corrections_show_up_only_with_the_retraining_consent(env):
    client, state, _, _ = env
    approve(state, "¿Cómo firmo?", "Con «Un saludo».")
    turn_on(client)
    off = client.get("/api/evolution/personal").json()
    assert off["entries"] == [] and off["counts"]["approved_corrections"] == 1 and off["counts"]["corrections_need_consent"]
    turn_on(client, training_data=True)
    on = client.get("/api/evolution/personal").json()
    assert [e["source"] for e in on["entries"]] == ["correction"] and on["counts"]["used"] == 1


def test_there_is_no_training_endpoint(env):
    client, _, _, _ = env
    for method in ("post", "put"):
        for path in ("/api/evolution/personal", "/api/evolution/personal/train", "/api/evolution/personal/run"):
            assert getattr(client, method)(path, json={}).status_code in (404, 405)


# ---------------------------------------------------------------- the command line
@pytest.fixture
def cli(env, bench, monkeypatch, capsys):
    """`spike evolve personal-adapter` on the bench: a Mac with MLX, the stubbed pipeline, no prompt."""
    monkeypatch.setattr(personal, "detect", lambda: hardware())
    monkeypatch.setattr(personal, "find_spec", lambda name: object())
    pipeline = bench.pipeline()
    monkeypatch.setattr(personal, "run_command", pipeline)
    real_job = personal.Job
    monkeypatch.setattr(personal, "Job", lambda *a, **kw: real_job(*a, root=bench.root, **kw))
    args = ["evolve", "personal-adapter"]
    bench.cli = types.SimpleNamespace(pipeline=pipeline, args=args, capsys=capsys, out=lambda: capsys.readouterr())
    return bench


def test_the_cli_is_off_by_default_and_turns_on_and_off(cli, capsys):
    assert main(["evolve", "personal-adapter"]) == 1
    err = capsys.readouterr().err
    assert "The personal adapter is off" in err and "nothing was done" in err and cli.cli.pipeline.commands == []
    assert main(["evolve", "personal-adapter", "--enable"]) == 0 and "Personal adapter on" in capsys.readouterr().out
    assert cli.state.evolution_settings()["personal_adapter"] is True
    assert main(["evolve", "personal-adapter", "--list"]) == 0
    assert "To train on: 40 examples (at least 30 needed)" in capsys.readouterr().out
    assert main(["evolve", "personal-adapter", "--disable"]) == 0 and "Personal adapter off." in capsys.readouterr().out
    assert cli.state.evolution_settings()["personal_adapter"] is False


def test_the_cli_marks_lists_and_excludes(cli, capsys):
    main(["evolve", "personal-adapter", "--enable"])
    capsys.readouterr()
    second = make_chat(cli.state, many(2, "Segundo"), start=9000.0)
    assert main(["evolve", "personal-adapter", "--mark", second, "--list"]) == 0
    out = capsys.readouterr().out
    assert "Marked chats: 2 -> 42 answers by SPIKE's local model" in out and out.count(" used ") == 42
    ref = f"{second}:" + cli.state.store.messages(second)[1]["id"]
    assert main(["evolve", "personal-adapter", "--exclude", ref, "--list"]) == 0
    out = capsys.readouterr().out
    assert "Excluded by you: 1" in out and "To train on: 41 examples" in out and " excluded " in out
    assert main(["evolve", "personal-adapter", "--include", ref, "--unmark", second, "--list"]) == 0
    assert "To train on: 40 examples" in capsys.readouterr().out
    assert main(["evolve", "personal-adapter", "--exclude", "nope"]) == 2
    assert "'nope' is not an example in the personal set" in capsys.readouterr().err
    assert cli.cli.pipeline.commands == []  # none of this trains


def test_the_cli_says_it_is_not_available_on_other_platforms(cli, capsys, monkeypatch):
    main(["evolve", "personal-adapter", "--enable"])
    capsys.readouterr()
    monkeypatch.setattr(personal, "detect", lambda: hardware(apple=False))
    assert main(["evolve", "personal-adapter", "--yes"]) == 1
    captured = capsys.readouterr()
    assert "Not available on this computer (Linux x86_64)" in captured.err and "needs a Mac with Apple silicon" in captured.err
    assert "To train on: 40 examples" in captured.out  # the counts are still shown
    assert cli.cli.pipeline.commands == [] and cli.state.evolution.store.versions() == []


def test_the_cli_needs_enough_examples_and_a_yes(cli, capsys, monkeypatch):
    main(["evolve", "personal-adapter", "--enable"])
    capsys.readouterr()
    assert main(["evolve", "personal-adapter", "--llama-cpp", str(cli.llama), "--model", str(cli.model)]) == 1
    assert "Not started. Run again with --yes" in capsys.readouterr().err  # no terminal, no yes: not started
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda question: "n")
    assert main(["evolve", "personal-adapter", "--llama-cpp", str(cli.llama), "--model", str(cli.model)]) == 1
    assert "Not started" in capsys.readouterr().err and cli.cli.pipeline.commands == []
    for entry in personal.build_set(cli.state.evolution.store, cli.state.store, False)["entries"][:11]:
        personal.set_excluded(cli.state.evolution.store, entry["id"], True)
    assert main(["evolve", "personal-adapter", "--yes"]) == 1
    assert "at least 30 examples are needed to train" in capsys.readouterr().err and cli.cli.pipeline.commands == []


def test_the_cli_needs_to_know_where_llama_cpp_and_the_model_are(cli, capsys, monkeypatch):
    main(["evolve", "personal-adapter", "--enable"])
    capsys.readouterr()
    monkeypatch.delenv("SPIKE_LLAMA_CPP", raising=False)
    assert main(["evolve", "personal-adapter", "--yes"]) == 2
    assert "pass --llama-cpp" in capsys.readouterr().err and cli.cli.pipeline.commands == []


def test_the_cli_trains_with_the_stubbed_pipeline_and_reports_the_verdict(cli, capsys, monkeypatch):
    main(["evolve", "personal-adapter", "--enable"])
    capsys.readouterr()
    monkeypatch.setenv("SPIKE_LLAMA_CPP", str(cli.llama))
    assert main(["evolve", "personal-adapter", "--yes", "--model", str(cli.model)]) == 0
    out = capsys.readouterr().out
    assert "Accepted and installed as adapter:personal" in out and "[prepare] " in out
    assert cli.state.evolution.store.active("adapter:personal") is not None
    assert (cli.folder / "spike-personal.gguf").is_file()


def test_the_cli_exit_code_says_rejected_and_nothing_is_installed(cli, capsys, monkeypatch):
    main(["evolve", "personal-adapter", "--enable"])
    capsys.readouterr()
    monkeypatch.setattr(personal, "run_command", cli.pipeline(general=(60, 55)))
    assert main(["evolve", "personal-adapter", "--yes", "--llama-cpp", str(cli.llama), "--model", str(cli.model)]) == 2
    assert "Rejected, not activated" in capsys.readouterr().out
    assert cli.state.evolution.store.versions() == [] and not (cli.folder / "spike-personal.gguf").exists()


def test_the_cli_rolls_the_personal_adapter_back(cli, capsys, tmp_path):
    install_accepted(cli.state, tmp_path)
    assert main(["evolve", "rollback", "adapter:personal"]) == 0
    out = capsys.readouterr().out
    assert "adapter:personal: back to the built-in version" in out and "Restart the local engine" in out
    assert not (cli.folder / "spike-personal.gguf").exists()


def test_the_store_keeps_marks_and_exclusions_apart_from_the_other_kinds(tmp_path):
    evo = EvolutionStore(tmp_path / "e.db")
    mark = evo.add("personal", {"conversation": "c1", "title": "t"}, status="marked")
    leave = evo.add("personal", {"ref": "c1:m1"}, status="excluded")
    assert [i["id"] for i in personal.marked(evo)] == [mark["id"]] and personal.excluded(evo) == {"c1:m1"}
    assert leave["kind"] == "personal" and evo.items("example") == [] and evo.items("correction") == []
