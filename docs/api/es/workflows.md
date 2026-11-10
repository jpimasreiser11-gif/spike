# Referencia de la API: `/api/workflows`

Idioma: [English](../en/workflows.md) | **Español** · [Índice de la API](README.md)

### `GET /api/workflows`

Función: `spike/server/workflow_api.py` → `list_workflows`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows'
```

### `POST /api/workflows`

Save a new workflow (its first version). Nothing invalid is saved.

Función: `spike/server/workflow_api.py` → `create_workflow`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `workflow` | object | sí |  |  |
| `base_revision` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `GET /api/workflows/catalog`

What a workflow may name, and the limits it is checked against.

Función: `spike/server/workflow_api.py` → `catalog`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/catalog'
```

### `POST /api/workflows/import`

A workflow exported from here or another project, saved as a new workflow with a new id.

Función: `spike/server/workflow_api.py` → `import_workflow`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `workflow` | object | sí |  |  |
| `base_revision` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/import' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `POST /api/workflows/validate`

Función: `spike/server/workflow_api.py` → `validate_workflow`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `workflow` | object | sí |  |  |
| `base_revision` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/validate' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `GET /api/workflows/{wid}`

Función: `spike/server/workflow_api.py` → `get_workflow`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |
| `revision` | query | integer \| null |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>'
```

### `PUT /api/workflows/{wid}`

The next version of a workflow; 409 when `base_revision` is not the newest any more.

Función: `spike/server/workflow_api.py` → `save_workflow`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `workflow` | object | sí |  |  |
| `base_revision` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/workflows/<wid>' \
  -H 'Content-Type: application/json' \
  -d '{"workflow": {}}'
```

### `DELETE /api/workflows/{wid}`

Función: `spike/server/workflow_api.py` → `delete_workflow`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict; workflow_running |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/workflows/<wid>'
```

### `GET /api/workflows/{wid}/export`

Función: `spike/server/workflow_api.py` → `export_workflow`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |
| `revision` | query | integer \| null |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/export'
```

### `GET /api/workflows/{wid}/runs`

Función: `spike/server/workflow_api.py` → `list_runs`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/runs'
```

### `POST /api/workflows/{wid}/runs`

Check the workflow and its inputs again, then start the run in the background; follow it with /events.

Función: `spike/server/workflow_api.py` → `start_run`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `inputs` | object \| null |  |  |  |
| `revision` | integer \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); tools_disabled; unknown provider '{…}' |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | invalid_inputs; la petición no cumple el esquema (validación de FastAPI) |
| `429` | too_many_runs |
| `500` | run_not_stored |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/<wid>/runs' \
  -H 'Content-Type: application/json' \
  -d '{"inputs": {}}'
```

### `GET /api/workflows/{wid}/runs/{rid}`

Función: `spike/server/workflow_api.py` → `get_run`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `rid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/runs/<rid>'
```

### `GET /api/workflows/{wid}/runs/{rid}/events`

The run's events from `after` on, then live until it ends. Only runs of this session have events.

Función: `spike/server/workflow_api.py` → `run_events`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `rid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |
| `after` | query | integer |  | `0` |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `404` | run_not_found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/runs/<rid>/events'
```

### `POST /api/workflows/{wid}/runs/{rid}/stop`

Stop a run: the node that is working is cancelled (an unanswered permission question with it), the rest are not started, and the record is stored as `cancelled`.

Función: `spike/server/workflow_api.py` → `stop_run`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `rid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | run_not_running; unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/workflows/<wid>/runs/<rid>/stop'
```

### `GET /api/workflows/{wid}/versions`

Función: `spike/server/workflow_api.py` → `versions`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `wid` | path | string | sí |  |
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_project; workflow_not_found |
| `409` | workflow_conflict |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workflows/<wid>/versions'
```
