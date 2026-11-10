# Referencia de la API: `/api/project-branches`, `/api/projects`

Idioma: [English](../en/projects.md) | **Español** · [Índice de la API](README.md)

### `GET /api/project-branches`

Función: `spike/server/workspace_api.py` → `branches`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/project-branches'
```

### `GET /api/projects`

Función: `spike/server/app.py` → `projects`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/projects'
```

### `POST /api/projects`

Función: `spike/server/app.py` → `create_project`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `name` | string | sí |  |  |
| `instructions` | string |  | `""` |  |
| `mode` | string |  | `"auto"` |  |
| `design` | string |  | `""` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown design system '{…}'; unknown mode '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `POST /api/projects/import`

Función: `spike/server/app.py` → `import_project_zip`

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header |
| `413` | the upload is limited to {…} MB |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `GET /api/projects/{pid}`

Función: `spike/server/app.py` → `get_project`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>'
```

### `PATCH /api/projects/{pid}`

Función: `spike/server/app.py` → `patch_project`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `name` | string \| null |  |  |  |
| `instructions` | string \| null |  |  |  |
| `mode` | string \| null |  |  |  |
| `design` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown design system '{…}'; unknown mode '{…}' |
| `404` | project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/projects/<pid>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `DELETE /api/projects/{pid}`

Función: `spike/server/app.py` → `delete_project`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | project not found |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/projects/<pid>'
```

### `GET /api/projects/{pid}/compare`

Función: `spike/server/workspace_api.py` → `compare`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/compare'
```

### `GET /api/projects/{pid}/export`

Función: `spike/server/app.py` → `export_project_zip`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/export'
```

### `GET /api/projects/{pid}/files`

Función: `spike/server/app.py` → `project_files`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/files'
```

### `GET /api/projects/{pid}/files/{path}`

Función: `spike/server/app.py` → `get_project_file`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |
| `path` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | file not found; project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/projects/<pid>/files/<path>'
```

### `PUT /api/projects/{pid}/files/{path}`

Función: `spike/server/app.py` → `put_project_file`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |
| `path` | path | string | sí |  |

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header |
| `404` | project not found |
| `413` | the upload is limited to {…} MB |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/projects/<pid>/files/<path>' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `DELETE /api/projects/{pid}/files/{path}`

Función: `spike/server/app.py` → `delete_project_file`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |
| `path` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | file not found; project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/projects/<pid>/files/<path>'
```

### `POST /api/projects/{pid}/fork`

Función: `spike/server/workspace_api.py` → `fork`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `name` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects/<pid>/fork' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `POST /api/projects/{pid}/merge`

Función: `spike/server/workspace_api.py` → `merge`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `token` | string | sí |  |  |
| `approved` | true | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/projects/<pid>/merge' \
  -H 'Content-Type: application/json' \
  -d '{"token": "string", "approved": true}'
```
