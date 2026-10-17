# Using SPIKE from other tools (OpenAI-compatible API and MCP)

`spike serve` also answers the OpenAI chat API at `http://127.0.0.1:8740/v1`, so tools that accept a custom
OpenAI-compatible endpoint can use SPIKE's specialists. Agents that speak MCP can instead call SPIKE as a tool
([below](#spike-as-an-mcp-server-claude-code-cursor-codex)). Nothing here is sent anywhere else: requests run on the
providers you configured in SPIKE, with the same paid-call guard.

## What the API offers

| Model id | What runs |
|---|---|
| `spike-auto` | the orchestrator: routes to one or more specialists, plans and merges like the app |
| `spike-<id>` (`spike-code`, `spike-medicine`, …) | that specialist only (its prompt and, when installed, its adapter) |
| `<provider>/<model>` (`spike-local/…`, `deepseek/deepseek-chat`, …) | passthrough to a provider configured in SPIKE, messages unchanged |

`GET /v1/models` lists them. `POST /v1/chat/completions` supports streaming (`stream`, `stream_options.include_usage`),
`max_tokens` / `max_completion_tokens`, `temperature`, `top_p`, `stop`, `tools` / `tool_calls`, `tool_choice: "none"`
and `response_format` (`json_object`, `json_schema`): the answer is checked against the schema, asked for once more
with the errors if it breaks it, and returned as bare JSON with `spike.contract` (`valid`, `attempts`, `errors`).
The client's `system` messages are added to the specialist's
prompt under "Instructions from the application calling SPIKE". Not supported: images (400), `n > 1` (400).

**How tools behave.** When the request carries the client's own `tools` (coding agents do), SPIKE runs one
specialist in *direct mode*: one model call with only the client's tools, and tool calls go back to the client,
which runs them as it always does. Without client tools, `spike-auto` runs the full orchestrator; SPIKE's own
tools that need approval (`write_file`, `python`, `web_fetch` by default) are refused there, because nobody can
answer the approval card through the API. The specialist that `spike-auto` picks in direct mode comes from the
lexical router on the last user message.

**Access.** Without `SPIKE_API_TOKEN` only programs on the same computer can call `/v1`, and requests from web
pages (any `Origin` header) are refused. To allow other machines or browser-based clients, start SPIKE with a
token and send it as the API key:

```bash
SPIKE_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" spike serve
```

Every client below takes an API key field; with no token configured, any placeholder works.

**Quality.** Whether a ~4B specialist is good enough for agentic coding or design work has **not been measured**
yet (see [STATUS](STATUS.md)); API tests only prove the protocol. Larger models configured as providers can be
used through the same endpoint with `<provider>/<model>`.

## Aider

From [aider's OpenAI-compatible docs](https://aider.chat/docs/llms/openai-compat.html) (the `openai/` prefix is required):

```bash
export OPENAI_API_BASE=http://127.0.0.1:8740/v1
export OPENAI_API_KEY=placeholder        # or your SPIKE_API_TOKEN
aider --model openai/spike-code
```

Aider will warn "Unknown context window size and costs"; per its docs the warning can be ignored
(`--no-show-model-warnings`). To silence it, add `.aider.model.metadata.json` (home directory, git root or
current directory) with the context your local engine runs with:

```json
{ "openai/spike-code": { "max_input_tokens": 32768, "max_output_tokens": 4096, "input_cost_per_token": 0,
  "output_cost_per_token": 0, "litellm_provider": "openai", "mode": "chat" } }
```

Aider edits through text formats, so it does not need tool calling.

## OpenCode

From [OpenCode's providers docs](https://opencode.ai/docs/providers/): `opencode.json` in the project root (or
`~/.config/opencode/opencode.json`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "spike": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "SPIKE (local)",
      "options": { "baseURL": "http://127.0.0.1:8740/v1", "apiKey": "{env:SPIKE_API_TOKEN}" },
      "models": {
        "spike-code": { "name": "SPIKE Code", "limit": { "context": 32768, "output": 4096 } },
        "spike-auto": { "name": "SPIKE Auto", "limit": { "context": 32768, "output": 4096 } }
      }
    }
  },
  "model": "spike/spike-code"
}
```

OpenCode's coding agent depends on tool calling; SPIKE passes its tools to the model in direct mode (natively
on llama.cpp, emulated where a provider lacks native tools). Set `limit` to the context you run.

## Continue

From [Continue's config reference](https://docs.continue.dev/reference): `~/.continue/config.yaml`
(Windows: `%USERPROFILE%\.continue\config.yaml`):

```yaml
name: SPIKE
version: 0.0.1
schema: v1
models:
  - name: SPIKE Code
    provider: openai
    model: spike-code
    apiBase: http://127.0.0.1:8740/v1
    apiKey: placeholder
    roles: [chat, edit, apply]
    capabilities: [tool_use]
```

`capabilities: [tool_use]` is needed for Continue's Agent mode, which it cannot detect for custom model names.

## open-design

[open-design](https://github.com/nexu-io/open-design) is configured in its Settings as a BYOK runtime: choose
an OpenAI-compatible endpoint and paste base URL `http://127.0.0.1:8740/v1`, an API key (required by its form;
a placeholder works without `SPIKE_API_TOKEN`) and a model such as `spike-auto`. Its source allows loopback
provider endpoints. Its quickstart notes that BYOK runs have no file tools, so the model must return the whole
artifact in its answer, a demanding task for a small local model (unmeasured).

