# API reference: `/api/runtime`

Language: [Español](../es/runtime.md) | **English** · [API index](README.md)

### `GET /api/runtime`

Handler: `spike/server/app.py` → `runtime_status`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/runtime'
```

### `POST /api/runtime/start`

Handler: `spike/server/app.py` → `runtime_start`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/runtime/start'
```

### `POST /api/runtime/stop`

Handler: `spike/server/app.py` → `runtime_stop`

**Response**: `200` — object

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/runtime/stop'
```
