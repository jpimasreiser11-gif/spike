"""Exact resume for `mlx_lm.lora` training; training/lora.py installs it.

mlx-lm's `--resume-adapter-file` reloads adapter weights only: the iteration count, the LR schedule, the optimizer
moments and the data order all restart. Here every adapter checkpoint (the first optimizer-update boundary on or
after each `save_every` multiple, so gradient accumulation is never split) also writes
<adapter_path>/resume/<iteration>/{adapters.safetensors, optimizer.safetensors, resume.json}: the optimizer state is
saved whole (including its step, which drives the LR schedule), and resume.json (written last, the directory is
renamed into place only when complete) records the iteration, optimizer step, epoch and position, the PRNG key, the
sha256 of train.jsonl and of the mlx config, and the mlx and mlx-lm versions. With SPIKE_RESUME=1 (or --spike-resume)
the latest complete checkpoint is loaded after those hashes and versions have been checked (a mismatch stops the run
with an error) and training continues at the next batch; with no checkpoint it starts from iteration 0.

Data order is a function of (seed, epoch): epoch e is mlx-lm's `iterate_batches` seeded from (seed, e), so resuming
just skips the batches of the current epoch already trained. Stock mlx-lm draws every epoch from one global numpy
stream that each validation pass also advances, which cannot be continued without saving that stream. The order
therefore differs from stock mlx-lm for the same seed; it is as random and as reproducible.

This relies on internals: `train` below is a copy of mlx_lm.tuner.trainer.train with the marked changes (a loop that
can start at iteration N cannot be hooked in from outside). `check_mlx_lm()` hashes the upstream functions it was
copied from and stops the run if they differ; tested with mlx-lm 0.32.2 (pinned in requirements-mac.txt).

`train` is adapted from mlx-lm's mlx_lm/tuner/trainer.py, Copyright © 2023-2024 Apple Inc., MIT License
(https://github.com/ml-explore/mlx-lm/blob/main/LICENSE).
"""

import hashlib
import inspect
import itertools
import json
import shutil
import sys
import time
from functools import partial
from importlib.metadata import version
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import numpy as np
from mlx.nn.utils import average_gradients
from mlx.utils import tree_flatten, tree_map, tree_unflatten
from mlx_lm import lora
from mlx_lm.cli_ui import TrainUI
from mlx_lm.tuner import trainer
from mlx_lm.tuner.trainer import TrainingArgs, _clear_cache, default_loss, evaluate, grad_checkpoint
from mlx_lm.utils import maybe_set_recommended_wired_limit

TESTED_MLX_LM = "0.32.2"
TESTED_FINGERPRINT = "ca7fdebec921d57aa3e1c92993ba0409b005f6b1aedea1e4c97cc7603251b076"
FILES = ("adapters.safetensors", "optimizer.safetensors")
KEEP = 2  # complete checkpoints kept; a crash while writing the newest leaves the previous one


def fingerprint() -> str:
    funcs = (trainer.train, trainer.iterate_batches, trainer.evaluate, inspect.unwrap(lora.train_model))
    return hashlib.sha256("".join(inspect.getsource(inspect.unwrap(f)) for f in funcs).encode()).hexdigest()


def check_mlx_lm() -> None:
    got = fingerprint()
    if got != TESTED_FINGERPRINT:
        raise SystemExit(
            f"mlx-lm {version('mlx-lm')} has a different trainer than the mlx-lm {TESTED_MLX_LM} that "
            f"training/spike_train/resume.py copies (fingerprint {got[:12]}, expected {TESTED_FINGERPRINT[:12]}). "
            f"Install the tested one (pip install mlx-lm=={TESTED_MLX_LM}), or compare train() there with "
            "mlx_lm/tuner/trainer.py and update TESTED_FINGERPRINT.")
    if len(mx.random.state) != 1:
        raise SystemExit("mx.random.state is not a single key any more; resume.py saves and restores that key")


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ordered_batches(dataset, batch_size, max_seq_length, seed, skip=0, comm_group=None,
                    iterate_batches=trainer.iterate_batches):
    """Training batches forever, in an order fixed by (seed, epoch); the first `skip` batches are not yielded."""
    per_epoch = len(dataset) // batch_size
    if per_epoch == 0:
        raise ValueError(f"Dataset must have at least batch_size={batch_size} examples but only has {len(dataset)}.")
    epoch, pos = divmod(skip, per_epoch)
    while True:
        epoch_seed = int(np.random.SeedSequence([seed, epoch]).generate_state(1)[0])
        batches = iterate_batches(dataset=dataset, batch_size=batch_size, max_seq_length=max_seq_length,
                                  loop=False, seed=epoch_seed, comm_group=comm_group)
        yield from itertools.islice(batches, pos, None)
        epoch, pos = epoch + 1, 0


