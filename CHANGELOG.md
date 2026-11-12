# Changelog

All notable changes to SPIKE. Versions follow [Semantic Versioning](https://semver.org/). Every number here
comes from [docs/STATUS.md](docs/STATUS.md), which says where and how it was measured.

## [0.1.0] — unreleased

First public version. **One specialist adapter, Medicine, passed its acceptance tests**; the others run as prompt
profiles on the base model, marked β, until theirs pass.

### Models and runtime
- Medicine adapter accepted (round 2): +35.07 points on MedMCQA, PubMedQA and MMLU-Pro health (2,318 questions),
  −0.62 on general knowledge (limit −1.5), after self-generated replay, sampling the domain to keep 30 % replay and
  LoRA scale 0.5 written into the GGUF. Round 1 had been rejected for forgetting (−7.62). Not published yet.
- Marketing's checkpoint sweep can choose too: `sweep_checkpoints.py` judges each candidate pairwise against the base
  model on up to 48 teacher-written tasks of the run's own valid split (never trained on, never the acceptance
  prompts) plus general-select, picks the passing one with the highest win rate, and runs the 24 acceptance prompts
  and the general suite once, on it. `evals/pairwise.py` keeps answers and judgments as they finish, continues an
  interrupted run, compares several adapters on the same base answers, and waits for the judge (exit 3) instead of
  needing it in memory while the 4B model answers. Tested with fakes; not run on real weights yet.
- One Qwen3.5-4B (Q4_K_M, llama.cpp) shared by 13 specialists, each with its own LoRA adapter slot switched per
  request with explicit scales; external providers (OpenAI-compatible, Anthropic, Gemini, DeepSeek, Ollama,
  LM Studio and others) with the same instructions and tools. Paid providers stay blocked until allowed; keys in
  the OS keychain.
- Orchestrator: lexical router (0.89 on 130 requests written blind, measured; see STATUS), LLM plan only for multi-domain requests,
  dependency graph merged by Core.
- `spike tune` measures threads and KV cache on the user's machine; `spike bench` records hardware and build.
- Measured speed: 16 GB x86 4-core CPU-only 6.2 tok/s at 1K context, 5.1 at 8K; Apple M4 Max 82 tok/s; 3.6 GiB
  anonymous memory (6.1 GiB RSS with the mapped model file).

### App
- Settings › Privacidad: back up settings, chats, memory, projects and your own skills to a ZIP (no API keys or
  connector secrets; SHA-256 per file; preview before restoring, nothing replaced without confirming), and delete all
  your data with a typed confirmation word; models and stored keys go only if their own boxes are ticked, and nothing
  is deleted when SPIKE's data folder is not a folder of its own (G34, G36).
- Dev sessions in the app: open a folder, plan or act, approve each edit and command on a card, see the changes and
  undo them, from the sidebar or Ctrl/Cmd+K; same engine as `spike dev` (O1).
- Task space for Forge answers, multi-step answers and Dev sessions: the plan with each step's state, each action with
  the permission it got (allowed once or always, denied, blocked by your settings, unanswered), the changed files and
  the deliverables, in one view. It is rebuilt from the events kept with each answer (Dev sessions now keep them too),
  so it reopens after a restart exactly as it ended and nothing runs again; full screen on a phone (O2).
- Settings › Skills: install a skill from a GitHub link. SPIKE downloads the archive, shows its license, SKILL.md and
  every file before writing anything, installs exactly what was shown and leaves it off until you turn it on; only
  MIT, Apache-2.0, BSD and ISC skills can be installed, and no model can start an install (O3).
- Phones and tablets: every view and Settings tab fits 375 and 768 px wide without sideways scrolling, buttons are at
  least 44 px for touch, and the message box stays above the on-screen keyboard (checked in headless Chromium, not
  yet on a real phone). The sidebar entries share one style on desktop too (G41).
