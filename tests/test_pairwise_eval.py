"""evals/pairwise.py without a model: answers and judgments are kept as they finish, a run continues where it stopped,
the judge is needed only after every answer exists, and several adapters are compared on the same base answers.

llama-server and the judge are replaced: the base model's answers say "plain", an adapter's say "good" (or "plain"
for an adapter that learned nothing), and the judge prefers the answer that says "good" whatever its position.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "training"))

import pairwise  # noqa: E402

PROMPTS = [{"id": f"mk-{i}", "prompt": f"Plan a campaign for shop {i}"} for i in range(6)]


class World:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.prompts = tmp_path / "prompts.jsonl"
        self.prompts.write_text("".join(json.dumps(p) + "\n" for p in PROMPTS))
        self.model = tmp_path / "base.gguf"
        self.model.write_bytes(b"GGUF base")
        self.adapters = {}
        for name, body in (("spike-marketing-good", b"GGUF good"), ("spike-marketing-same", b"GGUF same")):
            (tmp_path / f"{name}.gguf").write_bytes(body)
            self.adapters[name] = tmp_path / f"{name}.gguf"
        self.out = tmp_path / "out"
        self.generated: list[tuple[str, str]] = []
        self.judged: list[str] = []
        self.judge_up = True
        self.fail_after: int | None = None   # generation dies after this many answers (an interruption)
        world = self

        async def generate_with_server(args, system, adapters, prompts, variants, file):
            async def generate(prompt, variant):
                if world.fail_after is not None and len(world.generated) >= world.fail_after:
                    raise RuntimeError("killed")
                world.generated.append((variant, prompt["id"]))
                word = "plain" if variant in ("base", "spike-marketing-same") else "good"
                return {"content": f"{word} answer to {prompt['id']}", "finish_reason": "stop"}

            return await pairwise.answer_missing(prompts, variants, file, generate)

        class Judge:
            def __init__(self, url, model, concurrency=2):
                pass

            async def chat(self, messages, **kwargs):
                text = messages[1]["content"]
                a = text.split("ANSWER A:\n")[1].split("\n\nANSWER B:")[0]
                b = text.split("ANSWER B:\n")[1]
                world.judged.append(text.split("REQUEST:\n")[1].split("\n")[0])
                better = "A" if "good" in a and "good" not in b else "B" if "good" in b and "good" not in a else "tie"
                return json.dumps({"better": better, "reason": "x"}), ""

            async def aclose(self):
                pass

        async def reachable(url):
            return world.judge_up

        monkeypatch.setattr(pairwise, "generate_with_server", generate_with_server)
        monkeypatch.setattr(pairwise, "Teacher", Judge)
        monkeypatch.setattr(pairwise, "reachable", reachable)

    def go(self, *adapters: str, extra: tuple[str, ...] = ()) -> int:
        argv = ["--specialist", "marketing", "--prompts", str(self.prompts), "--model", str(self.model),
                "--out", str(self.out), *extra]
        for name in adapters or ("spike-marketing-good",):
            argv += ["--adapter", str(self.adapters[name])]
        return pairwise.main(argv)

    def rows(self, name: str) -> list[dict]:
        return [json.loads(line) for line in (self.out / name).read_text().splitlines()]


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def test_both_orders_must_agree_for_a_win_or_a_loss():
    assert pairwise.verdict_of("B", "A") == "win" and pairwise.verdict_of("A", "B") == "loss"
    assert {pairwise.verdict_of(*o) for o in (("B", "B"), ("A", "A"), ("TIE", "A"), ("B", "TIE"))} == {"tie"}


def test_one_adapter_gives_the_summary_install_reads(world, capsys):
    assert world.go() == 0
    summary = json.loads((world.out / "summary.json").read_text())
    assert summary["adapter"] == "spike-marketing-good" and summary["n"] == 6 and summary["wins"] == 6
    assert summary["win_rate"] == 1.0 and "adapters" not in summary and summary["prompts"] == str(world.prompts)
    pairs = world.rows("pairs.jsonl")
    assert [p["verdict"] for p in pairs] == ["win"] * 6 and pairs[0]["judge_orders"] == ["B", "A"]
    assert pairs[0]["base"] == "plain answer to mk-0" and pairs[0]["adapter"] == "good answer to mk-0"
    assert len(world.judged) == 12                                      # every prompt in both orders


def test_without_the_judge_the_answers_are_kept_and_the_run_continues_where_it_stopped(world, capsys):
    world.judge_up = False
    assert world.go() == pairwise.WAITING_FOR_JUDGE == 3
    assert len(world.rows("answers.jsonl")) == 12 and not (world.out / "judgments.jsonl").exists()
    assert "Start it (mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit" in capsys.readouterr().out
    world.judge_up, world.generated = True, []
    assert world.go() == 0
    assert world.generated == []                                       # no answer made twice
    world.judged.clear()
    assert world.go() == 0 and world.judged == []                       # finished: nothing to redo, no judge needed


def test_an_interrupted_generation_keeps_what_finished_and_a_cut_line_is_redone(world):
    world.fail_after = 5
    with pytest.raises(RuntimeError, match="killed"):
        world.go()
    kept = world.rows("answers.jsonl")
    assert len(kept) == 5
    with (world.out / "answers.jsonl").open("a") as f:
        f.write('{"variant": "base", "id": "mk-')                       # killed mid-line
    world.fail_after, world.generated = None, []
    assert world.go() == 0
    assert len(world.generated) == 7                                   # 12 - 5
    lines = (world.out / "answers.jsonl").read_text().splitlines()
    assert len(lines) == 12 and [json.loads(line) for line in lines[:5]] == kept   # the cut line is gone


def test_several_adapters_share_the_base_answers_and_each_is_judged(world):
    assert world.go("spike-marketing-good", "spike-marketing-same") == 0
    assert sum(1 for v, _ in world.generated if v == "base") == 6       # once, not once per adapter
    summary = json.loads((world.out / "summary.json").read_text())
    assert set(summary["adapters"]) == {"spike-marketing-good", "spike-marketing-same"}
    assert summary["adapters"]["spike-marketing-good"]["win_rate"] == 1.0
    assert summary["adapters"]["spike-marketing-same"] == {**summary["adapters"]["spike-marketing-same"], "ties": 6,
                                                           "win_rate": 0.5}
    assert "adapter" not in summary and "win_rate" not in summary       # not installable: one verdict per adapter
    assert {p["variant"] for p in world.rows("pairs.jsonl")} == {"spike-marketing-good", "spike-marketing-same"}


def test_adapters_can_be_added_to_a_run_but_not_dropped_or_changed_and_other_inputs_are_refused(world):
    assert world.go("spike-marketing-good") == 0
    world.generated.clear()
    assert world.go("spike-marketing-good", "spike-marketing-same") == 0
    assert {v for v, _ in world.generated} == {"spike-marketing-same"}  # only the new adapter answers
    with pytest.raises(SystemExit, match="has results for spike-marketing-same, which this run does not ask for"):
        world.go("spike-marketing-good")
    world.adapters["spike-marketing-same"].write_bytes(b"GGUF retrained")
    with pytest.raises(SystemExit, match="the adapter spike-marketing-same changed"):
        world.go("spike-marketing-good", "spike-marketing-same")
    with pytest.raises(SystemExit, match=r"other inputs \(max_tokens\)"):
        world.go("spike-marketing-good", extra=("--max-tokens", "64"))
    world.prompts.write_text(world.prompts.read_text() + json.dumps({"id": "mk-9", "prompt": "One more"}) + "\n")
    with pytest.raises(SystemExit, match=r"other inputs \(prompts_sha256\)"):
        world.go("spike-marketing-good")


def test_the_acceptance_verdict_needs_one_adapter_and_the_general_suite(world, tmp_path):
    recipe = ROOT / "training" / "configs" / "marketing.yaml"
    with pytest.raises(SystemExit):
        world.go("spike-marketing-good", "spike-marketing-same", extra=("--acceptance", str(recipe)))
    with pytest.raises(SystemExit, match="pass --general-eval"):
        world.go(extra=("--acceptance", str(recipe)))
    general = tmp_path / "general"
    general.mkdir()
    (general / "summary.json").write_text(json.dumps({"variants": ["base", "spike-marketing-good"], "suites": {
        "general": {"vs_base": {"spike-marketing-good": {"paired_n": 400, "delta_points": -2.0, "p_value": 0.1}}}}}))
    assert world.go(extra=("--acceptance", str(recipe), "--general-eval", str(general))) == 2   # forgets too much
    summary = json.loads((world.out / "summary.json").read_text())
    assert summary["accepted"] is False and summary["reasons"][-1] == "general: -2.00 pts (max drop 1.5)"
    assert yaml.safe_load(recipe.read_text())["acceptance"]["primary"]["min_win_rate"] == 0.6


def test_prompts_need_text_and_distinct_ids(tmp_path):
    bad = tmp_path / "p.jsonl"
    bad.write_text(json.dumps({"id": "a", "prompt": "x"}) + "\n" + json.dumps({"id": "a", "prompt": "y"}) + "\n")
    with pytest.raises(SystemExit, match="id 'a' is used twice"):
        pairwise.load_prompts(bad)
    bad.write_text(json.dumps({"id": "a"}) + "\n")
    with pytest.raises(SystemExit, match="has no prompt"):
        pairwise.load_prompts(bad)
    bad.write_text(json.dumps({"prompt": "no id"}) + "\n")
    assert pairwise.load_prompts(bad) == [{"prompt": "no id", "id": "line-1"}]


def test_judgments_are_kept_as_they_finish(world, monkeypatch):
    calls = 0
    original = pairwise.judge

    async def flaky(teacher, domain, prompt, a, b):
        nonlocal calls
        calls += 1
        if calls > 5:
            raise RuntimeError("judge died")
        return await original(teacher, domain, prompt, a, b)

    monkeypatch.setattr(pairwise, "judge", flaky)
    with pytest.raises(RuntimeError, match="judge died"):
        world.go()
    done = world.rows("judgments.jsonl")
    assert 1 <= len(done) <= 2 and all(len(r["judge_orders"]) == 2 for r in done)   # whole prompts only
    monkeypatch.setattr(pairwise, "judge", original)
    world.judged.clear()
    assert world.go() == 0
    assert len(world.judged) == 2 * (6 - len(done))


def test_the_judge_is_reached_at_its_models_endpoint():
    assert asyncio.run(pairwise.reachable("http://127.0.0.1:9/v1")) is False   # nothing listens on port 9
