# API reference: `/api/lab`

Language: [Español](../es/lab.md) | **English** · [API index](README.md)

### `POST /api/lab/execute`

Handler: `spike/server/lab_api.py` → `execute`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `quote_id` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | invalid_cases; invalid_target; one_probe_target |
| `403` | provider_blocked |
| `409` | changed_quote; expired_quote |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/lab/execute' \
  -H 'Content-Type: application/json' \
  -d '{"quote_id": "string"}'
```

### `POST /api/lab/preview`

Handler: `spike/server/lab_api.py` → `preview`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | "compare" \| "probe" |  | `"compare"` |  |
| `prompt` | string |  | `""` |  |
| `cases` | object[] |  |  |  |
| `cases[].prompt` | string | yes |  |  |
| `cases[].expected` | string \| null |  |  |  |
| `targets` | object[] | yes |  |  |
| `targets[].specialist` | string |  | `"core"` |  |
| `targets[].provider_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | invalid_cases; invalid_target; one_probe_target |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/lab/preview' \
  -H 'Content-Type: application/json' \
  -d '{"targets": [{}]}'
```

### `GET /api/lab/runs`

Handler: `spike/server/lab_api.py` → `runs`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/lab/runs'
```

### `GET /api/lab/runs/{run_id}/export`

Handler: `spike/server/lab_api.py` → `export`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `run_id` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `404` | unknown_run |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/lab/runs/<run_id>/export'
```
