# API reference: `/api/creator`

Language: [Español](../es/creator.md) | **English** · [API index](README.md)

### `POST /api/creator/blueprint`

A template filled with the user's answers: a Forge blueprint to review, its skills and design flag.

Handler: `spike/server/app.py` → `creator_blueprint`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `template` | string | yes |  |  |
| `fields` | object |  |  |  |
| `lang` | string |  | `"es"` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/blueprint' \
  -H 'Content-Type: application/json' \
  -d '{"template": "string"}'
```

### `POST /api/creator/data-app`

Handler: `spike/server/data_app_api.py` → `create`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | string | yes |  |  |
| `project_id` | string \| null |  |  |  |
| `lang` | string |  | `"es"` |  |
| `title` | string |  | `""` |  |
| `approved` | boolean |  | `false` |  |
| `labels` | object \| null |  |  |  |
| `labels.search` | string | yes |  |  |
| `labels.propose` | string | yes |  |  |
| `labels.hint` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | data_app_invalid |
| `403` | data_app_approval |
| `404` | data_app_project |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/data-app' \
  -H 'Content-Type: application/json' \
  -d '{"file": "string"}'
```

### `POST /api/creator/data-app/{sid}/approve`

Handler: `spike/server/data_app_api.py` → `approve`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `sid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `token` | string | yes |  |  |
| `approved` | boolean |  | `false` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | data_app_invalid |
| `403` | data_app_approval |
| `409` | data_app_conflict; data_app_expired |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/data-app/<sid>/approve' \
  -H 'Content-Type: application/json' \
  -d '{"token": "string"}'
```

### `POST /api/creator/data-app/{sid}/preview`

Handler: `spike/server/data_app_api.py` → `preview`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `sid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `edits` | object[] | yes |  |  |
| `edits[].row` | integer | yes |  |  |
| `edits[].column` | integer | yes |  |  |
| `edits[].value` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | data_app_invalid |
| `409` | data_app_conflict; data_app_expired |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/data-app/<sid>/preview' \
  -H 'Content-Type: application/json' \
  -d '{"edits": [{"row": 0, "column": 0, "value": "string"}]}'
```

### `GET /api/creator/data-files`

Handler: `spike/server/app.py` → `creator_data_files`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `404` | project not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/creator/data-files'
```

### `GET /api/creator/templates`

Handler: `spike/server/app.py` → `creator_templates`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `lang` | query | string |  | `"es"` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/creator/templates'
```
