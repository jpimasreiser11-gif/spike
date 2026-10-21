"""training/sweep_checkpoints.py: which saved checkpoint, at which LoRA scale, passes the recipe's rule on select suites.

The export and evaluation subprocesses are replaced by a recorder that leaves behind what export_adapter.py and
run_eval.py would (a GGUF and export.json, a summary.json in run_eval's format), so every command line, the scaled
adapter folders, the reuse of finished work and the choice are checked without a model. The one test that converts a
scaled candidate with llama.cpp's real converter needs SPIKE_LLAMA_CPP and SPIKE_CONVERT_PYTHON, like
tests/test_export_integration.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

import export_adapter  # noqa: E402
import sweep_checkpoints as sweep  # noqa: E402
from spike_train.evaluation import check_acceptance  # noqa: E402
from spike_train.export import convert, read_safetensors, write_safetensors  # noqa: E402

LLAMA_CPP = os.environ.get("SPIKE_LLAMA_CPP")
CONVERT_PY = os.environ.get("SPIKE_CONVERT_PYTHON")

TOTAL = 1000
CHECKPOINTS = (200, 400, 600, 800)  # saved every 200 iterations; the final adapter is iteration 1000
RANK, SCALE = 4, 2.0
MODULES = ["language_model.model.layers.3.self_attn.q_proj", "language_model.model.layers.0.mlp.down_proj"]
DIMS = {MODULES[0]: (16, 32), MODULES[1]: (48, 16)}

# default candidates: 0.125 -> it200 and 0.25 -> it200 are one, 0.5 is a tie between 400 and 600 (the earlier), 1@0.5
SELECT = {"it200-s1": {"medicine-select": (6.0, 0.001), "general-select": (-0.5, 0.4)},
          "it400-s1": {"medicine-select": (9.0, 0.001), "general-select": (-3.0, 0.01)},   # best gain, forgets
          "it1000-s0.5": {"medicine-select": (7.5, 0.001), "general-select": (-1.0, 0.3)}}
FINAL = {"it1000-s0.5": {"medicine": (7.0, 0.001), "general": (-1.0, 0.3)}}


def flag(cmd: list[str], name: str) -> str | None:
    return cmd[cmd.index(name) + 1] if name in cmd else None


def flags(cmd: list[str], name: str) -> list[str]:
    return [cmd[i + 1] for i, c in enumerate(cmd) if c == name]


def adapter_weights(seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {f"{m}.{ab}": rng.standard_normal((d_in, RANK) if ab == "lora_a" else (RANK, d_out)).astype(np.float32)
            for m, (d_in, d_out) in DIMS.items() for ab in ("lora_a", "lora_b")}


class Fake:
    """Replaces sweep.run: records every command and leaves what export_adapter.py / run_eval.py would."""

    def __init__(self):
        self.calls: list[list[str]] = []
        # "it<N>-s<S>" -> {suite: (delta_points, p_value)}; a copy, tests change it
        self.table = {k: {**SELECT.get(k, {}), **FINAL.get(k, {})} for k in {*SELECT, *FINAL}}
        self.exit = {}                    # script name -> exit code to fail with
        self.exported: dict[str, dict] = {}

    def scripts(self) -> list[str]:
        return [Path(c[1]).name for c in self.calls]

    def __call__(self, cmd: list[str]) -> int:
        self.calls.append(cmd)
        script = Path(cmd[1]).name
        if code := self.exit.get(script):
            return code
        return self.export(cmd) if script == "export_adapter.py" else self.evaluate(cmd)

    def export(self, cmd: list[str]) -> int:
        mlx, out, work = (Path(flag(cmd, f)) for f in ("--adapter", "--out", "--work"))
        name = flag(cmd, "--name")
        self.exported[name] = {"config": json.loads((mlx / "adapter_config.json").read_text(encoding="utf-8")),
                               "weights": (mlx / "adapters.safetensors").resolve()}
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.gguf").write_bytes(b"GGUF")
        work.mkdir(parents=True, exist_ok=True)
        (work / "export.json").write_text("{}")
        return 0

    def evaluate(self, cmd: list[str]) -> int:
        out = Path(flag(cmd, "--resume") or flag(cmd, "--out"))
        if "--resume" in cmd:
            assert (out / "predictions.jsonl").is_file()
        out.mkdir(parents=True, exist_ok=True)
        stems = [Path(a).stem for a in flags(cmd, "--adapter")]
        measured = {stem: self.table[stem.removeprefix("spike-medicine-")] for stem in stems}
        summary = {"meta": {"suites": flag(cmd, "--suites")}, "variants": ["base", *stems], "tasks": {},
                   "suites": {s: {"accuracy": {}, "vs_base": {
                       stem: {"paired_n": 400, "delta_points": m[s][0], "p_value": m[s][1]} for stem, m in measured.items()}}
                              for s in flag(cmd, "--suites").split(",")}}
        (out / "predictions.jsonl").write_text("{}\n")
        code = 0
        if "--acceptance" in cmd:
            acceptance = yaml.safe_load(Path(flag(cmd, "--acceptance")).read_text(encoding="utf-8"))["acceptance"]
            summary["acceptance"] = {}
            for stem in stems:
                ok, reasons = check_acceptance(summary, acceptance, stem)
                summary["acceptance"][stem] = {"accepted": ok, "reasons": reasons}
                code = code or (0 if ok else 2)
        (out / "summary.json").write_text(json.dumps(summary))
        return code


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A repo root with the real medicine recipe and suites, a finished (fake) training run and a recording runner."""
    root = tmp_path / "repo"
    (root / "training" / "configs").mkdir(parents=True)
    (root / "evals").mkdir()
    shutil.copy(ROOT / "training" / "configs" / "medicine.yaml", root / "training" / "configs")
    shutil.copy(ROOT / "evals" / "suites.yaml", root / "evals")
    runs = root / "training" / "runs" / "medicine"
    adapter = runs / "adapter"
    adapter.mkdir(parents=True)
    (runs / "run.json").write_text(json.dumps({"specialist": "medicine", "exit_code": 0, "git_commit": "abc1234",
                                               "counts": {"train": 1000, "iters": TOTAL}}))
    (adapter / "adapter_config.json").write_text(json.dumps(
        {"fine_tune_type": "lora", "iters": TOTAL, "learning_rate": 1e-4,
         "lora_parameters": {"rank": RANK, "scale": SCALE, "dropout": 0.05, "keys": ["self_attn.q_proj"]}}, indent=4))
    for it in CHECKPOINTS:
        write_safetensors(adapter / f"{it:07d}_adapters.safetensors", adapter_weights(it))
    write_safetensors(adapter / "adapters.safetensors", adapter_weights(TOTAL))
    model = tmp_path / "base.gguf"
    model.write_bytes(b"GGUF")
    llama = tmp_path / "llama.cpp"
    llama.mkdir()
    (llama / "convert_lora_to_gguf.py").write_text("")
    fake = Fake()
    monkeypatch.setattr(sweep, "ROOT", root)
    monkeypatch.setattr(sweep, "run", fake)
    w = SimpleNamespace(root=root, runs=runs, adapter=adapter, sweep=runs / "sweep", model=model, llama=llama, fake=fake)
    w.go = lambda *extra: sweep.main(["medicine", "--llama-cpp", str(llama), "--model", str(model), *extra])
    return w


