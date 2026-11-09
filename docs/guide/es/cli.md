# Línea de comandos

Idioma: **Español** | [English](../en/cli.md) · [Índice de la guía](README.md)

Todas las órdenes y opciones de `spike`, generadas a partir del propio analizador con
`python scripts/cli_reference.py` (la CI falla si esta página queda desfasada). Los textos de ayuda están en inglés,
igual que en `spike <orden> --help`; las órdenes `skills` y `connectors` los dan en los dos idiomas.

## Ejemplos

```bash
spike doctor                                  # hardware, llama-server y memoria que necesita cada modelo local
spike models pull qwen3.5-4b                  # descarga el modelo base, comprobado con el SHA-256 del Hub
spike serve --open                            # arranca la app en http://127.0.0.1:8740 y abre el navegador
spike chat "¿Qué hace un IECA?" --mode medicine
spike tune --quick                            # busca los hilos y la caché KV más rápidos en este equipo
spike skills validate                         # comprobaciones sin red de las skills incluidas
```

## `spike skills validate`

offline checks / comprobaciones sin red

| Opción | Por defecto | Qué hace |
|---|---|---|
| `paths` |  | skill folders or SKILL.md files (default: the bundled skills) / carpetas o SKILL.md |
| `--lang` (`es`, `en`) | `en` | language / idioma |

## `spike skills list`

local marketplace / marketplace local

| Opción | Por defecto | Qué hace |
|---|---|---|
| `index` |  | local index JSON / índice JSON local |
| `--lang` (`es`, `en`) | `en` | language / idioma |

## `spike skills install`

local marketplace / marketplace local

| Opción | Por defecto | Qué hace |
|---|---|---|
| `index` |  | local index JSON / índice JSON local |
| `--lang` (`es`, `en`) | `en` | language / idioma |
| `pack` |  | pack identifier / identificador de paquete |
| `--destination` | required | skills folder / carpeta de skills |
| `--yes` |  | approve writing / permitir escritura |

## `spike connectors validate`

offline checks / comprobaciones sin red

| Opción | Por defecto | Qué hace |
|---|---|---|
| `paths` |  | connectors catalog file (default: the bundled one) / catálogo de conectores |
| `--lang` (`es`, `en`) | `en` | language / idioma |

## `spike serve`

run the SPIKE app

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--host` | `127.0.0.1` | address to listen on (default 127.0.0.1: this computer only) |
| `--port` | `8740` | port (default 8740) |
| `--open` |  | open the browser |
| `--no-local` | `True` | do not start llama-server |
| `--allow-network` |  | allow a --host other than this computer (the app has no login) |

## `spike doctor`

check hardware, runtime and model memory needs

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--model` |  | GGUF file to check (default: every local model) |
| `--context` |  | context length in tokens for the memory estimate (default: recommended) |
| `--json` |  | print the report as JSON |
| `--strict` |  | exit 1 when llama-server or a local model is missing |
| `--no-model-check` |  | with --strict: do not require a local model |

## `spike models`

list or download models

