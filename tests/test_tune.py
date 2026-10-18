"""`spike tune`: candidates, context choice, saving the result, and a real run on the tiny model."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.runtime.hardware import HardwareInfo
from spike.runtime.llamacpp_server import find_binary
from spike.server.app import create_app
from spike.server.state import AppState
from spike.tune import pick_context, thread_candidates, tune


def hw(cores=8, logical=16, ram=16.0, apple=False) -> HardwareInfo:
    return HardwareInfo(os="Linux", arch="x86_64", cpu_model="test", physical_cores=cores, logical_cores=logical,
                        total_ram_gb=ram, available_ram_gb=ram / 2, apple_silicon=apple, cpu_flags=["avx2"])


@pytest.fixture(scope="module")
def tiny(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("tiny")
    subprocess.run([sys.executable, "tests/fixtures/make_tiny_gguf.py", str(out)], check=True, capture_output=True)
    return out / "spike-tiny.gguf"


def test_thread_candidates():
    assert thread_candidates(hw(8, 16)) == [16, 8, 7, 4]
    assert thread_candidates(hw(4, 4)) == [4, 3, 2]
    assert thread_candidates(hw(1, 1)) == [1]


def test_context_is_the_largest_that_fits_the_ram_share(monkeypatch, tiny):
    import spike.tune as t

    assert pick_context(tiny, "q8_0", hw(ram=16))["context"] == 2048  # never past the model's trained context
    # Qwen3.5-4B Q4_K_M: 2.74 GB file, ≈17 KiB of q8_0 KV cache per token (docs/STATUS.md, computed)
    info = type("Info", (), {"file_size": int(2.74 * 1024**3), "field": lambda self, k, d=None:
                             262144 if k == "context_length" else d})()
    monkeypatch.setattr(t, "read_gguf", lambda path: info)
    monkeypatch.setattr(t, "kv_cache_bytes", lambda i, ctx, kind: ctx * 17 * 1024 * (2 if kind == "f16" else 1))
    big = pick_context(tiny, "q8_0", hw(ram=16))
    assert big["context"] == 65536 and big["measured"] is False and big["estimated_gb"] <= big["budget_gb"] == 6.4
    assert pick_context(tiny, "q8_0", hw(ram=8))["context"] == 8192  # nothing fits 3.2 GB: the smallest


async def fake_tuner(model, quick=False):
    yield {"type": "tune_start", "threads": [4, 2], "gpu_layers": 0, "prompt": 256, "gen": 32}
    yield {"type": "tune_result", "threads": 4, "kv_cache_type": "q8_0", "gen_tok_s": 9.0, "prompt_tok_s": 80.0,
           "peak_rss_mb": 3000.0, "gpu_layers": 0}
    best = {"threads": 4, "kv_cache_type": "q8_0", "gpu_layers": 0, "context": 32768}
    yield {"type": "tune_done", "best": best, "report": {"best": best, "model": str(model), "results": []}}


@pytest.fixture
def env(tmp_path, monkeypatch, tiny):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    state = AppState(home=tmp_path)
    app = create_app(state)
    return TestClient(app), state, app


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_tune_saves_the_best_settings_and_the_report(env, tiny):
    client, state, app = env
    assert client.post("/api/tune", json={}).status_code == 400  # no local model yet
    client.put("/api/settings", json={"local_runtime": {**state.settings()["local_runtime"], "model": str(tiny)}})
    app.state.tuner = fake_tuner
    evs = events_of(client.post("/api/tune", json={"quick": True}))
    assert [e["type"] for e in evs] == ["tune_start", "tune_result", "tune_done"] and evs[-1]["applied"]
    rt = client.get("/api/settings").json()["local_runtime"]
    assert (rt["threads"], rt["kv_cache_type"], rt["context"], rt["model"]) == (4, "q8_0", 32768, str(tiny))
    assert client.get("/api/tune").json()["best"]["threads"] == 4


async def test_only_one_tuning_run_at_a_time(env, tiny):
    _, state, _ = env
    state.update_settings({"local_runtime": {**state.settings()["local_runtime"], "model": str(tiny)}})
    async with state._tuning:
        with pytest.raises(RuntimeError):
            await state.run_tune(tuner=fake_tuner).__anext__()


@pytest.mark.skipif(find_binary() is None, reason="llama-server not installed")
async def test_real_tuning_run_on_the_tiny_model(tiny):
    """Exercises the whole path against llama-server; the tiny model's speeds mean nothing."""
    events = [ev async for ev in tune(tiny, quick=True, hw=hw(cores=2, logical=2, ram=8), threads=[2, 1])]
    results = [e for e in events if e["type"] == "tune_result"]
    # its 16-wide attention heads cannot use a q8_0 cache: the run notes the failure and measures f16 instead
    assert [(r["threads"], r["kv_cache_type"]) for r in results] == [(2, "f16"), (1, "f16")]
    assert all(r["gen_tok_s"] > 0 and r["peak_rss_mb"] > 0 and not r.get("failed") for r in results)
    done = events[-1]
    assert done["type"] == "tune_done" and done["best"]["threads"] in (1, 2) and done["best"]["kv_cache_type"] == "f16"
    report = done["report"]
    assert report["context"]["measured"] is False and len(report["results"]) == 2
    assert report["failures"][0]["kv_cache_type"] == "q8_0" and "llama-server" in report["failures"][0]["error"]
