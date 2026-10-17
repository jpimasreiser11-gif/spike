# SPIKE status log

Persistent record of what is verified, what is built but unmeasured, and what is missing.
Rule: nothing is listed as done without the evidence next to it. Measured ≠ computed ≠ reported by others.

_Last update: 2026-10-17, commit on `main` in the development repository (not yet published)._

## Verified (with evidence)

| Area | Evidence | How to reproduce |
|---|---|---|
| Provider layer (OpenAI-compatible, Anthropic, tool emulation, paid-call guard) | 17 tests pass | `pytest tests/test_providers.py` |
| Router accuracy, held-out test split (never used for tuning) | **measured**: primary 46/50 = 0.92 (Wilson 95 % CI 0.81–0.97); exact set 40/50 = 0.80 (0.67–0.89); dev 22/24 | `pytest -s tests/test_core.py -k router_eval` |
| Planner validation, DAG execution, synthesis, agent loop, permissions, context trimming | unit tests pass | `pytest tests/test_core.py` |
| HTTP API, persistence, SSE chat | tests pass | `pytest tests/test_server.py` |
| Real llama-server: lifecycle, streaming, adapter isolation in every switch order vs fresh-server ground truth | tests pass against llama.cpp 62318cd (tiny random model) | `SPIKE_LLAMA_SERVER=… pytest tests/test_llamacpp_integration.py` |
| Bug found and fixed: `lora: []` ran the "base" model with all adapters at scale 1.0 | test fails on the old code, passes on the fix | same file, `test_empty_lora_list_is_not_the_base_model` |
| Adapter export MLX → PEFT → GGUF through llama.cpp's official converter: runtime LoRA = hand-merged weights (greedy tokens), ≠ base | test passes; a deliberately wrong LoRA magnitude makes it fail | `SPIKE_LLAMA_CPP=… SPIKE_CONVERT_PYTHON=… pytest tests/test_export_integration.py` |
| Qwen3.5 adapter names → `qwen35` GGUF LoRA tensors (`blk.N.attn_q`, `ffn_*`) | test passes on a tiny hybrid config | same file |
| Training data pipeline: license gate, template-aware decontamination, replay ratio, iters/LR schedule, mlx-lm config | 22 tests pass incl. an end-to-end `prepare.py` run on in-memory sources | `pytest tests/test_training.py` |
| Eval statistics: Wilson CI, exact McNemar, acceptance rules, pairwise summary | unit tests | same file |
| Web app: welcome, multi-specialist plan trace, tool permission card, history reload, settings, dark mode, English, mobile layout | Playwright smoke in Chromium; 5 Vitest tests | `node web/e2e/smoke.mjs` (with `tests/e2e/serve_scripted.py`), `npx vitest run` |
| Brand in the app and README: favicons, PWA manifest with maskable icon, avatar per specialist on every chip, empty-chat / error / no-model illustrations, README banner (light/dark) and specialists table | Playwright smoke passes; screenshots checked in light, dark, mobile and with the API failing; every catalog specialist has an avatar and a Hugging Face banner (test) | `node web/e2e/smoke.mjs`, `pytest tests/test_model_card.py` |
| Hugging Face model card generator: front matter, data/license table, embedded eval table and verdict, only from pipeline records | 4 unit tests (accepted, rejected, missing verdict, no advice line for non-sensitive) | `pytest tests/test_model_card.py` |
| Frontend network surface: only same-origin `/api/*` calls, one localStorage key | REA static audit | [audit](audits/2026-10-17-web-bundle-rea.md) |
| Installers: `scripts/install.sh` and `scripts/install.ps1` install pipx, build the web app, install SPIKE with pipx and run `spike doctor`; a failed model download ends with a clean error | both ran end to end with `--yes`/`-Yes` in an isolated home in the build container (Linux x86_64; `install.ps1` under PowerShell 7.4 for Linux, **not on Windows**); shellcheck clean | `HOME=$(mktemp -d) scripts/install.sh --yes` |
| Packaging: the wheel ships the web app, the sdist carries it, editable installs and the test suite need no Node.js, a wheel build without the bundle fails with a clear message | `python -m build` (wheel: 81 static files); clean dev-only venv: 69 passed, 4 skipped | `python -m build`, `pip install -e ".[dev]" && pytest` |
| Replay data licensing: Llama-3.1-generated replay (smol-magpie-ultra) excluded; human-written OpenAssistant oasst2 tree builder | Llama 3.1 license §1.b.i read in `meta-llama/llama-models`; builder unit test (ranking, review, deletion, language filters) | `pytest tests/test_training.py -k oasst` |
| CI workflow (Python on Linux/macOS/Windows, web, package, browser smoke, llama.cpp integration) | actionlint 1.7.7 + shellcheck 0.11.0 clean; llama-server built with the CI's flags (`GGML_NATIVE=OFF`, no OpenSSL) passes the 5 integration tests; **never run on GitHub** (no repository yet) | `actionlint .github/workflows/ci.yml` |
| OpenAI-compatible API `/v1` (models list, orchestrated and single-specialist completions, streaming chunks, client tool calls round trip, passthrough, approval-needing tools refused without blocking, token / loopback-only / Origin / Host checks) | 17 tests with the official `openai` Python client 3.33.0 over real HTTP; end to end against a real llama-server (tiny random model): `spike-finance` loaded the `spike-finance` adapter, streaming and usage correct | `pytest tests/test_openai_api.py` |
| Projects (own instructions and default specialist, isolated workspace for file tools, files, chats kept in their project, zip export → import identical, unsafe archives refused) | 6 API tests; browser smoke step (create, upload, export download, project chat) | `pytest tests/test_projects.py`, `node web/e2e/smoke.mjs` |
| Connectors (MCP): own client over stdio and Streamable HTTP; tools behind the broker (allow, per-tool deny, ask approved through the API); secrets only as server env; broken servers reported; one-click catalog in Settings | client tests against a server built with the official MCP SDK 2.3.0 over both transports; 9 API tests with a real uvicorn server; real upstream servers started from the catalog in the build container and one tool called on each: Filesystem 1.0.0 (14 tools), Memory 1.0.0 (9), Fetch 2026.10.10 (1, listed only), Git 2026.10.10 (12); browser smoke opens the catalog | `pytest tests/test_mcp_client.py tests/test_connectors.py` |
| Skills (Agent Skills `SKILL.md`): loader with spec validation, lexical router per specialist for local models, catalog + `load_skill` tool for API models, body cut to a quarter of the context (8K case tested), user skills override built-ins, zip import, packs (custom specialists + skills + connectors, no secrets) | 21 tests (8 routing cases in Spanish and English); browser smoke: Skills tab and a finance answer tagged with its skill | `pytest tests/test_skills.py` |
| Artifacts and documents: `create_docx`, `create_xlsx`, `create_pptx`, `create_pdf` (ask before writing, stay in the workspace, formulas that reach outside the file refused, Unicode PDF font), written files offered as downloads, HTML/SVG answers previewed in a sandboxed panel (`allow-scripts` only, CSP with `connect-src 'none'`) | 9 tests open the generated files again with python-docx, openpyxl, python-pptx and pypdf; 3 web unit tests; browser smoke: a probe page in the panel reports `storage:blocked parent:blocked api:blocked`, sends no request, the CSP refusal is logged, `.html` and `.docx` downloads arrive | `pytest tests/test_documents.py`, `node web/e2e/smoke.mjs` |
| Neural Memory: one local store (SQLite) for facts, decisions, preferences, the user's rules, chat summaries and project files; hybrid search (FTS5 BM25 + vectors, reciprocal rank fusion); rules always applied, notes recalled within a sixth of the context; deleting removes chunks, word index and vectors from the file; project files indexed on upload and forgotten on delete; summaries only from a local model; `remember` asks first | 14 tests (search by meaning with a stand-in embedder, budget at 200/600/1500 tokens, the deleted text absent from the raw database file, embeddings over HTTP from a real llama-server with the tiny model); 1 web unit test; browser smoke: a note added in Settings is recalled and shown on the next answer | `pytest tests/test_memory.py` |
| Privacy and spending: one guard in front of every provider withholds the user's file contents from remote providers unless allowed per provider (recalled file passages, file-reading tool results, answers written from files in the same run or earlier in the chat); monthly token or spend limits (prices entered by the user) stop calls before they are sent; local call log; retry a turn on another provider and edit a sent message (both replace the rest of the chat) | 13 tests, the main one on the wire: a fake OpenAI endpoint behind the real provider never receives the secret from a project file (memory passage and `read_file` result), and receives it once files are allowed (control); limits block with no request; plan and cross-turn taint; 1 web unit test; browser smoke: retry, edit, DeepSeek retry shows "Archivos protegidos", the call log lists the withheld passage | `pytest tests/test_privacy.py` |
| Undo and step-by-step view: before `write_file` or a document tool changes a file, a copy is kept (`$SPIKE_HOME/checkpoints`, 30 days, deleted with the chat); each step can be undone from the answer, and a file edited again afterwards is only overwritten after a second confirmation; every answer keeps its events with timings and can be replayed step by step | 6 tests (two writes undone back to no file, conflict refused then forced, `.docx` undone, failed calls offer no undo, copies deleted with the chat and pruned, events stored with merged text); 1 web unit test; browser smoke: undo removes the created file (404), the replay starts empty, shows the tool step and the final text, and offers no live permission buttons | `pytest tests/test_undo.py` |
| Benchmark harness end to end (TTFT, tok/s, RSS, build info) | runs against the tiny model; **its numbers are meaningless for quality or speed** | `spike bench --model <tiny.gguf>` |