| Opción | Por defecto | Qué hace |
|---|---|---|
| `action` (`list`, `pull`, `history`) |  | list: local models; pull: download one; history: versions of a component |
| `model` |  | model to pull (default qwen3.5-4b); for history, a component |
| `--quant` |  | pull: quantization, e.g. Q4_K_M (default: the model's own) |
| `--allow-unverified` |  | pull: download even when the Hub publishes no SHA-256 for the file (refused by default) |

## `spike chat`

one-shot chat through the orchestrator

| Opción | Por defecto | Qué hace |
|---|---|---|
| `message` |  | what to ask |
| `--mode` | `auto` | auto (the router picks) or a specialist id, e.g. medicine |
| `--provider` |  | provider id to answer with (default: the app's bindings) |
| `-q`, `--quiet` |  | print only the answer, no routing or tool events |

## `spike bench`

measure TTFT, generation speed and memory of a llama-server model

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--model` | required | path to a GGUF file |
| `--adapter` |  | LoRA GGUF to load (repeatable) |
| `--contexts` | `1024,8192,32768` | prompt lengths in tokens to test |
| `--gen` | `128` | tokens to generate per run |
| `--repeats` | `3` | runs per length (default 3) |
| `--threads` |  | CPU threads (default: llama-server's choice) |
| `--gpu-layers` |  | 0 = CPU only (the 16 GB target); 99 = Metal |
| `--kv` | `q8_0` | KV cache type, e.g. q8_0 or f16 (default q8_0) |
| `--server-context` |  | llama-server context for every length (default: longest prompt + gen + 256) |
| `--port` | `8799` | port for the temporary llama-server (default 8799) |
| `--out` |  | write the JSON report here |
| `--share` |  | save and print anonymous JSON / guardar e imprimir JSON anónimo (default: bench-share.json) |

## `spike tune`

measure threads and KV cache on this machine and save the fastest settings

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--model` |  | GGUF to tune for (default: the local model in Settings) |
| `--quick` |  | shorter runs (less precise) |

## `spike evolve`

check, learn, optimise or roll back what SPIKE learned from its use

| Opción | Por defecto | Qué hace |
|---|---|---|
| `action` (`check`, `router`, `strategy`, `optimize`, `candidate`, `activate`, `dataset`, `personal-adapter`, `rollback`, `export`) |  | what to do; see docs/guide/en/evolution.md |
| `component` |  | optimize, candidate, activate: a specialist; dataset: output folder; rollback: router, strategy, adapter:<specialist>, adapter:personal or prompt:<specialist>; export: output file |
| `--try` |  | optimize: an instruction line to try, besides the rules saved from corrections; candidate: a line to add |
| `--skill` |  | candidate: set a skill to always, off or auto |
| `--version` |  | activate: the candidate version (default: the newest) |
| `--max-calls` |  | optimize: at most this many model answers (default 120) |
| `--replay` |  | check: answer the accepted eval candidates again |
| `--prompts` |  | check: compare learned and candidate prompts on your eval questions (runs the model) |
| `--reset` |  | strategy: forget every recorded tool and skill use |
| `--enable` |  | personal-adapter: turn the feature on |
| `--disable` |  | personal-adapter: turn the feature off |
| `--list` |  | personal-adapter: list every example and whether it is used |
| `--mark` |  | personal-adapter: use this chat |
| `--unmark` |  | personal-adapter: stop using it |
| `--exclude` |  | personal-adapter: leave an example out |
| `--include` |  | personal-adapter: put it back |
| `--llama-cpp` |  | personal-adapter: llama.cpp checkout (default $SPIKE_LLAMA_CPP) |
| `--model` |  | personal-adapter: base GGUF (default: the local model in Settings) |
| `--yes` |  | personal-adapter: train without asking |
| `--json` |  | print the result as JSON |

## `spike forge`

run the Forge test tasks and measure their success rate

| Opción | Por defecto | Qué hace |
|---|---|---|
| `action` (`eval`) |  | eval: run the test tasks |
| `--provider` |  | provider for every role (default: the app's bindings) |
| `--baseline` |  | also run each task with the core model alone |
| `--only` |  | comma-separated task ids |
| `--tasks` |  | another tasks file (JSONL) |
| `--start-local` |  | start the local engine first (and stop it after) |
| `--model` |  | GGUF for the local engine (saved as the local model, as `spike tune` does) |
| `--out` |  | write the JSON report here |
| `--keep` |  | keep each task's files here (DIR/<task>-<mode>), with Forge's plan and verdicts |

## `spike dev`

code in a folder from the terminal: SPIKE reads, edits and runs commands with your OK, and /undo puts files back

| Opción | Por defecto | Qué hace |
|---|---|---|
| `path` | `.` | the folder to work in (default: this one) |
| `--provider` |  | provider for every specialist (default: the app's bindings) |
| `--specialist` | `code` | who answers: a specialist id, or auto (default: code) |
| `-p`, `--print` |  | run one request without questions and print the answer |
| `--plan` |  | start in read-only planning mode / empezar planificando sin modificar |
| `--accept-edits` |  | edit and create files without asking (commands still ask) |
| `-c`, `--continue` |  | continue the latest conversation in this folder |
| `--resume` |  | reopen a saved conversation in this folder / reabrir una sesión por ID |
| `--sessions` |  | list saved sessions without loading a model / listar sesiones sin cargar un modelo |
| `--limit` |  | sessions per page, 1–100 (default 20) / sesiones por página |
| `--offset` |  | skip this many sessions (default 0) / sesiones que omitir |
| `--start-local` |  | start the local engine first (and stop it after) |

## `spike adapters`

install a trained adapter if its eval results pass acceptance

| Opción | Por defecto | Qué hace |
|---|---|---|
| `action` (`install`) |  | install: check the eval results and install the adapter |
| `gguf` |  | the LoRA adapter GGUF |
| `--specialist` | required | specialist id, e.g. medicine |
| `--eval` | required | eval run directory (or its summary.json) from evals/run_eval.py, or evals/pairwise.py |
| `--config` |  | training config whose acceptance rule to apply (training/configs/<id>.yaml) |
| `--variant` |  | the adapter's variant name in the eval run, when it has several |
| `--skip-local-eval` |  | do not check the adapter against your accepted eval questions (Settings → Evolution) |

## `spike mcp`

serve SPIKE's specialists as MCP tools over stdio (Claude Code, Cursor, Codex)

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--start-local` |  | start the local engine in this process (when the SPIKE app is not running) |

## `spike render`

turn an animated HTML/SVG scene into an MP4, WebM or GIF (Spike Motion)

| Opción | Por defecto | Qué hace |
|---|---|---|
| `scene` |  | the scene file (.html or .svg) |
| `-o`, `--output` |  | video file (.mp4, .webm or .gif); default: the scene's name with .mp4 |
| `--size` | `16:9` | 16:9, 9:16, 1:1, 4:5, 1080p or WIDTHxHEIGHT (default 16:9) |
| `--fps` | `30` | frames per second (default 30) |
| `--seconds` |  | length; default: the scene's spike-duration or its animations |
| `--install-browser` |  | download Playwright's Chromium to render with (when Chrome is not installed) |
