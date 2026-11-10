# API reference: `/mcp`

Language: [Español](../es/mcp.md) | **English** · [API index](README.md)

JSON-RPC 2.0 over Streamable HTTP with JSON answers. Protocol errors come back with HTTP 200 and a JSON-RPC `error`: `-32700` invalid JSON (HTTP 400), `-32600` not a JSON-RPC 2.0 message, `-32601` unknown method, `-32602` bad `arguments` or unknown tool.

### `GET /mcp`

Handler: `spike/server/app.py` → `mcp_stream`

**Errors**

| Code | Message |
|---|---|
| `405` | — |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/mcp'
```

### `POST /mcp`

Handler: `spike/server/app.py` → `mcp_endpoint`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `jsonrpc` | "2.0" | yes |  |  |
| `id` | integer \| string |  |  | without it the message is a notification: answer `202`, no body |
| `method` | string | yes |  | `initialize`, `ping`, `tools/list` or `tools/call` |
| `params.name` | string |  |  | `tools/call`: `ask_spike` or `spike_<specialist>` |
| `params.arguments.question` | string |  |  | `tools/call`: the question (required by every tool) |
| `params.arguments.specialist` | string |  |  | `ask_spike`: a specialist id, or `auto` |
| `params.arguments.context` | string |  |  | material to answer about |

**Errors**

| Code | Message |
|---|---|
| `400` | invalid JSON |
| `401` | invalid or missing API key: send 'Authorization: Bearer &lt;SPIKE_API_TOKEN&gt;' |
| `403` | browser requests need an API token: start SPIKE with SPIKE_API_TOKEN set; without SPIKE_API_TOKEN only programs on this computer can use the API |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/mcp' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```
