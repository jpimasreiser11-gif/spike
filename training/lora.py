"""`python -m mlx_lm.lora` with SPIKE's chunked gated delta rule for Qwen3.5's linear-attention layers.

mlx-lm trains those layers with a per-token loop (its Metal kernel has no backward pass); the chunked form in
spike_train/gated_delta_chunked.py gives the same loss and gradients (tests/test_gated_delta_chunked.py) about
3x faster per step and with ~6 GB less peak memory on Qwen3.5-4B. All arguments go to mlx_lm.lora unchanged.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spike_train import gated_delta_chunked  # noqa: E402

if __name__ == "__main__":
    gated_delta_chunked.install()
    from mlx_lm import lora

    lora.main()
