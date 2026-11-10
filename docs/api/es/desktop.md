# Referencia de la API: `/api/desktop`

Idioma: [English](../en/desktop.md) | **Español** · [Índice de la API](README.md)

### `GET /api/desktop`

The setting, what this computer can do (and what is missing), and which providers could do the actions.

Función: `spike/server/desktop_api.py` → `desktop_status`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `refresh` | query | boolean |  | `false` |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/desktop'
```

### `POST /api/desktop/actions/{action_id}`

The user's answer to an approval card. Nothing runs without one.

Función: `spike/server/desktop_api.py` → `desktop_answer`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `action_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `decision` | "approve" \| "approve_batch" \| "deny" \| "stop" | sí |  |  |
| `n` | integer |  | `1` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | no pending desktop action with this id |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/actions/<action_id>' \
  -H 'Content-Type: application/json' \
  -d '{"decision": "approve"}'
```

### `POST /api/desktop/estimate`

What a task would send and cost at most, shown before it starts.

Función: `spike/server/desktop_api.py` → `desktop_estimate`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `provider_id` | string \| null |  |  |  |
| `max_steps` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/estimate' \
  -H 'Content-Type: application/json' \
  -d '{"provider_id": "string"}'
```

### `POST /api/desktop/run`

Función: `spike/server/desktop_api.py` → `desktop_run`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `goal` | string | sí |  |  |
| `provider_id` | string \| null |  |  |  |
| `conversation_id` | string \| null |  |  |  |
| `keep_screenshots` | boolean |  | `false` |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | describe what the task is |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | conversation not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/run' \
  -H 'Content-Type: application/json' \
  -d '{"goal": "string"}'
```

### `GET /api/desktop/shots/{task_id}/{n}`

A screenshot of the running task, for its cards. It is the user's screen: only this computer, never cached.

Función: `spike/server/desktop_api.py` → `desktop_shot`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `task_id` | path | string | sí |  |
| `n` | path | integer | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | screenshot not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/desktop/shots/<task_id>/<n>'
```

### `POST /api/desktop/stop`

Stop the running task now (the button that is always on screen while one runs).

Función: `spike/server/desktop_api.py` → `desktop_stop`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/desktop/stop'
```
