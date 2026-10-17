# SPIKE architecture

```
 Browser (React app, web/)                     CLI (spike …)
        │  REST + Server-Sent Events                │
        ▼                                           ▼
 FastAPI server (spike/server) ── SQLite store (conversations, settings, providers; no keys)
        │                         └─ SecretStore: OS keychain, or a 0600 file fallback
        ▼
 Orchestrator (spike/orchestrator)
   1 lexical router ─► 2 JSON-schema planner (only multi/ambiguous) ─► 3 subtask DAG ─► 4 synthesis
        │ each subtask = (provider, model, adapter, system prompt + user instructions)
        ▼
 Agent loop (spike/agent) ── tools (spike/tools) ── PermissionBroker: allow / ask / deny per tool
        │
        ▼
 Providers (spike/providers)
   ├─ llama.cpp (local)  ── one llama-server: base GGUF + every adapter, explicit per-request scales
   ├─ OpenAI-compatible  ── Ollama, LM Studio, OpenAI, DeepSeek, Gemini, OpenRouter, Groq, Mistral, Together, custom
   └─ Anthropic (native Messages API)
```

## Request flow

1. `POST /api/chat` with the conversation, mode (auto / a specialist / direct) and options.
2. The router scores the message against each specialist's weighted keywords (EN/ES, accent-insensitive).
   Clear single-domain requests go straight to that specialist; clear general ones to core.
3. Multi-domain or ambiguous requests get a plan from core: JSON constrained by a schema, validated
   (known specialists, backward dependencies, size cap), with a deterministic fallback.
4. Subtasks run by topological level. Each gets its specialist's system prompt, the user's custom
   instructions and per-specialist instructions, its adapter (local) or its bound provider/model (remote),
   and a token budget (`spike/core/context.py` keeps system prompt and latest turn, drops the oldest turns).
5. The agent loop streams text and reasoning, executes tool calls (native, or emulated with `<tool_call>`
   blocks for providers without native tools) and pauses on `ask` tools until the user answers in the UI.
6. Core synthesizes when more than one specialist contributed. Every step is an SSE event; the assistant
   message is stored with its route, plan, subtasks, tool calls, usage and timing.

## Specialists

`spike/specialists/catalog.yaml`: id, name, domain, description, adapter name (`spike-<id>`),
`adapter_status` (`planned` until an adapter passes its acceptance criteria), sensitivity flag (finance,
medicine, law, security show a limitations notice), tool allowlist, routing keywords and system prompt.
Users can add custom specialists (prompt profiles) and bind any specialist to any provider/model.

## Local runtime

`spike/runtime`: hardware detection and recommendations (`spike doctor`), GGUF metadata reader and
KV-cache calculator, model download with license allowlist, resume and SHA-256 verification, and the
llama-server lifecycle (`--parallel 1`, `--jinja`, flash attention auto, q8_0 KV by default, global adapter
scales reset to 0 at startup). See [ADR 0004](adr/0004-adapter-serving.md).

## Providers and safety rails

- Paid providers (every remote preset) refuse to send a request unless the user enabled `allow_paid` for
  that provider: no cost without explicit configuration. `/test` only lists models.
