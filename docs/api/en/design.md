# API reference: `/api/design-systems`

Language: [Español](../es/design.md) | **English** · [API index](README.md)

### `GET /api/design-systems`

Handler: `spike/server/app.py` → `design_systems`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/design-systems'
```

### `POST /api/design-systems/import`

Handler: `spike/server/app.py` → `import_design`

**Body**: the file's bytes (`application/octet-stream`), read by the handler.

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time); invalid Content-Length header |
| `413` | the upload is limited to {…} MB |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/design-systems/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `GET /api/design-systems/{ds_id}`

Handler: `spike/server/app.py` → `design_system`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `ds_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | design system not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/design-systems/<ds_id>'
```

### `DELETE /api/design-systems/{ds_id}`

Handler: `spike/server/app.py` → `delete_design`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `ds_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | design system not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/design-systems/<ds_id>'
```

### `GET /api/design-systems/{ds_id}/preview`

A sample page in the system's tokens, for the app's isolated preview (not served as a page).

Handler: `spike/server/app.py` → `design_preview`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `ds_id` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | design system not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/design-systems/<ds_id>/preview'
```