Total at this update: 212 Python tests (incl. the llama.cpp integration tests) and 13 web tests pass; lint clean (`ruff check .`); browser smoke `E2E OK`.

## Measured with real weights

Qwen3.5-4B Q4_K_M (unsloth GGUF, SHA-256 verified) on joan's Mac: Apple M4 Max, 14 cores, 36 GB, macOS 27,
Homebrew llama-server b11669-620d2225c (not the CI-pinned 62318cd), KV cache q8_0. Raw JSON next to each row.

**Speed and memory** (`spike bench`, 128 generated tokens, median of 3 runs):

| backend | context | TTFT | prompt tok/s | generation tok/s | peak RSS (MiB = 1024² bytes) |
|---|---|---|---|---|---|
| CPU only (`--gpu-layers 0`) | 1K | 8.4 s | 122.5 | 40.6 | 6,307 MiB |
| | 8K | 92.3 s | 88.8 | 29.5 | 6,309 MiB |
| | 32K | 814.7 s | 40.2 | 13.8 | 6,330 MiB |
| Metal (`--gpu-layers 99`) | 1K | 0.86 s | 1197 | 82.4 | 3,653 MiB |
| | 8K | 7.2 s | 1145 | 79.8 | 3,668 MiB |
| | 32K | 36.6 s | 895 | 66.5 | 3,719 MiB |

