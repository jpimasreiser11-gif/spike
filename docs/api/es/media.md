# Referencia de la API: `/api/media`

Idioma: [English](../en/media.md) | **Español** · [Índice de la API](README.md)

### `GET /api/media`

Función: `spike/server/media_api.py` → `status`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/media'
```

### `PUT /api/media/settings`

Función: `spike/server/media_api.py` → `settings`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `enabled` | boolean |  | `false` |  |
| `whisper_model` | string |  | `""` |  |
| `piper_model` | string |  | `""` |  |
| `piper_license` | string |  | `""` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/media/settings' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

### `POST /api/media/speak`

Función: `spike/server/media_api.py` → `speak`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `text` | string | sí |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | subtitles_command |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | speech_busy |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/media/speak' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string"}'
```

### `POST /api/media/transcribe`

Función: `spike/server/media_api.py` → `transcribe`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `audio` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | WAV; subtitles_command |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | speech_busy |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/media/transcribe' \
  -H 'Content-Type: application/json' \
  -d '{"audio": "string"}'
```