- Settings: every value is checked by the server before it is saved (a wrong one is refused with a message naming
  the setting, shown in Spanish or English) and the form checks it first; removing a provider no longer leaves the
  default or a specialist pointing at it (G40).
- First use: a short guided tour in Spanish or English (skip it, or open it again from Settings), and a command
  palette on Ctrl/Cmd+K for views, specialists and projects; Settings lists the keyboard shortcuts (G33, G35).
  Ctrl/Cmd+K used to open history search, which is now one of the palette's actions.
- `site/`: a presentation page in Spanish and English whose figures are generated from the evaluation and benchmark
  records and checked in CI; not published (G31).
- CI installs the built wheel in an empty folder, starts SPIKE without a model, checks `/api/health` and `/v1/models`
  and removes it again (G45; it does not replace testing the desktop installers on real machines).
- Settings › Errores: a local log of the app's last failures (no error messages, file contents or keys; paths
  shortened), with "copy as issue" that only copies the text; nothing is sent (G43).
- HTTP API reference in Spanish and English (`docs/api/`), generated from the app's routes with a `curl` example and
  the error codes of each route, checked in CI (G37).
- Sample projects: six ready-made projects in Spanish and English (an expenses sheet, a report brief, a mini web page, a
  long handbook, a workflow and a paper-only finance case), imported with one click from the Projects list (G39).
- The main web bundle went from 651.5 kB to 577.3 kB (gzip 212.0 to 191.8 kB): Forge, Research, Replay, Device Lab,
  history search, the workspace panel, the first-run wizard and the desktop task load when first opened (G26).
- `spike --help` covers every command and option; the CLI reference in `docs/guide/` is generated from the parser and
  checked in CI (G38). `spike models pull --revision <commit>` pins a model download to a commit of its repository,
  and dataset sources can pin one too; the commit is recorded in the manifests (G21).
- First run explains why a download failed (offline, low disk, cut midway with resume, checksum) and offers an
  external provider or importing a local `.gguf` file (G23); API errors reach the user as Spanish or English
  sentences without absolute paths (G24); every view and dialog returns keyboard focus when it closes (G28).
- User guide in Spanish and English for each module, with a FAQ and troubleshooting page tied to `spike doctor`
  (`docs/guide/`, G19, G32).
- Accessibility (WCAG 2.1/2.2 AA) checked in real Chromium on every main view and dialog, in light, dark and a
  375 px touch layout with reduced motion: dark-mode contrast fixed in Device Lab and Workflows, focus rings in
  Forge skills and artifact files, and names added to the Settings and artifact tab lists and the memory editor (G18).
- Lab, Creator, Settings and the subtitle studio load their code when first opened: the main bundle went from
  821.6 kB to 623.8 kB (gzip 259.1 to 204.0 kB), measured with `npm run build`.
- Settings › Especialistas shows each specialist's real state: its catalog status, whether an acceptance record backs
  it, whether the adapter file is there and loaded, the mode it answers in today and its active context layers (G4);
  the installed adapter file is checked by SHA-256 against the accepted one, whose record ships with SPIKE.
- Reliability fixes, each with a test that failed before it, in Analytics, projects and memory, MCP connectors,
  Workflows, Device Lab, Reverse Studio and Geo; a translation audit keeps Spanish and English in step (G13 to G17).
- Security updates: DOMPurify 3.4.17 for the Markdown sanitizer (critical advisories) and pypdf ≥ 6.21.4 for reading
  PDFs (crafted files could hang it); Vite and Vitest on their patched 5.x and 2.x releases.
- Spike Dev plans without changing anything (`--plan`, `/plan`, `/act`) and takes a skill per turn (`/skills`,
  `/skill`); Forge takes up to three skills per task and imports skill ZIPs; deliverables share one download and
  preview component (DEVFORGE1).
