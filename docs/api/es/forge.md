# Referencia de la API: `/api/forge`

Idioma: [English](../en/forge.md) | **Español** · [Índice de la API](README.md)

### `POST /api/forge/blueprint`

Draft a Forge blueprint for the user to review and approve; nothing runs yet.

Función: `spike/server/app.py` → `forge_blueprint`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `task` | string | sí |  |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown project '{…}'; unknown provider '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/blueprint' \
  -H 'Content-Type: application/json' \
  -d '{"task": "string"}'
```

### `GET /api/forge/prototypes`

The saved prototype runs of the project's folder (or the workspace), newest first: those `built` wait for the user's pick. `git` says whether this computer has git, which the feature needs.

Función: `spike/server/app.py` → `prototype_runs`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown project '{…}'; unknown provider '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/forge/prototypes'
```

### `POST /api/forge/prototypes`

Build the two approved blueprints on two git branches and compare them by running the same tests on both. Streams events tagged `proto: a|b`, then `proto_compare`; merging is a separate request the user makes.

Función: `spike/server/app.py` → `prototype_start`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `task` | string | sí |  |  |
| `blueprints` | object[] | sí |  |  |
| `tests` | object \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | Parallel Prototypes saves files, which needs tools: turn them on in Settings; each approach must save at least one file (a step with 'deliverables'); prototypes: {…}; unknown project '{…}'; unknown provider '{…}' |
| `403` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes' \
  -H 'Content-Type: application/json' \
  -d '{"task": "string", "blueprints": [{}]}'
```

### `POST /api/forge/prototypes/blueprints`

Draft two blueprints, one per approach, for the user to review and approve; nothing runs yet.

Función: `spike/server/app.py` → `prototype_blueprints`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `task` | string | sí |  |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown project '{…}'; unknown provider '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes/blueprints' \
  -H 'Content-Type: application/json' \
  -d '{"task": "string"}'
```

### `GET /api/forge/prototypes/{run_id}`

Función: `spike/server/app.py` → `prototype_run`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `run_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/forge/prototypes/<run_id>'
```

### `POST /api/forge/prototypes/{run_id}/discard`

Drop a run: the checkouts and the two branches SPIKE made. The user's own branches are never touched.

Función: `spike/server/app.py` → `prototype_discard`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `run_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `409` | this run is still building |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes/<run_id>/discard'
```

### `POST /api/forge/prototypes/{run_id}/merge`

Merge the approach the user chose into the branch the folder was on. Needs `approve: true`; a conflict, a folder that moved to another branch or has uncommitted changes to tracked files stops it, changing nothing.

Función: `spike/server/app.py` → `prototype_merge`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `run_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `choice` | "a" \| "b" | sí |  |  |
| `approve` | boolean |  | `false` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/forge/prototypes/<run_id>/merge' \
  -H 'Content-Type: application/json' \
  -d '{"choice": "a"}'
```
