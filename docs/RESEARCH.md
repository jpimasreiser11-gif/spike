# SPIKE research notes

What was investigated, what was concluded and from which source. Vendor and third-party figures are
labelled as such; SPIKE's own measurements are in [STATUS.md](STATUS.md). Research date: 2026-10-17.

## 1. Base model

Summary in [ADR 0001](adr/0001-base-model.md): **Qwen3.5-4B** (Apache-2.0). Key facts from the
[model card](https://huggingface.co/Qwen/Qwen3.5-4B): 32 layers in 8 blocks of (3 × Gated DeltaNet + 1 ×
gated attention), hidden 2560, FFN 9216, vocabulary 248,320, 262K native context, thinking on by default
(`enable_thinking: false` disables it; `/think` soft switches are not supported), vision encoder included.
Vendor long-context scores (AA-LCR 57.0, LongBench v2 50.0) show that the 262K window is not 262K of
reliable understanding; SPIKE sizes context by measured memory and will publish its own long-context eval.

Other candidates and why they lost: Gemma 4 E4B (lower reported knowledge/reasoning, kept as alternative),
Qwen3-4B-Instruct-2507 (dense attention: ~4.5× the KV cache at equal context, computed), Phi-4-mini
(lower reported MMLU-Pro), DeepSeek-V4.1-Flash (552B total; does not fit consumer hardware), Qwen3.6/3.8
(no model below 27B).

## 2. Inference engine

| Engine | CPU x86 | Apple Silicon | Per-request adapter switching | Role in SPIKE |
|---|---|---|---|---|
| **llama.cpp** (`llama-server`) | AVX2/AVX-512 kernels | Metal | yes: `lora` field with per-adapter scales | inference everywhere |
| MLX / mlx-lm | no | yes | one adapter per loaded model | **training** on the Mac |
| Ollama | wraps llama.cpp | wraps llama.cpp | adapters baked per model tag | supported as an external provider |
| vLLM | not the target | no | yes (GPU) | supported as an OpenAI-compatible provider |

llama.cpp facts verified in source (`ggml-org/llama.cpp` at 62318cd, built in the dev container):
`qwen35` architecture in the converter (`conversion/qwen.py`, `Qwen3_5TextModel`); LoRA GGUF conversion
needs only the base `config.json`; server LoRA semantics documented in [ADR 0004](adr/0004-adapter-serving.md).

## 3. Memory and quantization

- Weights (Hub file sizes, [unsloth/Qwen3.5-4B-GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF)):
  Q4_K_M 2.74 GB, Q5_K_M 3.14 GB, Q6_K 3.53 GB, Q8_0 4.48 GB, BF16 8.42 GB; vision projector 672 MB (F16).
- KV cache, *computed* from the architecture: 8 attention layers × 4 KV heads × 256 dims × 2 (K,V) ×
  2 bytes = 32 KiB per token at f16 (~17 KiB at q8_0). 32K context ≈ 1 GiB f16 / ≈ 0.53 GiB q8_0.
  The 24 Gated DeltaNet layers keep a fixed recurrent state per sequence instead of a growing cache.
  `spike/runtime/gguf.py::kv_cache_bytes` implements this from GGUF metadata (tested on a real file).
