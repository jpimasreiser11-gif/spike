# API reference: `/api/history`

Language: [Español](../es/history.md) | **English** · [API index](README.md)

### `POST /api/history/search`

Handler: `spike/server/history_api.py` → `search`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes |  |  |
| `scope` | "all" \| "workspace" \| "project" |  | `"all"` |  |
| `project_id` | string \| null |  |  |  |
| `match` | "words" \| "phrase" |  | `"words"` |  |
| `role` | "all" \| "user" \| "assistant" |  | `"all"` |  |
| `after` | number |  | `0` |  |
| `limit` | integer |  | `20` |  |
| `offset` | integer |  | `0` |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); history_filter |
| `404` | project_not_found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/history/search' \
  -H 'Content-Type: application/json' \
  -d '{"query": "string"}'
```