def checkpoint_due(it: int, accum: int, save_every: int) -> bool:
    """An optimizer-update boundary on or after a save_every multiple: one lies in (it - accum, it]."""
    return it % accum == 0 and it // save_every > (it - accum) // save_every


class Run:
    """The resume checkpoints of one training run (`args`: mlx_lm.lora's merged config namespace)."""

    def __init__(self, args, resume: bool):
        self.dir = Path(args.adapter_path) / "resume"
        self.resume, self.seed = resume, args.seed
        data = Path(args.data) / "train.jsonl"
        self.identity = {
            "train_jsonl_sha256": sha256(data) if data.is_file() else None,
            "config_sha256": sha256(args.config) if args.config else None,
            "mlx": version("mlx"), "mlx_lm": version("mlx-lm"), "seed": args.seed, "batch_size": args.batch_size,
            "grad_accumulation_steps": args.grad_accumulation_steps, "iters": args.iters}

    def latest(self):
        for d in sorted((p for p in self.dir.glob("*") if p.is_dir() and not p.name.endswith(".tmp")), reverse=True):
            try:
                meta = json.loads((d / "resume.json").read_text(encoding="utf-8"))
                if set(meta["files"]) == set(FILES) and all(sha256(d / n) == h for n, h in meta["files"].items()):
                    return d, meta
            except (OSError, ValueError, KeyError):
                pass
            print(f"spike-resume: ignoring incomplete checkpoint {d}", flush=True)
        return None

    def begin(self, model, optimizer, accum: int):
        """Load the latest checkpoint into model, optimizer and PRNG; returns (iteration, trained_tokens) to continue from."""
        for stale in self.dir.glob("*.tmp"):
            shutil.rmtree(stale, ignore_errors=True)
        if not self.resume:  # a fresh run must not leave checkpoints that a later resume would take for its own
            if any(self.dir.glob("*")):
                shutil.rmtree(self.dir.with_name("resume.old"), ignore_errors=True)
                self.dir.rename(self.dir.with_name("resume.old"))
                print(f"spike-resume: not resuming; moved the old checkpoints to {self.dir.with_name('resume.old')}", flush=True)
            return 0, 0
        found = self.latest()
        if not found:
            print(f"spike-resume: no complete checkpoint in {self.dir}; starting at iteration 0", flush=True)
            return 0, 0
        d, meta = found
        if self.identity["train_jsonl_sha256"] is None:
            raise SystemExit("spike-resume: cannot resume without <data>/train.jsonl to hash")
        changed = [f"{k}: {str(meta.get(k))[:16]} -> {str(v)[:16]}" for k, v in self.identity.items() if meta.get(k) != v]
        if changed:
            raise SystemExit(f"spike-resume: refusing to resume {d}: it was written by a different run ({'; '.join(changed)}). "
                             f"Restore the original files, or delete {self.dir} to train from scratch.")
        saved = mx.load(str(d / "adapters.safetensors"))
        if saved.keys() != dict(tree_flatten(model.trainable_parameters())).keys():
            raise SystemExit(f"spike-resume: {d}/adapters.safetensors does not match the model's trainable parameters")
        model.load_weights(list(saved.items()), strict=False)
        optimizer.state = tree_unflatten(list(mx.load(str(d / "optimizer.safetensors")).items()))
        hi, lo = meta["mx_random_key"]
        mx.random.seed((hi << 32) | lo)  # key(seed) is [seed >> 32, seed & 0xFFFFFFFF]: this sets the saved key
        mx.eval(model.parameters(), optimizer.state)
        it = meta["iteration"]
        if int(optimizer.step.item()) != meta["optimizer_step"] or it != meta["optimizer_step"] * accum:
            raise SystemExit(f"spike-resume: {d} is inconsistent: iteration {it}, optimizer step "
                             f"{meta['optimizer_step']} (saved) / {int(optimizer.step.item())} (loaded)")
        print(f"spike-resume: resumed from {d.name}: iteration {it}, optimizer step {meta['optimizer_step']}, "
              f"epoch {meta['epoch']} position {meta['position']}", flush=True)
        return it, meta["trained_tokens"]

    def save(self, it, model, optimizer, trained_tokens, per_epoch) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        final, tmp = self.dir / f"{it:07d}", self.dir / f"{it:07d}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        mx.save_safetensors(str(tmp / FILES[0]), dict(tree_flatten(model.trainable_parameters())))
        mx.save_safetensors(str(tmp / FILES[1]), dict(tree_flatten(optimizer.state)))
        epoch, position = divmod(it, per_epoch)
        meta = {**self.identity, "format": 1, "iteration": it, "optimizer_step": int(optimizer.step.item()),
                "epoch": epoch, "position": position, "batches_per_epoch": per_epoch,
                "data_order": "iterate_batches(seed=SeedSequence([seed, epoch]).generate_state(1)[0])",
                "mx_random_key": [int(x) for x in mx.random.state[0].tolist()], "trained_tokens": int(trained_tokens),
                "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": {n: sha256(tmp / n) for n in FILES}}
        (tmp / "resume.json.tmp").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (tmp / "resume.json.tmp").replace(tmp / "resume.json")  # last
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
        for old in sorted(p for p in self.dir.glob("*") if p.is_dir() and not p.name.endswith(".tmp"))[:-KEEP]:
            shutil.rmtree(old, ignore_errors=True)
        return final


