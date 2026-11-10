# API reference: `/api/media`

Language: [Español](../es/media.md) | **English** · [API index](README.md)

### `GET /api/media`

Handler: `spike/server/media_api.py` → `status`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/media'
```

### `PUT /api/media/settings`

Handler: `spike/server/media_api.py` → `settings`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `enabled` | boolean |  | `false` |  |
| `whisper_model` | string |  | `""` |  |
| `piper_model` | string |  | `""` |  |
| `piper_license` | string |  | `""` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/media/settings' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

### `POST /api/media/speak`

Handler: `spike/server/media_api.py` → `speak`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes |  |  |

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | subtitles_command |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | speech_busy |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/media/speak' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string"}'
```

### `POST /api/media/transcribe`

Handler: `spike/server/media_api.py` → `transcribe`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `audio` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | WAV; subtitles_command |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | speech_busy |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/media/transcribe' \
  -H 'Content-Type: application/json' \
  -d '{"audio": "string"}'
```