- Adapter size, *computed*: rank 16 on the chosen targets ≈ 21M parameters ≈ 42 MB at f16.
- Third-party reports, not verified by SPIKE: KV cache q4_0 degraded answers of a 9B Qwen3.5 in one
  coding task while q8_0 did not ([dipankar-das.com](https://dipankar-das.com/blog/i-went-deep-localllm/));
  SPIKE defaults to q8_0.

## 4. Training

Summary in [ADR 0002](adr/0002-training-method.md). Sources: Unsloth's Qwen3.5 guide (bf16 LoRA ≈ 10 GB for
4B; QLoRA not recommended for Qwen3.5; keep ≥ 75 % reasoning examples when mixing thinking and direct
data to preserve reasoning) ([unsloth.ai](https://unsloth.ai/docs/models/qwen3.5/fine-tune)); a public
mlx-lm LoRA run on Qwen3.5-4B (M1 64 GB: 11.1 GB peak, ~115 tok/s; validation loss did not predict accuracy)
([sciences44/mlx-lora-finetune](https://github.com/sciences44/mlx-lora-finetune)). mlx-lm semantics checked
in source: `iters` counts micro-batches; the optimizer and LR schedule step every
`grad_accumulation_steps`; `lora_parameters.keys` selects modules by exact path; `num_layers: -1` = all;
`lr_schedule.warmup` supported; Qwen3.5 module paths `language_model.model.layers.N.{self_attn,linear_attn,mlp}`.

Lesson applied from the sciences44 report: acceptance is decided by task metrics on held-out data, never by
validation loss.

**Replay written by the base model itself (an option, not yet measured).** The first medicine adapter, trained with
30 % oasst2 replay (human answers), was rejected for forgetting ([STATUS.md](STATUS.md)); its live probes lost the
persona and safety framing the base shows under the same system prompt and repeated a sentence. Two properties of
that replay, read from `prepare.py`: its answers are in a style the base model does not write, and its chats carry
no system prompt (`collect(..., None)`) while the domain chats do. `training/self_replay.py` makes the other kind: the
same prompts (the first user turn of the replay-source chats), answered by the base model itself, greedy, thinking off,
under the specialist's system prompt, so a replay row asks the adapter to keep doing what the base already does.
The idea that targets from the model's own distribution drift less is what two papers report, in settings that are
not this one (read: their arXiv pages, not their code). Self-Distillation Fine-Tuning ([Yang et al.,
arXiv:2402.13669](https://arxiv.org/abs/2402.13669)) has the model rewrite the task's reference answers itself and
reports, on Llama-2-7b-chat with LoRA, a smaller loss of safety and helpfulness than vanilla fine-tuning, with
general-knowledge benchmarks little changed by either. Self-Synthesized Rehearsal ([Huang et al.,
arXiv:2403.01244](https://arxiv.org/abs/2403.01244)) has the model generate its own rehearsal instances for continual
learning when the original data is unavailable, and reports general-domain ability preserved as well as or better
than conventional rehearsal. SPIKE's variant replays real prompts with the model's own answers instead, and whether it
keeps the general suite within 1.5 points on Qwen3.5-4B is open until a run is evaluated. Limits to keep in mind:
the answers come from the Q4_K_M GGUF that SPIKE serves while LoRA trains the bf16 weights; the base's own habits
(it named no option in 405 of 1,000 MedMCQA answers, STATUS.md) are copied too, since the filters only remove
truncated, empty, reasoning-bearing and looping answers; the replay is single-turn; and because the human
replay had no system prompt and this one does, a comparison of the two changes both at once.

## 5. Datasets (Hub licenses re-checked automatically at download time; URL sources use the license recorded with their pinned commit)

| Source | License | Use | Notes |
|---|---|---|---|
| [openlifescienceai/medmcqa](https://huggingface.co/datasets/openlifescienceai/medmcqa) | Apache-2.0 | medicine train (train split), eval (validation) | 183k train; expert explanations (`exp`) |
| [qiaojin/PubMedQA](https://huggingface.co/datasets/qiaojin/PubMedQA) | MIT | `pqa_artificial` train (211k), `pqa_labeled` eval (1k) | |
| [OpenAssistant/oasst2](https://huggingface.co/datasets/OpenAssistant/oasst2) | Apache-2.0 (registry value; HF blocked in the build container, re-checked at download) | general replay | human-written; en + es; one chat per best-ranked reply |
| [HuggingFaceTB/smoltalk](https://huggingface.co/datasets/HuggingFaceTB/smoltalk) smol-constraints | Apache-2.0 (card text only) | **excluded** | the Hub metadata declares no license, so the license gate refuses it, and the card does not name the generator; general replay is human-written oasst2 only |
| HuggingFaceTB/smoltalk smol-magpie-ultra | Apache-2.0 | **excluded** | generated with Llama-3.1-405B-Instruct; the [Llama 3.1 license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE) §1.b.i requires "Llama" at the start of the name of any distributed model trained on its outputs |
| [sujet-ai/Sujet-Finance-Instruct-177k](https://huggingface.co/datasets/sujet-ai/Sujet-Finance-Instruct-177k) | Apache-2.0 (aggregate); rows keep their upstream license | finance train, **filtered** by the `dataset` column to `ugursa/Yahoo-Finance-News-Sentences`, `zeroshot/twitter-financial-news-topic`, `zeroshot/twitter-financial-news-sentiment`, `yixuantt/FinEntity`; the first 2,000 rows of each (`max_per_value`), at most 8,000 | upstream audit: the four kept sources are classification and entity extraction (no QA), uploader-claimed MIT / odc-by, and their news and tweet text is third-party. Excluded: finance-alpaca (text-davinci-003 and GPT-3.5 outputs, CC BY-NC), ehc-contrived-financial (OpenAI davinci-turbo), lmsys-finance (GPT-4 and Claude outputs), financial_phrasebank and its copies (CC BY-NC-SA 3.0), FiQA_SA (non-commercial), AdaptLLM Headline and ConvFinQA (no license), FinTalk-19k, financial-classification, finqabench, FinRiskAnalysis (provenance unverified or LLM-generated) |
| [czyssrs/FinQA](https://github.com/czyssrs/FinQA) at `0f16e2867b` (original release; `train.json`, `test.json`) | MIT ([LICENSE](https://raw.githubusercontent.com/czyssrs/FinQA/0f16e2867befa6840783e58be38c9efb9229d742/LICENSE)) | finance train (6,251 questions; 385 dropped because a calculation step disagrees with its own arguments by more than 0.5 %, 5,367 chats after length and decontamination), eval (test, 1,147) | expert-written questions over S&P 500 reports with annotated programs. **Gold-facts setting**: the prompt contains the annotated supporting facts and no retrieval is done, so scores are not comparable with retriever-based FinQA results. Scored on the program's result or the annotated (rounded) answer, 0.5 % tolerance. Fetched from pinned URLs, sha256 checked on every load; dev split not used |
| [NExTplusplus/TAT-QA](https://github.com/NExTplusplus/TAT-QA) at `870accc41a` (`dataset_raw`) | MIT ([LICENSE](https://raw.githubusercontent.com/NExTplusplus/TAT-QA/870accc41953dcde885aabeb963d94aabdc0fbc3/LICENSE); the Hub card says CC BY 4.0) | finance train (13,215 questions; 7,064 chats after the 768-token limit and decontamination), eval (`test_gold`, 1,663) | hybrid table + text questions (span, multi-span, count, arithmetic) from financial reports; the table and text are given. Numbers scored with a 0.5 % tolerance ignoring scale words, %, $; spans by normalized exact match, multi-span as an unordered set. Pinned URLs with sha256; dev split not used |
| [TIGER-Lab/MMLU-Pro](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro) | MIT | eval only | 12k questions, 14 categories |
| openai/gsm8k | MIT (registry value) | eval only | re-checked on the Hub by the eval runner |
| [FreedomIntelligence/medical-o1-reasoning-SFT](https://huggingface.co/datasets/FreedomIntelligence/medical-o1-reasoning-SFT) | Apache-2.0 | **excluded** | generated with GPT-4o; OpenAI terms restrict training competing models |

## 6. Orchestration

Design and evidence in [ADR 0003](adr/0003-orchestration.md). The deciding constraint is CPU latency: every
extra model call costs a full prompt-processing pass, so routing is lexical first and the LLM planner runs
only for multi-domain or ambiguous requests. One base model with hot-swapped adapters makes specialist
switches free, which is what makes multi-specialist plans affordable on 16 GB.

## 7. Product references

Studied: claude.ai, Claude Code, Claude Cowork and DeepSeek's chat and agent harness, through their public
behaviour and documentation. Patterns adopted and reimplemented with SPIKE's own code and identity:

- Centred composer with model/specialist selector, conversation sidebar, streaming Markdown with code
  highlighting (claude.ai, DeepSeek).
- Collapsible reasoning and work trace (DeepSeek's thinking block; Claude's tool-use trace): SPIKE shows
  route, plan, per-specialist subtasks and tool calls.
- Inline permission prompts for tools with allow once / always / deny (Claude Code), configurable per tool.
- Workspace-scoped file tools and an explicit "what can the agent touch" model (Claude Code, Cowork).
- Settings split into general instructions, providers, specialists, tools and engine.

No proprietary code, assets or brand elements were copied. REA was not run against these products: they are
third-party services that SPIKE has no authorization to analyse. REA was used on SPIKE's own build
([audit](audits/2026-10-17-web-bundle-rea.md)).

## 8. Development methodology: REA and Superpowers (mandatory)

- **[Superpowers](https://github.com/obra/superpowers)** (MIT): brainstorm → plan → test-driven
  implementation → systematic debugging → verification before claiming completion → review. Applied in this
  repo: failing tests written before fixes (the adapter-scale bug was reproduced by a test that failed on the
  old code before the fix), mutation checks on the export test (a wrong LoRA magnitude makes it fail), and
  STATUS.md only lists results with evidence. Contributor workflow in [CONTRIBUTING.md](../CONTRIBUTING.md).
- **[REA](https://github.com/morluto/rea)** (MIT, `rea-agents` on npm): one MCP/CLI for evidence-backed
  reverse engineering of binaries, JavaScript/Electron apps, websites, APKs and captures. Used for the network
  audit of SPIKE's web bundle; to be used again for each release build and for any authorized target where a
  feature has to be understood from behaviour.

## 9. Open questions (answered only by measurement)

1. Real tok/s, TTFT and peak RSS of Qwen3.5-4B Q4_K_M on a 16 GB CPU-only x86 machine and on Apple Silicon.
2. Whether LoRA specialization beats the prompt-profile baseline by the acceptance margins per domain.
3. Long-context accuracy at 8K/16K/32K on 16 GB.
4. Quality of orchestrated multi-specialist answers against a single model with the same weights.
