# API reference: `/api/messages`

Language: [Español](../es/messages.md) | **English** · [API index](README.md)

### `POST /api/messages/{mid}/escalate`

The user clicked "ask <provider>" on a low-confidence answer: the one place a second opinion is sent. The message is the question; the provider's guard still applies (paid calls, monthly limits, files withheld).

Handler: `spike/server/app.py` → `escalate`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `mid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `provider_id` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | (message built at run time) |
| `404` | (message built at run time) |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |
| `502` | (message built at run time) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/messages/<mid>/escalate' \
  -H 'Content-Type: application/json' \
  -d '{"provider_id": "string"}'
```

### `POST /api/messages/{mid}/learn`

Save, reword or dismiss the rule proposed from a correction, or undo what a message saved to memory.

Handler: `spike/server/app.py` → `learn`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `mid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | "save" \| "dismiss" \| "undo" | yes |  |  |
| `text` | string \| null |  |  |  |
| `memory` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/messages/<mid>/learn' \
  -H 'Content-Type: application/json' \
  -d '{"action": "save"}'
```

### `POST /api/messages/{mid}/route`

The user retries this question with another specialist: a route correction the router learns from.

Handler: `spike/server/app.py` → `route_correction`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `mid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `specialist` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/messages/<mid>/route' \
  -H 'Content-Type: application/json' \
  -d '{"specialist": "string"}'
```
