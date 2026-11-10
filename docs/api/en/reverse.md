# API reference: `/api/reverse`

Language: [Español](../es/reverse.md) | **English** · [API index](README.md)

### `GET /api/reverse`

Handler: `spike/server/reverse_api.py` → `status`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/reverse'
```

### `PUT /api/reverse/file`

The user's edits to a file Reverse Studio made: only `reverse/*.html` that exists, in the project or the workspace.

Handler: `spike/server/reverse_api.py` → `save_file`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string \| null |  |  |  |
| `path` | string | yes |  |  |
| `html` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | reverse_path |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | reverse_file_missing; reverse_unknown_project |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/reverse/file' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string", "html": "string"}'
```

### `POST /api/reverse/generate`

Handler: `spike/server/reverse_api.py` → `generate`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `preview_id` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | reverse_path; reverse_unknown_provider |
| `403` | (message built at run time); request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | reverse_unknown_project |
| `409` | reverse_busy; reverse_changed; reverse_expired |
| `422` | (message built at run time); the request does not match the schema (FastAPI validation) |
| `502` | reverse_failed |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/reverse/generate' \
  -H 'Content-Type: application/json' \
  -d '{"preview_id": "string"}'
```

### `POST /api/reverse/preview`

Handler: `spike/server/reverse_api.py` → `preview`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `authorized` | any |  | `false` |  |
| `source` | "image" \| "url" \| "file" | yes |  |  |
| `image` | string \| null |  |  |  |
| `url` | string \| null |  |  |  |
| `path` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |
| `width` | integer \| null |  |  |  |
| `height` | integer \| null |  |  |  |
| `own_text` | string |  | `""` |  |
| `avoid` | string[] |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); reverse_authorization; reverse_unknown_provider; reverse_vision_required |
| `403` | request refused: it comes from another web site; reverse_context; {…} can only be changed on the computer SPIKE runs on |
| `404` | reverse_unknown_project |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/reverse/preview' \
  -H 'Content-Type: application/json' \
  -d '{"source": "image"}'
```