# ------------------------------------------------------------------------------------------- candidates
@pytest.mark.parametrize("text, fraction, scale", [
    ("0.25", Fraction(1, 4), 1), ("1", 1, 1), ("1@0.5", 1, Fraction(1, 2)), ("1/8", Fraction(1, 8), 1),
    (" 0.5 @ 0.75 ", Fraction(1, 2), Fraction(3, 4)), ("0.15@1", Fraction(3, 20), 1),
])
def test_candidates_are_fraction_at_scale(text, fraction, scale):
    assert sweep.parse_candidate(text) == (fraction, scale)


@pytest.mark.parametrize("text", ["0", "1.5", "-0.1", "0.5@0", "0.5@1.5", "0.5@-1", "x", "0.5@", "@0.5", "nan", "inf",
                                  "0.5@0.5@1", "", "1/0", "0.5@x"])
def test_bad_candidates_are_refused_with_the_value_in_the_message(text):
    with pytest.raises(SystemExit, match="bad --candidate"):
        sweep.parse_candidate(text)


def test_a_fraction_picks_the_nearest_checkpoint_a_tie_the_earlier_and_one_the_final_adapter(world):
    def pick(*specs):
        return [(c.iteration, c.checkpoint.name) for c in sweep.plan(list(specs), "medicine", world.adapter, TOTAL)]

    assert pick("0.125") == [(200, "0000200_adapters.safetensors")]   # 125: 200 is 75 away, nothing earlier
    assert pick("0.5") == [(400, "0000400_adapters.safetensors")]     # 500 is 100 from 400 and from 600: the earlier
    assert pick("0.3") == [(200, "0000200_adapters.safetensors")]     # 300 is 100 from 200 and from 400: the earlier
    assert pick("0.65") == [(600, "0000600_adapters.safetensors")]
    assert pick("0.99") == [(800, "0000800_adapters.safetensors")]    # 990: 800 is the last checkpoint, not the final
    assert pick("1") == [(1000, "adapters.safetensors")]
    assert pick("0.35", "0.9") == [(400, "0000400_adapters.safetensors"), (800, "0000800_adapters.safetensors")]


def test_candidates_with_the_same_iteration_and_scale_collapse_but_other_scales_do_not(world):
    specs = ["0.125", "0.25", "0.25@1", "0.25@0.5", "0.5", "1@0.5", "1", "1@0.50"]
    plan = sweep.plan(specs, "medicine", world.adapter, TOTAL)
    assert [(c.iteration, float(c.scale)) for c in plan] == [(200, 1), (200, 0.5), (400, 1), (1000, 0.5), (1000, 1)]
    assert plan[0].asked == ["0.125", "0.25", "0.25@1"] and plan[3].asked == ["1@0.5", "1@0.50"]
    assert [c.stem for c in plan] == ["spike-medicine-it200-s1", "spike-medicine-it200-s0.5", "spike-medicine-it400-s1",
                                      "spike-medicine-it1000-s0.5", "spike-medicine-it1000-s1"]
    assert [c.folder for c in plan][:2] == ["it200-s1", "it200-s0.5"]


def test_scales_read_as_compact_file_name_parts():
    assert [sweep.compact(Fraction(x)) for x in ("1", "0.5", "0.75", "0.125", "1/3", "0.1")] == [
        "1", "0.5", "0.75", "0.125", "0.3333333333333333", "0.1"]


