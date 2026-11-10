# API reference: `/api/backup`

Language: [Español](../es/backup.md) | **English** · [API index](README.md)

### `GET /api/backup/export`

Handler: `spike/server/backup_api.py` → `export`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `include_models` | query | boolean |  | `false` |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `415` | unsupported content type |
| `422` | the request does not match the schema (FastAPI validation) |
| `500` | (message built at run time) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/backup/export'
```

### `POST /api/backup/preview`

Handler: `spike/server/backup_api.py` → `preview`

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header |
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `413` | the backup is too large |
| `415` | unsupported content type |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/backup/preview' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `POST /api/backup/restore`

Adds what is missing; replaces existing files only with `overwrite=1` (the UI asks first).

Handler: `spike/server/backup_api.py` → `restore`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `overwrite` | query | boolean |  | `false` |

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header |
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `413` | the backup is too large |
| `415` | unsupported content type |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/backup/restore' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```
