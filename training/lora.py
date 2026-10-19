"""`python -m mlx_lm.lora` with SPIKE's chunked gated delta rule for Qwen3.5's linear-attention layers.

mlx-lm trains those layers with a per-token loop (its Metal kernel has no backward pass); the chunked form in
spike_train/gated_delta_chunked.py gives the same loss and gradients (tests/test_gated_delta_chunked.py) about
3x faster per step and with ~6 GB less peak memory on Qwen3.5-4B. All arguments go to mlx_lm.lora unchanged.

Optional memory caps for a shared machine: SPIKE_MLX_MEMORY_GB (mlx memory limit, a guideline mlx keeps to by
waiting and freeing its cache) and SPIKE_MLX_CACHE_GB (how much freed buffer memory mlx may keep for reuse).

Exact resume (spike_train/resume.py): every adapter checkpoint also saves the optimizer state, PRNG key and data
position under <adapter_path>/resume/. `SPIKE_RESUME=1` (or `--spike-resume`) continues from the latest complete one
after checking that train.jsonl, the config and the mlx/mlx-lm versions are unchanged, and trains from iteration 0 if
there is none; without it a run starts fresh and moves older checkpoints aside (to resume.old).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spike_train import gated_delta_chunked, resume  # noqa: E402


def apply_memory_limits(env, mx) -> dict:
    applied = {}
    for var, setter, key in (("SPIKE_MLX_MEMORY_GB", mx.set_memory_limit, "memory_gb"),
                             ("SPIKE_MLX_CACHE_GB", mx.set_cache_limit, "cache_gb")):
        if env.get(var):
            gb = float(env[var])
            setter(int(gb * 1024**3))
            applied[key] = gb
    return applied


def wants_resume(argv, env) -> bool:
    return "--spike-resume" in argv or env.get("SPIKE_RESUME", "").lower() in ("1", "true", "yes")


def main() -> None:
    import mlx.core

    if limits := apply_memory_limits(os.environ, mlx.core):
        print(f"mlx memory limits: {limits}", flush=True)
    gated_delta_chunked.install()
    resume.install(wants_resume(sys.argv, os.environ))
    sys.argv = [a for a in sys.argv if a != "--spike-resume"]  # not an mlx_lm.lora option
    from mlx_lm import lora

    lora.main()


if __name__ == "__main__":
    main()
