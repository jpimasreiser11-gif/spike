# SPIKE master plan

Living document. Every item has dependencies, verifiable tasks, deliverables and acceptance criteria.
Status legend: **✅ verified** (evidence linked), **🟡 built, not yet measured with real weights**,
**⬜ pending**. Evidence and measurements live in [STATUS.md](STATUS.md); decisions in [adr/](adr/).

Phases (from the directive's priorities): **P1** prove a quality system runs on our resources →
**P2** validate specialization, collaboration and context → **P3** consolidate app, integrations and
distribution. P3 work that was cheap to do early (app, providers) is already built, but nothing in P2 is
claimed until measured.

---

## 1. Overall feasibility
- **Decision**: one 4B base + LoRA adapters + router/planner is feasible on 16 GB: weights 2.74 GB (Q4_K_M),
  KV ~0.5 GiB at 32K with q8_0 (computed), adapters ~40 MB each (computed).
- **Depends on**: 2, 4, 17. **Tasks**: measure RSS, TTFT, tok/s on a 16 GB CPU-only machine (`spike bench --gpu-layers 0`).
- **Acceptance**: peak RSS ≤ 8 GB at 32K context; ≥ 5 tok/s generation on a 4-core x86 CPU; numbers in STATUS.md with hardware.
- **Status**: 🟡 harness verified on a tiny model; real model not yet benchmarked (the build container cannot download weights).

## 2. Base model selection
- **Decision**: Qwen3.5-4B (Apache-2.0); alternative Gemma 4 E4B. [ADR 0001](adr/0001-base-model.md).
- **Tasks**: run `evals/run_eval.py --suites general` on both candidates on the Mac; keep the decision only if Qwen3.5 ≥ Gemma.
- **Acceptance**: measured general-suite accuracy recorded for both. **Status**: 🟡 decision from published data; own comparison pending.

## 3. Specialist architecture
- **Decision**: 13 specialists (core, code, finance, medicine, law, marketing, science, data, math, education,
  writing, business, security) = the brand catalogue; one adapter each except core. Catalogue in
  `spike/specialists/catalog.yaml`, details in [SPECIALISTS.md](SPECIALISTS.md).
- **Acceptance**: each adapter passes its config's acceptance block; until then it runs as a prompt profile marked β.
- **Status**: ✅ catalogue, prompts and routing keywords; ⬜ adapters (none trained yet).

## 4. Shared memory / model management
- **Decision**: one llama-server process, all adapters loaded, per-request explicit scales, `--parallel 1`. [ADR 0004](adr/0004-adapter-serving.md).
- **Acceptance**: adapter isolation equals fresh-server ground truth in every switch order.
- **Status**: ✅ `tests/test_llamacpp_integration.py` (found and fixed the `lora: []` = all-adapters bug).

## 5. Training and adaptation
- **Decision**: bf16 LoRA on mlx-lm, verified distillation, replay. [ADR 0002](adr/0002-training-method.md).
- **Tasks**: per specialist `prepare.py` → (`distill.py`) → `train.sh` → `export_adapter.py` → eval; one command: `training/scripts/run_specialist.sh`.
- **Acceptance**: config acceptance criteria met on held-out evals; `run.json` + eval `summary.json` committed.
- **Status**: ✅ pipeline unit/integration tested (export numerically verified); ⬜ first real run (medicine) on the Mac.

## 6. Datasets and licenses
- **Decision**: registry `training/datasets.yaml` with role (train/eval/excluded), license re-checked on the Hub; train allowlist = permissive licenses only.
- **Acceptance**: prepare.py refuses non-allowlisted or role-mismatched sources; manifest records license and SHA-256 per run.
- **Status**: ✅ gate tested (`tests/test_training.py`); 🟡 sources for medicine/finance/marketing chosen; others pending.
  Llama-3.1-generated replay (smol-magpie-ultra) excluded after reading the Llama 3.1 license (§1.b.i: models trained on
  its outputs must start their name with "Llama"); human-written OpenAssistant oasst2 replaces it.

## 7. Reasoning capability
- **Decision**: keep Qwen3.5 thinking mode available; train on explanation-rich answers (MedMCQA `exp` ≥ 40 chars, PubMedQA long answers, verified teacher traces optional via `--keep-reasoning`); planner and short answers run without thinking.
- **Acceptance**: no drop on general suite; per-domain gains with reasoning prompts. **Status**: 🟡.

## 8. Context and optimization
- **Decision**: hybrid attention keeps KV small; default context by RAM (`spike/runtime/hardware.py`: <7.5 GB → 8K, <15.5 GB → 16K, <31 GB → 32K, else 64K), q8_0 KV; token-budget trimming keeps system prompt + latest turn (`spike/core/context.py`).
- **Tasks**: long-context eval (needle and LongBench-style) at 8K/16K/32K on the real model; measure TTFT vs prompt length.
- **Acceptance**: documented maximum context where accuracy stays within 5 points of 4K and RSS fits 16 GB. **Status**: 🟡 trimming tested; long-context eval ⬜.

## 9. Multi-model orchestration
- **Decision**: lexical router → JSON-schema planner only when needed → DAG → synthesis. [ADR 0003](adr/0003-orchestration.md).
- **Acceptance**: router test split ≥ 0.85 primary (met: 0.92); orchestrated answers beat single-model answers on a multi-domain set (pairwise) — pending real weights.
- **Status**: ✅ router measured; 🟡 end-to-end quality.

## 10. External providers
- **Decision**: one OpenAI-compatible provider (llama.cpp, Ollama, LM Studio, OpenAI, DeepSeek, Gemini, OpenRouter, Groq, Mistral, Together, custom) + native Anthropic; tool calling emulated with `<tool_call>` blocks when not native; paid providers blocked unless `allow_paid`; keys in the OS keychain.
- **Acceptance**: same custom instructions, specialist binding and tools work across providers; limitations reported, not simulated.
- **Status**: ✅ unit-tested with recorded wire formats (17 provider tests); ⬜ live checks against real APIs (needs user keys; never run without them).

## 11. Backend
- **Decision**: FastAPI + SSE, SQLite store, permission broker for tools, runtime manager. `spike/server/app.py`.
- **Acceptance**: API covered by tests; chat streams, persists and recovers. **Status**: ✅ `tests/test_server.py`.

## 12. Frontend
- **Decision**: React 18 + Vite + TypeScript, no UI framework; Markdown sanitized (DOMPurify); fonts bundled.
- **Acceptance**: every visible control is wired to a real endpoint; e2e smoke in a real browser (desktop, mobile, dark mode).
- **Status**: ✅ `web/e2e/smoke.mjs`, `web/src/run.test.ts`.

## 13. Visual design
- **Decision**: joan's official cactus logo and palette (`brand/`); derived icons only; specialist colours; light/dark.
- **Acceptance**: no invented logo; brand consistent in app, README and installers. **Status**: ✅ app (favicons, PWA icons, specialist avatars, empty/error/no-model illustrations) and README from joan's brand set in `brand/`; ✅ Hugging Face model cards (`training/model_card.py`, per-specialist banner); ⬜ native installer icons and DMG/NSIS art, ready in `brand/icons/` and `brand/installers/`, wait for native packages (today's installers are scripts).

