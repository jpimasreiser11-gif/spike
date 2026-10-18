# Changelog

All notable changes to SPIKE. Versions follow [Semantic Versioning](https://semver.org/). Every number here
comes from [docs/STATUS.md](docs/STATUS.md), which says where and how it was measured.

## [0.1.0] — unreleased

First public version. **No specialist adapter is trained yet**: each specialist runs as a prompt profile on the
base model and the app marks it β until an adapter passes its acceptance tests.

### Models and runtime
- One Qwen3.5-4B (Q4_K_M, llama.cpp) shared by 13 specialists, each with its own LoRA adapter slot switched per
  request with explicit scales; external providers (OpenAI-compatible, Anthropic, Gemini, DeepSeek, Ollama,
  LM Studio and others) with the same instructions and tools. Paid providers stay blocked until allowed; keys in
  the OS keychain.
- Orchestrator: lexical router (0.92 on a held-out set, measured), LLM plan only for multi-domain requests,
  dependency graph merged by Core.
- `spike tune` measures threads and KV cache on the user's machine; `spike bench` records hardware and build.
- Measured speed: 16 GB x86 4-core CPU-only 6.2 tok/s at 1K context, 5.1 at 8K; Apple M4 Max 82 tok/s; 3.6 GiB
  resident.

### App
- Chat, projects, files, artifacts panel (isolated frame), Word/Excel/PowerPoint/PDF output, Markdown with
  sanitizing, undo of file changes, step-by-step replay, temporary chats.
- Neural Memory (facts, decisions, rules, summaries, documents; local and editable).
- Skills (`SKILL.md`, MIT/Apache only) and MCP connectors from a reviewed catalog, with MCP Apps views.
- Privacy and spend: no file contents to remote providers unless allowed, monthly limits, call log.
- Forge (planner, executor, mandatory verifier), Creator templates, Spike Design (design systems), Spike Data
  (DuckDB, Vega-Lite), Spike Finance (market data, backtests, paper trading; real orders off by default and
  confirmed one by one), Spike Motion (video from HTML/SVG scenes, offline and frame-exact).
- `spike dev` coding agent in the terminal; OpenAI-compatible `/v1` endpoint; SPIKE as an MCP server.

### Learning from use (Evolution)
- Corrections become memory rules and proposed eval questions; route corrections teach the router only if its
  protected test split does not drop; failure library; regression checks; versions with rollback for router,
  adapters and prompts.
- Learned instructions and skill modes kept only if they pass more of the user's eval questions and lose none.
- With the user's consent, approved corrections (from SPIKE's local model only) export as SFT and DPO data.

### Training and evaluation
- Recipe per specialist with acceptance criteria written before training; mlx-lm LoRA on Apple silicon
  (chunked gated delta rule, 5.7x faster, measured); export to GGUF; exact-answer evals with confidence
  intervals and McNemar tests; model cards generated from the eval run.

- Forge measured on the 16 GB x86 machine with the base model: 6/10 tasks against 9/10 for the core model alone,
  and 8.3x slower, so it is not announced yet.

### Not measured yet
- Quality of any trained adapter, how well a 4B model follows skills or writes scenes, and installer runs on
  clean Windows and macOS machines.
