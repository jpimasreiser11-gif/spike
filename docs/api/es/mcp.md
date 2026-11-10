# Referencia de la API: `/mcp`

Idioma: [English](../en/mcp.md) | **Español** · [Índice de la API](README.md)

JSON-RPC 2.0 sobre Streamable HTTP con respuestas JSON. Los errores del protocolo vuelven con HTTP 200 y un `error` JSON-RPC: `-32700` JSON no válido (HTTP 400), `-32600` no es un mensaje JSON-RPC 2.0, `-32601` método desconocido, `-32602` `arguments` incorrectos o herramienta desconocida.

### `GET /mcp`

Función: `spike/server/app.py` → `mcp_stream`

**Errores**

| Código | Mensaje |
|---|---|
| `405` | — |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/mcp'
```

### `POST /mcp`

Función: `spike/server/app.py` → `mcp_endpoint`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `jsonrpc` | "2.0" | sí |  |  |
| `id` | integer \| string |  |  | sin él el mensaje es una notificación: respuesta `202` sin cuerpo |
| `method` | string | sí |  | `initialize`, `ping`, `tools/list` o `tools/call` |
| `params.name` | string |  |  | `tools/call`: `ask_spike` o `spike_<especialista>` |
| `params.arguments.question` | string |  |  | `tools/call`: la pregunta (obligatoria en todas las herramientas) |
| `params.arguments.specialist` | string |  |  | `ask_spike`: un id de especialista, o `auto` |
| `params.arguments.context` | string |  |  | material sobre el que responder |

**Errores**

| Código | Mensaje |
|---|---|
| `400` | invalid JSON |
| `401` | invalid or missing API key: send 'Authorization: Bearer &lt;SPIKE_API_TOKEN&gt;' |
| `403` | browser requests need an API token: start SPIKE with SPIKE_API_TOKEN set; without SPIKE_API_TOKEN only programs on this computer can use the API |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/mcp' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```
