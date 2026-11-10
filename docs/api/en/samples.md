# API reference: `/api/samples`

Language: [Español](../es/samples.md) | **English** · [API index](README.md)

### `GET /api/samples`

Handler: `spike/server/samples_api.py` → `samples`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `lang` | query | string |  | `"en"` |

**Response**: `200` — object[]

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/samples'
```

### `POST /api/samples/{sample_id}/import`

Handler: `spike/server/samples_api.py` → `import_sample`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `sample_id` | path | string | yes |  |
| `lang` | query | string |  | `"en"` |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `404` | unknown_sample |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/samples/<sample_id>/import'
```
