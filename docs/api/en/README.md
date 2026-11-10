# SPIKE HTTP API reference

Language: [Español](../es/README.md) | **English** · [README](../../../README.md)

Generated from the app's OpenAPI by `python scripts/api_reference.py`; CI runs it with `--check` and fails when these
pages are stale. Do not edit them by hand.

`spike serve` listens on **http://127.0.0.1:8740** (`--host` and `--port` change it). The web app uses `/api`; any OpenAI client can
use `/v1`; MCP clients (Claude Code, Cursor, Codex) can use `/mcp`, or `spike mcp` over stdio.

## Access rules

- `spike serve` refuses any request whose `Host` or `Origin` header names another host (403, against DNS rebinding and
  calls from other sites). `curl` from this computer sends neither problem header.
- Requests that change settings must come from the app's own origin or from a program without an `Origin` header.
- `/v1` and `/mcp`: only programs on this computer, unless SPIKE runs with `SPIKE_API_TOKEN` set; then every request
  needs `Authorization: Bearer $SPIKE_API_TOKEN` (401 without it) and may come from another machine.

## Common errors

Each route lists the codes it declares or raises; these are the usual meanings.

| Code | Meaning |
|---|---|
| `400` | The request is not valid for this route (missing or wrong value, unknown item named in the body). |
| `401` | `/v1`, `/mcp`: `SPIKE_API_TOKEN` is set and the request has no valid `Authorization: Bearer` header. |
| `403` | Refused: unknown `Host`/`Origin`, a browser request without a token, or an action the user has not allowed. |
| `404` | The project, chat, file, job or other item named in the path does not exist. |
| `405` | `GET /mcp`: the server sends no messages of its own; use `POST`. |
| `409` | Conflict with the current state: busy, already running, already exists, or expired. |
| `413` | The upload is larger than the limit the message names. |
| `422` | The body or a parameter does not match the schema (FastAPI validation; the answer says which field). |
| `500`, `502` | `/v1`: SPIKE or the upstream provider failed; the error body says why. |

## Areas

| Area | Page | Routes |
|---|---|---|
| `/api/analytics` | [analytics.md](analytics.md) | 1 |
| `/api/artifact-versions` | [artifact.md](artifact.md) | 3 |
| `/api/backup` | [backup.md](backup.md) | 3 |
| `/api/browser` | [browser.md](browser.md) | 13 |
| `/api/calls` | [calls.md](calls.md) | 2 |
| `/api/chat` | [chat.md](chat.md) | 1 |
| `/api/checkpoints` | [checkpoints.md](checkpoints.md) | 1 |
| `/api/connectors`, `/api/connectors-audit` | [connectors.md](connectors.md) | 9 |
| `/api/conversations` | [conversations.md](conversations.md) | 7 |
| `/api/creator` | [creator.md](creator.md) | 6 |
| `/api/design-systems` | [design.md](design.md) | 5 |
| `/api/desktop` | [desktop.md](desktop.md) | 6 |
| `/api/device-lab` | [device.md](device.md) | 4 |
| `/api/evolution` | [evolution.md](evolution.md) | 22 |
| `/api/finance` | [finance.md](finance.md) | 11 |
| `/api/forge` | [forge.md](forge.md) | 7 |
| `/api/glossary`, `/api/glossary-export`, `/api/glossary-import` | [glossary.md](glossary.md) | 6 |
| `/api/health` | [health.md](health.md) | 1 |
| `/api/history` | [history.md](history.md) | 1 |
| `/api/jobs` | [jobs.md](jobs.md) | 2 |
| `/api/lab` | [lab.md](lab.md) | 4 |
| `/api/media` | [media.md](media.md) | 4 |
| `/api/memory`, `/api/memory-export`, `/api/memory-folders`, `/api/memory-graph`, `/api/memory-import`, `/api/memory-status` | [memory.md](memory.md) | 23 |
| `/api/messages` | [messages.md](messages.md) | 3 |
| `/api/minds` | [minds.md](minds.md) | 1 |
| `/api/pack` | [pack.md](pack.md) | 2 |
| `/api/permissions` | [permissions.md](permissions.md) | 1 |
| `/api/presets` | [presets.md](presets.md) | 1 |
| `/api/privacy` | [privacy.md](privacy.md) | 2 |
| `/api/project-branches`, `/api/projects` | [projects.md](projects.md) | 15 |
| `/api/providers` | [providers.md](providers.md) | 5 |
| `/api/questions` | [questions.md](questions.md) | 1 |
| `/api/research` | [research.md](research.md) | 3 |
| `/api/reverse` | [reverse.md](reverse.md) | 4 |
| `/api/runtime` | [runtime.md](runtime.md) | 3 |
| `/api/samples` | [samples.md](samples.md) | 2 |
| `/api/sandbox` | [sandbox.md](sandbox.md) | 1 |
| `/api/settings` | [settings.md](settings.md) | 2 |
| `/api/setup` | [setup.md](setup.md) | 4 |
| `/api/skills` | [skills.md](skills.md) | 5 |
| `/api/specialist-documents`, `/api/specialists` | [specialists.md](specialists.md) | 2 |
| `/api/subtitles` | [subtitles.md](subtitles.md) | 6 |
| `/api/system` | [system.md](system.md) | 1 |
| `/api/tools` | [tools.md](tools.md) | 1 |
| `/api/tune` | [tune.md](tune.md) | 2 |
| `/api/tutor` | [tutor.md](tutor.md) | 5 |
| `/api/usage` | [usage.md](usage.md) | 1 |
| `/api/workflows` | [workflows.md](workflows.md) | 15 |
| `/api/workspace` | [workspace.md](workspace.md) | 1 |
| `/v1/chat`, `/v1/models` | [v1.md](v1.md) | 2 |
| `/mcp` | [mcp.md](mcp.md) | 2 |

## Limits of this reference

- Error codes come from a static scan of each handler and the `spike.server` helpers it calls by name. A code raised
  deeper (or with a computed status) is not listed; a helper shared by several routes may list a code that one of
  them never reaches.
- Many routes return plain JSON objects without a declared model, so their response is listed as `object`.