## SPIKE as an MCP server (Claude Code, Cursor, Codex)

Here SPIKE is a tool the other agent calls, not its model: the agent keeps its own model and asks SPIKE's
specialists when it wants a second opinion in medicine, finance, law and the rest.

| Tool | What it does |
|---|---|
| `ask_spike` | the orchestrator picks one or several specialists and merges their answers; `specialist` can fix one |
| `spike_<id>` (`spike_medicine`, `spike_finance`, …) | that specialist only |

Every tool takes `question` and an optional `context` (text, data or code to work from) and returns the answer as
text plus `structuredContent` `{answer, specialists}`. As with `/v1`, calls get no memory, no connectors and no chat
history in the app, and SPIKE's tools that need approval are refused.

Two transports:

- **stdio**: `spike mcp` (the agent starts it). It uses a running `spike serve`'s settings and providers; add
  `--start-local` to start the local engine itself when the app is not running. The engine starts in the
  background, so `initialize` answers at once and the first call waits for the model to load.
- **Streamable HTTP**: `POST http://127.0.0.1:8740/mcp` on a running `spike serve`, with the `/v1` access rules
  (loopback only and no `Origin` header without `SPIKE_API_TOKEN`; with it, `Authorization: Bearer <token>`).

The setups below are each tool's documented format. They have **not been tried with those clients**; what is tested
is the protocol, with SPIKE's own MCP client and the official MCP Python SDK over both transports
(`tests/test_mcp_server.py`).

**Claude Code** ([docs](https://code.claude.com/docs/en/mcp)):

```bash
claude mcp add --transport stdio --scope user spike -- spike mcp --start-local
# or, with `spike serve` running:
claude mcp add --transport http spike http://127.0.0.1:8740/mcp
# add  --header "Authorization: Bearer $SPIKE_API_TOKEN"  when SPIKE runs with a token
```

**Cursor** (`~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project; [docs](https://cursor.com/docs/mcp)):

```json
{
  "mcpServers": {
    "spike": { "type": "stdio", "command": "spike", "args": ["mcp", "--start-local"] }
  }
}
```

or `"spike": { "url": "http://127.0.0.1:8740/mcp" }` with `spike serve` running.

**Codex CLI** (`~/.codex/config.toml`; [docs](https://developers.openai.com/codex/mcp)):

```toml
[mcp_servers.spike]
command = "spike"
args = ["mcp", "--start-local"]
startup_timeout_sec = 30
tool_timeout_sec = 600  # the default, 60 s, is short for a 4B model answering on a CPU
```

or `codex mcp add spike -- spike mcp --start-local`. With `spike serve` running, use `url =
"http://127.0.0.1:8740/mcp"` (and `bearer_token_env_var = "SPIKE_API_TOKEN"` when SPIKE runs with a token).

**Speed.** An answer takes as long as it takes in the app: on a CPU a long answer can take minutes (see the
measured speeds in [STATUS](STATUS.md)). Claude Code documents `MCP_TOOL_TIMEOUT` for slow tools; Cursor's docs
name no tool timeout setting.

## Anything else

Point any OpenAI SDK at the endpoint:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8740/v1", api_key="placeholder")
answer = client.chat.completions.create(model="spike-medicine", messages=[{"role": "user", "content": "…"}])
```

The response carries an extra `spike` field with the specialists that answered (or the provider, for passthrough).
