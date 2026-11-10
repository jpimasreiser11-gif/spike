# API reference: `/api/workflows`

Language: [Español](../es/workflows.md) | **English** · [API index](README.md)

### `GET /api/workflows`

Handler: `spike/server/workflow_api.py` → `list_workflows`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows'
```

### `POST /api/workflows`

Save a new workflow (its first version). Nothing invalid is saved.

Handler: `spike/server/workflow_api.py` → `create_workflow`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `workflow` | object | yes |  |  |
| `base_revision` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `GET /api/workflows/catalog`

What a workflow may name, and the limits it is checked against.

Handler: `spike/server/workflow_api.py` → `catalog`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/catalog'
```

### `POST /api/workflows/import`

A workflow exported from here or another project, saved as a new workflow with a new id.

Handler: `spike/server/workflow_api.py` → `import_workflow`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `workflow` | object | yes |  |  |
| `base_revision` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/import' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `POST /api/workflows/validate`

Handler: `spike/server/workflow_api.py` → `validate_workflow`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `workflow` | object | yes |  |  |
| `base_revision` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/validate' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `GET /api/workflows/{wid}`

Handler: `spike/server/workflow_api.py` → `get_workflow`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |
| `revision` | query | integer \| null |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>'
```

### `PUT /api/workflows/{wid}`

The next version of a workflow; 409 when `base_revision` is not the newest any more.

Handler: `spike/server/workflow_api.py` → `save_workflow`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `workflow` | object | yes |  |  |
| `base_revision` | integer \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/workflows/<wid>' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `DELETE /api/workflows/{wid}`

Handler: `spike/server/workflow_api.py` → `delete_workflow`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict; workflow_running |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/workflows/<wid>'
```

### `GET /api/workflows/{wid}/export`

Handler: `spike/server/workflow_api.py` → `export_workflow`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |
| `revision` | query | integer \| null |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/export'
```

### `GET /api/workflows/{wid}/runs`

Handler: `spike/server/workflow_api.py` → `list_runs`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/runs'
```

### `POST /api/workflows/{wid}/runs`

Check the workflow and its inputs again, then start the run in the background; follow it with /events.

Handler: `spike/server/workflow_api.py` → `start_run`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `inputs` | object \| null |  |  |  |
| `revision` | integer \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); tools_disabled; unknown provider '{…}' |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | invalid_inputs; the request does not match the schema (FastAPI validation) |
| `429` | too_many_runs |
| `500` | run_not_stored |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/<wid>/runs' \
  -H 'Content-Type: application/json' \
  -d '{"inputs": {}}'
```

### `GET /api/workflows/{wid}/runs/{rid}`

Handler: `spike/server/workflow_api.py` → `get_run`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `rid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/runs/<rid>'
```

### `GET /api/workflows/{wid}/runs/{rid}/events`

The run's events from `after` on, then live until it ends. Only runs of this session have events.

Handler: `spike/server/workflow_api.py` → `run_events`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `rid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |
| `after` | query | integer |  | `0` |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `404` | run_not_found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/runs/<rid>/events'
```

### `POST /api/workflows/{wid}/runs/{rid}/stop`

Stop a run: the node that is working is cancelled (an unanswered permission question with it), the rest are not started, and the record is stored as `cancelled`.

Handler: `spike/server/workflow_api.py` → `stop_run`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `rid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | run_not_running; unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/<wid>/runs/<rid>/stop'
```

### `GET /api/workflows/{wid}/versions`

Handler: `spike/server/workflow_api.py` → `versions`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `wid` | path | string | yes |  |
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/versions'
```
