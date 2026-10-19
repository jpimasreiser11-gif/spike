"""Exact resume of LoRA training (training/spike_train/resume.py) with real mlx and mlx-lm on a tiny random model.

No model or tokenizer is downloaded: the model is built in memory and the dataset holds token ids."""

import json
import shutil
import sys
from itertools import islice
from pathlib import Path
from types import SimpleNamespace

import pytest

mx = pytest.importorskip("mlx.core")
pytest.importorskip("mlx_lm")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

import lora as spike_lora  # noqa: E402  (training/lora.py)
import mlx.optimizers as optim  # noqa: E402
import yaml  # noqa: E402
from mlx.utils import tree_flatten  # noqa: E402
from mlx_lm import lora as mlx_lora  # noqa: E402
from mlx_lm.models import llama  # noqa: E402
from mlx_lm.tuner.datasets import CacheDataset  # noqa: E402
from mlx_lm.tuner.trainer import TrainingArgs  # noqa: E402
from mlx_lm.tuner.utils import build_schedule, linear_to_lora_layers  # noqa: E402
from spike_train import gated_delta_chunked, resume  # noqa: E402

N, ACCUM, SAVE_EVERY, PER_EPOCH = 12, 2, 4, 5   # checkpoints at 4, 8, 12; epochs end at 5 and 10


class Crash(Exception):
    pass


@pytest.fixture(autouse=True)
def cpu_device():
    """Reductions on a GPU may differ in the last bits from run to run; on the CPU these runs are bit-for-bit repeatable."""
    previous = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(previous)


class Rows:
    """What mlx_lm's CacheDataset wraps: raw rows to look at, `process` to make (token ids, prompt offset)."""

    def __init__(self, n):
        self.rows = [[i + 1] * (3 + 2 * i) + [40 + i] for i in range(n)]   # example i is recognisable by its tokens

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]

    def process(self, row):
        return row, 0


def tiny_model(lora_seed=0):
    mx.random.seed(0)   # the base model is the same in every run
    model = llama.Model(llama.ModelArgs(
        model_type="llama", hidden_size=32, num_hidden_layers=2, intermediate_size=64, num_attention_heads=4,
        num_key_value_heads=2, rms_norm_eps=1e-5, vocab_size=64, tie_word_embeddings=True))
    model.freeze()
    mx.random.seed(lora_seed)
    linear_to_lora_layers(model, 2, {"rank": 4, "scale": 2.0, "dropout": 0.1})   # dropout draws from mx.random
    return model


def optimizer():
    return optim.Adam(learning_rate=build_schedule({"name": "cosine_decay", "warmup": 2, "arguments": [1e-2, 6, 1e-4]}))


def paths(tmp_path):
    """A data dir with a train.jsonl and a config file, created once per test."""
    data, cfg = tmp_path / "data", tmp_path / "mlx.yaml"
    if not data.exists():
        data.mkdir()
        (data / "train.jsonl").write_text('{"text": "a"}\n{"text": "b"}\n', encoding="utf-8")
        cfg.write_text("iters: 12\n", encoding="utf-8")
    return data, cfg


def run_args(tmp_path, adapter):
    data, cfg = paths(tmp_path)
    return SimpleNamespace(adapter_path=str(adapter), seed=0, data=str(data), config=str(cfg), batch_size=1,
                           grad_accumulation_steps=ACCUM, iters=N)


def training(adapter, run, lora_seed=0, iters=N, callback=None):
    model, opt = tiny_model(lora_seed), optimizer()
    args = TrainingArgs(batch_size=1, iters=iters, val_batches=2, steps_per_report=3, steps_per_eval=6,
                        steps_per_save=SAVE_EVERY, adapter_file=adapter / "adapters.safetensors", max_seq_length=64,
                        grad_accumulation_steps=ACCUM)
    adapter.mkdir(parents=True, exist_ok=True)
    try:
        resume.train(model, opt, CacheDataset(Rows(PER_EPOCH)), CacheDataset(Rows(4)), args, training_callback=callback, run=run)
    finally:
        mx.eval(model.parameters())
    return model, opt


class CrashAt:
    def __init__(self, iteration):
        self.iteration = iteration

    def on_train_loss_report(self, info):
        if info["iteration"] == self.iteration:
            raise Crash

    def on_val_loss_report(self, info):
        pass


def same(a, b, what):
    a, b = dict(tree_flatten(a)), dict(tree_flatten(b))
    assert a.keys() == b.keys() and a, what
    for k in a:
        assert a[k].dtype == b[k].dtype and a[k].shape == b[k].shape, k
        assert mx.allclose(a[k], b[k], rtol=1e-5, atol=1e-7).item(), (what, k)


def differs(a, b):
    a, b = dict(tree_flatten(a)), dict(tree_flatten(b))
    return any(not mx.allclose(a[k], b[k], rtol=1e-5, atol=1e-7).item() for k in a)


def interrupted(tmp_path, adapter, crash_at=9):
    """A run that dies after iteration `crash_at` (past the iteration-8 checkpoint)."""
    with pytest.raises(Crash):
        training(adapter, resume.Run(run_args(tmp_path, adapter), resume=False), callback=CrashAt(crash_at))
    return adapter


