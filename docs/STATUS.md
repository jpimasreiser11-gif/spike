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
| Frontend network surface: only same-origin `/api/*` calls, one localStorage key | REA static audit | [audit](audits/2026-10-17-web-bundle-rea.md) |
| Installers: `scripts/install.sh` and `scripts/install.ps1` install pipx, build the web app, install SPIKE with pipx and run `spike doctor`; a failed model download ends with a clean error | both ran end to end with `--yes`/`-Yes` in an isolated home in the build container (Linux x86_64; `install.ps1` under PowerShell 7.4 for Linux, **not on Windows**); shellcheck clean | `HOME=$(mktemp -d) scripts/install.sh --yes` |
| Packaging: the wheel ships the web app, the sdist carries it, editable installs and the test suite need no Node.js, a wheel build without the bundle fails with a clear message | `python -m build` (wheel: 64 static files); clean dev-only venv: 69 passed, 4 skipped | `python -m build`, `pip install -e ".[dev]" && pytest` |
| Replay data licensing: Llama-3.1-generated replay (smol-magpie-ultra) excluded; human-written OpenAssistant oasst2 tree builder | Llama 3.1 license §1.b.i read in `meta-llama/llama-models`; builder unit test (ranking, review, deletion, language filters) | `pytest tests/test_training.py -k oasst` |
| CI workflow (Python on Linux/macOS/Windows, web, package, browser smoke, llama.cpp integration) | actionlint 1.7.7 + shellcheck 0.11.0 clean; llama-server built with the CI's flags (`GGML_NATIVE=OFF`, no OpenSSL) passes the 5 integration tests; **never run on GitHub** (no repository yet) | `actionlint .github/workflows/ci.yml` |
| Benchmark harness end to end (TTFT, tok/s, RSS, build info) | runs against the tiny model; **its numbers are meaningless for quality or speed** | `spike bench --model <tiny.gguf>` |

Total at this update: 74 Python tests and 5 web tests pass; lint clean (`ruff check .`); browser smoke `E2E OK`.

## Built, not yet measured with real weights

- Qwen3.5-4B inference speed, TTFT and peak RSS on a 16 GB CPU-only machine and on Apple Silicon.
- Any trained adapter (medicine, finance, marketing recipes are ready; nothing has been trained).
- End-to-end quality of orchestrated answers; long-context accuracy.
- Live calls to external providers (needs the user's keys; never done without explicit configuration).
- Installers on fresh macOS and Windows machines (Homebrew and winget paths not exercised; Linux path verified above).
- OpenAssistant oasst2 rows from the Hub: the builder follows the published schema (`message_id`, `parent_id`, `role`,
  `rank`, `review_result`, `deleted`, `synthetic`, `lang`), not yet read from the real dataset because the build
  container cannot reach huggingface.co; `prepare.py` stops if a source builds no chats.
- The first GitHub Actions run.

## Computed (not measured)

- KV cache of Qwen3.5-4B: 32 KiB/token f16, ≈ 17 KiB q8_0 → 32K context ≈ 1.0 GiB f16 / 0.53 GiB q8_0.
- Adapter size rank 16 on the chosen targets: ≈ 21M parameters ≈ 42 MB f16.
- 16 GB budget at 32K, Q4_K_M: 2.74 GB weights + 0.53 GiB KV + ~0.5 GB buffers + 13 adapters (0.55 GB) ≈ 4.4 GB.

## Blockers

1. **No model weights in the build container**: its network policy blocks huggingface.co, so real-model
   benchmarks and evals must run on joan's Mac (or the environment must allow huggingface.co; the container
   itself is a 4-core x86 machine with 15.7 GB RAM, a good proxy for the 16 GB CPU-only target).
2. **Publication**: no GitHub repository chosen yet; nothing has been pushed.

## Next steps (in order)

1. Benchmark Qwen3.5-4B Q4_K_M CPU-only and with Metal (`spike bench`), record here.
2. `general` + `medicine` baseline evals of the prompt-profile system (no adapter) on the Mac.
3. Train, export and evaluate the medicine adapter; accept or reject by its criteria.
4. Finance, then marketing (teacher distillation).
5. Long-context eval; orchestrated vs single-model pairwise eval.
6. Choose the repository, enable CI, publish with measured tables.
