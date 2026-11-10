# API reference: `/api/dev`

Language: [Español](../es/dev.md) | **English** · [API index](README.md)

### `GET /api/dev/history`

Saved conversations of one folder, newest first (read-only: nothing is opened or run).

Handler: `spike/server/dev_api.py` → `history`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `folder` | query | string | yes |  |
| `limit` | query | integer |  | `20` |
| `offset` | query | integer |  | `0` |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | dev_folder_missing; dev_folder_not_dir; dev_folder_relative |
| `403` | dev_folder_forbidden |
| `409` | dev_folder_broad |
| `422` | the request does not match the schema (FastAPI validation) |
| `500` | dev_history_unreadable |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/history?folder=<folder>'
```

### `POST /api/dev/permissions/{request_id}`

Handler: `spike/server/dev_api.py` → `decide`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `request_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `decision` | "allow_once" \| "allow_always" \| "deny" | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | no pending permission request with this id |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/permissions/<request_id>' \
  -H 'Content-Type: application/json' \
  -d '{"decision": "allow_once"}'
```

### `POST /api/dev/questions/{question_id}`

Handler: `spike/server/dev_api.py` → `answer`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `question_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `answer` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | no pending question with this id |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/questions/<question_id>' \
  -H 'Content-Type: application/json' \
  -d '{"answer": "string"}'
```

### `GET /api/dev/sessions`

Handler: `spike/server/dev_api.py` → `list_active`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions'
```

### `POST /api/dev/sessions`

Handler: `spike/server/dev_api.py` → `open_session`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder` | string | yes |  |  |
| `confirm_broad` | boolean |  | `false` |  |
| `resume` | boolean |  | `false` |  |
| `resume_id` | string \| null |  |  |  |
| `plan` | boolean \| null |  |  |  |
| `specialist` | string |  | `"code"` |  |
| `provider_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); dev_folder_missing; dev_folder_not_dir; dev_folder_relative; dev_provider_unknown; dev_resume_both; dev_specialist_unknown |
| `403` | dev_folder_forbidden |
| `404` | dev_resume_unknown |
| `409` | dev_folder_broad; dev_session_open |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions' \
  -H 'Content-Type: application/json' \
  -d '{"folder": "string"}'
```

### `GET /api/dev/sessions/{session_id}`

Handler: `spike/server/dev_api.py` → `get_session`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>'
```

### `DELETE /api/dev/sessions/{session_id}`

Handler: `spike/server/dev_api.py` → `close_session`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/dev/sessions/<session_id>'
```

### `POST /api/dev/sessions/{session_id}/cancel`

Handler: `spike/server/dev_api.py` → `cancel`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/cancel'
```

### `GET /api/dev/sessions/{session_id}/changes`

Handler: `spike/server/dev_api.py` → `changes`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/changes'
```

### `POST /api/dev/sessions/{session_id}/clear`

Handler: `spike/server/dev_api.py` → `clear`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `409` | dev_turn_running |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/clear'
```

### `GET /api/dev/sessions/{session_id}/files/{path}`

A file of the session's folder as a download (the list of files a turn made, with preview).

Handler: `spike/server/dev_api.py` → `get_file`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |
| `path` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | the path is outside the folder |
| `404` | dev_session_unknown; file not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/files/<path>'
```

### `GET /api/dev/sessions/{session_id}/messages`

Handler: `spike/server/dev_api.py` → `messages`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/messages'
```

### `POST /api/dev/sessions/{session_id}/mode`

Handler: `spike/server/dev_api.py` → `set_mode`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `plan` | boolean | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `409` | dev_turn_running |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/mode' \
  -H 'Content-Type: application/json' \
  -d '{"plan": false}'
```

### `POST /api/dev/sessions/{session_id}/turn`

Handler: `spike/server/dev_api.py` → `turn`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `message` | string | yes |  |  |
| `skills` | string[] |  |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | dev_session_unknown |
| `409` | dev_turn_running |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/turn' \
  -H 'Content-Type: application/json' \
  -d '{"message": "string"}'
```

### `POST /api/dev/sessions/{session_id}/undo`

Put back the files of the latest change not undone yet; files that changed since need `force`.

Handler: `spike/server/dev_api.py` → `undo`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `force` | boolean |  | `false` |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `404` | dev_session_unknown |
| `409` | dev_turn_running; dev_undo_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/undo' \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'
```

### `GET /api/dev/skills`

Handler: `spike/server/dev_api.py` → `skills`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/skills'
```