def test_installed_mlx_lm_is_the_one_resume_py_copies():
    resume.check_mlx_lm()   # fails when mlx-lm's trainer changed: pip install mlx-lm==<resume.TESTED_MLX_LM>


def test_another_mlx_lm_stops_a_resume_but_a_fresh_run_falls_back_to_the_stock_loop(monkeypatch, capsys):
    monkeypatch.setattr(resume, "fingerprint", lambda: "0" * 64)
    monkeypatch.setattr(resume.lora, "train_model", resume.lora.train_model)   # restored after the test
    with pytest.raises(SystemExit, match="different trainer"):
        resume.install(True)
    before = resume.lora.train_model
    resume.install(False)
    assert resume.lora.train_model is before and "without resume checkpoints" in capsys.readouterr().err


def test_checkpoints_fall_on_optimizer_update_boundaries():
    # prepare.py's real shape: save_every 200 with 16 micro-batches per update; 200 and 600 are mid-accumulation
    assert [i for i in range(1, 1025) if resume.checkpoint_due(i, 16, 200)] == [208, 400, 608, 800, 1008]
    assert [i for i in range(1, 25) if resume.checkpoint_due(i, 1, 10)] == [10, 20]


@pytest.mark.parametrize("skip", range(0, 13))
def test_data_order_resumes_without_repeating_or_skipping(skip):
    data = CacheDataset(Rows(PER_EPOCH))

    def batches(skip, n):
        return [b[0].tolist() for b in islice(resume.ordered_batches(data, 1, 64, seed=7, skip=skip), n)]

    full = batches(0, 15)
    assert batches(skip, 15 - skip) == full[skip:]
    for epoch in range(3):   # each epoch is every example exactly once
        assert sorted(b[0][0] for b in full[epoch * PER_EPOCH:(epoch + 1) * PER_EPOCH]) == [1, 2, 3, 4, 5]
    assert full[:PER_EPOCH] != full[PER_EPOCH:2 * PER_EPOCH]   # reshuffled every epoch


def test_resumed_run_equals_uninterrupted_run(tmp_path):
    straight_model, straight_opt = training(tmp_path / "straight", resume.Run(run_args(tmp_path, tmp_path / "straight"), False))
    adapter = interrupted(tmp_path, tmp_path / "stopped")
    assert sorted(p.name for p in (adapter / "resume").iterdir()) == ["0000004", "0000008"]
    meta = json.loads((adapter / "resume" / "0000008" / "resume.json").read_text())
    assert (meta["iteration"], meta["optimizer_step"], meta["epoch"], meta["position"]) == (8, 4, 1, 3)
    assert meta["train_jsonl_sha256"] and meta["config_sha256"] and meta["mlx_lm"] and meta["mlx"] and len(meta["mx_random_key"]) == 2

    # a new process: different LoRA init and PRNG, fresh optimizer; everything must come from the checkpoint
    model, opt = training(adapter, resume.Run(run_args(tmp_path, adapter), resume=True), lora_seed=99)
    same(straight_model.trainable_parameters(), model.trainable_parameters(), "adapter weights")
    same(straight_opt.state, opt.state, "optimizer state")
    assert opt.step.item() == straight_opt.step.item() == N // ACCUM
    assert sorted(p.name for p in (adapter / "resume").iterdir()) == ["0000008", "0000012"]   # only the newest two kept


def test_resuming_only_the_adapter_weights_is_not_exact(tmp_path):
    """The control: mlx-lm's --resume-adapter-file (weights only) lands elsewhere, so the check above can tell."""
    straight_model, _ = training(tmp_path / "straight", resume.Run(run_args(tmp_path, tmp_path / "straight"), False))
    adapter = interrupted(tmp_path, tmp_path / "stopped")
    model = tiny_model()
    model.load_weights(str(adapter / "resume" / "0000008" / "adapters.safetensors"), strict=False)
    args = TrainingArgs(batch_size=1, iters=N - 8, val_batches=2, steps_per_report=3, steps_per_eval=100,
                        steps_per_save=100, adapter_file=tmp_path / "w" / "a.safetensors", max_seq_length=64,
                        grad_accumulation_steps=ACCUM)
    (tmp_path / "w").mkdir()
    resume.train(model, optimizer(), CacheDataset(Rows(PER_EPOCH)), None, args, run=resume.Run(run_args(tmp_path, tmp_path / "w"), False))
    assert differs(straight_model.trainable_parameters(), model.trainable_parameters())


