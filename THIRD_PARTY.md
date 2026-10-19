# Third-party components, models and data

SPIKE's own code is Apache-2.0 ([LICENSE](LICENSE)). This file lists what SPIKE uses from others, under
which license, and whether it is **redistributed** in SPIKE's repository or packages, or only
**downloaded on the user's machine** from its original source. Licenses were read from the package
registries (PyPI, npm) and the Hugging Face Hub on 2026-10-17; the model and dataset licenses are re-checked
automatically at download time and SPIKE refuses anything outside its allowlist
(`training/spike_train/licenses.py`, `spike/runtime/models.py`).

## Models (downloaded by the user, not redistributed)

| Model | Source | License | Use |
|---|---|---|---|
| Qwen3.5-4B (GGUF, default Q4_K_M) | `unsloth/Qwen3.5-4B-GGUF`, quantized from `Qwen/Qwen3.5-4B` | Apache-2.0 | base model for every specialist |
| Qwen3.5-2B (GGUF) | `unsloth/Qwen3.5-2B-GGUF` | Apache-2.0 | optional smaller base |
| Qwen3.5-4B (safetensors) | `Qwen/Qwen3.5-4B` | Apache-2.0 | LoRA training base (mlx-lm) and adapter export |
| Qwen3-Embedding-0.6B (GGUF Q8_0) | `Qwen/Qwen3-Embedding-0.6B-GGUF` (official) | Apache-2.0 | Neural Memory search by meaning (optional) |
| Qwen3.6-35B-A3B (MLX 4-bit) | `mlx-community/Qwen3.6-35B-A3B-4bit` | Apache-2.0 | local teacher for marketing distillation (optional) |

SPIKE adapters trained from these bases are derivative works and are released under Apache-2.0 together
with the data attributions below. No adapter has been released yet.

## Datasets (downloaded by the user at training/eval time, not redistributed)

| Dataset | Hub id | License | Role | Attribution / notes |
|---|---|---|---|---|
| OpenAssistant Conversations 2 | `OpenAssistant/oasst2` | Apache-2.0 | general replay | human-written, crowd-sourced (Köpf et al., 2023); English and Spanish messages only |
| SmolTalk (smol-constraints) | `HuggingFaceTB/smoltalk` | Apache-2.0 (card text only) | **excluded** | the Hub metadata declares no license and the card does not name the generator model; general replay is human-written OpenAssistant oasst2 only |
| SmolTalk (smol-magpie-ultra) | `HuggingFaceTB/smoltalk` | Apache-2.0 | **excluded** | generated with Llama-3.1-405B-Instruct; the Llama 3.1 license (§1.b.i) requires "Llama" at the beginning of the name of any distributed model trained on its outputs, so SPIKE does not use it |
| MedMCQA | `openlifescienceai/medmcqa` | Apache-2.0 | medicine train + eval | Pal et al., 2022 |
| PubMedQA (pqa_artificial, pqa_labeled) | `qiaojin/PubMedQA` | MIT | medicine train / eval | Jin et al., 2019 |
| Sujet-Finance-Instruct-177k (subset) | `sujet-ai/Sujet-Finance-Instruct-177k` | Apache-2.0 (aggregate); each row keeps its upstream license | finance train | only rows from `ugursa/Yahoo-Finance-News-Sentences`, `zeroshot/twitter-financial-news-topic`, `zeroshot/twitter-financial-news-sentiment` and `yixuantt/FinEntity` (classification and entity extraction, uploader-claimed MIT / odc-by; the news and tweet text is third-party). The other upstream sources were audited and excluded (OpenAI/Anthropic-generated answers, non-commercial or unlicensed content, unverified provenance; list in `training/datasets.yaml`) |
| FinQA | `github.com/czyssrs/FinQA` at commit `0f16e28`, fetched by URL | MIT | finance train + eval | Chen et al., EMNLP 2021; used in the gold-facts setting (supporting facts given), not comparable with retriever-based results |
| TAT-QA | `github.com/NExTplusplus/TAT-QA` at commit `870accc`, fetched by URL | MIT (repository LICENSE; the Hub card says CC BY 4.0) | finance train + eval | Zhu et al., ACL 2021 |
| MMLU-Pro | `TIGER-Lab/MMLU-Pro` | MIT | eval only | Wang et al., 2024 |
| GSM8K | `openai/gsm8k` | MIT | eval only | Cobbe et al., 2021 |
| medical-o1-reasoning-SFT | `FreedomIntelligence/medical-o1-reasoning-SFT` | Apache-2.0 | **excluded** | generated with GPT-4o; OpenAI's terms restrict using outputs to build competing models |