def test_planning_errors_say_what_is_missing(world, tmp_path):
    with pytest.raises(SystemExit, match="no adapter folder"):
        sweep.plan(["0.5"], "medicine", tmp_path / "nothing", TOTAL)
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "adapters.safetensors").write_bytes(b"x")  # a final adapter alone is not a set of checkpoints
    with pytest.raises(SystemExit, match="has no <iteration>_adapters.safetensors checkpoints"):
        sweep.plan(["1@0.5"], "medicine", empty, TOTAL)
    (world.adapter / "adapters.safetensors").unlink()
    with pytest.raises(SystemExit, match="final adapter, but .*adapters.safetensors does not exist"):
        sweep.plan(["0.5", "1"], "medicine", world.adapter, TOTAL)
    assert sweep.plan(["0.5"], "medicine", world.adapter, TOTAL)[0].iteration == 400   # without asking for the final one


def test_the_final_adapter_of_a_run_that_did_not_finish_is_not_iteration_total(world):
    (world.runs / "run.json").write_text(json.dumps({"exit_code": 137, "git_commit": "abc", "counts": {"iters": TOTAL}}))
    assert sweep.load_run("medicine")["exit_code"] == 137
    assert sweep.plan(["0.5"], "medicine", world.adapter, TOTAL, finished=False)[0].iteration == 400   # checkpoints are
    with pytest.raises(SystemExit, match="run.json records a training run that did not finish"):
        sweep.plan(["1@0.5"], "medicine", world.adapter, TOTAL, finished=False)
    with pytest.raises(SystemExit, match="did not finish"):
        world.go("--candidate", "1@0.5")
    assert world.fake.calls == []


def test_a_checkpoint_older_than_the_recorded_run_is_refused(world):
    """medicine's folder held two aborted runs before the recorded one: a file they left must never be a candidate."""
    import os

    ckpt = world.adapter / "0000400_adapters.safetensors"
    started = ckpt.stat().st_mtime + 60
    with pytest.raises(SystemExit, match="written before the recorded run started"):
        sweep.plan(["0.5"], "medicine", world.adapter, TOTAL, started=started)
    os.utime(ckpt, (started + 1, started + 1))
    assert sweep.plan(["0.5"], "medicine", world.adapter, TOTAL, started=started)[0].iteration == 400
    record = json.loads((world.runs / "run.json").read_text(encoding="utf-8"))  # main() reads started_utc from run.json
    (world.runs / "run.json").write_text(json.dumps({**record, "started_utc": "2999-01-01T00:00:00Z"}))
    with pytest.raises(SystemExit, match="written before the recorded run started"):
        world.go()


def test_planned_iterations_come_from_the_run_record_or_mlx_lora_yaml(world):
    assert sweep.load_run("medicine") == {"git_commit": "abc1234", "iters": TOTAL, "exit_code": 0, "started_utc": None}
    (world.runs / "run.json").write_text(json.dumps({"git_commit": "d00d", "counts": {}}))
    with pytest.raises(SystemExit, match="cannot tell how many iterations"):
        sweep.load_run("medicine")
    data = world.root / "training" / "data" / "medicine"
    data.mkdir(parents=True)
    (data / "mlx_lora.yaml").write_text("iters: 777\n")
    assert sweep.load_run("medicine") == {"git_commit": "d00d", "iters": 777, "exit_code": None, "started_utc": None}
    (world.runs / "run.json").unlink()
    with pytest.raises(SystemExit, match="run.json not found"):
        sweep.load_run("medicine")


# ------------------------------------------------------------------------------------- scaled adapters
def test_the_scaled_adapter_folder_multiplies_the_scale_keeps_everything_else_and_links_the_checkpoint(world, tmp_path):
    original = (world.adapter / "adapter_config.json").read_text(encoding="utf-8")
    c = sweep.plan(["0.5@0.25"], "medicine", world.adapter, TOTAL)[0]
    dest = tmp_path / "mlx"
    sweep.write_scaled_adapter(c, world.adapter, dest)
    sweep.write_scaled_adapter(c, world.adapter, dest)  # again: a re-run replaces the link, no error
    config = json.loads((dest / "adapter_config.json").read_text(encoding="utf-8"))
    expected = json.loads(original)
    expected["lora_parameters"]["scale"] = SCALE * 0.25
    assert config == expected and config["lora_parameters"]["rank"] == RANK
    assert (dest / "adapters.safetensors").is_symlink()
    assert (dest / "adapters.safetensors").resolve() == (world.adapter / "0000400_adapters.safetensors").resolve()
    assert (world.adapter / "adapter_config.json").read_text(encoding="utf-8") == original   # the run's own config is not touched
    one = sweep.plan(["0.5"], "medicine", world.adapter, TOTAL)[0]
    sweep.write_scaled_adapter(one, world.adapter, tmp_path / "mlx1")
    assert json.loads((tmp_path / "mlx1" / "adapter_config.json").read_text(encoding="utf-8")) == json.loads(original)
    (world.adapter / "adapter_config.json").write_text(json.dumps({"lora_parameters": {"rank": 4}}))
    with pytest.raises(SystemExit, match="no lora_parameters.scale"):
        sweep.write_scaled_adapter(c, world.adapter, tmp_path / "mlx2")