def test_resume_refuses_a_changed_train_jsonl(tmp_path):
    adapter = interrupted(tmp_path, tmp_path / "stopped")
    (tmp_path / "data" / "train.jsonl").write_text('{"text": "a"}\n{"text": "CHANGED"}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match=r"refusing to resume .*train_jsonl_sha256"):
        training(adapter, resume.Run(run_args(tmp_path, adapter), resume=True))


def test_resume_refuses_a_changed_config_or_version(tmp_path, monkeypatch):
    adapter = interrupted(tmp_path, tmp_path / "stopped")
    (tmp_path / "mlx.yaml").write_text("iters: 13\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"config_sha256"):
        training(adapter, resume.Run(run_args(tmp_path, adapter), resume=True))
    (tmp_path / "mlx.yaml").write_text("iters: 12\n", encoding="utf-8")
    monkeypatch.setattr(resume, "version", lambda name: "0.0.1")
    with pytest.raises(SystemExit, match=r"mlx_lm"):
        training(adapter, resume.Run(run_args(tmp_path, adapter), resume=True))


def test_incomplete_newest_checkpoint_falls_back_to_the_previous_one(tmp_path):
    straight_model, _ = training(tmp_path / "straight", resume.Run(run_args(tmp_path, tmp_path / "straight"), False))
    adapter = interrupted(tmp_path, tmp_path / "stopped")
    (adapter / "resume" / "0000008" / "optimizer.safetensors").write_bytes(b"torn write")   # newest is damaged
    (adapter / "resume" / "0000010.tmp").mkdir()   # and a write that never finished
    model, _ = training(adapter, resume.Run(run_args(tmp_path, adapter), resume=True), lora_seed=5)
    same(straight_model.trainable_parameters(), model.trainable_parameters(), "adapter weights")
    assert not (adapter / "resume" / "0000010.tmp").exists()


def test_resume_without_a_checkpoint_trains_from_scratch_and_a_fresh_run_moves_old_ones_aside(tmp_path):
    adapter = tmp_path / "run"
    training(adapter, resume.Run(run_args(tmp_path, adapter), resume=True))   # nothing to resume: a normal run
    assert (adapter / "resume" / "0000012" / "resume.json").is_file()
    training(adapter, resume.Run(run_args(tmp_path, adapter), resume=False))   # not resuming: old checkpoints are not mixed in
    assert (adapter / "resume.old" / "0000012" / "resume.json").is_file()
    shutil.rmtree(adapter / "resume.old")


def test_lora_py_resumes_through_mlx_lm_main(tmp_path, monkeypatch):
    """`python training/lora.py --config X` and then again with SPIKE_RESUME=1, through mlx_lm.lora.main()."""
    data, _ = paths(tmp_path)
    monkeypatch.setattr(gated_delta_chunked, "install", lambda *a, **k: None)   # leave the other tests' reference alone
    for name in ("train_model", "train", "load", "load_dataset", "get_reporting_callbacks"):
        monkeypatch.setattr(mlx_lora, name, getattr(mlx_lora, name))   # restored after the test
    monkeypatch.setattr(mlx_lora, "load", lambda *a, **k: (tiny_model(), None))
    monkeypatch.setattr(mlx_lora, "load_dataset", lambda args, tok: (Rows(PER_EPOCH), Rows(4), Rows(4)))
    crash = {"at": None}
    monkeypatch.setattr(mlx_lora, "get_reporting_callbacks", lambda *a, **k: CrashAt(crash["at"]) if crash["at"] else None)

    def run(name, resume_env, crash_at=None):
        adapter = tmp_path / name
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump({
            "model": "tiny", "train": True, "data": str(data), "seed": 0, "num_layers": 2, "batch_size": 1, "iters": N,
            "grad_accumulation_steps": ACCUM, "save_every": SAVE_EVERY, "steps_per_report": 3, "steps_per_eval": 6,
            "val_batches": 2, "max_seq_length": 64, "adapter_path": str(adapter), "learning_rate": 1e-2,
            "lr_schedule": {"name": "cosine_decay", "warmup": 2, "arguments": [1e-2, 6, 1e-4]},
            "lora_parameters": {"rank": 4, "scale": 2.0, "dropout": 0.1}}), encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["lora.py", "--config", str(tmp_path / f"{name}.yaml")]
                            + (["--spike-resume"] if resume_env == "flag" else []))
        monkeypatch.setenv("SPIKE_RESUME", "1") if resume_env == "env" else monkeypatch.delenv("SPIKE_RESUME", raising=False)
        crash["at"] = crash_at
        spike_lora.main()
        return adapter

    straight = run("straight", None)
    stopped = tmp_path / "stopped"
    with pytest.raises(Crash):
        run("stopped", None, crash_at=9)
    assert not (stopped / "resume.old").exists()
    for how in ("env", "flag"):   # twice: the second finds the 0000012 checkpoint of a finished run and trains nothing
        run("stopped", how)
        a = mx.load(str(straight / "adapters.safetensors"))
        b = mx.load(str(stopped / "adapters.safetensors"))
        assert a.keys() == b.keys() and all(mx.allclose(a[k], b[k], rtol=1e-5, atol=1e-7).item() for k in a)
    a = mx.load(str(straight / "resume" / "0000012" / "optimizer.safetensors"))
    b = mx.load(str(stopped / "resume" / "0000012" / "optimizer.safetensors"))
    assert a.keys() == b.keys() and all(mx.allclose(a[k], b[k], rtol=1e-5, atol=1e-7).item() for k in a)
