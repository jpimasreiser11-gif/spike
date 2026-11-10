# API reference: `/api/pack`

Language: [Español](../es/pack.md) | **English** · [API index](README.md)

### `GET /api/pack/export`

Handler: `spike/server/app.py` → `pack_export`

**Response**: `200`

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/pack/export'
```

### `POST /api/pack/import`

Handler: `spike/server/app.py` → `pack_import`

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header; invalid specialist in pack: {…} |
| `413` | the upload is limited to {…} MB |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/pack/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```
