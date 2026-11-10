# API reference: `/api/evolution`

Language: [Español](../es/evolution.md) | **English** · [API index](README.md)

### `GET /api/evolution`

Handler: `spike/server/app.py` → `evolution`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution'
```

### `GET /api/evolution/candidates.jsonl`

Handler: `spike/server/app.py` → `export_candidates`

**Response**: `200`

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/candidates.jsonl'
```

### `POST /api/evolution/check`

Handler: `spike/server/app.py` → `evolution_check`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `replay` | boolean |  | `false` |  |
| `prompts` | boolean |  | `false` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/check' \
  -H 'Content-Type: application/json' \
  -d '{"replay": false}'
```

### `POST /api/evolution/examples/build`

Handler: `spike/server/app.py` → `build_examples`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `409` | (message built at run time) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/examples/build'
```

### `GET /api/evolution/items`

Handler: `spike/server/app.py` → `evolution_items`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `kind` | query | string \| null |  |  |
| `status` | query | string \| null |  |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/items'
```

### `PATCH /api/evolution/items/{iid}`

Handler: `spike/server/app.py` → `patch_evolution_item`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `iid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | "proposed" \| "accepted" \| "approved" \| "rejected" \| "new" \| "ignored" \| null |  |  |  |
| `question` | string \| null |  |  |  |
| `checks` | object \| null |  |  |  |
| `cause` | string \| null |  |  |  |
| `fix` | string \| null |  |  |  |
| `verified` | boolean \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); a {…} cannot be changed this way |
| `404` | item not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/evolution/items/<iid>' \
  -H 'Content-Type: application/json' \
  -d '{"status": "proposed"}'
```

### `DELETE /api/evolution/items/{iid}`

Handler: `spike/server/app.py` → `delete_evolution_item`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `iid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | item not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/evolution/items/<iid>'
```

### `GET /api/evolution/items/{iid}/issue`

Handler: `spike/server/app.py` → `failure_issue`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `iid` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `404` | failure not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/items/<iid>/issue'
```

### `GET /api/evolution/personal`

Handler: `spike/server/evolution_api.py` → `personal`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/personal'
```

### `PUT /api/evolution/personal/exclusions`

Handler: `spike/server/evolution_api.py` → `exclude`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `ref` | string | yes |  |  |
| `excluded` | boolean |  | `true` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | that example is not in the personal set |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/evolution/personal/exclusions' \
  -H 'Content-Type: application/json' \
  -d '{"ref": "string"}'
```

### `POST /api/evolution/personal/marks`

Handler: `spike/server/evolution_api.py` → `mark_chat`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `conversation` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | (message built at run time) |
| `409` | turn on the personal adapter in Settings → Evolución first |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/personal/marks' \
  -H 'Content-Type: application/json' \
  -d '{"conversation": "string"}'
```

### `DELETE /api/evolution/personal/marks/{conversation}`

Handler: `spike/server/evolution_api.py` → `unmark_chat`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `conversation` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | that chat is not marked |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/evolution/personal/marks/<conversation>'
```

### `GET /api/evolution/prompts`

Handler: `spike/server/app.py` → `learned_prompts`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/prompts'
```

### `POST /api/evolution/prompts/{specialist}/activate`

Compare the candidate with the version in use on the user's eval questions and use it only if it passes. One model job at a time, like the optimiser, so the computer stays usable.

Handler: `spike/server/evolution_api.py` → `activate_prompt`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `specialist` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `version` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | (message built at run time) |
| `409` | an optimisation is already running; job cancelled |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/prompts/<specialist>/activate' \
  -H 'Content-Type: application/json' \
  -d '{"version": 0}'
```

### `POST /api/evolution/prompts/{specialist}/candidate`

Handler: `spike/server/evolution_api.py` → `propose_prompt`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `specialist` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `instructions` | string[] |  |  |  |
| `skills` | object |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/prompts/<specialist>/candidate' \
  -H 'Content-Type: application/json' \
  -d '{"instructions": ["string"]}'
```

### `POST /api/evolution/prompts/{specialist}/optimize`

Evolution level 2 with its progress as server-sent events; one at a time, so the computer stays usable.

Handler: `spike/server/app.py` → `optimize_prompt`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `specialist` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `instructions` | string[] |  |  |  |
| `max_calls` | integer \| null |  |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `404` | unknown specialist '{…}' |
| `409` | an optimisation is already running |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/prompts/<specialist>/optimize' \
  -H 'Content-Type: application/json' \
  -d '{"instructions": ["string"]}'
```

### `POST /api/evolution/rollback`

Handler: `spike/server/app.py` → `evolution_rollback`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `component` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | (message built at run time) |
| `409` | the previous adapter file is gone |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/rollback' \
  -H 'Content-Type: application/json' \
  -d '{"component": "string"}'
```

### `POST /api/evolution/router/learn`

Handler: `spike/server/app.py` → `learn_router`

**Response**: `200` — object

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/router/learn'
```

### `GET /api/evolution/strategy`

Handler: `spike/server/evolution_api.py` → `strategy_table`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/strategy'
```

### `DELETE /api/evolution/strategy`

Handler: `spike/server/evolution_api.py` → `reset_strategy`

**Response**: `200` — object

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/evolution/strategy'
```

### `POST /api/evolution/strategy/learn`

Handler: `spike/server/evolution_api.py` → `learn_strategy`

**Response**: `200` — object

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/strategy/learn'
```

### `GET /api/evolution/{name}.jsonl`

Approved correction examples: `training` (chats for SFT) or `preferences` (pairs for DPO).

Handler: `spike/server/app.py` → `export_examples`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `name` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `404` | not found |
| `409` | turn on “Use my corrections to retrain” in Settings → Evolution first |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/<name>.jsonl'
```
