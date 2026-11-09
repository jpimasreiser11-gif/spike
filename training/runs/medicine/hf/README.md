---
license: apache-2.0
base_model: Qwen/Qwen3.5-4B
language:
- en
- es
pipeline_tag: text-generation
tags:
- spike
- lora
- gguf
- medicine
datasets:
- OpenAssistant/oasst2
- openlifescienceai/medmcqa
- qiaojin/PubMedQA
---

![Spike Medicine](banner.png)

# Spike Medicine

LoRA adapter for [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) that turns it into SPIKE's medicine and health sciences specialist. Clinical reasoning, pharmacology, physiology, diagnostics and evidence-based medicine.

**Accepted by its acceptance criteria, which were written before training** (see Evaluation).

## Use

In SPIKE: put `spike-medicine-it13270-s0.5.gguf` in `~/.spike/adapters/`; the app loads it next to the base model and routes medicine and health sciences requests to it.

With llama.cpp directly:

```bash
llama-server -m Qwen3.5-4B-Q4_K_M.gguf --lora spike-medicine-it13270-s0.5.gguf
```

## Training

- Method: LoRA, rank 16, alpha 16.0, on `down_proj`, `gate_proj`, `k_proj`, `o_proj`, `q_proj`, `up_proj`, `v_proj`; trained in bf16 with mlx-lm.
- Steps: 13270 micro-batches of 1, learning rate 0.0001, seed 0.
- Examples: 13270 train, 270 validation; 9478 domain chats, general replay 30% of the mix (target 30%).
- Removed before training: 11375 by format or quality filters, 1 duplicates, 17 that shared a 13-gram with an eval set.

| dataset | license | used as |
|---|---|---|
| [openlifescienceai/medmcqa](https://huggingface.co/datasets/openlifescienceai/medmcqa) | apache-2.0 | training |
| [qiaojin/PubMedQA](https://huggingface.co/datasets/qiaojin/PubMedQA) | mit | training |
| [OpenAssistant/oasst2](https://huggingface.co/datasets/OpenAssistant/oasst2) | apache-2.0 | training |
| [openlifescienceai/medmcqa](https://huggingface.co/datasets/openlifescienceai/medmcqa) | apache-2.0 | evaluation and decontamination only |
| [qiaojin/PubMedQA](https://huggingface.co/datasets/qiaojin/PubMedQA) | mit | evaluation and decontamination only |
| [TIGER-Lab/MMLU-Pro](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro) | mit | evaluation and decontamination only |

Distillation teachers (a model whose answers the adapter was trained on):

| teacher | license | used as |
|---|---|---|
| [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | apache-2.0 | wrote training answers |

## Evaluation

Variant `spike-medicine-it13270-s0.5` against the same base model with the same prompts (run `final`). Accuracy is exact-answer scoring; the 95% interval is Wilson's, the paired test is McNemar's.

Model `Qwen3.5-4B-Q4_K_M.gguf`, llama.cpp `b11669-620d2225c`, greedy, thinking off, max_tokens 2048, host `macOS-27.0-arm64-arm-64bit`.

| task | variant | n | accuracy | 95% CI | Δ vs base (pts) | McNemar p | unparsed | truncated |
|---|---|---|---|---|---|---|---|---|
| medmcqa-val | base | 1000 | 0.276 | 0.249–0.304 |  |  | 409 | 24 |
| medmcqa-val | spike-medicine-it13270-s0.5 | 1000 | 0.643 | 0.613–0.672 | +36.70 | 0 | 26 | 34 |
| mmlu-pro-general | base | 800 | 0.637 | 0.604–0.670 |  |  | 10 | 37 |
| mmlu-pro-general | spike-medicine-it13270-s0.5 | 800 | 0.631 | 0.597–0.664 | -0.62 | 0.7433 | 1 | 26 |
| mmlu-pro-health | base | 818 | 0.309 | 0.279–0.342 |  |  | 241 | 27 |
| mmlu-pro-health | spike-medicine-it13270-s0.5 | 818 | 0.621 | 0.587–0.654 | +31.17 | 0 | 16 | 31 |
| pubmedqa-labeled | base | 500 | 0.422 | 0.380–0.466 |  |  | 0 | 1 |
| pubmedqa-labeled | spike-medicine-it13270-s0.5 | 500 | 0.804 | 0.767–0.836 | +38.20 | 0 | 1 | 1 |
| **general (pooled)** | base | 800 | 0.637 | 0.604–0.670 |  |  | 10 | 37 |
| **general (pooled)** | spike-medicine-it13270-s0.5 | 800 | 0.631 | 0.597–0.664 | -0.62 | 0.7433 | 1 | 26 |
| **medicine (pooled)** | base | 2318 | 0.319 | 0.301–0.339 |  |  | 650 | 52 |
| **medicine (pooled)** | spike-medicine-it13270-s0.5 | 2318 | 0.670 | 0.651–0.689 | +35.07 | 0 | 43 | 66 |

**spike-medicine-it13270-s0.5: ACCEPTED**
- medicine: +35.07 pts (need ≥ 3.0), p = 0 (need ≤ 0.05)
- general: -0.62 pts (max drop 1.5)

## Limitations

- Measured on exact-answer benchmarks only; these do not measure the quality or safety of open-ended answers.
- A 4B model makes mistakes with confidence. Check important facts against primary sources.
- Spike Medicine gives general information, not professional advice, and it is not a medical device.

## License

The adapter is released under `apache-2.0`, like the base model. Each dataset and teacher keeps its own license (tables above). Part of the SPIKE project.