Evidence: `evals/results/bench-mac-20261017/bench-{cpu-ngl0,metal-ngl99}.json`. CPU RSS includes the mmap'd
model file and, by inference (not measured), llama.cpp's repacked CPU copy of the weights; `spike bench` now
records `peak_rss_anon_mb` on Linux to separate them. This is an Apple CPU, not the 16 GB x86 target.

**Baseline accuracy, no adapter** ("baseline@512 (rescored)", Metal, greedy, thinking off, max_tokens 512,
specialist system prompts; generated with the old extractor and re-scored from the saved responses after the
extractor fix: 403 parses and 289 verdicts changed):

| task | n | accuracy | Wilson 95 % CI | unparsed | truncated |
|---|---|---|---|---|---|
| general (MMLU-Pro history/philosophy/psychology/other) | 800 | 0.557 | 0.523–0.592 | 105 | 166 |
| MedMCQA validation | 1000 | 0.242 | 0.216–0.270 | 440 | 194 |
| MMLU-Pro health | 818 | 0.248 | 0.220–0.279 | 298 | 314 |
| PubMedQA labeled | 500 | 0.426 | 0.383–0.470 | 0 | 470 |
| medicine (pooled) | 2318 | 0.284 | 0.266–0.303 | 738 | 978 |

Evidence: `evals/results/baseline-mac-20261017/summary.{json,md}`. A diagnostic, not the adapter comparison:
many medicine answers end with a disclaimer and name no option (scored as wrong), and 94 % of PubMedQA answers
hit the 512-token limit. The adapter verdict comes from base and adapter evaluated in one run at 2048 tokens.

