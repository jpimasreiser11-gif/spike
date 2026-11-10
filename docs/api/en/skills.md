# API reference: `/api/skills`

Language: [Español](../es/skills.md) | **English** · [API index](README.md)

### `GET /api/skills`

Handler: `spike/server/app.py` → `skills`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/skills'
```

### `POST /api/skills/import`

Handler: `spike/server/app.py` → `import_skills`

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header |
| `413` | the upload is limited to {…} MB |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/skills/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `POST /api/skills/import-github/install`

Handler: `spike/server/skill_import_api.py` → `install`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `preview_id` | string | yes |  |  |
| `sha256` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | hash_mismatch; invalid_skill |
| `403` | license_blocked |
| `404` | preview_expired |
| `409` | exists |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/skills/import-github/install' \
  -H 'Content-Type: application/json' \
  -d '{"preview_id": "string", "sha256": "string"}'
```

### `POST /api/skills/import-github/preview`

Handler: `spike/server/skill_import_api.py` → `preview`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/skills/import-github/preview' \
  -H 'Content-Type: application/json' \
  -d '{"url": "string"}'
```

### `GET /api/skills/{name}`

Handler: `spike/server/app.py` → `get_skill`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `name` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | skill not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/skills/<name>'
```

### `PUT /api/skills/{name}`

Handler: `spike/server/app.py` → `toggle_skill`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `name` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `enabled` | boolean | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | skill not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/skills/<name>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

### `DELETE /api/skills/{name}`

Handler: `spike/server/app.py` → `delete_skill`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `name` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | built-in skills can be disabled, not deleted |
| `404` | skill not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/skills/<name>'
```