## 14. Tools and connectors
- **Decision**: built-in tools with per-tool allow/ask/deny: calculator, time, workspace read/list/write, sandboxed Python (rlimits, timeout; network not blocked, documented), web fetch (private IPs blocked).
- **Acceptance**: permission card flow works end to end; tools refuse path traversal and private addresses.
- **Status**: ✅ unit + e2e. MCP connectors ⬜ (planned after P2; must reuse the same permission broker).

## 15. Reverse engineering of the references
- **Decision**: study public behaviour of claude.ai, Claude Code, Cowork and DeepSeek (layout, streaming, trace of tool use, permission prompts, settings structure); reproduce principles with SPIKE's own code and identity. REA is used only on software we own or are authorized to analyse. Findings in [RESEARCH.md](RESEARCH.md#product-references).
- **Status**: ✅ patterns applied (centred composer, collapsible traces, inline permission cards, model/specialist picker).

## 16. Development skills and tools
- **Decision**: Superpowers methodology (brainstorm → plan → TDD → verify before claiming) in [CONTRIBUTING.md](../CONTRIBUTING.md); REA for evidence-based analysis of authorized targets; llama.cpp, mlx-lm, Playwright, Vitest, Ruff.
- **Status**: ✅ applied (red tests before fixes, e.g. the adapter-scale bug).

