# API reference: `/api/errors`

Language: [Español](../es/errors.md) | **English** · [API index](README.md)

### `GET /api/errors`

Handler: `spike/server/errors_api.py` → `errors`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `limit` | query | integer |  | `200` |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/errors'
```

### `DELETE /api/errors`

Handler: `spike/server/errors_api.py` → `clear`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/errors'
```

### `GET /api/errors/report`

The text for "copy as issue": the browser copies it; nothing leaves this computer from here.

Handler: `spike/server/errors_api.py` → `report`

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/errors/report'
```