@pytest.mark.parametrize("spec, factor", [("0.5", 1), ("0.5@0.5", 0.5), ("1@0.75", 0.75), ("0.25@0.125", 0.125)])
def test_the_peft_alpha_of_a_scaled_candidate_is_scale_times_candidate_scale_times_rank(world, tmp_path, spec, factor):
    c = sweep.plan([spec], "medicine", world.adapter, TOTAL)[0]
    sweep.write_scaled_adapter(c, world.adapter, tmp_path / "mlx")
    weights = read_safetensors(tmp_path / "mlx" / "adapters.safetensors")   # through the link
    config = json.loads((tmp_path / "mlx" / "adapter_config.json").read_text(encoding="utf-8"))
    tensors, peft = convert(weights, config, None)
    assert peft["r"] == RANK and peft["lora_alpha"] == pytest.approx(SCALE * factor * RANK)
    assert peft["lora_alpha"] / peft["r"] == pytest.approx(SCALE * factor)     # the multiplier PEFT and llama.cpp apply
    unscaled = convert(weights, json.loads((world.adapter / "adapter_config.json").read_text(encoding="utf-8")), None)[0]
    assert all(np.array_equal(tensors[k], unscaled[k]) for k in tensors)         # only alpha changes, not the weights


# --------------------------------------------------------------------------------------------- the rule
def test_the_rule_is_the_recipes_own_with_every_suite_renamed_to_select():
    cfg = yaml.safe_load((ROOT / "training" / "configs" / "medicine.yaml").read_text(encoding="utf-8"))
    suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]
    rule = sweep.select_rule(cfg["acceptance"], suites)
    assert rule == {"primary": {"suite": "medicine-select", "min_gain_points": 3.0, "max_p_value": 0.05},
                    "regression": {"suite": "general-select", "max_drop_points": 1.5}}
    assert sweep.rule_suites(rule) == ["medicine-select", "general-select"]
    assert sweep.rule_suites(cfg["acceptance"]) == ["medicine", "general"]
    assert cfg["acceptance"]["primary"]["suite"] == "medicine"   # the recipe itself is not edited
    gains = {v: {"suites": {"medicine-select": {"vs_base": {v: {"delta_points": d, "p_value": 0.01, "paired_n": 9}}},
                            "general-select": {"vs_base": {v: {"delta_points": g, "p_value": 0.5, "paired_n": 9}}}}}
             for v, d, g in (("a", 5.0, -1.4), ("b", 5.0, -1.6), ("c", 2.9, 0.0))}
    outcomes = {v: check_acceptance(s, rule, v)[0] for v, s in gains.items()}
    assert outcomes == {"a": True, "b": False, "c": False}   # -1.4 within the 1.5 limit, -1.6 not; +2.9 under the 3.0 gain
    # results of the acceptance suites do not stand in for the select suites
    acceptance_only = {"suites": {"medicine": {"vs_base": {"a": {"delta_points": 31.9, "p_value": 0.0}}},
                                  "general": {"vs_base": {"a": {"delta_points": 0.0, "p_value": 1.0}}}}}
    assert check_acceptance(acceptance_only, rule, "a") == (False, ["suite 'medicine-select' was not evaluated for a"])


def test_the_sweep_refuses_a_recipe_without_select_suites_or_without_an_exact_answer_rule():
    cfg = yaml.safe_load((ROOT / "training" / "configs" / "medicine.yaml").read_text(encoding="utf-8"))
    suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]
    with pytest.raises(SystemExit, match="no suite medicine-select, general-select"):
        sweep.select_rule(cfg["acceptance"], {k: v for k, v in suites.items() if not k.endswith("-select")})
    with pytest.raises(SystemExit, match="no suite general-select"):
        sweep.select_rule(cfg["acceptance"], {k: v for k, v in suites.items() if k != "general-select"})
    marketing = yaml.safe_load((ROOT / "training" / "configs" / "marketing.yaml").read_text(encoding="utf-8"))
    with pytest.raises(SystemExit, match="not judged by exact-answer suites"):
        sweep.select_rule(marketing["acceptance"], suites)
    assert sweep.select_rule({"primary": cfg["acceptance"]["primary"]}, suites)["primary"]["suite"] == "medicine-select"


def row(iteration, scale, delta, passes=True):
    return {"stem": f"it{iteration}-s{scale:g}", "iteration": iteration, "scale": scale, "passes": passes,
            "select": {"primary": {"delta_points": delta}}}


def test_the_chosen_candidate_passes_and_has_the_largest_gain_ties_to_the_earlier_and_weaker():
    rows = [row(200, 1, 6.0), row(400, 1, 9.0, passes=False), row(1000, 0.5, 7.5), row(600, 1, 7.0)]
    assert sweep.choose(rows)["stem"] == "it1000-s0.5"            # 9.0 fails the rule, so it is not a candidate to pick
    assert sweep.choose([row(800, 1, 5.0), row(400, 1, 5.0), row(600, 1, 5.0)])["stem"] == "it400-s1"
    assert sweep.choose([row(400, 1, 5.0), row(400, 0.5, 5.0), row(400, 0.75, 5.0)])["stem"] == "it400-s0.5"
    assert sweep.choose([row(400, 1, 9.0, passes=False), row(200, 1, 4.0, passes=False)]) is None
    assert sweep.choose([]) is None


# ----------------------------------------------------------------------------------- the whole sweep
def calls_of(w, script):
    return [c for c in w.fake.calls if Path(c[1]).name == script]