- Undo checks its backups before restoring and restores atomically; skill and pack imports ignore Finder metadata
  and validate before writing; the context window keeps tool calls with their results; dark mode meets WCAG AA
  contrast; Replay and proof downloads work by keyboard (Gemini, G3 and G6 to G11).
- Chat, projects, files, artifacts panel (isolated frame), Word/Excel/PowerPoint/PDF output, Markdown with
  sanitizing, undo of file changes, step-by-step replay, temporary chats.
- Neural Memory (facts, decisions, rules, summaries, documents; local and editable).
  It can index folders you choose (nothing until you add one; links out of the folder ignored; only changed files
  read again; answers cite the file; "Forget folder" removes its text, word index and vectors), keep a glossary per
  project and global (CSV import/export), track the Education tutor's topics on an SM-2 review schedule, and draw a
  knowledge graph of the entities your notes share (relations proposed by the local model only once you confirm).
- Skills (`SKILL.md`, MIT/Apache only) and MCP connectors from a reviewed catalog, with MCP Apps views.
- Privacy and spend: no file contents to remote providers unless allowed, monthly limits, call log.
- Forge (planner, executor, mandatory verifier), Creator templates, Spike Design (design systems), Spike Data
  (DuckDB, Vega-Lite), Spike Finance (market data, backtests, paper trading; real orders off by default and
  confirmed one by one), Spike Motion (video from HTML/SVG scenes, offline and frame-exact).
- `spike dev` coding agent in the terminal; OpenAI-compatible `/v1` endpoint; SPIKE as an MCP server.
- Trustworthy answers: each answer's claims are labelled verified, hypothesis or unchecked by fixed rules (a
  summary chip and, behind "ver comprobación", a badge per claim), and citations are checked against the run's
  sources: a fabricated fragment or a changed number makes the claim unchecked. A low-confidence answer can offer a
  second opinion from an external provider you configured; nothing is sent until you click, and file contents,
  paid-call permission and monthly limits apply as for any provider.
- Code isolation: where the computer has `bwrap` (Linux) or `sandbox-exec` (macOS), the code a model writes
  (`python`, `data_python`) runs with no network and writes only in its working folder and a private temp folder.
  Setting `sandbox`: `auto` (default), `off` or `required` (also isolates `spike dev`'s `run_command` and refuses
  to run code without a sandbox). Under `auto` a command you approve runs outside the sandbox with your rights, so
  `npm install` and `git pull` keep working, and its card says so. Windows and computers without the program run as
  before. SPIKE ships no sandbox of its own.
- Team work: Claude leads and Codex builds through the repository (`AGENTS.md`, `docs/team/`): a task board
  with a CI check and a detached Codex worker (`scripts/team/codex_worker.py`) that works on `codex/<id>`
  branches and never pushes `main`. Running with the real Codex CLI on the owner's Mac since 2026-10-26.
- Projects: notes travel in the project ZIP (validated, rolled back if an import fails); symbolic links are
  refused by the project file API and left out of the ZIP. The OpenAI-compatible API answers `usage: null`
  instead of invented zeros, and the proof manifest says it is not independent verification. (S1, Codex)
- Nine more original bundled skills, and offline `spike skills validate` / `spike connectors validate`
  that CI runs on the bundled set. (A1, Codex)
- `spike bench --share` writes an anonymous allowlisted result; v1 JSON schemas for packs, projects, proof
  manifests and shared benchmarks; `COMPATIBILITY.md` generated from CI and measured rows. (A2, Codex)
- Analytics: CSV rescue, data contracts, SQL Guardian (read-only, LIMIT, EXPLAIN), lineage in the proof
  package and five baseline forecasts chosen by backtest error. (A3, Codex)
- Dev: Dependency Doctor (uses audit tools only if installed) and Visual Critic (contrast, alt, names,
  overflow, small targets), each run on request and with permission. (A5, Codex)
- Lab: compare prompts or cases across specialists and providers, and probe a provider's capabilities with
  an estimate first and the paid-call guard. (A8, Codex)
