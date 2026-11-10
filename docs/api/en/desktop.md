# API reference: `/api/desktop`

Language: [Español](../es/desktop.md) | **English** · [API index](README.md)

### `GET /api/desktop`

The setting, what this computer can do (and what is missing), and which providers could do the actions.

Handler: `spike/server/desktop_api.py` → `desktop_status`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `refresh` | query | boolean |  | `false` |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/desktop'
```

### `POST /api/desktop/actions/{action_id}`

The user's answer to an approval card. Nothing runs without one.

Handler: `spike/server/desktop_api.py` → `desktop_answer`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `action_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `decision` | "approve" \| "approve_batch" \| "deny" \| "stop" | yes |  |  |
| `n` | integer |  | `1` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | no pending desktop action with this id |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/actions/<action_id>' \
  -H 'Content-Type: application/json' \
  -d '{"decision": "approve"}'
```

### `POST /api/desktop/estimate`

What a task would send and cost at most, shown before it starts.

Handler: `spike/server/desktop_api.py` → `desktop_estimate`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `provider_id` | string \| null |  |  |  |
| `max_steps` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/estimate' \
  -H 'Content-Type: application/json' \
  -d '{"provider_id": "string"}'
```

### `POST /api/desktop/run`

Handler: `spike/server/desktop_api.py` → `desktop_run`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `goal` | string | yes |  |  |
| `provider_id` | string \| null |  |  |  |
| `conversation_id` | string \| null |  |  |  |
| `keep_screenshots` | boolean |  | `false` |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | describe what the task is |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | conversation not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/run' \
  -H 'Content-Type: application/json' \
  -d '{"goal": "string"}'
```

### `GET /api/desktop/shots/{task_id}/{n}`

A screenshot of the running task, for its cards. It is the user's screen: only this computer, never cached.

Handler: `spike/server/desktop_api.py` → `desktop_shot`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `task_id` | path | string | yes |  |
| `n` | path | integer | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | screenshot not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/desktop/shots/<task_id>/<n>'
```

### `POST /api/desktop/stop`

Stop the running task now (the button that is always on screen while one runs).

Handler: `spike/server/desktop_api.py` → `desktop_stop`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/stop'
```