def test_a_sweep_exports_each_candidate_once_evaluates_them_together_and_runs_the_acceptance_suites_on_the_chosen(
        world, capsys):
    assert world.go() == 0
    assert world.fake.scripts() == ["export_adapter.py"] * 3 + ["run_eval.py"] * 2
    gguf = world.sweep / "gguf"
    stems = ["spike-medicine-it200-s1", "spike-medicine-it400-s1", "spike-medicine-it1000-s0.5"]   # 0.125 and 0.25 are one
    folders = ["it200-s1", "it400-s1", "it1000-s0.5"]
    for cmd, stem, folder in zip(calls_of(world, "export_adapter.py"), stems, folders, strict=True):
        assert cmd[0] == sys.executable and cmd[2] == "medicine"
        assert flag(cmd, "--llama-cpp") == str(world.llama) and flag(cmd, "--base") == "Qwen/Qwen3.5-4B"   # the recipe's
        assert flag(cmd, "--name") == stem and flag(cmd, "--out") == str(gguf)
        assert flag(cmd, "--work") == str(world.sweep / folder)
        assert flag(cmd, "--adapter") == str(world.sweep / folder / "mlx")
        assert "--python" not in cmd and "--check-model" not in cmd
        assert Path(flag(cmd, "--work")).is_relative_to(world.sweep)       # never the run's own export.json
        assert not Path(flag(cmd, "--out")).is_relative_to(Path.home() / ".spike")
    assert not (world.runs / "export.json").exists() and not (world.runs / "peft").exists()
    # what each export was given: the checkpoint, and the scale multiplied
    given = world.fake.exported
    assert given[stems[0]]["config"]["lora_parameters"] == {"rank": RANK, "scale": SCALE, "dropout": 0.05,
                                                            "keys": ["self_attn.q_proj"]}
    assert given[stems[2]]["config"]["lora_parameters"]["scale"] == SCALE * 0.5
    assert given[stems[1]]["weights"] == (world.adapter / "0000400_adapters.safetensors").resolve()
    assert given[stems[2]]["weights"] == (world.adapter / "adapters.safetensors").resolve()

    select, final = calls_of(world, "run_eval.py")
    assert select[0] == sys.executable and Path(select[1]).name == "run_eval.py"
    assert flag(select, "--suites") == "medicine-select,general-select" and flag(select, "--model") == str(world.model)
    assert flags(select, "--adapter") == [str(gguf / f"{s}.gguf") for s in stems]
    assert flag(select, "--max-tokens") == "2048" and flag(select, "--out") == str(world.sweep / "select")
    assert "--acceptance" not in select and "--resume" not in select
    assert flag(final, "--suites") == "medicine,general" and flag(final, "--model") == str(world.model)
    assert flags(final, "--adapter") == [str(gguf / f"{stems[2]}.gguf")]   # the chosen one alone
    assert flag(final, "--acceptance") == str(world.root / "training" / "configs" / "medicine.yaml")
    assert flag(final, "--max-tokens") == "2048" and flag(final, "--out") == str(world.sweep / "final")

    out = json.loads((world.sweep / "summary.json").read_text(encoding="utf-8"))
    assert out["specialist"] == "medicine" and out["recipe"] == "training/configs/medicine.yaml"
    assert out["run"] == {"git_commit": "abc1234", "iters": TOTAL, "started_utc": None} and out["exit_code"] == 0
    assert out["select"]["suites"] == ["medicine-select", "general-select"]
    assert out["select"]["rule"]["primary"]["suite"] == "medicine-select" and out["select"]["results"].endswith("sweep/select")
    assert out["chosen"] == stems[2]
    a, b, c = out["candidates"]
    assert (a["asked"], a["fraction"], a["iteration"], a["scale"], a["stem"]) == (["0.125", "0.25"], 0.125, 200, 1, stems[0])
    assert (c["asked"], c["fraction"], c["iteration"], c["scale"]) == (["1@0.5"], 1.0, 1000, 0.5)
    assert c["checkpoint"].endswith("adapters.safetensors") and c["gguf"].endswith(f"sweep/gguf/{stems[2]}.gguf")
    assert a["select"] == {"primary": {"suite": "medicine-select", "paired_n": 400, "delta_points": 6.0, "p_value": 0.001},
                           "regression": {"suite": "general-select", "paired_n": 400, "delta_points": -0.5, "p_value": 0.4}}
    assert [r["passes"] for r in out["candidates"]] == [True, False, True]   # it400 has the best gain but forgets
    assert b["select"]["primary"]["delta_points"] == 9.0 and "general-select: -3.00 pts (max drop 1.5)" in b["reasons"]
    assert c["reasons"] == ["medicine-select: +7.50 pts (need ≥ 3.0), p = 0.001 (need ≤ 0.05)",
                            "general-select: -1.00 pts (max drop 1.5)"]
    assert out["final"] == {"suites": ["medicine", "general"], "results": "training/runs/medicine/sweep/final",
                            "accepted": True, "exit_code": 0, "reused": False,
                            "reasons": ["medicine: +7.00 pts (need ≥ 3.0), p = 0.001 (need ≤ 0.05)",
                                        "general: -1.00 pts (max drop 1.5)"]}
    markdown = (world.sweep / "summary.md").read_text(encoding="utf-8")
    assert all(s in markdown for s in stems) and "ACCEPTED" in markdown and "Chosen: `" + stems[2] + "`" in markdown
    printed = capsys.readouterr().out
    assert (f"spike adapters install training/runs/medicine/sweep/gguf/{stems[2]}.gguf --specialist medicine "
            "--eval training/runs/medicine/sweep/final --config training/configs/medicine.yaml") in printed


