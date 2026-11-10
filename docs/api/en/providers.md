# API reference: `/api/providers`

Language: [Español](../es/providers.md) | **English** · [API index](README.md)

### `GET /api/providers`

Handler: `spike/server/app.py` → `providers`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/providers'
```

### `POST /api/providers`

Handler: `spike/server/app.py` → `add_provider`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | string \| null |  |  |  |
| `preset` | string \| null |  |  |  |
| `kind` | string \| null |  |  |  |
| `name` | string \| null |  |  |  |
| `base_url` | string \| null |  |  |  |
| `model` | string \| null |  |  |  |
| `api_key` | string \| null |  |  |  |
| `paid` | boolean \| null |  |  |  |
| `allow_paid` | boolean \| null |  |  |  |
| `share_files` | boolean \| null |  |  |  |
| `limits` | object \| null |  |  |  |
| `limits.monthly_tokens` | integer \| null |  |  |  |
| `limits.monthly_cost` | number \| null |  |  |  |
| `limits.price_in` | number \| null |  |  |  |
| `limits.price_out` | number \| null |  |  |  |
| `capabilities` | object \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | base_url must be an http(s) URL; id or preset is required; kind must be one of {…} |
| `409` | provider '{…}' already exists |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/providers' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string"}'
```

### `PATCH /api/providers/{pid}`

Handler: `spike/server/app.py` → `patch_provider`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | string \| null |  |  |  |
| `preset` | string \| null |  |  |  |
| `kind` | string \| null |  |  |  |
| `name` | string \| null |  |  |  |
| `base_url` | string \| null |  |  |  |
| `model` | string \| null |  |  |  |
| `api_key` | string \| null |  |  |  |
| `paid` | boolean \| null |  |  |  |
| `allow_paid` | boolean \| null |  |  |  |
| `share_files` | boolean \| null |  |  |  |
| `limits` | object \| null |  |  |  |
| `limits.monthly_tokens` | integer \| null |  |  |  |
| `limits.monthly_cost` | number \| null |  |  |  |
| `limits.price_in` | number \| null |  |  |  |
| `limits.price_out` | number \| null |  |  |  |
| `capabilities` | object \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | base_url must be an http(s) URL |
| `404` | provider not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/providers/<pid>' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string"}'
```

### `DELETE /api/providers/{pid}`

Handler: `spike/server/app.py` → `delete_provider`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | the built-in local provider cannot be removed |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/providers/<pid>'
```

### `POST /api/providers/{pid}/test`

Checks connectivity with the model list endpoint, which no supported provider bills for.

Handler: `spike/server/app.py` → `test_provider`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `pid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/providers/<pid>/test'
```
