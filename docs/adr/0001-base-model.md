# ADR 0001: Base model, Qwen3.5-4B shared by every specialist

Status: accepted (2026-10-17). Revisit when a newer open ~4B model is released or when our own
measurements on the target hardware contradict the figures below.

## Context

Each specialist should be about 4B parameters and SPIKE must run on 16 GB RAM machines without a GPU.
The candidates were compared on the 17 criteria of the master directive. Figures below are **vendor or
third-party reports, not SPIKE measurements**, unless marked *computed*. Vendor scores mix thinking and
non-thinking modes and are not directly comparable across families; SPIKE's own harness
(`evals/run_eval.py`, `spike bench`) produces the numbers that count.

| Model | License | Size | Context | MMLU-Pro | GPQA-D | IFEval | LCB v6 | KV cache at 32K, f16 (*computed*) |
|---|---|---|---|---|---|---|---|---|
| **Qwen3.5-4B** | Apache-2.0 | 4B LM + vision encoder | 262K | 79.1 | 76.2 | 89.8 | 55.8 | **1.0 GiB** (8 attention layers × 4 KV heads × 256) |
| Gemma 4 E4B | Apache-2.0 | ~4B effective (PLE) | 128K | 69.4 | 58.6 | n/r | 52.0 | not computed (sliding/global mix, shared KV) |
| Qwen3-4B-Instruct-2507 | Apache-2.0 | 4.0B dense, 36 layers | 262K | 69.6 | 62.0 | 83.4 | 35.1 | 4.5 GiB (36 layers × 8 KV heads × 128) |
| Phi-4-mini | MIT | 3.8B dense | 128K | 52.8 (third party) | n/r | n/r | n/r | not computed |
| DeepSeek-V4.1-Flash | MIT | 552B total, 8–16B active, 510 GB checkpoint | — | — | — | — | — | does not fit any consumer machine |
| Qwen3.6-35B-A3B | Apache-2.0 | 35B total / 3B active | 262K | 85.2 | 86.0 | n/r | 80.4 | too large for 16 GB; **chosen as distillation teacher** |

n/r = not reported by the source. Sources: model cards for
[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B),
[Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
[Gemma 4](https://huggingface.co/google/gemma-4-26B-A4B), [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B);
Phi-4-mini from [tech-insider.org](https://tech-insider.org/gemma-4-vs-phi-4-mini-vs-qwen3-5-2026/);
DeepSeek-V4.1-Flash from [openclawdc.com](https://openclawdc.com/blog/deepseek-v4-1-flash-local-requirements/).
No newer small Qwen exists: Qwen3.6 and 3.8 ship 27B and larger
([codersera.com](https://codersera.com/blog/qwen-3-8-model-lineup-2026/), third party).

## Decision

Use **Qwen3.5-4B** as the single base for all specialists, served as one GGUF
(`unsloth/Qwen3.5-4B-GGUF`, Q4_K_M = 2.74 GB on the Hub) with one LoRA adapter per specialist.

Why:
1. Highest reported quality at ~4B on knowledge, reasoning and instruction following, under Apache-2.0
   (weights and adapters can be redistributed).
2. Hybrid Gated DeltaNet + gated attention: only 8 of 32 layers keep a KV cache, so long context is cheap
   on 16 GB (computed 32 KiB/token at f16; the 24 linear-attention layers keep a fixed-size state).
3. Supported by llama.cpp (`qwen35` architecture; LoRA conversion verified in
   `tests/test_export_integration.py`) and by mlx-lm (`mlx_lm/models/qwen3_5.py`) for training on the Mac.
4. Thinking and non-thinking modes in one model (`enable_thinking`), which the orchestrator uses
   (planner and short answers without thinking, hard problems with it).

Alternative kept: **Gemma 4 E4B** (Apache-2.0) if Qwen3.5 underperforms in our own evaluations.

## Consequences

- One model in memory serves every specialist; switching specialist costs no reload (ADR 0004).
- QLoRA is not used (ADR 0002). Vision input is not exposed in v0.1 (the mmproj file is optional).
- All quality and speed claims must come from SPIKE's own runs on documented hardware (docs/STATUS.md).
