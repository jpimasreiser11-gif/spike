<p align="center">
  <img src="brand/spike-mark.png" alt="SPIKE cactus logo" width="120">
</p>
<h1 align="center">SPIKE</h1>
<p align="center"><b>A family of small specialist models with an orchestrator, built to run on an ordinary 16 GB computer.</b><br>
Local first, open source (Apache-2.0), and able to use external API models with the same instructions, specialists and tools.</p>

---

> **Project status: early, honest.** The app, orchestrator, provider layer, local runtime and the full
> training/evaluation pipeline are built and tested. **No specialist adapter has been trained yet**, and the
> real model has not yet been benchmarked on target hardware. Until an adapter passes its acceptance tests,
> each specialist runs as a prompt profile on the base model and the app marks it β.
> Details with evidence: [docs/STATUS.md](docs/STATUS.md).

## What SPIKE is

- **One base, many specialists.** Every specialist (Finance, Medicine, Marketing, Law, Code, Science, Math,
  Data, Education, Writing, Business, Security, plus Core) shares one Qwen3.5-4B model in memory and adds a
  small LoRA adapter (~42 MB, computed). Switching specialist costs no reload.
- **An orchestrator, not a chain of calls.** A zero-cost lexical router handles clear requests; only
  multi-domain or ambiguous ones get an LLM plan (JSON, schema-validated), executed as a dependency graph
  and merged by Core. Router accuracy on a held-out set: 0.92 (46/50), measured.
- **Your models, or theirs.** The same instructions, specialist bindings and tools work with llama.cpp,
  Ollama, LM Studio, OpenAI, Anthropic, DeepSeek, Gemini, OpenRouter, Groq, Mistral, Together or any
  OpenAI-compatible server. Paid providers stay blocked until you allow them; keys live in your OS keychain.
- **Tools with permissions.** Calculator, workspace files, sandboxed Python and web fetch, each allow / ask /
  deny, with an inline permission prompt.
- **Measured, not announced.** Exact-answer evals with confidence intervals and McNemar tests, acceptance
  criteria written before training, and a benchmark command that records hardware and build.

## Quick start

Requirements: Python 3.11+, [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`), 16 GB RAM
recommended, ~3 GB disk for the model.

```bash
git clone <repository-url> spike && cd spike     # PyPI package after the first release
(cd web && npm ci && npm run build) && pipx install .
brew install llama.cpp                   # macOS / Linux with Homebrew; other platforms: official llama.cpp releases
spike doctor                             # what this machine can run, and with how much context
spike models pull qwen3.5-4b             # Q4_K_M by default, license and SHA-256 checked
spike serve --open                       # app at http://127.0.0.1:8740
```

Or use the installer scripts in [`scripts/`](scripts/) (they show every step before running it).
SPIKE works without a local model too: add an external provider in Settings → Providers.

## Documentation

| | |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | components, request flow, providers, tools |
| [Master plan](docs/PLAN.md) | the 24-point plan with acceptance criteria and status |
| [Research](docs/RESEARCH.md) | base model, engines, memory, training, datasets, references, with sources |
| [Specialists](docs/SPECIALISTS.md) | scope, data, evaluation and risks per specialist |
| [Training](docs/TRAINING.md) | train, export and evaluate an adapter on an Apple Silicon Mac |
| [Status](docs/STATUS.md) | what is verified, what is pending, blockers |
| [Decisions](docs/adr/) | ADRs: base model, training method, orchestration, adapter serving |

## Development

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,keyring]"
pytest                                    # integration tests run when SPIKE_LLAMA_SERVER / SPIKE_LLAMA_CPP are set
cd web && npm ci && npx vitest run && npm run build
```

Contributions follow a test-first, evidence-first workflow: [CONTRIBUTING.md](CONTRIBUTING.md).
Security reports: [SECURITY.md](SECURITY.md).

## License

Code: [Apache-2.0](LICENSE). Base model Qwen3.5-4B: Apache-2.0. Datasets and third-party components keep
their own licenses: [THIRD_PARTY.md](THIRD_PARTY.md). The SPIKE name and cactus logo are the project's
identity; see [brand/](brand/).

SPIKE's sensitive specialists (medicine, finance, law, security) are not professional advice and are not a
medical device.
