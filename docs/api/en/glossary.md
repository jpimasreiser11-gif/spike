# API reference: `/api/glossary`, `/api/glossary-export`, `/api/glossary-import`

Language: [Español](../es/glossary.md) | **English** · [API index](README.md)

### `GET /api/glossary`

Handler: `spike/server/memory_api.py` → `list_glossary`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `q` | query | string \| null |  |  |
| `limit` | query | integer |  | `1000` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/glossary'
```

### `POST /api/glossary`

Handler: `spike/server/memory_api.py` → `add_glossary`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `term` | string | yes |  |  |
| `translation` | string | yes |  |  |
| `lang` | string |  | `""` |  |
| `note` | string |  | `""` |  |
| `scope` | string |  | `"global"` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/glossary' \
  -H 'Content-Type: application/json' \
  -d '{"term": "string", "translation": "string"}'
```

### `GET /api/glossary-export`

Handler: `spike/server/memory_api.py` → `export_glossary`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string |  | `"global"` |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/glossary-export'
```

### `POST /api/glossary-import`

Handler: `spike/server/memory_api.py` → `import_glossary`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string |  | `"global"` |

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header; unknown memory scope '{…}' |
| `413` | the upload is limited to {…} MB |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/glossary-import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `PUT /api/glossary/{entry_id}`

Handler: `spike/server/memory_api.py` → `update_glossary`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `entry_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `term` | string \| null |  |  |  |
| `translation` | string \| null |  |  |  |
| `lang` | string \| null |  |  |  |
| `note` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | entry not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/glossary/<entry_id>' \
  -H 'Content-Type: application/json' \
  -d '{"term": "string"}'
```

### `DELETE /api/glossary/{entry_id}`

Handler: `spike/server/memory_api.py` → `delete_glossary`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `entry_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | entry not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/glossary/<entry_id>'
```
