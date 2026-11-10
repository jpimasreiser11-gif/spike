# Referencia de la API: `/api/reverse`

Idioma: [English](../en/reverse.md) | **Español** · [Índice de la API](README.md)

### `GET /api/reverse`

Función: `spike/server/reverse_api.py` → `status`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/reverse'
```

### `PUT /api/reverse/file`

The user's edits to a file Reverse Studio made: only `reverse/*.html` that exists, in the project or the workspace.

Función: `spike/server/reverse_api.py` → `save_file`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `project_id` | string \| null |  |  |  |
| `path` | string | sí |  |  |
| `html` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | reverse_path |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | reverse_file_missing; reverse_unknown_project |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/reverse/file' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string", "html": "string"}'
```

### `POST /api/reverse/generate`

Función: `spike/server/reverse_api.py` → `generate`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `preview_id` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | reverse_path; reverse_unknown_provider |
| `403` | (mensaje construido al ejecutar); request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | reverse_unknown_project |
| `409` | reverse_busy; reverse_changed; reverse_expired |
| `422` | (mensaje construido al ejecutar); la petición no cumple el esquema (validación de FastAPI) |
| `502` | reverse_failed |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/reverse/generate' \
  -H 'Content-Type: application/json' \
  -d '{"preview_id": "string"}'
```

### `POST /api/reverse/preview`

Función: `spike/server/reverse_api.py` → `preview`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `authorized` | any |  | `false` |  |
| `source` | "image" \| "url" \| "file" | sí |  |  |
| `image` | string \| null |  |  |  |
| `url` | string \| null |  |  |  |
| `path` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |
| `width` | integer \| null |  |  |  |
| `height` | integer \| null |  |  |  |
| `own_text` | string |  | `""` |  |
| `avoid` | string[] |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); reverse_authorization; reverse_unknown_provider; reverse_vision_required |
| `403` | request refused: it comes from another web site; reverse_context; {…} can only be changed on the computer SPIKE runs on |
| `404` | reverse_unknown_project |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/reverse/preview' \
  -H 'Content-Type: application/json' \
  -d '{"source": "image"}'
```