def test_python_and_base_are_passed_to_the_export_when_given(world):
    assert world.go("--python", "/conv/bin/python", "--base", "/models/hf-qwen", "--candidate", "0.25", "--no-final") == 0
    cmd = calls_of(world, "export_adapter.py")[0]
    assert flag(cmd, "--python") == "/conv/bin/python" and flag(cmd, "--base") == "/models/hf-qwen"


def test_a_rejected_final_run_is_the_verdict_and_exits_2(world, capsys):
    world.fake.table["it1000-s0.5"]["general"] = (-4.0, 0.001)   # the acceptance sample disagrees with the select one
    assert world.go() == 2
    out = json.loads((world.sweep / "summary.json").read_text(encoding="utf-8"))
    assert out["chosen"] == "spike-medicine-it1000-s0.5" and out["exit_code"] == 2
    assert out["final"]["accepted"] is False and out["final"]["exit_code"] == 2
    assert out["final"]["reasons"][-1] == "general: -4.00 pts (max drop 1.5)"
    assert "REJECTED" in capsys.readouterr().out
    assert "REJECTED" in (world.sweep / "summary.md").read_text(encoding="utf-8")


def test_no_candidate_passing_the_select_rule_exits_2_without_running_the_acceptance_suites(world, capsys):
    world.fake.table["it200-s1"]["medicine-select"] = (2.9, 0.001)     # gain too small
    world.fake.table["it1000-s0.5"]["medicine-select"] = (7.5, 0.2)    # not significant
    assert world.go() == 2
    assert world.fake.scripts() == ["export_adapter.py"] * 3 + ["run_eval.py"]
    out = json.loads((world.sweep / "summary.json").read_text(encoding="utf-8"))
    assert out["chosen"] is None and out["final"] is None and out["exit_code"] == 2
    assert len(out["candidates"]) == 3 and not any(r["passes"] for r in out["candidates"])   # all are reported
    assert "no candidate passes" in capsys.readouterr().out
    assert "Chosen: none" in (world.sweep / "summary.md").read_text(encoding="utf-8")
    assert not (world.sweep / "final").exists()


def test_no_final_stops_after_choosing(world, capsys):
    assert world.go("--no-final") == 0
    assert world.fake.scripts() == ["export_adapter.py"] * 3 + ["run_eval.py"]
    out = json.loads((world.sweep / "summary.json").read_text(encoding="utf-8"))
    assert out["chosen"] == "spike-medicine-it1000-s0.5" and out["final"] is None and out["exit_code"] == 0
    assert "without --no-final" in capsys.readouterr().out


def test_candidates_given_on_the_command_line_replace_the_default(world):
    world.fake.table["it400-s0.75"] = {"medicine-select": (3.5, 0.01), "general-select": (0.0, 1.0)}
    world.fake.table["it600-s0.75"] = {"medicine-select": (4.0, 0.01), "general-select": (0.0, 1.0)}
    assert world.go("--candidate", "0.5@0.75", "--candidate", "0.65@0.75", "--no-final") == 0   # 0.65 -> 600, 0.5 -> 400
    out = json.loads((world.sweep / "summary.json").read_text(encoding="utf-8"))
    assert [r["stem"] for r in out["candidates"]] == ["spike-medicine-it400-s0.75", "spike-medicine-it600-s0.75"]


def test_a_finished_sweep_run_again_does_nothing_and_gives_the_same_summary(world):
    assert world.go() == 0
    first = (world.sweep / "summary.json").read_text(encoding="utf-8")
    world.fake.calls.clear()
    assert world.go() == 0
    assert world.fake.calls == []
    out = json.loads((world.sweep / "summary.json").read_text(encoding="utf-8"))
    assert out["final"]["reused"] is True and out["final"]["accepted"] is True and out["final"]["exit_code"] == 0
    assert {**out, "final": {**out["final"], "reused": False}} == json.loads(first)


def test_an_interrupted_sweep_does_only_what_is_missing(world):
    assert world.go() == 0
    world.fake.calls.clear()
    (world.sweep / "it400-s1" / "export.json").unlink()                # killed during this candidate's export
    (world.sweep / "gguf" / "spike-medicine-it1000-s0.5.gguf").unlink()  # and the GGUF of another one is gone
    assert world.go() == 0
    assert [flag(c, "--name") for c in calls_of(world, "export_adapter.py")] == [
        "spike-medicine-it400-s1", "spike-medicine-it1000-s0.5"]
    assert world.fake.scripts() == ["export_adapter.py"] * 2           # the same candidates: results are reused


def test_an_interrupted_select_evaluation_is_finished_with_resume(world):
    select = world.sweep / "select"
    select.mkdir(parents=True)
    (select / "predictions.jsonl").write_text("{}\n")                   # run_eval.py was killed: rows, no summary
    assert world.go("--no-final") == 0
    cmd = calls_of(world, "run_eval.py")[0]
    assert flag(cmd, "--resume") == str(select) and "--out" not in cmd
    assert flags(cmd, "--adapter") and flag(cmd, "--suites") == "medicine-select,general-select"


