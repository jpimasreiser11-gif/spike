# Referencia de la API: `/api/subtitles`

Idioma: [English](../en/subtitles.md) | **Español** · [Índice de la API](README.md)

### `GET /api/subtitles`

Función: `spike/server/subtitles_api.py` → `status`

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | project not found |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/subtitles'
```

### `POST /api/subtitles/burn`

Función: `spike/server/subtitles_api.py` → `burn`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `cues` | object[] | sí |  |  |
| `cues[].start_ms` | integer | sí |  |  |
| `cues[].end_ms` | integer | sí |  |  |
| `cues[].text` | string | sí |  |  |
| `path` | string | sí |  |  |
| `project_id` | string \| null |  |  |  |
| `approved` | boolean |  | `false` |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | subtitles_command |
| `403` | request refused: it comes from another web site; subtitles_approval; {…} can only be changed on the computer SPIKE runs on |
| `404` | project not found |
| `409` | speech_busy |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/burn' \
  -H 'Content-Type: application/json' \
  -d '{"cues": [{"start_ms": 0, "end_ms": 0, "text": "string"}], "path": "string"}'
```

### `POST /api/subtitles/edit`

Función: `spike/server/subtitles_api.py` → `transform`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `cues` | object[] | sí |  |  |
| `cues[].start_ms` | integer | sí |  |  |
| `cues[].end_ms` | integer | sí |  |  |
| `cues[].text` | string | sí |  |  |
| `action` | "shift" \| "split" \| "merge" | sí |  |  |
| `index` | integer |  | `0` |  |
| `delta_ms` | integer |  | `0` |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/edit' \
  -H 'Content-Type: application/json' \
  -d '{"cues": [{"start_ms": 0, "end_ms": 0, "text": "string"}], "action": "shift"}'
```

### `POST /api/subtitles/export`

Función: `spike/server/subtitles_api.py` → `download`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `cues` | object[] | sí |  |  |
| `cues[].start_ms` | integer | sí |  |  |
| `cues[].end_ms` | integer | sí |  |  |
| `cues[].text` | string | sí |  |  |
| `format` | "srt" \| "vtt" | sí |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/export' \
  -H 'Content-Type: application/json' \
  -d '{"cues": [{"start_ms": 0, "end_ms": 0, "text": "string"}], "format": "srt"}'
```

### `POST /api/subtitles/import`

Función: `spike/server/subtitles_api.py` → `read`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `text` | string | sí |  |  |
| `format` | "srt" \| "vtt" | sí |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/import' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string", "format": "srt"}'
```

### `POST /api/subtitles/transcribe`

Función: `spike/server/subtitles_api.py` → `transcribe`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `path` | string | sí |  |  |
| `project_id` | string \| null |  |  |  |
| `approved` | boolean |  | `false` |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | subtitles_command |
| `403` | request refused: it comes from another web site; subtitles_approval; {…} can only be changed on the computer SPIKE runs on |
| `404` | project not found |
| `409` | speech_busy |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/subtitles/transcribe' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string"}'
```
