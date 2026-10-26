<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/github/readme-banner-dark.png">
  <img alt="SPIKE" src="brand/github/readme-banner-light.png">
</picture>

<p align="center"><b>A family of small specialist models with an orchestrator, built to run on an ordinary 16 GB computer.</b><br>
Local first, open source (Apache-2.0), and able to use external API models with the same instructions, specialists and tools.</p>

---

> **Project status: early, honest.** The app, orchestrator, provider layer, local runtime and the full
> training/evaluation pipeline are built and tested. **No specialist adapter has been trained yet.** Until an
> adapter passes its acceptance tests, each specialist runs as a prompt profile on the base model and the app
> marks it β.
> Details with evidence: [docs/STATUS.md](docs/STATUS.md).

## What SPIKE is

- **One base, many specialists.** Every specialist (Finance, Medicine, Marketing, Law, Code, Science, Math,
  Data, Education, Writing, Business, Security, plus Core) shares one Qwen3.5-4B model in memory and adds a
  small LoRA adapter (~42 MB, computed). Switching specialist costs no reload.
- **An orchestrator, not a chain of calls.** A zero-cost lexical router handles clear requests; only
  multi-domain or ambiguous ones get an LLM plan (JSON, schema-validated), executed as a dependency graph
  and merged by Core. Router accuracy: 0.92 (46/50) on the original test split, but only 0.46 (60/130) on a set written blind
  later (2026-10-26), because the first questions were written with the keywords; being improved, measured.
- **Your models, or theirs.** The same instructions, specialist bindings and tools work with llama.cpp,
  Ollama, LM Studio, OpenAI, Anthropic, DeepSeek, Gemini, OpenRouter, Groq, Mistral, Together or any
  OpenAI-compatible server. Paid providers stay blocked until you allow them; keys live in your OS keychain.
- **Tools with permissions.** Calculator, workspace files, sandboxed Python and web fetch, each allow / ask /
  deny, with an inline permission prompt.
- **Memory.** SPIKE remembers facts, decisions, your rules, chat summaries and project files, finds them by
  words and meaning, and shows what it used; everything is local and editable.
- **Artifacts and documents.** HTML and SVG answers open in an isolated side panel; Word, Excel, PowerPoint and
  PDF files are written to your workspace and offered as downloads.
- **Projects.** Instructions, a default specialist, files and chats per project; file tools work in the
  project's own folder; export and import a project as one zip.
- **Skills and connectors.** Agent Skills (`SKILL.md`) chosen per request for small local models, MCP
  connectors from a reviewed one-click catalog, both behind the same permissions.
- **Works with your tools.** An OpenAI-compatible endpoint (`/v1`) lets Aider, OpenCode, Continue, open-design
  or any OpenAI SDK use `spike-auto` or a single specialist ([integrations](docs/INTEGRATIONS.md)).
- **Measured, not announced.** Exact-answer evals with confidence intervals and McNemar tests, acceptance
  criteria written before training, and a benchmark command that records hardware and build.

<table>
  <tr><td align="center"><img src="brand/specialists/core/avatar-core-128.png" width="56" alt=""><br>Core</td><td align="center"><img src="brand/specialists/code/avatar-code-128.png" width="56" alt=""><br>Code</td><td align="center"><img src="brand/specialists/finance/avatar-finance-128.png" width="56" alt=""><br>Finance</td><td align="center"><img src="brand/specialists/medicine/avatar-medicine-128.png" width="56" alt=""><br>Medicine</td><td align="center"><img src="brand/specialists/law/avatar-law-128.png" width="56" alt=""><br>Law</td><td align="center"><img src="brand/specialists/marketing/avatar-marketing-128.png" width="56" alt=""><br>Marketing</td><td align="center"><img src="brand/specialists/science/avatar-science-128.png" width="56" alt=""><br>Science</td></tr>
  <tr><td align="center"><img src="brand/specialists/data/avatar-data-128.png" width="56" alt=""><br>Data</td><td align="center"><img src="brand/specialists/math/avatar-math-128.png" width="56" alt=""><br>Math</td><td align="center"><img src="brand/specialists/education/avatar-education-128.png" width="56" alt=""><br>Education</td><td align="center"><img src="brand/specialists/writing/avatar-writing-128.png" width="56" alt=""><br>Writing</td><td align="center"><img src="brand/specialists/business/avatar-business-128.png" width="56" alt=""><br>Business</td><td align="center"><img src="brand/specialists/security/avatar-security-128.png" width="56" alt=""><br>Security</td></tr>