def test_more_candidates_than_a_finished_select_run_are_added_with_resume_fewer_are_refused(world):
    assert world.go("--candidate", "0.25", "--no-final") == 0           # it200 only
    world.fake.calls.clear()
    assert world.go("--candidate", "0.25", "--candidate", "0.5", "--no-final") == 0
    cmd = calls_of(world, "run_eval.py")[0]
    assert flag(cmd, "--resume") == str(world.sweep / "select") and len(flags(cmd, "--adapter")) == 2
    out = json.loads((world.sweep / "summary.json").read_text(encoding="utf-8"))
    assert [r["iteration"] for r in out["candidates"]] == [200, 400]
    with pytest.raises(SystemExit, match="spike-medicine-it400-s1, which this run does not ask for"):
        world.go("--candidate", "0.25", "--no-final")                  # it400 was tried: it must stay in the report
    assert json.loads((world.sweep / "select" / "summary.json").read_text(encoding="utf-8"))["variants"][1:] == [
        "spike-medicine-it200-s1", "spike-medicine-it400-s1"]


def test_the_acceptance_suites_run_once_a_second_choice_does_not_get_another_look(world):
    assert world.go() == 0
    assert len([c for c in world.fake.calls if "--acceptance" in c]) == 1
    world.fake.table["it400-s1"] = {"medicine-select": (30.0, 0.0001), "general-select": (0.0, 1.0)}   # now the best
    shutil.rmtree(world.sweep / "select")                                # a new selection would pick it400
    with pytest.raises(SystemExit, match="has results for spike-medicine-it1000-s0.5, which this run does not ask for"):
        world.go()
    assert len([c for c in world.fake.calls if "--acceptance" in c]) == 1   # no second look at the acceptance suites


def test_final_results_without_a_verdict_are_finished_with_resume(world):
    assert world.go() == 0
    final = world.sweep / "final"
    summary = json.loads((final / "summary.json").read_text(encoding="utf-8"))
    del summary["acceptance"]                                          # run without --acceptance
    (final / "summary.json").write_text(json.dumps(summary))
    world.fake.calls.clear()
    assert world.go() == 0
    cmd = calls_of(world, "run_eval.py")[0]
    assert flag(cmd, "--resume") == str(final) and flag(cmd, "--acceptance")


def test_a_failing_export_or_evaluation_stops_with_exit_1_and_says_so(world):
    world.fake.exit["export_adapter.py"] = 3
    with pytest.raises(SystemExit, match=r"exporting spike-medicine-it200-s1 failed \(exit 3\)"):
        world.go()
    assert world.fake.scripts() == ["export_adapter.py"]
    world.fake.exit.clear()
    world.fake.exit["run_eval.py"] = 1
    with pytest.raises(SystemExit, match=r"run_eval.py exited with 1 for training/runs/medicine/sweep/select"):
        world.go()
    world.fake.exit.clear()
    world.fake.exit["run_eval.py"] = 2       # exit 2 is a verdict only when --acceptance was given
    with pytest.raises(SystemExit, match="exited with 2"):
        world.go()


def test_missing_inputs_stop_before_any_work(world, tmp_path):
    with pytest.raises(SystemExit, match="base model not found"):
        sweep.main(["medicine", "--llama-cpp", str(world.llama), "--model", str(tmp_path / "nope.gguf")])
    with pytest.raises(SystemExit, match="no convert_lora_to_gguf.py"):
        sweep.main(["medicine", "--llama-cpp", str(tmp_path), "--model", str(world.model)])
    with pytest.raises(SystemExit, match="bad --candidate"):
        world.go("--candidate", "2")
    (world.root / "evals" / "suites.yaml").write_text(yaml.safe_dump({"suites": {}}))
    with pytest.raises(SystemExit, match="evals/suites.yaml has no suite medicine-select, general-select"):
        world.go()
    with pytest.raises(SystemExit, match="no recipe at"):
        sweep.main(["nothing", "--llama-cpp", str(world.llama), "--model", str(world.model)])
    assert world.fake.calls == []


# --------------------------------------------------------------------------------- export_adapter.py
def run_export(tmp_path, monkeypatch, *flags_):
    """export_adapter.main() with the converter subprocess and the GGUF check replaced; returns the repo root."""
    root = tmp_path / "repo"
    adapter = root / "training" / "runs" / "medicine" / "adapter"
    adapter.mkdir(parents=True, exist_ok=True)
    (adapter / "adapter_config.json").write_text(json.dumps({"lora_parameters": {"rank": RANK, "scale": SCALE}}))
    write_safetensors(adapter / "adapters.safetensors", adapter_weights(1))
    base = tmp_path / "hf-base"
    base.mkdir(exist_ok=True)
    (base / "model.safetensors.index.json").write_text(json.dumps(
        {"weight_map": {m.replace("language_model.model.", "model.language_model.", 1) + ".weight": "x.safetensors"
                        for m in MODULES}}))
    converted = []

    def fake_convert(cmd, check):
        converted.append(cmd)
        Path(cmd[cmd.index("--outfile") + 1]).write_bytes(b"GGUF")

    monkeypatch.setattr(export_adapter, "ROOT", root)
    monkeypatch.setattr(export_adapter.subprocess, "run", fake_convert)
    monkeypatch.setattr(export_adapter, "check_gguf",
                        lambda path, peft: {"arch": "qwen35", "tensors": 4, "alpha": peft["lora_alpha"], "bytes": 4})
    monkeypatch.setattr(sys, "argv", ["export_adapter.py", "medicine", "--llama-cpp", "/llama", "--base", str(base),
                                      "--out", str(tmp_path / "out"), *flags_])
    assert export_adapter.main() == 0
    return root, converted[0]


