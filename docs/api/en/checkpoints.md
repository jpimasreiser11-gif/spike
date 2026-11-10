# API reference: `/api/checkpoints`

Language: [Español](../es/checkpoints.md) | **English** · [API index](README.md)

### `POST /api/checkpoints/{cp_id}/undo`

Put back the files one tool call changed, and mark that step as undone in its chat.

Handler: `spike/server/app.py` → `undo_step`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cp_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `force` | boolean |  | `false` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/checkpoints/<cp_id>/undo' \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'
```
