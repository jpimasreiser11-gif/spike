# API reference: `/api/permissions`

Language: [Español](../es/permissions.md) | **English** · [API index](README.md)

### `POST /api/permissions/{request_id}`

Handler: `spike/server/app.py` → `decide`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `request_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `decision` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | no pending permission request with this id |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/permissions/<request_id>' \
  -H 'Content-Type: application/json' \
  -d '{"decision": "string"}'
```