**Training data, medicine** (`training/data/medicine/manifest.json` on the Mac): 26,050 training examples,
6,513 iterations; replay 0.30 of the mix from 13,002 OpenAssistant chats built from the real dataset (12,994
kept); MedMCQA keeps 12,609 of 24,000 rows (short explanations and multi-answer questions dropped); 21 examples
removed for sharing a 13-gram with an eval set.

**Training memory and speed, Qwen3.5-4B LoRA with mlx-lm on the M4 Max (36 GB)**, measured on joan's Mac
2026-10-17: the first medicine run (batch 4, 2048 tokens) ran out of Metal memory on its first step. One LoRA step
with gradient checkpointing peaks at 11 GB with 128-token sequences, 23 GB at 768 and over 27 GB at 1024 (out of
memory), about 19 MB per token. The recipe is now batch 1 × 16 accumulation (same effective batch and updates)
and at most 768 tokens per example, longer chats dropped rather than truncated (4.0 % of medicine's): 18.7 GB
peak RSS, no swap growth. Speed: 64 examples in 647 s (≈ 9.5 s each), because mlx-lm trains Qwen3.5's
Gated DeltaNet layers with a per-token loop (its Metal kernel has no backward pass); one medicine epoch (25,010
examples) would have taken ≈ 66 h. Fixed with a chunked, differentiable delta rule
(`training/spike_train/gated_delta_chunked.py`, 16-token chunks, training path only): on the same 64 medicine
chats 112.5 s vs 647 s (5.7×, 110 vs 21 tok/s), train loss 1.675 vs 1.672, val loss 0.564 vs 0.566, peak RSS
11.4 GB; on real Qwen3.5-4B activations the 24 linear-attention layers match mlx-lm's loop within 4.9e-4, and one
LoRA step's gradients have min cosine 0.998. Projected full medicine epoch ≈ 10 h (estimate from that rate, not
yet measured).

## Built, not yet measured with real weights

- Qwen3.5-4B inference speed, TTFT and peak RSS on a 16 GB CPU-only x86 machine (Apple Silicon measured above).
- Any trained adapter: medicine is ready to run on the Mac (waiting for joan's go-ahead on one ≈ 10 h run or
  ≈ 3 h slices resumed from checkpoints); finance and marketing follow.
- End-to-end quality of orchestrated answers; long-context accuracy.
- Which skills the local 4B model actually follows (the table goes here only once measured with real weights).
- Memory search quality with the real embedding model (Qwen3-Embedding-0.6B): the meaning-only similarity floor (0.45) is a placeholder until calibrated on a labelled set; embedding speed and RAM on the 16 GB target.
- Live calls to external providers (needs the user's keys; never done without explicit configuration).
- Installers on fresh macOS and Windows machines (Homebrew and winget paths not exercised; Linux path verified above).
- The first GitHub Actions run.

## Computed (not measured)

- KV cache of Qwen3.5-4B: 32 KiB/token f16, ≈ 17 KiB q8_0 → 32K context ≈ 1.0 GiB f16 / 0.53 GiB q8_0.
- Adapter size rank 16 on the chosen targets: ≈ 21M parameters ≈ 42 MB f16.
- 16 GB budget at 32K, Q4_K_M: 2.74 GB weights + 0.53 GiB KV + ~0.5 GB buffers + 13 adapters (0.55 GB) ≈ 4.4 GB.

## Blockers

1. **No model weights in the build container**: its network policy blocks huggingface.co, so real-model
   benchmarks and evals run on joan's Mac. joan has since allowed huggingface.co in a newer cloud environment, and
   the 16 GB CPU-only measurement is running there; its numbers go here once they exist.
2. **Publication**: joan chose a private GitHub repository `spike`; waiting for joan to create it (sessions cannot
   create repositories). Nothing has been pushed.

## Next steps (in order)

1. ~~Benchmark CPU-only and Metal on the Mac~~ (done, above); the 16 GB x86 CPU benchmark needs huggingface.co.
2. ~~Baseline evals on the Mac~~ (done, above).
3. Train, export and evaluate the medicine adapter; accept or reject by its criteria.
4. Finance, then marketing (teacher distillation).
5. Long-context eval; orchestrated vs single-model pairwise eval.
6. Choose the repository, enable CI, publish with measured tables.