</table>

Scope, data and evaluation of each one: [docs/SPECIALISTS.md](docs/SPECIALISTS.md).

## Why SPIKE

1. **Small enough for the computer you have.** One 4B base model (Qwen3.5-4B, Q4_K_M) ran on a 16 GB CPU-only
   machine at 5.1–6.2 tok/s up to an 8K prompt, with 3.6 GiB of anonymous memory (peak RSS 6.1 GiB, which also counts
   the mapped model file). The slow cases are published too, below.
2. **Specialists that share one model.** Thirteen specialists share the base in memory and, once trained, switch as
   ~42 MB adapters (computed) without a reload. Today none has a trained adapter that passed its acceptance test:
   each runs as a prompt profile on the base model, is marked β, and is not claimed to beat the base until it passes.
3. **Routing before spending compute.** A lexical router sends clear requests to a specialist without a model
   call (46/50 on a held-out set, measured); only multi-domain or ambiguous requests get an LLM plan.
4. **Local first, external APIs when you choose.** The same instructions, specialists and tools run on the local
   model or on providers you allow; paid ones stay blocked until you enable them (tested against stand-in
   endpoints, not yet against live services).
5. **Evidence before announcements.** Each number comes with the command that reproduces it, and negative results
   stay in [docs/STATUS.md](docs/STATUS.md): the multi-agent Forge mode showed no gain over the base model alone in
   four runs, so it is not announced.

## Speed on real hardware (measured)

Qwen3.5-4B Q4_K_M, llama.cpp, KV cache q8_0, 128 generated tokens, median of 3 runs:

| machine | prompt | time to first word | generation | memory |
|---|---|---|---|---|
| 16 GB x86, 4 cores, CPU only | 1K tokens | 52 s | 6.2 tok/s | 3.6 GiB anonymous, 6.1 GiB RSS with the mapped model file |
| | 8K tokens | 13 min | 5.1 tok/s | 3.6 GiB anonymous, 6.1 GiB RSS |
| Apple M4 Max, Metal | 1K tokens | 0.9 s | 82 tok/s | 3.6 GiB RSS |
| | 8K tokens | 7.2 s | 80 tok/s | 3.6 GiB RSS |

On a CPU-only computer SPIKE starts at an 8K context: a 32K prompt took about 1.5 h to the first word there. Raw reports and
method: [docs/STATUS.md](docs/STATUS.md#measured-with-real-weights).

## SPIKE next to Ollama, LM Studio, Open WebUI and Jan

These tools do different jobs, and SPIKE is new. The table says what each one *is*; it does not rank quality or
speed. Cells about the others come from each project's own repository, docs or site, checked 2026-10-20 (sources
below). **"not checked"** means it was not looked up for this table, not that the feature is missing. The SPIKE column
follows [docs/STATUS.md](docs/STATUS.md).