- Parallel Minds (opt-in per message): 2 to 4 independent read-only answers, the one with the best trust
  labels shown and the others collapsed; the composer shows "×N time and tokens" and the cost first, and the
  paid-call guard and monthly limits cover every call.
- Parallel Prototypes (opt-in in Forge): two approaches built on two git branches and compared by the same
  tests; your branch is not touched and nothing is merged until you approve.
- Desktop actions (off by default; Settings › Escritorio): an API provider with a computer-use tool can look
  at your screen and use the mouse and keyboard for a task you describe; local models never do. Every action
  is a card you approve; "approve the next N" covers at most 5 and never purchases, sends, deletions or
  password fields; Stop, a step cap and a cost estimate come first. Screenshots go only to the provider you
  chose, through the paid-call, limit and privacy guard, and are not saved unless you ask. Tested with fake
  drivers and a scripted provider; not yet run on a real screen or against the live API.
- Project branches, artifact comments, knowledge per specialist and a job queue with a Jobs panel. (A9, Codex)
- Skills marketplace from an index you choose (license and SHA-256 checked, nothing remote by default) and 30
  bundled skills, five of them Creator templates. (A11, Codex)
- Creator: a CSV or XLSX becomes a small local app to search and edit it; the original changes only after you
  approve the edits. (A12, Codex)
- Images in the composer for providers with vision, and optional local dictation (whisper.cpp) and reading
  aloud (Piper) with the voice's license shown. (A13, Codex)
- Audio and subtitles: local transcription, an SRT/VTT editor and a burned-in MP4, each step approved. (A14, Codex)
- Research: chats as Jupyter notebooks, Paper Rebuilder into a Forge plan you review, and a contradiction map
  with exact quotes. (A15, Codex)
- Local conversation search and `spike dev --sessions` / `--resume`. (Codex)
- Desktop launcher and first-run model wizard with resumable, SHA-256-checked downloads; installer candidates
  (.dmg, .exe, AppImage) built by a manual workflow and never published automatically; on 2026-11-02 each was
  built, installed and answered with a tiny test model on GitHub's macOS, Windows and Linux runners. (I1, I2, Codex)
- Installers with the real model: a manual workflow installs the native installers on fresh runners, lets the app
  download Qwen3.5-4B through its own first-run setup (SHA-256 checked), asks one question and uninstalls. On
  2026-11-02 Windows Server 2022 and Ubuntu 24.04 passed (generation 4.9 and 7.9 tok/s, see STATUS); the free macOS
  runner (7 GiB) is below the app's 8 GiB guard, so macOS with the real model is not tested on a runner. (I3)
- Release readiness gate that refuses simulated or stale evidence, and a separate launch video project. (Codex)
- Router: about 3,850 Spanish and English domain keywords, threshold 2.0 and `multi_ratio` 0.75, so requests
  without the old hand-picked keywords no longer fall back to Core: 0.46 to 0.89 on a blind holdout of 130
  requests; still about 1 ms per route. (M9)
- Blender and Godot 4 with the programs you already have (SPIKE never downloads them): the Code specialist
  renders a 3D scene to a small preview and scaffolds and checks a Godot game headless; each run asks first,
  stays in the workspace and follows the sandbox setting. Tested with fake programs only. (A18)
- Spike Geo: `geo_map` and `geo_measure` draw GeoJSON or CSV lat/lon files as an SVG map with no tile server, with
  a choropleth by a numeric property and a legend, and measure distances (haversine) and polygon areas on a sphere
  of radius 6371.0088 km (up to about 0.5 % for distances and 1 % for areas against WGS 84, said in the result). (A16)
- Spike View recorder: record what the browser connector does as a local JSON script and replay it step by step.
  Text typed into password-like fields is not stored, and the replay asks before every step that may submit and
  before a domain the browser settings do not allow. (A16)
