# API reference: `/api/privacy`

Language: [Español](../es/privacy.md) | **English** · [API index](README.md)

### `POST /api/privacy/delete`

Handler: `spike/server/backup_api.py` → `delete_all`

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | the confirmation word does not match; ask for a new one |
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `409` | refused: this is not SPIKE's own data folder |
| `415` | unsupported content type |
| `422` | send a JSON object with the confirmation word |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/privacy/delete' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `GET /api/privacy/delete-word`

The word the user must type to confirm deleting everything; single use, valid for 10 minutes.

Handler: `spike/server/backup_api.py` → `delete_word`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `lang` | query | string |  | `"en"` |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `415` | unsupported content type |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/privacy/delete-word'
```