| | SPIKE | Ollama | LM Studio | Open WebUI | Jan |
|---|---|---|---|---|---|
| Code license | Apache-2.0 | MIT | Proprietary app, free to use at home and at work; its CLI, SDKs and MLX engine are MIT | Own license since v0.6.6: a branding clause on top of BSD-3-style terms (its docs: not OSI-approved); BSD-3 up to v0.6.5 | Apache-2.0 |
| Runs models on your computer | Yes, through llama.cpp | Yes (cloud models are optional) | Yes, llama.cpp; MLX on Apple Silicon | Connects to Ollama and OpenAI-compatible servers that run the models | Yes, llama.cpp |
| Models you get | Downloads one base, Qwen3.5-4B (SHA-256 checked). No specialist adapter is trained or accepted yet | A library of many open models from other makers | A catalog of other makers' models (56 listed, 47 local) and Hugging Face search | Whatever its connected servers offer | Downloads models from Hugging Face |
| Routes a request to a specialist by itself | Yes: lexical router plus a planner for multi-domain requests; specialists are prompt profiles for now | not checked | not checked | Not described in its feature docs; you pick a model or a preset | not checked |
| OpenAI-compatible API | Yes: `/v1` with `spike-auto` or one specialist; tested with the official `openai` client | Yes, a subset: chat completions, responses, completions, embeddings, models | Yes: responses, chat completions, completions, embeddings, models | Its own API has an OpenAI-compatible chat completions endpoint | Yes: local server at `127.0.0.1:1337/v1` |
| MCP | Client (stdio, Streamable HTTP) and server; tested with the official MCP SDK, not with Claude Code, Cursor or Codex | Client not checked; its docs offer a web-search MCP server for other clients | MCP host since 0.3.17 | Native since v0.6.31, Streamable HTTP only (stdio via the mcpo proxy) | Supported; needs a model with tool calling |
| GPU backends | CPU and Metal measured; no other GPU backend tested | NVIDIA CUDA, AMD ROCm, Apple Metal, Vulkan | Apple Silicon on macOS; 4 GB+ VRAM recommended on Windows; the rest not checked | Left to the server it connects to | CUDA (NVIDIA), Vulkan (AMD, Intel), Metal |
| Several users | No accounts or roles: built for one person on one computer | not checked | not checked | Yes: roles, groups, per-resource permissions | not checked |

Sources, all checked 2026-10-20:

