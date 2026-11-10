# API reference: `/api/setup`

Language: [Español](../es/setup.md) | **English** · [API index](README.md)

### `GET /api/setup`

Handler: `spike/server/setup_api.py` → `status`

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/setup'
```

### `POST /api/setup/download`

Handler: `spike/server/setup_api.py` → `download`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `specialists` | string[] |  |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | Adapter unavailable |
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |
| `409` | Installation busy or insufficient resources |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/setup/download' \
  -H 'Content-Type: application/json' \
  -d '{"specialists": ["string"]}'
```

### `POST /api/setup/import`

Handler: `spike/server/setup_api.py` → `import_local_model`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  |  |
| `sha256` | string \| null |  |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | message |
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |
| `409` | Installation busy |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/setup/import' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string"}'
```

### `POST /api/setup/quit`

Handler: `spike/server/setup_api.py` → `quit_app`

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/setup/quit'
```
