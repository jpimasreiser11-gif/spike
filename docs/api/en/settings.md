# API reference: `/api/settings`

Language: [Español](../es/settings.md) | **English** · [API index](README.md)

### `GET /api/settings`

Handler: `spike/server/app.py` → `get_settings`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/settings'
```

### `PUT /api/settings`

Handler: `spike/server/app.py` → `put_settings`

**Body** (`application/json`)

Any JSON value; the handler reads it itself.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/settings' \
  -H 'Content-Type: application/json' \
  -d '{}'
```
