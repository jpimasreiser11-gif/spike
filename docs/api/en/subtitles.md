# API reference: `/api/subtitles`

Language: [Español](../es/subtitles.md) | **English** · [API index](README.md)

### `GET /api/subtitles`

Handler: `spike/server/subtitles_api.py` → `status`

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | project not found |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/subtitles'
```

### `POST /api/subtitles/burn`

Handler: `spike/server/subtitles_api.py` → `burn`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `cues` | object[] | yes |  |  |
| `cues[].start_ms` | integer | yes |  |  |
| `cues[].end_ms` | integer | yes |  |  |
| `cues[].text` | string | yes |  |  |
| `path` | string | yes |  |  |
| `project_id` | string \| null |  |  |  |
| `approved` | boolean |  | `false` |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | subtitles_command |
| `403` | request refused: it comes from another web site; subtitles_approval; {…} can only be changed on the computer SPIKE runs on |
| `404` | project not found |
| `409` | speech_busy |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/burn' \
  -H 'Content-Type: application/json' \
  -d '{"cues": [{"start_ms": 0, "end_ms": 0, "text": "string"}], "path": "string"}'
```

### `POST /api/subtitles/edit`

Handler: `spike/server/subtitles_api.py` → `transform`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `cues` | object[] | yes |  |  |
| `cues[].start_ms` | integer | yes |  |  |
| `cues[].end_ms` | integer | yes |  |  |
| `cues[].text` | string | yes |  |  |
| `action` | "shift" \| "split" \| "merge" | yes |  |  |
| `index` | integer |  | `0` |  |
| `delta_ms` | integer |  | `0` |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/edit' \
  -H 'Content-Type: application/json' \
  -d '{"cues": [{"start_ms": 0, "end_ms": 0, "text": "string"}], "action": "shift"}'
```

### `POST /api/subtitles/export`

Handler: `spike/server/subtitles_api.py` → `download`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `cues` | object[] | yes |  |  |
| `cues[].start_ms` | integer | yes |  |  |
| `cues[].end_ms` | integer | yes |  |  |
| `cues[].text` | string | yes |  |  |
| `format` | "srt" \| "vtt" | yes |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/export' \
  -H 'Content-Type: application/json' \
  -d '{"cues": [{"start_ms": 0, "end_ms": 0, "text": "string"}], "format": "srt"}'
```

### `POST /api/subtitles/import`

Handler: `spike/server/subtitles_api.py` → `read`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes |  |  |
| `format` | "srt" \| "vtt" | yes |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/import' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string", "format": "srt"}'
```

### `POST /api/subtitles/transcribe`

Handler: `spike/server/subtitles_api.py` → `transcribe`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  |  |
| `project_id` | string \| null |  |  |  |
| `approved` | boolean |  | `false` |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | subtitles_command |
| `403` | request refused: it comes from another web site; subtitles_approval; {…} can only be changed on the computer SPIKE runs on |
| `404` | project not found |
| `409` | speech_busy |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/transcribe' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string"}'
```
