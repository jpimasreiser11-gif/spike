# API reference: `/api/tutor`

Language: [Español](../es/tutor.md) | **English** · [API index](README.md)

### `GET /api/tutor`

Handler: `spike/server/memory_api.py` → `list_topics`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `due` | query | boolean |  | `false` |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/tutor'
```

### `POST /api/tutor`

Handler: `spike/server/memory_api.py` → `add_topic`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `scope` | string |  | `"global"` |  |
| `notes` | string |  | `""` |  |
| `mastery` | integer |  | `0` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); unknown memory scope '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/tutor' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `PATCH /api/tutor/{topic_id}`

Handler: `spike/server/memory_api.py` → `patch_topic`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `topic_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string \| null |  |  |  |
| `notes` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | topic not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/tutor/<topic_id>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `DELETE /api/tutor/{topic_id}`

Handler: `spike/server/memory_api.py` → `delete_topic`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `topic_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | topic not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/tutor/<topic_id>'
```

### `POST /api/tutor/{topic_id}/review`

Handler: `spike/server/memory_api.py` → `review_topic`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `topic_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `grade` | integer | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | topic not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/tutor/<topic_id>/review' \
  -H 'Content-Type: application/json' \
  -d '{"grade": 0}'
```