def train(model, optimizer, train_dataset, val_dataset=None, args=None, loss=default_loss,
          iterate_batches=trainer.iterate_batches, training_callback=None, run=None):
    """mlx_lm.tuner.trainer.train, copied; the changes are marked SPIKE."""
    args = args or TrainingArgs()
    _ = maybe_set_recommended_wired_limit()
    world = mx.distributed.init()
    world_size = world.size()
    rank = world.rank()

    if args.grad_checkpoint:
        grad_checkpoint(model.layers[0])

    loss_value_and_grad = nn.value_and_grad(model, loss)

    grad_accum_steps = args.grad_accumulation_steps
    if grad_accum_steps < 1:
        raise ValueError("grad_accumulation_steps must be at least 1")

    # SPIKE: continue from the latest checkpoint (before `state` is captured: the optimizer state is replaced)
    start, trained_tokens = run.begin(model, optimizer, grad_accum_steps) if run else (0, 0)
    per_epoch = len(train_dataset) // args.batch_size

    state = [model.state, optimizer.state, mx.random.state]

    @partial(mx.compile, inputs=state, outputs=state)
    def step(batch, prev_grad, do_update):
        (lvalue, toks), grad = loss_value_and_grad(model, *batch)

        if prev_grad is not None:
            grad = tree_map(lambda x, y: x + y, grad, prev_grad)

        if do_update:
            grad = average_gradients(grad)
            if grad_accum_steps > 1:
                grad = tree_map(lambda x: x / grad_accum_steps, grad)
            optimizer.update(model, grad)
            grad = None

        return lvalue, toks, grad

    model.train()
    losses = 0
    n_tokens = 0
    steps = 0
    train_time = 0
    grad_accum = None

    ui = TrainUI(args.iters - start, rank=rank)  # SPIKE: remaining iterations
    with ui:
        # Main training loop
        for it, batch in zip(
            range(start + 1, args.iters + 1),  # SPIKE: start + 1
            ordered_batches(  # SPIKE: order fixed by (seed, epoch), skipping what the checkpoint already trained
                train_dataset, args.batch_size, args.max_seq_length, run.seed if run else 0, skip=start,
                comm_group=world, iterate_batches=iterate_batches),
            strict=False,
        ):
            tic = time.perf_counter()
            if val_dataset and (
                it == 1 or it % args.steps_per_eval == 0 or it == args.iters
            ):
                if args.val_batches == -1:
                    val_total = len(val_dataset) // args.batch_size
                else:
                    val_total = min(
                        len(val_dataset) // args.batch_size, args.val_batches
                    )

                tic = time.perf_counter()
                with ui.val_task(val_total) as advance_val:
                    val_loss = evaluate(
                        model=model,
                        dataset=val_dataset,
                        loss=loss,
                        batch_size=args.batch_size,
                        num_batches=args.val_batches,
                        max_seq_length=args.max_seq_length,
                        iterate_batches=iterate_batches,
                        progress_callback=advance_val,
                    )
                model.train()
                val_time = time.perf_counter() - tic
                ui.report_val(it, val_loss, val_time)

                if training_callback is not None:
                    training_callback.on_val_loss_report(
                        {
                            "iteration": it - 1,
                            "val_loss": val_loss,
                            "val_time": val_time,
                        }
                    )

                tic = time.perf_counter()

            lvalue, toks, grad_accum = step(
                batch,
                grad_accum,
                it % grad_accum_steps == 0,
            )

            losses += lvalue
            n_tokens += toks
            steps += 1
            mx.eval(state, losses, n_tokens, grad_accum)
            _clear_cache(args.clear_cache_threshold)
            train_time += time.perf_counter() - tic

            ui.advance()

            # Report training loss if needed
            if it % args.steps_per_report == 0 or it == args.iters:
                train_loss = mx.distributed.all_sum(losses, stream=mx.cpu).item()
                train_loss /= steps * world_size
                n_tokens = mx.distributed.all_sum(n_tokens, stream=mx.cpu).item()
                learning_rate = optimizer.learning_rate.item()
                it_sec = args.steps_per_report / train_time
                tokens_sec = float(n_tokens) / train_time
                trained_tokens += n_tokens
                peak_mem = mx.get_peak_memory() / 1e9
                ui.report_train(it, train_loss, tokens_sec, trained_tokens)

                if training_callback is not None:
                    training_callback.on_train_loss_report(
                        {
                            "iteration": it,
                            "train_loss": train_loss,
                            "learning_rate": learning_rate,
                            "iterations_per_second": it_sec,
                            "tokens_per_second": tokens_sec,
                            "trained_tokens": trained_tokens,
                            "peak_memory": peak_mem,
                        }
                    )

                losses = 0
                n_tokens = 0
                steps = 0
                train_time = 0

            # Save adapter weights
            if it % args.steps_per_save == 0 and rank == 0:
                adapter_weights = dict(tree_flatten(model.trainable_parameters()))
                mx.save_safetensors(str(args.adapter_file), adapter_weights)
                checkpoint = (
                    Path(args.adapter_file).parent / f"{it:07d}_adapters.safetensors"
                )
                mx.save_safetensors(str(checkpoint), adapter_weights)
                ui.report_save(checkpoint)

            # SPIKE: the resume checkpoint, on an optimizer-update boundary
            if run and rank == 0 and checkpoint_due(it, grad_accum_steps, args.steps_per_save):
                ui.report_save(run.save(it, model, optimizer, trained_tokens, per_epoch))

    # Save final weights
    if rank == 0:
        adapter_weights = dict(tree_flatten(model.trainable_parameters()))
        mx.save_safetensors(str(args.adapter_file), adapter_weights)


def install(resume: bool) -> None:
    """Make mlx_lm.lora train with the resumable loop (call before `lora.main()`). With an mlx-lm other than the tested
    one a resuming run stops; a fresh run trains with mlx-lm's own loop and writes no resume checkpoints."""
    try:
        check_mlx_lm()
    except SystemExit as exc:
        if resume:
            raise
        print(f"warning: {exc}\ntraining with mlx-lm's own loop, without resume checkpoints", file=sys.stderr, flush=True)
        return
    train_model = inspect.unwrap(lora.train_model)

    def resumable_train_model(args, *rest, **kw):
        lora.train = partial(train, run=Run(args, resume))  # train_model looks `train` up in mlx_lm.lora at call time
        return train_model(args, *rest, **kw)

    resumable_train_model.__wrapped__ = train_model
    lora.train_model = resumable_train_model
