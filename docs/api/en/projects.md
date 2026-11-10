# API reference: `/api/project-branches`, `/api/projects`

Language: [Español](../es/projects.md) | **English** · [API index](README.md)

### `GET /api/project-branches`

Handler: `spike/server/workspace_api.py` → `branches`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/project-branches'
```

### `GET /api/projects`

Handler: `spike/server/app.py` → `projects`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/projects'
```

### `POST /api/projects`

Handler: `spike/server/app.py` → `create_project`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `instructions` | string |  | `""` |  |
| `mode` | string |  | `"auto"` |  |
| `design` | string |  | `""` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown design system '{…}'; unknown mode '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `POST /api/projects/import`

Handler: `spike/server/app.py` → `import_project_zip`

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header |
| `413` | the upload is limited to {…} MB |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `GET /api/projects/{pid}`

Handler: `spike/server/app.py` → `get_project`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>'
```

### `PATCH /api/projects/{pid}`

Handler: `spike/server/app.py` → `patch_project`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string \| null |  |  |  |
| `instructions` | string \| null |  |  |  |
| `mode` | string \| null |  |  |  |
| `design` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown design system '{…}'; unknown mode '{…}' |
| `404` | project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/projects/<pid>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `DELETE /api/projects/{pid}`

Handler: `spike/server/app.py` → `delete_project`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | project not found |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/projects/<pid>'
```

### `GET /api/projects/{pid}/compare`

Handler: `spike/server/workspace_api.py` → `compare`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/compare'
```

### `GET /api/projects/{pid}/export`

Handler: `spike/server/app.py` → `export_project_zip`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/export'
```

### `GET /api/projects/{pid}/files`

Handler: `spike/server/app.py` → `project_files`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/files'
```

### `GET /api/projects/{pid}/files/{path}`

Handler: `spike/server/app.py` → `get_project_file`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |
| `path` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | file not found; project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/files/<path>'
```

### `PUT /api/projects/{pid}/files/{path}`

Handler: `spike/server/app.py` → `put_project_file`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |
| `path` | path | string | yes |  |

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header |
| `404` | project not found |
| `413` | the upload is limited to {…} MB |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/projects/<pid>/files/<path>' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `DELETE /api/projects/{pid}/files/{path}`

Handler: `spike/server/app.py` → `delete_project_file`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |
| `path` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | file not found; project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/projects/<pid>/files/<path>'
```

### `POST /api/projects/{pid}/fork`

Handler: `spike/server/workspace_api.py` → `fork`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects/<pid>/fork' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `POST /api/projects/{pid}/merge`

Handler: `spike/server/workspace_api.py` → `merge`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `token` | string | yes |  |  |
| `approved` | true | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects/<pid>/merge' \
  -H 'Content-Type: application/json' \
  -d '{"token": "string", "approved": true}'
```