def test_export_adapter_writes_the_runs_own_files_unless_told_otherwise(tmp_path, monkeypatch):
    root, cmd = run_export(tmp_path, monkeypatch)
    run_dir = root / "training" / "runs" / "medicine"
    assert (tmp_path / "out" / "spike-medicine.gguf").is_file()          # spike-<specialist>.gguf, as before
    assert (run_dir / "peft" / "adapter_model.safetensors").is_file() and (run_dir / "peft" / "adapter_config.json").is_file()
    report = json.loads((run_dir / "export.json").read_text(encoding="utf-8"))
    assert report["gguf"] == str(tmp_path / "out" / "spike-medicine.gguf") and report["peft"]["lora_alpha"] == SCALE * RANK
    assert cmd[cmd.index("--outfile") + 1] == str(tmp_path / "out" / "spike-medicine.gguf")
    assert cmd[2] == str(run_dir / "peft")


def test_export_adapter_name_and_work_move_the_gguf_peft_and_export_json(tmp_path, monkeypatch):
    work = tmp_path / "sweep" / "it400-s0.5"
    root, cmd = run_export(tmp_path, monkeypatch, "--name", "spike-medicine-it400-s0.5", "--work", str(work))
    run_dir = root / "training" / "runs" / "medicine"
    assert (tmp_path / "out" / "spike-medicine-it400-s0.5.gguf").is_file()
    assert not (tmp_path / "out" / "spike-medicine.gguf").exists()
    assert cmd[2] == str(work / "peft") and (work / "peft" / "adapter_model.safetensors").is_file()
    assert json.loads((work / "export.json").read_text(encoding="utf-8"))["gguf"] == str(tmp_path / "out" / "spike-medicine-it400-s0.5.gguf")
    assert not (run_dir / "export.json").exists() and not (run_dir / "peft").exists()   # the run's own record is untouched
    # --work does not move where the default adapter is read from: this one came from training/runs/medicine/adapter
    assert json.loads((work / "peft" / "adapter_config.json").read_text(encoding="utf-8"))["r"] == RANK


def test_export_adapter_name_is_a_stem_not_a_path(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        run_export(tmp_path, monkeypatch, "--name", "../elsewhere/x")


# ------------------------------------------------------------------------------ the real converter
@pytest.mark.skipif(not (LLAMA_CPP and CONVERT_PY), reason="SPIKE_LLAMA_CPP / SPIKE_CONVERT_PYTHON not set")
def test_a_scaled_candidate_converts_with_llama_cpp_and_the_gguf_carries_the_scaled_alpha(tmp_path):
    """The sweep's own scaled adapter folder through export_adapter.py and convert_lora_to_gguf.py: the GGUF's alpha is
    scale x SCALE x rank (llama.cpp applies alpha / rank), the weights are the checkpoint's."""
    pytest.importorskip("gguf", reason="llama.cpp's gguf package builds the tiny model config")
    from spike.runtime.gguf import read_gguf
    from tests.fixtures import make_tiny_gguf as tiny

    hf_base = tmp_path / "hf-base"
    hf_base.mkdir()
    (hf_base / "config.json").write_text(json.dumps(tiny.hf_config()))
    modules = {"self_attn.q_proj": (tiny.N_EMBD, tiny.N_EMBD), "mlp.up_proj": (tiny.N_EMBD, tiny.N_FF)}
    base_weights = {f"model.layers.{i}.{m}.weight": np.zeros((d_out, d_in), np.float32)   # the converter indexes the files
                    for i in range(tiny.N_LAYER) for m, (d_in, d_out) in modules.items()}
    write_safetensors(hf_base / "model.safetensors", base_weights)
    rng = np.random.default_rng(3)
    weights = {f"model.layers.{i}.{m}.{ab}": (rng.standard_normal((d_in, RANK) if ab == "lora_a" else (RANK, d_out)) * 0.3
                                              ).astype(np.float32)
               for i in range(tiny.N_LAYER) for m, (d_in, d_out) in modules.items() for ab in ("lora_a", "lora_b")}
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    write_safetensors(adapter / "0000400_adapters.safetensors", weights)
    (adapter / "adapter_config.json").write_text(json.dumps(
        {"fine_tune_type": "lora", "lora_parameters": {"rank": RANK, "scale": SCALE, "dropout": 0.0, "keys": sorted(modules)}}))
    for spec, factor in (("0.5", 1.0), ("0.5@0.5", 0.5)):
        c = sweep.plan([spec], "test", adapter, 800)[0]
        work = tmp_path / "sweep" / c.folder
        sweep.write_scaled_adapter(c, adapter, work / "mlx")
        proc = subprocess.run([sys.executable, str(ROOT / "training" / "export_adapter.py"), "test", "--llama-cpp", LLAMA_CPP,
                               "--adapter", str(work / "mlx"), "--base", str(hf_base), "--out", str(tmp_path / "gguf"),
                               "--name", c.stem, "--work", str(work), "--python", CONVERT_PY, "--outtype", "f32"],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-3000:]
        meta = read_gguf(tmp_path / "gguf" / f"{c.stem}.gguf").metadata
        assert meta["general.type"] == "adapter" and meta["adapter.lora.alpha"] == pytest.approx(SCALE * factor * RANK)
        assert json.loads((work / "export.json").read_text(encoding="utf-8"))["check"]["alpha"] == pytest.approx(SCALE * factor * RANK)