- **Ollama**: [LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE) (MIT), [quickstart](https://docs.ollama.com/quickstart) and [FAQ](https://docs.ollama.com/faq) (runs locally), [model library](https://ollama.com/library), [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility), [hardware support](https://docs.ollama.com/gpu), [web search (MCP server)](https://docs.ollama.com/capabilities/web-search), [docs index](https://docs.ollama.com/llms.txt).
- **LM Studio**: [terms](https://lmstudio.ai/terms) (proprietary software), [free for work](https://lmstudio.ai/blog/free-for-work), [GitHub organization](https://github.com/lmstudio-ai) (MIT repositories), [docs home](https://lmstudio.ai/docs/app) (llama.cpp, MLX), [model catalog](https://lmstudio.ai/models), [OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat), [MCP](https://lmstudio.ai/docs/app/mcp), [system requirements](https://lmstudio.ai/docs/app/system-requirements).
- **Open WebUI**: [LICENSE](https://github.com/open-webui/open-webui/blob/main/LICENSE), [license page](https://docs.openwebui.com/license/), [README](https://github.com/open-webui/open-webui) (connects to Ollama and OpenAI-compatible APIs, roles and groups), [getting started](https://docs.openwebui.com/getting-started/), [features](https://docs.openwebui.com/features/), [API endpoints](https://docs.openwebui.com/getting-started/api-endpoints), [MCP](https://docs.openwebui.com/features/extensibility/mcp).
- **Jan**: [LICENSE](https://github.com/janhq/jan/blob/main/LICENSE) and [README](https://github.com/janhq/jan) (Apache-2.0, Hugging Face models, local server), [API server](https://docs.jan.ai/desktop/api-server), [MCP](https://www.jan.ai/docs/desktop/mcp), [local engine](https://docs.jan.ai/desktop/llama-cpp) (llama.cpp, CUDA, Vulkan, Metal).

What they do that SPIKE does not:

- **Ollama** offers a library of many models where SPIKE offers one base, documents four GPU backends, and lists many
  integrations. SPIKE can point at an Ollama server as an OpenAI-compatible provider (not tried against the real product).
- **LM Studio** is a desktop app with an in-app model catalog, a CLI, SDKs and a headless mode (`llmster`).
- **Open WebUI** describes itself as multi-user, with roles and groups, document search (RAG) and a model arena.
  SPIKE is one person on one computer.
- **Jan** is a desktop app with installers for Windows, macOS and Linux. SPIKE is a Python package plus llama.cpp,
  set up from the terminal or by the installer scripts; it has no packaged desktop app.
- **SPIKE is new**: it has the measurements in this repository and no track record yet.

Not claimed here: that SPIKE answers better than any of them (no specialist has an accepted evaluation verdict, and
none is shown to beat the base model), or that it is faster (the others were not benchmarked). SPIKE's bet is a
router and specialists on one small model that fits a CPU-only 16 GB computer, with numbers published next to the
command that reproduces them.

## Quick start

Requirements: Python 3.11+, [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`), 16 GB RAM
recommended, ~3 GB disk for the model.

```bash
git clone <repository-url> spike && cd spike     # PyPI package after the first release
(cd web && npm ci && npm run build) && pipx install ".[docs,finance,data,motion]"
brew install llama.cpp                   # macOS / Linux with Homebrew; other platforms: official llama.cpp releases
spike doctor                             # what this machine can run, and with how much context
spike models pull qwen3.5-4b             # Q4_K_M by default, license and SHA-256 checked
spike tune                               # optional: measures threads and KV cache here, saves the fastest
spike serve --open                       # app at http://127.0.0.1:8740
```

Or use the installer scripts in [`scripts/`](scripts/) (they show every step before running it).
SPIKE works without a local model too: add an external provider in Settings → Providers.
Pages, slides and documents can follow a design system (`DESIGN.md`): SPIKE's own, 20 generic ones, or yours (Settings → Diseño).
Spike Finance reads public prices, runs backtests, measures portfolio risk and keeps a paper trading account; real orders stay off unless you set them up, and each one waits for your click (Settings → Finanzas).
Spike Data answers questions about CSV, Excel, Parquet, JSON or SQLite files with SQL it shows you, draws charts from the results and exports the analysis as a page, Word or PDF.
Crear (Create) turns a template (web page, app, dashboard, data to app, Word document, presentation, automation) and a few answers into a Forge plan you review; the team builds it with the template's skill and your design system and checks it against the plan.
Spike Motion makes videos from code: the model writes an animated HTML/SVG scene and SPIKE renders it frame by frame to MP4, WebM or GIF, in the chat or with `spike render escena.html` (needs ffmpeg and Chrome or Chromium; `spike render --install-browser` downloads Chromium).
SPIKE improves from your use, on your computer: it tries the rules from your corrections on each specialist's prompt and keeps them only if more of your eval questions pass (`spike evolve optimize medicine`); with your consent, approved corrections become retraining data (`spike evolve dataset`).
To code in a folder from the terminal: `spike dev [folder]` (edits and commands ask first; `/undo` puts files back).
Connectors (MCP servers) can bring their own views (MCP Apps), which SPIKE shows isolated next to the tool's result.
Other agents can use SPIKE too: as an OpenAI-compatible endpoint (`/v1`) or as an MCP server (`spike mcp`, for
Claude Code, Cursor or Codex); see [integrations](docs/INTEGRATIONS.md).

## Documentation

| | |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | components, request flow, providers, tools |
| [Master plan](docs/PLAN.md) | the 24-point plan, adopted improvements, acceptance criteria and status |
| [Research](docs/RESEARCH.md) | base model, engines, memory, training, datasets, references, with sources |
| [Specialists](docs/SPECIALISTS.md) | scope, data, evaluation and risks per specialist |
| [Training](docs/TRAINING.md) | train, export and evaluate an adapter on an Apple Silicon Mac |
| [Integrations](docs/INTEGRATIONS.md) | use SPIKE from Aider, OpenCode, Continue, open-design and OpenAI SDKs |
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
