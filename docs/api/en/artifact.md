# API reference: `/api/artifact-versions`

Language: [Español](../es/artifact.md) | **English** · [API index](README.md)

### `POST /api/artifact-versions`

Handler: `spike/server/workspace_api.py` → `version`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `title` | string | yes |  |  |
| `content` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/artifact-versions' \
  -H 'Content-Type: application/json' \
  -d '{"title": "string", "content": "string"}'
```

### `GET /api/artifact-versions/{aid}/comments`

Handler: `spike/server/workspace_api.py` → `comments`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `aid` | path | string | yes |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/artifact-versions/<aid>/comments'
```

### `POST /api/artifact-versions/{aid}/comments`

Handler: `spike/server/workspace_api.py` → `comment`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `aid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `line` | integer | yes |  |  |
| `text` | string | yes |  |  |
| `parent` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/artifact-versions/<aid>/comments' \
  -H 'Content-Type: application/json' \
  -d '{"line": 0, "text": "string"}'
```
