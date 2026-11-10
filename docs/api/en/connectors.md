# API reference: `/api/connectors`, `/api/connectors-audit`

Language: [Español](../es/connectors.md) | **English** · [API index](README.md)

### `GET /api/connectors`

Handler: `spike/server/app.py` → `connectors`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/connectors'
```

### `POST /api/connectors`

Handler: `spike/server/app.py` → `add_connector`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | string | yes |  |  |
| `name` | string | yes |  |  |
| `transport` | string |  | `"stdio"` |  |
| `command` | string |  | `""` |  |
| `args` | string[] |  |  |  |
| `url` | string |  | `""` |  |
| `description` | string |  | `""` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | connector not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string", "name": "string"}'
```

### `GET /api/connectors-audit`

Handler: `spike/server/app.py` → `connectors_audit`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `limit` | query | integer |  | `100` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/connectors-audit'
```

### `PUT /api/connectors/{cid}`

Handler: `spike/server/app.py` → `update_connector`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `enabled` | boolean \| null |  |  |  |
| `policy` | string \| null |  |  |  |
| `secrets` | object \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | connector not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/connectors/<cid>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

### `DELETE /api/connectors/{cid}`

Handler: `spike/server/app.py` → `delete_connector`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | connector not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/connectors/<cid>'
```

### `GET /api/connectors/{cid}/view`

Handler: `spike/server/app.py` → `connector_view_page`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |
| `uri` | query | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | connector not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/connectors/<cid>/view?uri=<uri>'
```

### `POST /api/connectors/{cid}/view/call`

{"result": CallToolResult}, or {"needs_approval": true} when the tool asks and the user has not allowed it.

Handler: `spike/server/app.py` → `connector_view_call`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `view` | string | yes |  |  |
| `name` | string | yes |  |  |
| `arguments` | object |  |  |  |
| `approved` | boolean |  | `false` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | (message built at run time) |
| `404` | connector not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors/<cid>/view/call' \
  -H 'Content-Type: application/json' \
  -d '{"view": "string", "name": "string"}'
```

### `POST /api/connectors/{cid}/view/event`

What a view did in the app (opened a link, wrote a message, gave context): kept in the audit log.

Handler: `spike/server/app.py` → `connector_view_event`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `view` | string | yes |  |  |
| `event` | "open-link" \| "message" \| "model-context" \| "log" \| "display-mode" \| "refused" | yes |  |  |
| `detail` | string |  | `""` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | connector not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors/<cid>/view/event' \
  -H 'Content-Type: application/json' \
  -d '{"view": "string", "event": "open-link"}'
```

### `POST /api/connectors/{cid}/view/read`

Handler: `spike/server/app.py` → `connector_view_read`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `cid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `view` | string | yes |  |  |
| `uri` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | connector not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors/<cid>/view/read' \
  -H 'Content-Type: application/json' \
  -d '{"view": "string", "uri": "string"}'
```