- API keys are stored in the OS keychain (`keyring`), never in SQLite or responses.
- `GuardedProvider` (`spike/providers/guard.py`) wraps every provider the app creates. Messages carry `private`
  parts (file contents: a `read_file` result, a file passage memory recalled into the system prompt, a report or
  earlier answer written by a model that saw files); for a remote provider without `share_files` each part is
  replaced by a notice, and a part that is not found word for word withholds its whole message. The guard also
  checks the monthly limits before a call and writes every call (tokens from the provider's usage, or an estimate)
  to the `calls` table.
- Capabilities (streaming, native tools, JSON schema, adapters, reasoning, context) are declared per
  provider; when a feature is missing SPIKE emulates it only if reliable (tool calls) and otherwise reports
  the limitation.

## Tools

| Tool | Default policy | Limits |
|---|---|---|
| calculator | allow | AST-restricted arithmetic, exponent cap |
| current_time | allow | — |
| read_file, list_dir | allow | confined to the workspace (`SPIKE_WORKSPACE`), traversal rejected |
| write_file | ask | workspace only |
| python | ask | separate process, `-I`, CPU 20 s, memory 512 MB (Linux), 30 s timeout; **network is not blocked** |
| web_fetch | ask | http(s) only, private/loopback/link-local addresses refused, no redirects, 2 MB cap |

In a project's chats the file tools work in that project's own folder (`$SPIKE_HOME/projects/<id>/files`).

**Connectors (MCP).** `spike/connectors/` holds a small MCP client ([ADR 0005](adr/0005-mcp-client.md)), the
curated catalog (`catalog.yaml`, pinned versions, licenses in [THIRD_PARTY](../THIRD_PARTY.md)) and the manager.
An enabled connector's tools are named `mcp__<connector>__<tool>`, offered to every specialist and gated by the
same broker: the connector's policy (ask by default) applies to each tool, and a per-tool policy overrides it.
Secrets go to the keychain and reach the server only as its environment (stdio) or headers (HTTP).

**Skills.** `spike/skills/engine.py` loads Agent Skills folders (`SKILL.md`) from `spike/skills/bundled/` and
`$SPIKE_HOME/skills/`. For local models a lexical router picks at most one skill per specialist run from its
keywords and description (bindings restrict which specialists may use it) and puts its body in the system
prompt, cut to a quarter of the context budget; API models get the list of names and descriptions and a
`load_skill` tool. Packs (`/api/pack/*`) move custom specialists, user skills and custom connectors, never secrets.

**Artifacts and documents.** `spike/tools/documents.py` writes .docx, .xlsx, .pptx and .pdf files into the
workspace (or the project's folder) from a small Markdown subset or structured rows and slides; the optional
`docs` extra provides the libraries. A tool result that wrote a file carries `file` in its `tool_result` event, and
the web app offers it from `/api/workspace/files/…` or `/api/projects/{id}/files/…` as a download. HTML and SVG
code blocks, and written `.html`/`.svg` files, open in the artifact panel: an iframe with `sandbox="allow-scripts"`
whose `srcdoc` starts with a strict Content-Security-Policy (`web/src/components/Artifact.tsx`).

**Neural Memory.** `spike/memory/` keeps one SQLite file: memories (fact, decision, preference, rule, summary,
document) scoped globally or to a project, split into chunks indexed by FTS5 and, when the embedding model is
installed (`spike models pull qwen3-embedding-0.6b`), by vectors from a second llama-server started with
`--embedding --pooling last`. Before each chat the app recalls the user's rules plus the chunks that match the
message (BM25 and cosine rankings fused by reciprocal rank) and the orchestrator adds them to every specialist's
system prompt within a sixth of its context budget. Project files are indexed on upload; every few messages a
local model summarises the chat into a `summary` memory; `remember` and `recall` tools let Core save and search.

**OpenAI-compatible API.** `spike/server/openai_api.py` serves `/v1` ([integrations](INTEGRATIONS.md)): the
orchestrator for `spike-auto`, one specialist for `spike-<id>`, direct mode when the client brings its own
tools, and passthrough for `<provider>/<model>`.

## Training and evaluation (offline, on the developer Mac)

`training/` builds data, trains mlx-lm LoRA adapters and exports them to GGUF; `evals/` measures base vs.
adapter through llama-server with explicit scales. See [TRAINING.md](TRAINING.md).

## Repository layout

```
spike/          Python package (server, orchestrator, agent, providers, tools, runtime, store, CLI, bench)
web/            React + Vite + TypeScript app (built into the Python wheel)
training/       data preparation, distillation, mlx-lm training, adapter export, configs, seeds
evals/          evaluation suites, runner, pairwise judge, router eval data
tests/          pytest: unit, API, real llama-server integration, official-converter export
docs/           plan, research, architecture, status, ADRs, audits
brand/          official SPIKE logo and derived assets
scripts/        installers
```