Files written by SPIKE contributors and shipped in this repository (`training/seeds/`, `evals/data/`,
`evals/router/`) are Apache-2.0.

## Inference and training tools (installed separately, not redistributed)

| Component | License | Use |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`, `convert_lora_to_gguf.py`, `gguf`) | MIT | local inference, adapter export |
| [mlx](https://github.com/ml-explore/mlx), [mlx-lm](https://github.com/ml-explore/mlx-lm) | MIT | training on Apple Silicon |
| PyTorch | BSD-style (Apache-2.0 AND BSD-3-Clause AND MIT AND others, per PyPI) | needed by llama.cpp's converter |
| transformers, datasets, huggingface_hub, safetensors, sentencepiece | Apache-2.0 | training data and export |
| numpy | BSD-3-Clause (with bundled 0BSD, MIT, Zlib, CC0-1.0 parts) | training and export |
| [FFmpeg](https://ffmpeg.org) | LGPL-2.1+ (GPL-2.0+ for builds with libx264) | encodes Spike Motion videos; SPIKE runs the user's own `ffmpeg` binary |
| Chromium / Google Chrome (Playwright's download, or the installed browser) | BSD-3-Clause (Chromium); Chrome under Google's terms | plays Spike Motion scenes |

## Skills shipped with SPIKE (`spike/skills/bundled/`, redistributed as verbatim copies with their licenses)

Fetched on 2026-10-17 from each repository's `main` branch (raw.githubusercontent.com); each skill folder carries
the upstream license file. SPIKE's routing hints for them live separately in `bindings.yaml`.

| Skill | Source | License |
|---|---|---|
| test-driven-development (+ writing-good-tests.md), systematic-debugging (+ 3 reference files), writing-plans, verification-before-completion | [obra/superpowers](https://github.com/obra/superpowers) | MIT, © 2025 Jesse Vincent (`LICENSE` in each folder) |
| frontend-design, mcp-builder (+ 4 reference files), webapp-testing (+ scripts/with_server.py and 3 examples) | [anthropics/skills](https://github.com/anthropics/skills) | Apache-2.0 (`LICENSE.txt` in each folder) |
| medical-evidence-summary, financial-ratio-analysis, campaign-brief, motion-scene | written for SPIKE | Apache-2.0 |
| web-design-guidelines (+ `references/guidelines.md`, a pinned copy of Vercel's Web Interface Guidelines) | [nexu-io/open-design](https://github.com/nexu-io/open-design) `skills/`, from [vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines) | MIT, © 2025 Vercel Labs (`LICENSE` in the folder) |

Not shipped: anthropics/skills `docx`, `pdf`, `pptx`, `xlsx` (source-available, not open source) and
`skill-creator` (depends on sub-agents and many resource files); Superpowers `brainstorming` (needs its
browser companion).

## Design systems shipped with SPIKE (`spike/design/systems/`)

20 generic design systems copied verbatim (`DESIGN.md` and `tokens.css`) from
[nexu-io/open-design](https://github.com/nexu-io/open-design) `design-systems/` at commit `78d5637cb49da07e81314d1544b5fc6d37c95084`
(2026-10-16), Apache-2.0 (copy of the license in `spike/design/systems/LICENSE-open-design`; the repository has no
NOTICE file): neutral-modern (upstream `default`, renamed), minimal, clean, modern, refined, mono, flat, editorial,
publication, brutalism, neobrutalism, glassmorphism, claymorphism, corporate, friendly, retro, spacious, bold, paper,
professional. Their manifests mark them "OpenDesign curated bundled fixture". The fonts they name are SIL OFL fonts
(Google Fonts); no font file is shipped.

Not shipped: the other 134 open-design systems. Those that imitate a company's look (Airbnb, Apple, Stripe, Linear,
Vercel, Notion, car makers, banks and many more) and those whose text names a company or a commercial font
(dashboard, elegant, warm-editorial, trading-terminal) are left out on purpose; the remaining generic ones can be
imported by the user (Settings → Diseño). `spike` is SPIKE's own system, from its logo palette (Apache-2.0).

## Connectors in the catalog (downloaded and run on the user's computer when enabled, not redistributed)

Checked on 2026-10-17 against each package registry and repository; versions are pinned in
`spike/connectors/catalog.yaml`.

| Connector | Package / endpoint | Version | License | Source |
|---|---|---|---|---|
| Filesystem | npm `@modelcontextprotocol/server-filesystem` | 1.0.0 | MIT per the package README; the repository LICENSE licenses new contributions as Apache-2.0 (code from authors who have not relicensed stays MIT) and the npm metadata says "SEE LICENSE IN LICENSE" without shipping one | https://github.com/modelcontextprotocol/servers |
| Memory | npm `@modelcontextprotocol/server-memory` | 1.0.0 | same as Filesystem | https://github.com/modelcontextprotocol/servers |
| Fetch | PyPI `mcp-server-fetch` | 2026.10.10 | MIT (wheel ships the MIT LICENSE) | https://github.com/modelcontextprotocol/servers |
| Git | PyPI `mcp-server-git` | 2026.10.10 | MIT (wheel ships the MIT LICENSE) | https://github.com/modelcontextprotocol/servers |
| Playwright browser | npm `@playwright/mcp` | 0.0.83 | Apache-2.0 (registry and repository) | https://github.com/microsoft/playwright-mcp |
| GitHub | hosted endpoint `https://api.githubcopilot.com/mcp/` | — | MIT (server code) | https://github.com/github/github-mcp-server |
| Claude Code | the user's own `claude` CLI (`claude mcp serve`) | — | proprietary; SPIKE only starts the CLI the user installed | https://code.claude.com/docs/en/mcp |