- Architecture Explorer: `architecture_graph` draws the module dependency graph of a folder of Python and
  JavaScript/TypeScript, with import cycles in red and a table of them; the size limits and what was left out are
  shown. (A16)
- Reverse Studio (Settings › Design): turn a screenshot you own (needs a provider with vision and the existing paid
  and file-sharing permissions) or a page on localhost or in your project (works with the local model) into one
  editable HTML/CSS file. An ownership confirmation is required and saved with the result; logos, images and brand
  text become placeholders; a pixel similarity score is measured for that run only. (A20)
- Device Lab: check a web app running on this computer in six emulated screen sizes plus your own, with overflow and
  the elements that cause it, small tap targets and text, console errors and failed requests, and screenshots. Only
  local addresses unless you name a host for that run; each run asks first. It emulates viewports in a desktop
  browser engine and is not a real-device test; an Android screenshot is offered only if adb is already installed. (A21)
- Workflows (Create › Workflows): chain inputs, specialists, tools, conditions and outputs on a canvas that works
  with the keyboard alone; each workflow is checked before it is saved or run, tool steps ask permission like the
  chat does, Stop cancels cleanly and every run keeps a record with measured times. Workflows are JSON files in the
  project folder and can be exported and imported. (A22)
- Fixes: portable benchmark paths and Windows project cleanup; the browser tests wait for the end of each
  answer; Forge tests observe imports under Linux's private /tmp; a chat no longer stores the user's message twice.

### Security and packaging (release review, L2)
- Development tools: vite 8.3.5, vitest 5.0.5 and @vitejs/plugin-react 6.1.2 close the dev-server and test-runner
  advisories; `npm audit` reports 0 vulnerabilities (G27).
- `spike serve` refuses a `--host` that makes it reachable from the network unless `--allow-network` is given,
  because the app has no login; unknown API routes answer 404 instead of the web page.
- A test blocks every non-loopback connection while it walks the main API flows (chat, projects, memory,
  settings, skills, connectors, first-run status) and fails if any tries to leave the machine (G29).
- An answer can no longer make the browser load an image, style or media file from another site by itself (text
  the model read could have used that to send conversation data out without approval): such images become links
  (O4-1, `docs/audits/2026-11-security-review.md`).
- Monthly limits count the calls still running, not only the finished ones: calls that start together (two chats,
  parallel workflow steps, clients of `/v1`) stop where calls one after another would. Before, six calls started at
  once under a 13,000-token limit with 3,000 used all ran, 21,600 tokens; now four run (O4-2).
- A path through a `.git` folder is refused in project archives, file uploads, packs and `write_file`: git runs
  programs named in `.git/config`.
- Pack import brings in only the fields the Connectors form can enter; environment variables, headers, secret
  definitions and links in a pack are dropped.
- A provider is local only when its address's host is this computer; moving a provider to another address makes it
  remote (file contents withheld unless allowed, paid-call rule applies).
- `web_fetch` refuses the shared address space 100.64.0.0/10 and IPv4-mapped IPv6 forms.
- Desktop builds carry the license text of every bundled Python and web package, NOTICE and THIRD_PARTY.md
  (`licenses/third-party/`); the web app serves the OFL text of its fonts as `/FONT-LICENSES.txt`.
- The notices of the libraries llama.cpp compiles into `llama-server` (cpp-httplib, nlohmann/json, xxHash and six
  more), copied from tag b11709, ship as `licenses/native/llama-vendored.txt`; those of the npm packages in the web
  UI that `llama-server` embeds as `licenses/native/llama-ui-npm.txt` (`packaging/llama_ui_notices.py`).
- `docs/release/REVIEW-v0.1.md`: v0.1 checklist with evidence, findings, secrets scan and license table.
- `web_fetch` resolves a name once, checks every address and connects to a checked one (the `Host` header, TLS
  server name and certificate check stay those of the name), so DNS rebinding after the check cannot move the request;
  behind an HTTP proxy in the environment it looks the name up again and refuses a changed answer.
