# API reference: `/api/conversations`

Language: [Español](../es/conversations.md) | **English** · [API index](README.md)

### `GET /api/conversations`

Handler: `spike/server/app.py` → `conversations`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/conversations'
```

### `POST /api/conversations`

Handler: `spike/server/app.py` → `new_conversation`

**Body** (`application/json`)

Any JSON value; the handler reads it itself.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/conversations' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "string"}'
```

### `GET /api/conversations/{cid}`

Handler: `spike/server/app.py` → `get_conversation`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | conversation not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/conversations/<cid>'
```

### `PATCH /api/conversations/{cid}`

Handler: `spike/server/app.py` → `patch_conversation`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `title` | string \| null |  |  |  |
| `mode` | string \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | conversation not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/conversations/<cid>' \
  -H 'Content-Type: application/json' \
  -d '{"title": "string"}'
```

### `DELETE /api/conversations/{cid}`

Handler: `spike/server/app.py` → `delete_conversation`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/conversations/<cid>'
```

### `POST /api/conversations/{cid}/branch`

A copy of the chat up to (not including) one of the user's messages, so an edit can go on in its own chat and the original stays as it was. Undo stays with the original chat's steps.

Handler: `spike/server/app.py` → `branch_conversation`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `before` | string | yes |  |  |
| `title` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | 'before' must be a user message of this conversation |
| `404` | conversation not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/conversations/<cid>/branch' \
  -H 'Content-Type: application/json' \
  -d '{"before": "string"}'
```

### `GET /api/conversations/{cid}/proof`

The chat with every recorded step, its model calls and file checksums, as a verifiable zip.

Handler: `spike/server/app.py` → `proof_package`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |
| `include` | query | string \| null |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | Unknown proof section / Sección de prueba desconocida |
| `404` | conversation not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/conversations/<cid>/proof'
```
