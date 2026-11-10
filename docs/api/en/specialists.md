# API reference: `/api/specialist-documents`, `/api/specialists`

Language: [Español](../es/specialists.md) | **English** · [API index](README.md)

### `POST /api/specialist-documents`

Handler: `spike/server/workspace_api.py` → `document`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `specialist` | string | yes |  |  |
| `filename` | string | yes |  |  |
| `text` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown specialist |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/specialist-documents' \
  -H 'Content-Type: application/json' \
  -d '{"specialist": "string", "filename": "string", "text": "string"}'
```

### `GET /api/specialists`

Handler: `spike/server/app.py` → `specialists`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/specialists'
```