- `spike models pull` refuses when the Hub publishes no SHA-256; `--allow-unverified` downloads anyway with a warning.
  Each download writes `<model>.gguf.manifest.json` and `spike doctor` shows unverified files.
- Proof packages, the call log, provider error messages and exported packs keep only scheme, host, port and path of
  any address; userinfo, query and fragment are dropped.
- A connector header with a credential-looking name and a literal value moves to the key store (older rows on first
  read); the settings database keeps a placeholder.
- Design tokens are checked after CSS escapes are decoded, and `image-set(` is refused.
- A project path with a `:` in any part is refused (Windows alternate data streams).
- Every GitHub Action is pinned to a full commit SHA with its tag in a comment; the real-model installer check only
  accepts a "Native installers" run of `main` or of a version tag push.

### Learning from use (Evolution)
- Tool strategy learning: successes and failures of tools and skills are counted per task type from real runs; the
  counts only break ties between skills the router scores equal (at least 5 uses each, kept only while skill
  routing and the regression checks still pass); a table in Settings › Evolución, resettable, with rollback.
- Prompt regression: `spike evolve candidate`, `check --prompts` and `activate` compare a candidate prompt with the
  one in use on your eval questions and block it if it scores more than 2 points lower.
- Personal adapter (off by default, Apple silicon only, never trained on real weights yet): a LoRA built only from
  the corrections you approve and the chats you mark, every example listed and excludable, installed only if
  general knowledge drops by at most 1.5 points.
- Corrections become memory rules and proposed eval questions; route corrections teach the router only if its
  protected test split does not drop; failure library; regression checks; versions with rollback for router,
  adapters and prompts.
- Learned instructions and skill modes kept only if they pass more of the user's eval questions and lose none.
- With the user's consent, approved corrections (from SPIKE's local model only) export as SFT and DPO data.

### Training and evaluation
- A topics distillation run saves the teacher's tasks and each batch of answers as it goes and continues where it
  stopped when run again (`<out>.parts/`), with the same rows as a run that never stopped.
