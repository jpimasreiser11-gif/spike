# Referencia de la API: `/api/evolution`

Idioma: [English](../en/evolution.md) | **Español** · [Índice de la API](README.md)

### `GET /api/evolution`

Función: `spike/server/app.py` → `evolution`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution'
```

### `GET /api/evolution/candidates.jsonl`

Función: `spike/server/app.py` → `export_candidates`

**Respuesta**: `200`

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/candidates.jsonl'
```

### `POST /api/evolution/check`

Función: `spike/server/app.py` → `evolution_check`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `replay` | boolean |  | `false` |  |
| `prompts` | boolean |  | `false` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/check' \
  -H 'Content-Type: application/json' \
  -d '{"replay": false}'
```

### `POST /api/evolution/examples/build`

Función: `spike/server/app.py` → `build_examples`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `409` | (mensaje construido al ejecutar) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/examples/build'
```

### `GET /api/evolution/items`

Función: `spike/server/app.py` → `evolution_items`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `kind` | query | string \| null |  |  |
| `status` | query | string \| null |  |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/items'
```

### `PATCH /api/evolution/items/{iid}`

Función: `spike/server/app.py` → `patch_evolution_item`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `iid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `status` | "proposed" \| "accepted" \| "approved" \| "rejected" \| "new" \| "ignored" \| null |  |  |  |
| `question` | string \| null |  |  |  |
| `checks` | object \| null |  |  |  |
| `cause` | string \| null |  |  |  |
| `fix` | string \| null |  |  |  |
| `verified` | boolean \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); a {…} cannot be changed this way |
| `404` | item not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/evolution/items/<iid>' \
  -H 'Content-Type: application/json' \
  -d '{"status": "proposed"}'
```

### `DELETE /api/evolution/items/{iid}`

Función: `spike/server/app.py` → `delete_evolution_item`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `iid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | item not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/evolution/items/<iid>'
```

### `GET /api/evolution/items/{iid}/issue`

Función: `spike/server/app.py` → `failure_issue`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `iid` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `404` | failure not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/items/<iid>/issue'
```

### `GET /api/evolution/personal`

Función: `spike/server/evolution_api.py` → `personal`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/personal'
```

### `PUT /api/evolution/personal/exclusions`

Función: `spike/server/evolution_api.py` → `exclude`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `ref` | string | sí |  |  |
| `excluded` | boolean |  | `true` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | that example is not in the personal set |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/evolution/personal/exclusions' \
  -H 'Content-Type: application/json' \
  -d '{"ref": "string"}'
```

### `POST /api/evolution/personal/marks`

Función: `spike/server/evolution_api.py` → `mark_chat`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `conversation` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | (mensaje construido al ejecutar) |
| `409` | turn on the personal adapter in Settings → Evolución first |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/personal/marks' \
  -H 'Content-Type: application/json' \
  -d '{"conversation": "string"}'
```

### `DELETE /api/evolution/personal/marks/{conversation}`

Función: `spike/server/evolution_api.py` → `unmark_chat`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `conversation` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | that chat is not marked |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/evolution/personal/marks/<conversation>'
```

### `GET /api/evolution/prompts`

Función: `spike/server/app.py` → `learned_prompts`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/prompts'
```

### `POST /api/evolution/prompts/{specialist}/activate`

Compare the candidate with the version in use on the user's eval questions and use it only if it passes. One model job at a time, like the optimiser, so the computer stays usable.

Función: `spike/server/evolution_api.py` → `activate_prompt`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `specialist` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `version` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | (mensaje construido al ejecutar) |
| `409` | an optimisation is already running; job cancelled |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/prompts/<specialist>/activate' \
  -H 'Content-Type: application/json' \
  -d '{"version": 0}'
```

### `POST /api/evolution/prompts/{specialist}/candidate`

Función: `spike/server/evolution_api.py` → `propose_prompt`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `specialist` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `instructions` | string[] |  |  |  |
| `skills` | object |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/prompts/<specialist>/candidate' \
  -H 'Content-Type: application/json' \
  -d '{"instructions": ["string"]}'
```

### `POST /api/evolution/prompts/{specialist}/optimize`

Evolution level 2 with its progress as server-sent events; one at a time, so the computer stays usable.

Función: `spike/server/app.py` → `optimize_prompt`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `specialist` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `instructions` | string[] |  |  |  |
| `max_calls` | integer \| null |  |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `404` | unknown specialist '{…}' |
| `409` | an optimisation is already running |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/prompts/<specialist>/optimize' \
  -H 'Content-Type: application/json' \
  -d '{"instructions": ["string"]}'
```

### `POST /api/evolution/rollback`

Función: `spike/server/app.py` → `evolution_rollback`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `component` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | (mensaje construido al ejecutar) |
| `409` | the previous adapter file is gone |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/rollback' \
  -H 'Content-Type: application/json' \
  -d '{"component": "string"}'
```

### `POST /api/evolution/router/learn`

Función: `spike/server/app.py` → `learn_router`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/router/learn'
```

### `GET /api/evolution/strategy`

Función: `spike/server/evolution_api.py` → `strategy_table`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/strategy'
```

### `DELETE /api/evolution/strategy`

Función: `spike/server/evolution_api.py` → `reset_strategy`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/evolution/strategy'
```

### `POST /api/evolution/strategy/learn`

Función: `spike/server/evolution_api.py` → `learn_strategy`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/evolution/strategy/learn'
```

### `GET /api/evolution/{name}.jsonl`

Approved correction examples: `training` (chats for SFT) or `preferences` (pairs for DPO).

Función: `spike/server/app.py` → `export_examples`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `name` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `404` | not found |
| `409` | turn on “Use my corrections to retrain” in Settings → Evolution first |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/evolution/<name>.jsonl'
```