## 17. Performance on 16 GB machines
- **Tasks**: `spike doctor` (memory plan) and `spike bench` on (a) a 16 GB x86 CPU-only machine, (b) Apple Silicon; record build, threads, quant, KV type.
- **Acceptance**: measured table in STATUS.md; installer refuses or warns below requirements. **Status**: 🟡 tools ready; measurements ⬜.

## 18. System compatibility
- **Decision**: claim only tested platforms. Targets: macOS arm64 (Metal), Linux x86_64 (AVX2), Windows x86_64.
- **Acceptance**: CI green on Linux/macOS/Windows for the app; real-model smoke per platform before claiming it.
- **Status**: ✅ Linux x86_64 (tests incl. real llama-server); ⬜ others.

## 19. Installation and distribution
- **Decision**: `pipx`/`uv tool` install of the Python package with the built web app inside; `scripts/install.sh` / `install.ps1` show and confirm each step, install llama.cpp through its official Homebrew formula or winget package (or point to the official releases) and run `spike doctor`; model download with license check and SHA-256 verification (`spike models pull`).
- **Acceptance**: fresh-machine install to first answer in ≤ 3 commands, verified per platform. **Status**: 🟡 both scripts run end to end in an isolated home on Linux (`install.ps1` under PowerShell 7.4 on Linux, not on Windows); wheel and sdist build verified; ⬜ fresh macOS/Windows machines.

## 20. Tests and benchmarks
- **Decision**: pytest (unit, API, real llama-server integration, official-converter export), Vitest, Playwright smoke, router eval, model evals with Wilson CIs and McNemar, `spike bench`.
- **Acceptance**: CI runs everything that needs no weights; model results reproducible from committed configs. **Status**: ✅ 74 Python + 5 web tests; CI workflow (`.github/workflows/ci.yml`: Python on Linux/macOS/Windows, web, package, browser smoke, llama.cpp integration) lint-checked with actionlint + shellcheck, ⬜ not yet run on GitHub (no repository); ⬜ model results.

## 21. Documentation
- README, ARCHITECTURE, RESEARCH, PLAN, STATUS, SPECIALISTS, TRAINING, ADRs, SECURITY, CONTRIBUTING, THIRD_PARTY. **Status**: ✅ written; kept in sync with evidence.

## 22. Licensing and publication
- **Decision**: code Apache-2.0; adapters Apache-2.0 (base is Apache-2.0); datasets used only under allowlisted licenses with attribution in THIRD_PARTY.md and each adapter's manifest; no third-party brand assets.
- **Acceptance**: every released artifact has a license and provenance record. **Status**: ✅ code; ⬜ adapters (none yet).

## 23. Open-source strategy
- **Plan**: publish when P1 measurements exist (real numbers make the README credible); good-first-issues for new specialists' recipes; reproducible eval tables; issue templates; transparent STATUS.md.
- **Status**: ✅ issue templates (bug, specialist recipe) and PR template in `.github/`; joan chose a private GitHub repository `spike`, made public once P1 results exist; ⬜ first push.

## 24. Objective completion criteria
SPIKE 1.0 is done only when all 15 conditions of the directive hold with evidence. Current mapping:

| # | Condition | Status |
|---|---|---|
| 1 | Viable, documented architecture | ✅ ADRs 0001–0004 |
| 2 | Real specialist adapters with data, configs, evals | ⬜ pipeline ✅, adapters pending |
| 3 | Orchestrator coordinates verifiably | ✅ tests + router eval; 🟡 real-weight quality |
| 4 | Runs on target hardware, limits measured | ⬜ |
| 5 | Real professional app | ✅ |
| 6 | Local specialists usable | 🟡 as prompt profiles until adapters pass |
| 7 | External providers unified | ✅ unit-tested; ⬜ live |
| 8 | Configurable instructions work per backend | ✅ tests |
| 9 | Tools work | ✅ |
| 10 | Main components tested | ✅ |
| 11 | Usable install and distribution | 🟡 |
| 12 | Documented | ✅ |
| 13 | Licenses respected | ✅ gate; ⬜ adapter releases |
| 14 | Repo ready for open source | 🟡 waiting for repository |
| 15 | Reproducible evidence of function, performance, quality | 🟡 function ✅; performance and quality ⬜ |
