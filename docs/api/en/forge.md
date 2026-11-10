# API reference: `/api/forge`

Language: [Español](../es/forge.md) | **English** · [API index](README.md)

### `POST /api/forge/blueprint`

Draft a Forge blueprint for the user to review and approve; nothing runs yet.

Handler: `spike/server/app.py` → `forge_blueprint`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `task` | string | yes |  |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown project '{…}'; unknown provider '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/blueprint' \
  -H 'Content-Type: application/json' \
  -d '{"task": "string"}'
```

### `GET /api/forge/prototypes`

The saved prototype runs of the project's folder (or the workspace), newest first: those `built` wait for the user's pick. `git` says whether this computer has git, which the feature needs.

Handler: `spike/server/app.py` → `prototype_runs`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown project '{…}'; unknown provider '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/forge/prototypes'
```

### `POST /api/forge/prototypes`

Build the two approved blueprints on two git branches and compare them by running the same tests on both. Streams events tagged `proto: a|b`, then `proto_compare`; merging is a separate request the user makes.

Handler: `spike/server/app.py` → `prototype_start`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `task` | string | yes |  |  |
| `blueprints` | object[] | yes |  |  |
| `tests` | object \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | Parallel Prototypes saves files, which needs tools: turn them on in Settings; each approach must save at least one file (a step with 'deliverables'); prototypes: {…}; unknown project '{…}'; unknown provider '{…}' |
| `403` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes' \
  -H 'Content-Type: application/json' \
  -d '{"task": "string", "blueprints": [{}]}'
```

### `POST /api/forge/prototypes/blueprints`

Draft two blueprints, one per approach, for the user to review and approve; nothing runs yet.

Handler: `spike/server/app.py` → `prototype_blueprints`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `task` | string | yes |  |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | unknown project '{…}'; unknown provider '{…}' |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes/blueprints' \
  -H 'Content-Type: application/json' \
  -d '{"task": "string"}'
```

### `GET /api/forge/prototypes/{run_id}`

Handler: `spike/server/app.py` → `prototype_run`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `run_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/forge/prototypes/<run_id>'
```

### `POST /api/forge/prototypes/{run_id}/discard`

Drop a run: the checkouts and the two branches SPIKE made. The user's own branches are never touched.

Handler: `spike/server/app.py` → `prototype_discard`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `run_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `409` | this run is still building |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes/<run_id>/discard'
```

### `POST /api/forge/prototypes/{run_id}/merge`

Merge the approach the user chose into the branch the folder was on. Needs `approve: true`; a conflict, a folder that moved to another branch or has uncommitted changes to tracked files stops it, changing nothing.

Handler: `spike/server/app.py` → `prototype_merge`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `run_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `choice` | "a" \| "b" | yes |  |  |
| `approve` | boolean |  | `false` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes/<run_id>/merge' \
  -H 'Content-Type: application/json' \
  -d '{"choice": "a"}'
```
