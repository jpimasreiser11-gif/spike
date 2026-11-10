# API reference: `/api/research`

Language: [Español](../es/research.md) | **English** · [API index](README.md)

### `POST /api/research/analyze`

Handler: `spike/server/research_api.py` → `analyze`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `preview_id` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown_provider |
| `403` | (message built at run time) |
| `404` | unknown_project |
| `409` | changed_preview; expired_preview |
| `422` | invalid_analysis; the request does not match the schema (FastAPI validation) |
| `502` | analysis_failed |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/research/analyze' \
  -H 'Content-Type: application/json' \
  -d '{"preview_id": "string"}'
```

### `GET /api/research/notebooks/{conversation_id}`

Handler: `spike/server/research_api.py` → `export_notebook`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `conversation_id` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_conversation |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/research/notebooks/<conversation_id>'
```

### `POST /api/research/preview`

Handler: `spike/server/research_api.py` → `preview`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | "paper" \| "contradictions" | yes |  |  |
| `paths` | string[] | yes |  |  |
| `project_id` | string \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |
| `language` | "es" \| "en" |  | `"es"` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid_sources; unknown_provider |
| `404` | unknown_project |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/research/preview' \
  -H 'Content-Type: application/json' \
  -d '{"kind": "paper", "paths": ["string"]}'
```
