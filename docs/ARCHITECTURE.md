# SPIKE architecture

```
 Browser (React app, web/)                     CLI (spike …)
        │  REST + Server-Sent Events                │
        ▼                                           ▼
 FastAPI server (spike/server) ── SQLite store (conversations, settings, providers; no keys)
        │                         └─ SecretStore: OS keychain, or a 0600 file fallback
        ▼
 Orchestrator (spike/orchestrator)
   1 lexical router ─► 2 JSON-schema planner (only multi/ambiguous) ─► 3 subtask DAG ─► 4 checker ─► 5 synthesis
   (Forge: an approved blueprint replaces 1–2; its deliverables and criteria are checked in 4)
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
6. A multi-step plan is checked (`orchestrator/verify.py`): one constrained-JSON call to core marks each result ok or
   says what to fix; a result with a fix, and every subtask that used it, runs again with the note, at most twice.
   SPIKE itself checks that each deliverable file was saved. A checker answer that is not valid JSON sends nothing
   back and the run says it could not verify. Core then synthesizes (the integrator). Every step is an SSE event; the assistant
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

- Write tools declare `targets(args)`; before running them the agent loop asks the run's checkpointer
  (`spike/store/checkpoints.py`) to copy those files, records their hashes after the call, and puts the checkpoint
  id on the `tool_result` event. `POST /api/checkpoints/{id}/undo` restores them (409 if a file changed since,
  unless `force`). The chat route stores the run's events (text pieces merged, `t` = seconds from the start) in the
  answer's meta for the step-by-step view.

| Tool | Default policy | Limits |
|---|---|---|
| calculator | allow | AST-restricted arithmetic, exponent cap |
| current_time | allow | — |
| read_file, list_dir | allow | confined to the workspace (`SPIKE_WORKSPACE`), traversal rejected |
| write_file | ask | workspace only |
| python | ask | separate process, `-I`, CPU 20 s, memory 512 MB (Linux), 30 s timeout; no network and no writes outside its temp folder **when the computer has a sandbox** (below) |
| web_fetch | ask | http(s) only, private/loopback/link-local addresses refused, no redirects, 2 MB cap |

In a project's chats the file tools work in that project's own folder (`$SPIKE_HOME/projects/<id>/files`).

**Code isolation (`spike/tools/sandbox.py`).** `python`, `data_python` and `spike dev`'s `run_command` can run inside
the computer's own sandbox. SPIKE ships none: it builds the command line for a program the user already has. The
setting `sandbox` (Settings → Tools, `PUT /api/settings`) is `auto` (default: isolate the code a model writes, `python`
and `data_python`, when possible), `off` (never) or `required` (isolate everything, `run_command` too, and refuse to
run code when there is no working sandbox; the tool's `review()` returns a deny, so nobody is asked to approve code
that will not run). Under `auto` a `run_command` is **not** isolated: the user approves each exact command, and
isolation would stop `npm install`, `git pull` and tools installed under the home folder. Its card and result say
`not isolated: approved commands run outside the sandbox in auto mode` (reason code `approved_command`, not the "no
sandbox" codes). `GET /api/sandbox` says what the computer offers and why not.
Detection runs once per start (and again each time Settings is opened): the program is found (`shutil.which("bwrap")`,
`/usr/bin/sandbox-exec`) and then tried with the real flags on a harmless Python start, so a `bwrap` that cannot
create namespaces here counts as missing, with what it printed as the reason.

| | Linux | macOS | Windows, or no program |
|---|---|---|---|
| Program | `bwrap` (bubblewrap) on `PATH` | `/usr/bin/sandbox-exec -p <profile>` (generated SBPL profile) | none: the code runs as before and the result says `not isolated: <reason>` |
| Network | none (own network namespace, `--unshare-net`; not even the loopback) | denied by the profile | open |
| Writes | only the working folder (`run_command`, under `required`: the workspace; `python`: its own temp folder) and a private `/tmp` (a tmpfs, so it uses RAM); everything else is read-only or absent | only the same folders plus a private temp folder SPIKE creates and removes, and `/dev/null` | anywhere the user can |
| Reads | `/usr`, `/bin`, `/sbin`, `/lib*` (host symlinks kept), a few `/etc` files (loader cache, user and group names, time zone, `alternatives`, `os-release`, `terminfo`), the Python interpreter's prefixes, the writable folders; `python` also reads the workspace (not writable, so Forge's import check can read the saved files; `data_python` sees only its copies of the files) | the system (`/usr`, `/bin`, `/sbin`, `/System`, `/Library`, `/Applications`, `/opt`, `/private/etc`, a few `/private/var/db` folders), the interpreter, the writable folders and the workspace; the home folder's contents are not readable, but names and sizes of other files can be seen | everything the user can read |
| Other | own PID and IPC namespaces, capabilities dropped, new session, dies with its parent | no process or Mach service access beyond starting programs | |

What it does not do: filter system calls (no seccomp profile), limit CPU or memory (the `python` tool keeps its
rlimits; `run_command` has none), hide environment variables (they are passed on; `HOME` and `TMPDIR` point to the
private temp folder), or protect against a kernel bug. Programs that live outside the system folders, such as ones
installed under the home folder by nvm, cargo or pyenv, are not visible to a `run_command` isolated under `required`,
and commands that need the network (`npm install`, `git pull`) fail there: that is why `auto` leaves approved commands
alone, and `required` is for people who want every command contained. NixOS and other systems
that keep programs outside `/usr` are reported as "does not work here" by the detection. The macOS profile has been
generated and checked as text and with a fake `sandbox-exec`; `sandbox-exec` is deprecated by Apple but still ships.
The result of every isolated or not-isolated run ends with a line `[sandbox: isolated (bwrap): …]` or
`[sandbox: not isolated: <reason>]` (the same is in `ToolResult.data["isolation"]`), and the permission
request carries `isolation` (`Tool.isolation(args)`) so the card in the app, in Spanish or English, and the `spike
dev` prompt say before the user answers whether the run will be isolated.

**Connectors (MCP).** `spike/connectors/` holds a small MCP client ([ADR 0005](adr/0005-mcp-client.md)), the
curated catalog (`catalog.yaml`, pinned versions, licenses in [THIRD_PARTY](../THIRD_PARTY.md)) and the manager.
An enabled connector's tools are named `mcp__<connector>__<tool>`, offered to every specialist and gated by the
same broker: the connector's policy (ask by default) applies to each tool, and a per-tool policy overrides it.
Secrets go to the keychain and reach the server only as its environment (stdio) or headers (HTTP).
A tool can also review each call (`Tool.review` → `Review`): `PermissionBroker.policy_for_call` lets a deny win,
then the review's own allow/ask/deny. The catalog Playwright connector uses `connectors/browser.py` for this
(Spike View): domain rules from the `browser` setting, questions that are never "always" (`once`) for form
submissions, uploads and code, and `--blocked-origins` at start; the permission event carries the reason, its
code (translated in the app) and the domain, which `allow_domain` / `block_domain` save.

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

**Learning from the user (Evolution level 1).** `spike/memory/learn.py` reads only the user's own message, with
fixed patterns (Spanish, English, Catalan) and no model: a sentence starting "recuerda que…", "a partir de
ahora…", "remember that…" is saved before the run (rule, preference or fact) and named in that run's prompt; a
message that corrects the previous answer ("No, …", "Te equivocas: …") yields a proposed rule kept in the answer's
`meta.learn`, which the user saves (with their own wording), dismisses or later undoes through
`POST /api/messages/{id}/learn`. Rules then reach every later chat through recall.

**Evolution (E1–E6).** `spike/evolution/` learns from use without a model call, in `$SPIKE_HOME/evolution.db`
(`store.py`: items and versions, each version pointing at the one it replaced). A saved correction keeps its
question, wrong answer and rule and proposes an eval question (`candidates.py`: checks are strings the answer must
or must not contain, suggested from the numbers the user wrote; word-trigram overlap with SPIKE's eval questions
blocks duplicates). "Reintentar → Con otro especialista" calls `POST /api/messages/{id}/route`; `router_learning.py`
picks words of the corrected questions that no other specialist's corrections or dev questions use, weights them
just enough to win and keeps them only if the dev split holds; `gate()` then requires better corrections and no
drop on dev or test, and the overlay is applied in `AppState._load_catalog`. Run and tool failures are recorded
from the chat route. `checks.py` is `spike evolve check`; `adapters.py` installs an adapter only when
`acceptance.py` (a test-checked copy of the training rule) passes, keeps every file in `adapters/history` by
checksum and rolls back by hard link.

**Evolution levels 2–3 (D).** `prompts.py` searches a `Variant` (instruction lines plus a mode per skill) for one
specialist: every one-step move from the best so far is scored on the user's accepted candidates with checks,
answered by `checks.answer_with_variant` without memory at temperature 0; a move counts only if it passes more and
loses none, the winner is re-run, and `AppState.optimize_prompt` adds `spike evolve check` as the gate. Every attempt
is a `prompt:<specialist>` version (active only if accepted); `AppState.learned_prompts()` passes the active ones to
the orchestrator as `learned_instructions` (a prompt section) and `learned_skills` (forced or disabled skills).
`dataset.py` turns corrections into `example` items only when the setting `evolution.training_data` is on and both
answers' `meta.route` names `spike-local`; approved ones export through `GET /api/evolution/{training,preferences}.jsonl`
or `spike evolve dataset`. `adapters.install_checked` reloads the engine with the new adapter, answers the same
eval and rolls back on any loss.

**Collective and Forge (C2).** Planner subtasks carry a role (`research` or `execute`); the checker and the
integrator are fixed stages after any multi-step plan. Forge (`spike/forge/`) adds a first phase: `POST
/api/forge/blueprint` drafts goal, requirements, steps (specialist, role, instruction, dependencies, files to save)
and acceptance criteria with constrained JSON; the user edits and approves it in the Forge screen, and `POST
/api/chat` with `forge` runs it (`Blueprint.from_user` validates it strictly: known specialists, earlier
dependencies, relative paths, no file saved twice). A step that saves files gets the file tools it needs for the
run. Before the checker, SPIKE checks the saved files itself (`verify.check_files`: Python compiles and uses no
undefined name, JSON parses, CSV rows have equal width, text is not empty; each Python file is then imported through
the `python` tool with its usual permission, in a temporary copy of the saved files): a failure is a fact in the
checker's input, private when the file's author read the user's files, and sends the step back with the error. The
checker also judges each criterion; the answer ends with a `forge_report` (criteria, deliverables, rounds, what
stayed unresolved). `spike forge eval` runs the ten tasks of `spike/forge/tasks.jsonl` in empty folders, with their
checks run by SPIKE (Python in a limited subprocess), against the core model alone with `--baseline`.

**`spike dev` (C3).** `spike/dev/` reuses the orchestrator and the agent loop with its own registry: the usual file tools on the chosen folder plus `edit_file`, `search`, `find_files` and `run_command` as shared tools (every specialist gets them), its own permission broker (the app's policies; `--accept-edits` allows the edit tools) and its own store `$SPIKE_HOME/dev/sessions.db` with checkpoints in `$SPIKE_HOME/dev/checkpoints` (one conversation per run, titled `dev:<folder>`; `/undo` takes the latest checkpoint of any of them). The terminal (`spike/dev/terminal.py`) settles each permission request and question before the loop goes on, runs each request as a task on one event loop so Ctrl-C cancels the request and not the session, and allows 30 model calls per request. `run_command` runs in the sandbox described under Tools only when the setting is `required` (no network; writes only in the folder); under `auto`, the default, the user's approval of each exact command is the guard and the command runs with their rights, and the startup line and each approval prompt say which of the two it is.

**Spike Design (C4).** `spike/design/library.py` keeps design systems as folders with `DESIGN.md` and an optional `tokens.css`: bundled ones in `spike/design/systems/`, the user's in `$SPIKE_HOME/design-systems/` (same id = the user's wins). `OrchestratorOptions.design` adds a section to the system message of every specialist and of the integrator in the run (Forge steps included; not the checker, which only judges results): the tokens without comments, the request to paste them into the first `<style>`, then DESIGN.md cut to a fifth of the context. The chat's `design_system` overrides the project's `design`; `"none"` drops it. `GET /api/design-systems/{id}/preview` returns a sample page that the app shows in the same sandbox and CSP as artifacts.

**Spike Finance (C5).** `spike/finance/`: `market.py` reads public tickers and candles through `ccxt.async_support` (a factory, so tests inject a fake exchange), caches closed candles in `$SPIKE_HOME/finance/market.db` and downloads only what is missing, page by page; `load_csv` reads the user's own prices. `backtest.py` is SPIKE's own (long only, signal at a bar's close, trade at the next open, fees and slippage); `analysis.py` holds the metrics and the portfolio risk. `paper.py` is a simulated account in `paper.db`. `live.py` keeps real-order proposals in `live.db`: `propose` checks the settings (`finance.live`) and limits and sends nothing; `confirm`, reached only through `POST /api/finance/live/orders/{id}/confirm` (loopback client, same-origin, the id in the body and in `X-Spike-Confirm`), checks everything again, marks the order `sending` so a second click cannot repeat it, and calls `create_order` once. `tools.py` gives the finance specialist seven tools; `propose_live_order` is `interactive_only`, which the orchestrator drops for headless callers (`/v1`, MCP), and its result carries `data["ui"]`, which the agent loop passes on as the tool_result event's `ui` so the app can draw the order card.

**MCP Apps (C6).** Implemented from the SEP-1865 specification (2026-01-26). `McpClient` announces `io.modelcontextprotocol/ui` in `initialize` and keeps the whole `CallToolResult`. `spike/connectors/apps.py` reads a tool's `_meta.ui` (`resourceUri`, `visibility`), turns a `resources/read` result into a view (only `text/html;profile=mcp-app`, up to 2 MB, a SHA-256 for review), cleans the declared CSP domains and builds the policy. `ConnectorManager` registers only tools visible to the model, keeps every tool in `Connection.by_remote`, and serves a view (`app_resource`), a view's tool call (`app_call`: same connector, `app` visibility, `PermissionBroker.policy_for_call`) and resource reads (`app_read`), each written to `AuditLog`. `McpTool.run` puts `{"kind": "mcp_app", connector, tool, uri, result}` in `data["ui"]`, which reaches the chat as the tool_result's `ui`. In the app, `McpApp.tsx` loads the page from `/api/connectors/{id}/view`, wraps it after a head carrying the policy, runs it in `sandbox="allow-scripts"` and answers its JSON-RPC; `ui/message` and `ui/update-model-context` travel as window events to the composer and to the next `/api/chat` request (`view_context`, added to the system message as data).

**Spike Data (C7).** `spike/analytics/engine.py` opens an in-memory DuckDB per call (1 GB memory, 2 threads, a temporary spill folder), loads the given workspace files as tables named after them (CSV through `read_csv` with a second try with decimal commas for semicolon files, Parquet, JSON; `.xlsx` and SQLite through pandas), then applies `LOCK` (`enable_external_access=false`, no replacement scans, no extension autoload or install, `lock_configuration=true`) before the model's SQL runs; a timer calls `interrupt()` after 30 s. `charts.py` turns a result into a Vega-Lite spec with the rows inline under the fields `x`, `y` and `series`, so nothing the model wrote reaches the spec but column names used as titles. `tools.py` gives the Data specialist four tools; their results carry `data["ui"]` (`data_table`, `data_tables`, `chart`, `code_run`) and are marked private (the user's data). `report.py` lays out a report's blocks as Word or PDF with the document tools' builders; `POST /api/analytics/report` checks the blocks (PNG images verified with Pillow, sizes capped). In the app, `chart.ts` checks the spec again and draws it with Vega (loaded on first use) using the expression interpreter and a loader that refuses all requests; `DataViews.tsx` shows tables, charts and code runs and builds the report (an HTML page for the artifact panel, or blocks for the server).

**Creator (C8).** `spike/creator.py` holds the templates (web, app, dashboard, data to app, document, presentation, automation): each has its questions, its Forge steps with the specialist, role, files and dependencies, its acceptance criteria and the skills its steps follow. `build()` checks the answers (required, page and slide counts 1–40, data files as relative paths with a supported extension, braces neutralised so answers cannot reach the format fields) and fills a blueprint with `method: "template"` without any model call, so the plan is the same on a 4B model on CPU; the app shows it in Forge's review before anything runs. `POST /api/chat` takes `skills` (up to 3, each a known skill): the orchestrator gives them to the steps that produce files and not to research steps, as mode `chosen`. `GET /api/creator/data-files` lists data files in the workspace or the project folder (hidden folders and links skipped). No new engine: a Creator run is a Forge run.

**Spike Motion (D).** `spike/motion/render.py` serves the scene from a route at `http://scene.invalid/` with a CSP that allows only inline code and `data:` URLs, refuses every other request, and installs a virtual clock before the scene's scripts: `performance.now`, `Date`, `setTimeout`/`setInterval` and `requestAnimationFrame` follow it and `Math.random` is seeded. For frame N it runs the timers due up to N/fps, then the queued animation-frame callbacks, pauses every Web/CSS animation and sets its `currentTime` from the virtual time it started at, and seeks SVG animations; then it takes a PNG screenshot and pipes it to `ffmpeg` (H.264 MP4, VP9 WebM or a paletted GIF). The length comes from the call, `<meta name="spike-duration">`, or the end of the last finite animation. `tools.py` wraps it as `render_video` (Code and Core), whose result carries `data["ui"]` kind `video` so the chat shows a player; the server sends `.mp4`/`.webm`/`.gif` with their media type and byte ranges. The bundled `motion-scene` skill teaches the scene contract, the Creator has a "Vídeo animado" template, and `spike render` does the same from the terminal.

