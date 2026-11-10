# Referencia de la API: `/api/dev`

Idioma: [English](../en/dev.md) | **Español** · [Índice de la API](README.md)

### `GET /api/dev/history`

Saved conversations of one folder, newest first (read-only: nothing is opened or run).

Función: `spike/server/dev_api.py` → `history`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `folder` | query | string | sí |  |
| `limit` | query | integer |  | `20` |
| `offset` | query | integer |  | `0` |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | dev_folder_missing; dev_folder_not_dir; dev_folder_relative |
| `403` | dev_folder_forbidden |
| `409` | dev_folder_broad |
| `422` | la petición no cumple el esquema (validación de FastAPI) |
| `500` | dev_history_unreadable |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/history?folder=<folder>'
```

### `POST /api/dev/permissions/{request_id}`

Función: `spike/server/dev_api.py` → `decide`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `request_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `decision` | "allow_once" \| "allow_always" \| "deny" | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | no pending permission request with this id |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/permissions/<request_id>' \
  -H 'Content-Type: application/json' \
  -d '{"decision": "allow_once"}'
```

### `POST /api/dev/questions/{question_id}`

Función: `spike/server/dev_api.py` → `answer`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `question_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `answer` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | no pending question with this id |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/questions/<question_id>' \
  -H 'Content-Type: application/json' \
  -d '{"answer": "string"}'
```

### `GET /api/dev/sessions`

Función: `spike/server/dev_api.py` → `list_active`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions'
```

### `POST /api/dev/sessions`

Función: `spike/server/dev_api.py` → `open_session`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `folder` | string | sí |  |  |
| `confirm_broad` | boolean |  | `false` |  |
| `resume` | boolean |  | `false` |  |
| `resume_id` | string \| null |  |  |  |
| `plan` | boolean \| null |  |  |  |
| `specialist` | string |  | `"code"` |  |
| `provider_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); dev_folder_missing; dev_folder_not_dir; dev_folder_relative; dev_provider_unknown; dev_resume_both; dev_specialist_unknown |
| `403` | dev_folder_forbidden |
| `404` | dev_resume_unknown |
| `409` | dev_folder_broad; dev_session_open |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions' \
  -H 'Content-Type: application/json' \
  -d '{"folder": "string"}'
```

### `GET /api/dev/sessions/{session_id}`

Función: `spike/server/dev_api.py` → `get_session`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>'
```

### `DELETE /api/dev/sessions/{session_id}`

Función: `spike/server/dev_api.py` → `close_session`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/dev/sessions/<session_id>'
```

### `POST /api/dev/sessions/{session_id}/cancel`

Función: `spike/server/dev_api.py` → `cancel`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/cancel'
```

### `GET /api/dev/sessions/{session_id}/changes`

Función: `spike/server/dev_api.py` → `changes`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/changes'
```

### `POST /api/dev/sessions/{session_id}/clear`

Función: `spike/server/dev_api.py` → `clear`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `409` | dev_turn_running |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/clear'
```

### `GET /api/dev/sessions/{session_id}/files/{path}`

A file of the session's folder as a download (the list of files a turn made, with preview).

Función: `spike/server/dev_api.py` → `get_file`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |
| `path` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | the path is outside the folder |
| `404` | dev_session_unknown; file not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/files/<path>'
```

### `GET /api/dev/sessions/{session_id}/messages`

Función: `spike/server/dev_api.py` → `messages`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/messages'
```

### `POST /api/dev/sessions/{session_id}/mode`

Función: `spike/server/dev_api.py` → `set_mode`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `plan` | boolean | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `409` | dev_turn_running |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/mode' \
  -H 'Content-Type: application/json' \
  -d '{"plan": false}'
```

### `POST /api/dev/sessions/{session_id}/turn`

Función: `spike/server/dev_api.py` → `turn`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `message` | string | sí |  |  |
| `skills` | string[] |  |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | dev_session_unknown |
| `409` | dev_turn_running |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/turn' \
  -H 'Content-Type: application/json' \
  -d '{"message": "string"}'
```

### `POST /api/dev/sessions/{session_id}/undo`

Put back the files of the latest change not undone yet; files that changed since need `force`.

Función: `spike/server/dev_api.py` → `undo`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `session_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `force` | boolean |  | `false` |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `404` | dev_session_unknown |
| `409` | dev_turn_running; dev_undo_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/dev/sessions/<session_id>/undo' \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'
```

### `GET /api/dev/skills`

Función: `spike/server/dev_api.py` → `skills`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/dev/skills'
```