- Resumed evals, checkpoint sweeps and the forgetting fix keep SHA-256 receipts of their inputs and refuse to mix
  results from changed inputs (Codex's PR #2, rebased by Gemini Argon).
- Multiple-choice answer extraction also reads `Answer: Option B`, a letter line followed by confidence or
  disclaimer notes, `option B is correct` and `we select option B`, without reading an option argued against or a
  capital-letter word as the answer (not yet measured on saved eval predictions; re-score them with `--rescore`).
- Data recipes for the other 10 specialists (M5, M6, Codex) and their license review (M7): 15 sources verified
  on the Hub (license, commit, every row counted and formatted, `training/verify_sources.py`); OpenBookQA and
  WikiSQL rejected, so Science and Data get their data by distillation instead (next bullet).
- Science and Data have training recipes: an open teacher writes the tasks from short topic labels and then the
  answers, keeping a multiple-choice answer only when two independent answers agree with the key and a SQL exercise
  only when it runs in a sandboxed in-memory SQLite database and a second answer returns the same rows. No AI-written
  seed prompts are used (Marketing's 24 were removed) and `distill.seeds` now needs a declared human author.
  Hand-written held-out evals (60 science questions; 5 small databases with 60 SQL questions scored by execution)
  back the acceptance suites. Nothing has been distilled or trained yet. (M10)
- Recipe per specialist with acceptance criteria written before training; mlx-lm LoRA on Apple silicon
  (chunked gated delta rule, 5.7x faster, measured); export to GGUF; exact-answer evals with confidence
  intervals and McNemar tests; model cards generated from the eval run.

- Forge measured four times on the 16 GB x86 machine with the base model: 6, 9, 8 and 9 of 10 tasks against 9, 8,
  9 and 9 for the core model alone, and 3.7-8.3x slower, so no gain is shown and it is not announced. Its checker now
  reads the saved files and no longer overrules correct numbers with its own estimates (work sent back in 1 task
  instead of 4-5).
- An agent that reaches its tool-step limit gets one last call to answer instead of ending in an error.
- Installers tested on clean GitHub runners (Ubuntu 24.04, macOS 26 arm64, Windows Server 2025): install, model
  download and a first answer from the real model. They now stop with an error when a step fails, and
  `--no-model`/`-NoModel` skip the download.
- Installers also pass on Windows PowerShell 5.1 and on Linux without Homebrew, where they download llama.cpp's
  official prebuilt build (pinned b11709, SHA-256 checked). They prefer Python 3.13, 3.12 or 3.11: Python 3.15 has
  no duckdb wheel and the install failed.
- Marketing (judged by pairwise win rate) is accepted only if the general suite also holds, both in the
  training script and in `spike adapters install`; pairwise answers are greedy; distillation checks the
  teacher's Hub license before use and records it in every example; prepare.py stops on a recipe with no
  domain data instead of writing an empty training set.
- Finance recipe rebuilt after a license audit: only 4 of Sujet-Finance's 18 upstream sources kept (the rest
  are model-generated, non-commercial or of unknown origin), plus FinQA and TAT-QA (MIT) fetched from pinned
  commits with sha256 checks; finance eval adds exact-answer FinQA and TAT-QA test sets.
- Training on a shared Mac runs under a RAM guard: it stops when swap grows or free memory runs low, waits until
  memory is free again and resumes exactly where it stopped (optimizer state, schedule and data order included).
- Forge checks the saved files itself before its checker reads them: Python compiles, reads no undefined name
  and imports (through the `python` tool and its permission), JSON and CSV parse; a failure sends the step back
  with the error. Measured once (run 4): they never fired, Forge 9/10 and the model alone 9/10, so no gain.
- Self-generated replay against forgetting (`training/self_replay.py`, `prepare.py --self-replay`): the base model's
  own greedy answers to the replay prompts, under the specialist's system prompt, replace the human-written ones;
  it refuses a generator whose license is not allowed and a server with a LoRA applied. Built and tested, not yet
  measured. Every training chat now goes through one filter, so a too-long correction is counted once, not twice.
- Checkpoint sweep against forgetting without retraining (`training/sweep_checkpoints.py`): exports saved checkpoints
  and the final adapter at a smaller LoRA scale, picks one on the `*-select` suites with the recipe's own acceptance
  rule, then runs the acceptance suites once on it; every candidate tried is reported. `export_adapter.py` gained
  `--name` and `--work` so a sweep never overwrites the run's export. Built and tested, not yet run on the real
  medicine checkpoints.
- Unattended fix for a rejection for forgetting (`training/fix_forgetting.py`): the checkpoint sweep, and if nothing is accepted
  one retrain whose only change is self-generated replay (archive of the first run, base-only llama-server, `self_replay.py`,
  `prepare.py --self-replay`, RAM-guarded training, the sweep again), one detached command that stops at the first accepted
  result and continues where it stopped when run again. Built and tested with fakes, not yet run on the Mac.
- Model cards for pairwise-judged adapters (marketing), with every training source's license and the
  attribution CC-BY and ODC-BY ask for; `llama3.1` is no longer accepted for training data or teachers.

### Measured and rejected
- First trained adapter, medicine (LoRA r16, 25,469 steps, 9 h 44 min on an M4 Max): +31.9 pts on the medicine
  suite but −7.6 pts on the general suite against a 1.5-pt limit, so it is rejected and Medicine stays a prompt
  profile. `run_eval.py --resume` finishes an interrupted evaluation without regenerating complete groups.

### Not measured yet
- Quality of any trained adapter, how well a 4B model follows skills or writes scenes, the installer on a
  desktop (non-server) Windows, and the native macOS installer with the real model.
