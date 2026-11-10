# API reference: `/api/calls`

Language: [Español](../es/calls.md) | **English** · [API index](README.md)

### `GET /api/calls`

Handler: `spike/server/app.py` → `calls`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `limit` | query | integer |  | `200` |
| `remote` | query | boolean |  | `false` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/calls'
```

### `DELETE /api/calls`

Handler: `spike/server/app.py` → `clear_calls`

**Response**: `200` — object

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/calls'
```
