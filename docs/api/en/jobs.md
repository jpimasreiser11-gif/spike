# API reference: `/api/jobs`

Language: [Español](../es/jobs.md) | **English** · [API index](README.md)

### `GET /api/jobs`

Handler: `spike/server/workspace_api.py` → `jobs`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/jobs'
```

### `POST /api/jobs/{jid}/cancel`

Handler: `spike/server/workspace_api.py` → `cancel`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `jid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | job not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/jobs/<jid>/cancel'
```