**OpenAI-compatible API.** `spike/server/openai_api.py` serves `/v1` ([integrations](INTEGRATIONS.md)): the
orchestrator for `spike-auto`, one specialist for `spike-<id>`, direct mode when the client brings its own
tools, and passthrough for `<provider>/<model>`.

**MCP server.** `spike/server/mcp_server.py` makes SPIKE a tool for other agents: `ask_spike` runs the
orchestrator, `spike_<id>` one specialist. One JSON-RPC handler serves stdio (`spike mcp`) and `POST /mcp`; runs
use the headless broker and no memory, like `/v1`.

## Training and evaluation (offline, on the developer Mac)

`training/` builds data, trains mlx-lm LoRA adapters and exports them to GGUF; `evals/` measures base vs.
adapter through llama-server with explicit scales. See [TRAINING.md](TRAINING.md).

## Repository layout

```
spike/          Python package (server, orchestrator, agent, providers, tools, runtime, store, CLI, bench)
web/            React + Vite + TypeScript app (built into the Python wheel)
training/       data preparation, distillation, mlx-lm training, adapter export, configs, seeds
evals/          evaluation suites, runner, pairwise judge (the router set is spike/evolution/router_labeled.jsonl)
tests/          pytest: unit, API, real llama-server integration, official-converter export
docs/           plan, research, architecture, status, ADRs, audits
brand/          official SPIKE logo and derived assets
scripts/        installers
archive/fase0/  the Phase 0 preparation (audit, Plan Maestro v3, probes, reports), kept as it was with its history
```
