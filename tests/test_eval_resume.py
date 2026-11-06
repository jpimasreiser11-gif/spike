"""Run the evaluation loop with fixed items and a stand-in server; no weights or network."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import run_eval as ev  # noqa: E402
from spike_train.evaluation import Item  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    (tmp_path / "training").mkdir()
    (tmp_path / "evals").mkdir()
    (tmp_path / "training/datasets.yaml").write_text("sources: {}\n")
    (tmp_path / "evals/suites.yaml").write_text(
        "suites:\n  tiny:\n    specialist: core\n    tasks:\n      - name: quiz\n")
    model = tmp_path / "base.gguf"
    model.write_bytes(b"base")
    w = SimpleNamespace(root=tmp_path, calls=[], servers=[], adapters={}, served=None, fail=False,
                        start_fail=False, system="Solve the question",
                        items=[Item("q1", "quiz", "Choose A", "mcq", "A", 2)])

    class Server:
        def __init__(self, config):
            self.base_url = "http://test"
            w.adapters = {p.stem: {} for p in config.adapters}
        async def start(self):
            w.servers.append("start")
            if w.start_fail:
                raise RuntimeError("startup interrupted")
        async def stop(self):
            w.servers.append("stop")

    class Client:
        def __init__(self, *args, **kwargs):
            self.http = self
        async def adapters(self):
            return w.served if w.served is not None else w.adapters
        def lora(self, name):
            return name
        async def get(self, *args):
            return SimpleNamespace(json=lambda: {"build_info": "test-build"})
        async def chat(self, system, prompt, lora, max_tokens, seed):
            w.calls.append(lora or "base")
            if w.fail:
                raise RuntimeError("interrupted")
            return {"content": "A", "finish_reason": "stop"}
        async def aclose(self):
            pass

    monkeypatch.setattr(ev, "ROOT", tmp_path)
    monkeypatch.setattr(ev, "Client", Client)
    monkeypatch.setattr(ev, "load_items", lambda *args: w.items)
    monkeypatch.setattr("spike.runtime.llamacpp_server.LlamaServer", Server)
    monkeypatch.setattr("spike.specialists.catalog.load_catalog",
                        lambda: SimpleNamespace(get=lambda _: SimpleNamespace(system_prompt=w.system)))
    w.args = SimpleNamespace(suites="tiny", model=str(model), adapter=[], server_url=None, acceptance=None,
                             limit=None, max_tokens=32, parallel=1, ctx_per_slot=256, ngl=0, threads=1,
                             kv_cache_type="q8_0", seed=0, out=str(tmp_path / "results"), resume=None)
    w.go = lambda: asyncio.run(ev.run(w.args))
    w.out = Path(w.args.out)
    return w


@pytest.mark.parametrize("change", ["model", "seed", "max_tokens", "system", "prompt", "gold", "suites", "legacy"])
def test_resume_refuses_changed_identity_before_starting_or_rewriting(world, change):
    assert world.go() == 0
    original = (world.out / "predictions.jsonl").read_bytes()
    if change == "model":
        Path(world.args.model).write_bytes(b"different weights")
    elif change in ("seed", "max_tokens"):
        setattr(world.args, change, getattr(world.args, change) + 1)
    elif change == "system":
        world.system = "Different specialist instructions"
    elif change in ("prompt", "gold"):
        setattr(world.items[0], change, "B")
    elif change == "suites":
        with (world.root / "evals/suites.yaml").open("a") as f:
            f.write("# changed\n")
    else:
        (world.out / "inputs.json").unlink(missing_ok=True)
    world.calls.clear()
    world.servers.clear()
    world.args.resume = world.args.out
    with pytest.raises(SystemExit, match="provenance"):
        world.go()
    assert not world.calls and not world.servers
    assert (world.out / "predictions.jsonl").read_bytes() == original


def test_resume_reuses_base_and_adds_a_new_adapter_without_losing_rows_on_failure(world):
    assert world.go() == 0
    original = (world.out / "predictions.jsonl").read_bytes()
    adapter = world.root / "specialist.gguf"
    adapter.write_bytes(b"adapter")
    world.args.adapter.append(str(adapter))
    world.args.resume = world.args.out
    world.calls.clear()
    world.fail = True
    with pytest.raises(RuntimeError, match="interrupted"):
        world.go()
    assert (world.out / "predictions.jsonl").read_bytes() == original
    world.fail = False
    world.calls.clear()
    assert world.go() == 0
    assert world.calls == ["specialist"]
    assert json.loads((world.out / "summary.json").read_text())["variants"] == ["base", "specialist"]
    adapter.write_bytes(b"replaced")
    with pytest.raises(SystemExit, match="provenance"):
        world.go()


def test_fresh_out_refuses_to_overwrite_existing_predictions(world):
    assert world.go() == 0
    world.calls.clear()
    with pytest.raises(SystemExit, match="--resume"):
        world.go()
    assert not world.calls


def test_external_server_cannot_resume_unverifiable_weights(world):
    world.args.server_url = "http://test"
    assert world.go() == 0
    world.args.resume = world.args.out
    with pytest.raises(SystemExit, match="provenance.*server"):
        world.go()


def test_server_failure_stops_the_server_and_can_resume_before_any_answers(world):
    world.start_fail = True
    with pytest.raises(RuntimeError, match="startup interrupted"):
        world.go()
    assert world.servers == ["start", "stop"]
    world.start_fail = False
    world.args.resume = world.args.out
    assert world.go() == 0


def test_server_must_actually_load_the_requested_adapters(world):
    adapter = world.root / "specialist.gguf"
    adapter.write_bytes(b"adapter")
    world.args.adapter = [str(adapter)]
    world.served = {}
    with pytest.raises(SystemExit, match="provenance.*adapters"):
        world.go()
    assert not world.calls and world.servers == ["start", "stop"]


def test_acceptance_without_any_adapter_cannot_succeed(world):
    recipe = world.root / "acceptance.yaml"
    recipe.write_text("acceptance:\n  primary:\n    suite: tiny\n    min_gain_points: 3\n")
    world.args.acceptance = str(recipe)
    with pytest.raises(SystemExit, match="acceptance.*adapter"):
        world.go()
    assert not world.calls
