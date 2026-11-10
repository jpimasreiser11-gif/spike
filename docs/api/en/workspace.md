# API reference: `/api/workspace`

Language: [Español](../es/workspace.md) | **English** · [API index](README.md)

### `GET /api/workspace/files/{path}`

Files the tools wrote outside a project (documents, pages), offered as downloads.

Handler: `spike/server/app.py` → `get_workspace_file`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `path` | path | string | yes |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | the path is outside the workspace |
| `404` | file not found |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/workspace/files/<path>'
```
