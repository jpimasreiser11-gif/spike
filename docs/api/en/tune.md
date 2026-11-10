# API reference: `/api/tune`

Language: [Español](../es/tune.md) | **English** · [API index](README.md)

### `GET /api/tune`

Handler: `spike/server/app.py` → `tune_report`

**Response**: `200` — object \| null

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/tune'
```

### `POST /api/tune`

Handler: `spike/server/app.py` → `run_tune`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `quick` | boolean |  | `false` |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/tune' \
  -H 'Content-Type: application/json' \
  -d '{"quick": false}'
```
