# Third-party components, models and data

SPIKE's own code is Apache-2.0 ([LICENSE](LICENSE)). This file lists what SPIKE uses from others, under
which license, and whether it is **redistributed** in SPIKE's repository or packages, or only
**downloaded on the user's machine** from its original source. Licenses were read from the package
registries (PyPI, npm) and the Hugging Face Hub on 2026-10-17; the model and dataset licenses are re-checked
automatically at download time and SPIKE refuses anything outside its allowlist
(`training/spike_train/licenses.py`, `spike/runtime/models.py`).

## Models (downloaded by the user, not redistributed)

| Model | Source | License | Use |
|---|---|---|---|
| Qwen3.5-4B (GGUF, default Q4_K_M) | `unsloth/Qwen3.5-4B-GGUF`, quantized from `Qwen/Qwen3.5-4B` | Apache-2.0 | base model for every specialist |
| Qwen3.5-2B (GGUF) | `unsloth/Qwen3.5-2B-GGUF` | Apache-2.0 | optional smaller base |
| Qwen3.5-4B (safetensors) | `Qwen/Qwen3.5-4B` | Apache-2.0 | LoRA training base (mlx-lm) and adapter export |
| Qwen3.6-35B-A3B (MLX 4-bit) | `mlx-community/Qwen3.6-35B-A3B-4bit` | Apache-2.0 | local teacher for marketing distillation (optional) |

SPIKE adapters trained from these bases are derivative works and are released under Apache-2.0 together
with the data attributions below. No adapter has been released yet.

## Datasets (downloaded by the user at training/eval time, not redistributed)

| Dataset | Hub id | License | Role | Attribution / notes |
|---|---|---|---|---|
| OpenAssistant Conversations 2 | `OpenAssistant/oasst2` | Apache-2.0 | general replay | human-written, crowd-sourced (Köpf et al., 2023); English and Spanish messages only |
| SmolTalk (smol-constraints) | `HuggingFaceTB/smoltalk` | Apache-2.0 | general replay | synthetic; the card does not name the generator model, to be confirmed before any adapter release |
| SmolTalk (smol-magpie-ultra) | `HuggingFaceTB/smoltalk` | Apache-2.0 | **excluded** | generated with Llama-3.1-405B-Instruct; the Llama 3.1 license (§1.b.i) requires "Llama" at the beginning of the name of any distributed model trained on its outputs, so SPIKE does not use it |
| MedMCQA | `openlifescienceai/medmcqa` | Apache-2.0 | medicine train + eval | Pal et al., 2022 |
| PubMedQA (pqa_artificial, pqa_labeled) | `qiaojin/PubMedQA` | MIT | medicine train / eval | Jin et al., 2019 |
| Sujet-Finance-Instruct-177k | `sujet-ai/Sujet-Finance-Instruct-177k` | Apache-2.0 | finance train | aggregates 18 public datasets; their upstream terms must be audited before any finance adapter is released |
| MMLU-Pro | `TIGER-Lab/MMLU-Pro` | MIT | eval only | Wang et al., 2024 |
| GSM8K | `openai/gsm8k` | MIT | eval only | Cobbe et al., 2021 |
| medical-o1-reasoning-SFT | `FreedomIntelligence/medical-o1-reasoning-SFT` | Apache-2.0 | **excluded** | generated with GPT-4o; OpenAI's terms restrict using outputs to build competing models |

Files written by SPIKE contributors and shipped in this repository (`training/seeds/`, `evals/data/`,
`evals/router/`) are Apache-2.0.

## Inference and training tools (installed separately, not redistributed)

| Component | License | Use |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`, `convert_lora_to_gguf.py`, `gguf`) | MIT | local inference, adapter export |
| [mlx](https://github.com/ml-explore/mlx), [mlx-lm](https://github.com/ml-explore/mlx-lm) | MIT | training on Apple Silicon |
| PyTorch | BSD-style (Apache-2.0 AND BSD-3-Clause AND MIT AND others, per PyPI) | needed by llama.cpp's converter |
| transformers, datasets, huggingface_hub, safetensors, sentencepiece | Apache-2.0 | training data and export |
| numpy | BSD-3-Clause (with bundled 0BSD, MIT, Zlib, CC0-1.0 parts) | training and export |

## Python runtime dependencies (installed from PyPI, not vendored)

| Package | Version checked | License |
|---|---|---|
| fastapi | 0.143.3 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| PyYAML | 6.0.3 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| keyring (optional) | 25.7.0 | MIT |
| pytest, pytest-asyncio, ruff (development only) | — | MIT |

## Web app (bundled into `web/dist`, which ships inside the Python package)

| Package | Version | License |
|---|---|---|
| react, react-dom | 18.3.1 | MIT |
| marked | 14.1.3 | MIT |
| dompurify | 3.1.7 | MPL-2.0 OR Apache-2.0 (used under Apache-2.0) |
| highlight.js | 11.10.0 | BSD-3-Clause |
| @fontsource/inter (Inter typeface) | 5.x | SIL Open Font License 1.1 |
| @fontsource/nunito (Nunito typeface) | 5.x | SIL Open Font License 1.1 |

Build and test tools (vite, @vitejs/plugin-react, typescript, vitest, jsdom, playwright-core) are used only
at development time and are not part of the bundle. Their license texts are in `web/node_modules/*/LICENSE`
after `npm ci`; a release build must include the license texts of the bundled packages above.

## External API providers

SPIKE can call OpenAI, Anthropic, DeepSeek, Google Gemini, OpenRouter, Groq, Mistral, Together and any
OpenAI-compatible server, only with the user's own keys and after the user allows paid calls. Use of those
services is governed by each provider's terms; SPIKE ships none of their code, names as identity, or assets.

## Brand

The SPIKE name, cactus logo and palette in [brand/](brand/) are the project's own identity and are not
licensed for use as another product's identity.