Not listed: the SQLite reference server (archived upstream with "no security guarantees") and `codex mcp-server`
(removed from the Codex CLI; its replacement is not an MCP server).

MCP Apps support follows the SEP-1865 specification (2026-01-26) published in
[modelcontextprotocol/ext-apps](https://github.com/modelcontextprotocol/ext-apps) (MIT); SPIKE implements it in its own
code and includes nothing from that repository.

## Python runtime dependencies (installed from PyPI, not vendored)

| Package | Version checked | License |
|---|---|---|
| fastapi | 0.143.3 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| PyYAML | 6.0.3 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| numpy | 2.5.4 | BSD-3-Clause (with bundled 0BSD, MIT, Zlib, CC0-1.0 parts) |
| jsonschema (answer contracts) | 4.26.0 | MIT |
| referencing, rpds-py, jsonschema-specifications (pulled in by jsonschema) | 0.37.0, 2026.9.1, 2025.9.1 | MIT, MIT, MIT |
| keyring (optional) | 25.7.0 | MIT |
| ccxt (optional, `finance` extra: market data and real orders; also used by the tests' development install) | 4.5.88 | MIT |
| aiohttp, aiohappyeyeballs, aiosignal, frozenlist, multidict, propcache, yarl, attrs, aiohttp-fast-zlib, zlib-ng (pulled in by ccxt) | 3.14.5, 2.7.1, 1.4.0, 1.8.0, 6.9.1, 0.5.2, 1.25.1, 26.1.0, 0.3.0, 1.0.0 | Apache-2.0 AND MIT, PSF-2.0, Apache-2.0, Apache-2.0, Apache-2.0, Apache-2.0, Apache-2.0, MIT, Apache-2.0, PSF-2.0 |
| requests, urllib3, idna, certifi, cryptography, cffi, pycparser, orjson, coincurve, uvloop (pulled in by ccxt) | 2.34.2, 2.8.0, 3.18, 2026.7.22, 50.0.2, 2.0.0, 3.0, 3.13.0, 21.0.0, 0.22.1 | Apache-2.0, MIT, BSD-3-Clause, MPL-2.0, Apache-2.0 OR BSD-3-Clause, MIT, BSD-3-Clause, MPL-2.0 AND (Apache-2.0 OR MIT), MIT OR Apache-2.0, MIT |
| pytest, pytest-asyncio, ruff (development only) | — | MIT |
| openai (development only: tests of the `/v1` API) | 3.33.0 | Apache-2.0 |
| mcp (development only: builds the MCP server the connector tests run against) | 2.3.0 | MIT |
| gguf (development only: tests build a tiny random model; from llama.cpp) | 0.19.0 | MIT |
| python-docx (optional, `docs` extra: Word documents) | 1.2.0 | MIT |
| openpyxl (optional, `docs`: Excel workbooks) | 3.1.5 | MIT |
| python-pptx (optional, `docs`: PowerPoint decks) | 1.0.2 | MIT |
| reportlab (optional, `docs`: PDF) | 5.0.1 | BSD-3-Clause style ("BSD license", © ReportLab Inc.) |
| lxml, Pillow, XlsxWriter, et-xmlfile, charset-normalizer, typing_extensions (pulled in by the `docs` libraries) | 6.1.3, 13.0.0, 3.2.9, 2.0.0, 3.5.2, 4.16.0 | BSD-3-Clause, MIT-CMU, BSD-2-Clause, MIT, MIT, PSF-2.0 |
| pypdf (development only: tests read the generated PDFs back) | 6.21.1 | BSD-3-Clause |
| duckdb (optional, `data` extra: SQL over the user's data files) | 1.5.6 | MIT |
| pandas (optional, `data`: Excel and SQLite loading, available to `data_python`) | 3.0.6 | BSD-3-Clause |
| python-dateutil, six (pulled in by pandas) | 2.9.0.post0, 1.17.0 | Apache-2.0 OR BSD-3-Clause, MIT |
| playwright (optional, `motion` extra: plays a video scene frame by frame in Chromium) | 1.56.0 | Apache-2.0 |
| pyee, greenlet (pulled in by playwright) | 13.0.1, 3.5.6 | MIT, MIT AND PSF-2.0 |

PDFs embed a subset of the first Unicode font found on the user's system (DejaVu Sans on Linux, Arial Unicode
on macOS, Arial on Windows, or `SPIKE_PDF_FONT`); SPIKE ships no font files for this, and falls back to the
built-in Helvetica (Latin-1 only) when none is found.

## Web app (bundled into `web/dist`, which ships inside the Python package)

| Package | Version | License |
|---|---|---|
| react, react-dom | 18.3.1 | MIT |
| marked | 14.1.3 | MIT |
| dompurify | 3.4.16 | MPL-2.0 OR Apache-2.0 (used under Apache-2.0) |
| vega, vega-lite, vega-interpreter (charts; a separate chunk loaded on the first chart) | 6.4.0, 6.5.0, 2.3.2 | BSD-3-Clause |
| vega-\* and d3-\* modules, delaunator, internmap, topojson-client, robust-predicates, json-stringify-pretty-compact, tslib (bundled with Vega) | as locked in `web/package-lock.json` | BSD-3-Clause or ISC; ISC; ISC; ISC; Unlicense; MIT; 0BSD |
| highlight.js | 11.10.0 | BSD-3-Clause |
| @fontsource/inter (Inter typeface) | 5.x | SIL Open Font License 1.1 |
| @fontsource/nunito (Nunito typeface) | 5.x | SIL Open Font License 1.1 |

Build and test tools (vite, @vitejs/plugin-react, typescript, vitest, jsdom, playwright-core) are used only
at development time and are not part of the bundle. Their license texts are in `web/node_modules/*/LICENSE`
after `npm ci`; a release build must include the license texts of the bundled packages above.

## External API providers

SPIKE can call OpenAI, Anthropic, DeepSeek, Google Gemini, OpenRouter, Groq, Mistral, Together and any
OpenAI-compatible server, only with the user's own keys and after the user allows paid calls. Use of those
services is governed by each provider's terms; SPIKE ships none of their code, names as identity, or assets.

## Brand

The SPIKE name, cactus logo and palette in [brand/](brand/) are the project's own identity. Apache-2.0
grants no trademark rights (section 6), so they may not be used as another product's identity.

- The original cactus logo (`brand/spike-logo-original.png`) was drawn for the project by its founder.
- The other brand images were generated from that logo with ChatGPT's image generation (prompts in
  `brand/IMAGENES-Y-PROMPTS.md`, originals in `brand/source/`) and cut, resized and composed with
  `brand/tools/build_brand.py` and `build_round2.py`.
- Taglines in the images are set in Nunito, SIL Open Font License 1.1 (`brand/tools/Nunito-OFL.txt`).
- The web app ships derived copies: favicons and app icons, the 13 specialist avatars and three state
  illustrations in `web/public/`.
