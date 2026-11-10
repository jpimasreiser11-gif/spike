# API reference: `/api/minds`

Language: [Español](../es/minds.md) | **English** · [API index](README.md)

### `POST /api/minds/estimate`

What Parallel Minds would cost for this message, shown before the user sends it. Calls no model.

Handler: `spike/server/app.py` → `minds_estimate`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `n` | integer \| null |  |  |  |
| `picks` | object[] \| null |  |  |  |
| `picks[].mode` | string \| null |  |  |  |
| `picks[].provider_id` | string \| null |  |  |  |
| `message` | string |  | `""` |  |
| `mode` | string |  | `"auto"` |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |
| `conversation_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); Parallel Minds needs a prose answer: it cannot be combined with a Forge blueprint or an answer contract (JSON); unknown mode '{…}'; unknown provider '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/minds/estimate' \
  -H 'Content-Type: application/json' \
  -d '{"n": 0}'
```
