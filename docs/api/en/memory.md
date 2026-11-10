# API reference: `/api/memory`, `/api/memory-export`, `/api/memory-folders`, `/api/memory-graph`, `/api/memory-import`, `/api/memory-status`

Language: [Español](../es/memory.md) | **English** · [API index](README.md)

### `GET /api/memory`

Handler: `spike/server/app.py` → `list_memory`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `kind` | query | string \| null |  |  |
| `q` | query | string \| null |  |  |
| `limit` | query | integer |  | `200` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory'
```

### `POST /api/memory`

Handler: `spike/server/app.py` → `add_memory`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes |  |  |
| `kind` | string |  | `"fact"` |  |
| `scope` | string |  | `"global"` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string"}'
```

### `DELETE /api/memory`

Handler: `spike/server/app.py` → `clear_memory`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory?scope=<scope>'
```

### `GET /api/memory-export`

Handler: `spike/server/app.py` → `export_memory`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-export'
```

### `GET /api/memory-folders`

Handler: `spike/server/memory_api.py` → `list_folders`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-folders'
```

### `POST /api/memory-folders`

Handler: `spike/server/memory_api.py` → `add_folder`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  |  |
| `scope` | string |  | `"global"` |  |
| `include` | string[] \| null |  |  |  |
| `exclude` | string[] \| null |  |  |  |
| `max_file_bytes` | integer \| null |  |  |  |
| `max_files` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-folders' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string"}'
```

### `GET /api/memory-folders/{folder_id}`

Handler: `spike/server/memory_api.py` → `get_folder`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `folder_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | folder not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-folders/<folder_id>'
```

### `PATCH /api/memory-folders/{folder_id}`

Handler: `spike/server/memory_api.py` → `patch_folder`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `folder_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `include` | string[] \| null |  |  |  |
| `exclude` | string[] \| null |  |  |  |
| `max_file_bytes` | integer \| null |  |  |  |
| `max_files` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | folder not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/memory-folders/<folder_id>' \
  -H 'Content-Type: application/json' \
  -d '{"include": ["string"]}'
```

### `DELETE /api/memory-folders/{folder_id}`

Handler: `spike/server/memory_api.py` → `forget_folder`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `folder_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | folder not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory-folders/<folder_id>'
```

### `GET /api/memory-folders/{folder_id}/files`

Handler: `spike/server/memory_api.py` → `folder_files`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `folder_id` | path | string | yes |  |
| `limit` | query | integer |  | `500` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `404` | folder not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-folders/<folder_id>/files'
```

### `POST /api/memory-folders/{folder_id}/reindex`

Handler: `spike/server/memory_api.py` → `reindex_folder`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `folder_id` | path | string | yes |  |

**Body** (`application/json`)

Any JSON value; the handler reads it itself.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | folder not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-folders/<folder_id>/reindex' \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'
```

### `GET /api/memory-graph`

Handler: `spike/server/memory_api.py` → `memory_graph`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `node` | query | string \| null |  |  |
| `depth` | query | integer |  | `1` |
| `limit` | query | integer |  | `30` |
| `notes` | query | boolean |  | `true` |
| `proposed` | query | boolean |  | `false` |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph'
```

### `GET /api/memory-graph/entities`

Handler: `spike/server/memory_api.py` → `graph_entities`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `q` | query | string \| null |  |  |
| `kind` | query | string \| null |  |  |
| `limit` | query | integer |  | `50` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph/entities'
```

### `POST /api/memory-graph/propose`

Ask the local model for relations between the entities of one note; the answers are proposals.

Handler: `spike/server/memory_api.py` → `propose_relations`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `memory_id` | string | yes |  |  |
| `provider_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | (message built at run time) |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |
| `503` | (message built at run time) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-graph/propose' \
  -H 'Content-Type: application/json' \
  -d '{"memory_id": "string"}'
```

### `GET /api/memory-graph/relations`

Handler: `spike/server/memory_api.py` → `graph_relations`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `status` | query | string \| null |  |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph/relations'
```

### `POST /api/memory-graph/relations`

Handler: `spike/server/memory_api.py` → `add_relation`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `scope` | string |  | `"global"` |  |
| `source` | string | yes |  |  |
| `label` | string | yes |  |  |
| `target` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-graph/relations' \
  -H 'Content-Type: application/json' \
  -d '{"source": "string", "label": "string", "target": "string"}'
```

### `PATCH /api/memory-graph/relations/{relation_id}`

Handler: `spike/server/memory_api.py` → `patch_relation`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `relation_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | "proposed" \| "confirmed" \| "rejected" | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | relation not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/memory-graph/relations/<relation_id>' \
  -H 'Content-Type: application/json' \
  -d '{"status": "proposed"}'
```

### `DELETE /api/memory-graph/relations/{relation_id}`

Handler: `spike/server/memory_api.py` → `delete_relation`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `relation_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | relation not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory-graph/relations/<relation_id>'
```

### `GET /api/memory-graph/svg`

Handler: `spike/server/memory_api.py` → `memory_graph_svg`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `node` | query | string \| null |  |  |
| `depth` | query | integer |  | `1` |
| `limit` | query | integer |  | `30` |
| `notes` | query | boolean |  | `true` |
| `proposed` | query | boolean |  | `false` |
| `lang` | query | string |  | `"en"` |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph/svg'
```

### `POST /api/memory-import`

Handler: `spike/server/app.py` → `import_memory`

**Body**: a JSON object the handler reads itself; its fields are not in the schema.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | invalid Content-Length header; invalid memory file: {…}; unknown memory scope '{…}' |
| `413` | the upload is limited to {…} MB |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-import' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### `GET /api/memory-status`

Handler: `spike/server/app.py` → `memory_status`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-status'
```

### `PUT /api/memory/{mid}`

Handler: `spike/server/app.py` → `update_memory`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `mid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string \| null |  |  |  |
| `kind` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | memory not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/memory/<mid>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string"}'
```

### `DELETE /api/memory/{mid}`

Handler: `spike/server/app.py` → `delete_memory`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `mid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | memory not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory/<mid>'
```
