# Referencia de la API: `/api/memory`, `/api/memory-export`, `/api/memory-folders`, `/api/memory-graph`, `/api/memory-import`, `/api/memory-status`

Idioma: [English](../en/memory.md) | **Español** · [Índice de la API](README.md)

### `GET /api/memory`

Función: `spike/server/app.py` → `list_memory`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `kind` | query | string \| null |  |  |
| `q` | query | string \| null |  |  |
| `limit` | query | integer |  | `200` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory'
```

### `POST /api/memory`

Función: `spike/server/app.py` → `add_memory`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `text` | string | sí |  |  |
| `kind` | string |  | `"fact"` |  |
| `scope` | string |  | `"global"` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string"}'
```

### `DELETE /api/memory`

Función: `spike/server/app.py` → `clear_memory`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory?scope=<scope>'
```

### `GET /api/memory-export`

Función: `spike/server/app.py` → `export_memory`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-export'
```

### `GET /api/memory-folders`

Función: `spike/server/memory_api.py` → `list_folders`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-folders'
```

### `POST /api/memory-folders`

Función: `spike/server/memory_api.py` → `add_folder`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `path` | string | sí |  |  |
| `scope` | string |  | `"global"` |  |
| `include` | string[] \| null |  |  |  |
| `exclude` | string[] \| null |  |  |  |
| `max_file_bytes` | integer \| null |  |  |  |
| `max_files` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-folders' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string"}'
```

### `GET /api/memory-folders/{folder_id}`

Función: `spike/server/memory_api.py` → `get_folder`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `folder_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | folder not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-folders/<folder_id>'
```

### `PATCH /api/memory-folders/{folder_id}`

Función: `spike/server/memory_api.py` → `patch_folder`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `folder_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `include` | string[] \| null |  |  |  |
| `exclude` | string[] \| null |  |  |  |
| `max_file_bytes` | integer \| null |  |  |  |
| `max_files` | integer \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | folder not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/memory-folders/<folder_id>' \
  -H 'Content-Type: application/json' \
  -d '{"include": ["string"]}'
```

### `DELETE /api/memory-folders/{folder_id}`

Función: `spike/server/memory_api.py` → `forget_folder`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `folder_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | folder not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory-folders/<folder_id>'
```

### `GET /api/memory-folders/{folder_id}/files`

Función: `spike/server/memory_api.py` → `folder_files`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `folder_id` | path | string | sí |  |
| `limit` | query | integer |  | `500` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `404` | folder not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-folders/<folder_id>/files'
```

### `POST /api/memory-folders/{folder_id}/reindex`

Función: `spike/server/memory_api.py` → `reindex_folder`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `folder_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

Cualquier valor JSON; la función lo lee por su cuenta.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | folder not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-folders/<folder_id>/reindex' \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'
```

### `GET /api/memory-graph`

Función: `spike/server/memory_api.py` → `memory_graph`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `node` | query | string \| null |  |  |
| `depth` | query | integer |  | `1` |
| `limit` | query | integer |  | `30` |
| `notes` | query | boolean |  | `true` |
| `proposed` | query | boolean |  | `false` |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph'
```

### `GET /api/memory-graph/entities`

Función: `spike/server/memory_api.py` → `graph_entities`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `q` | query | string \| null |  |  |
| `kind` | query | string \| null |  |  |
| `limit` | query | integer |  | `50` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph/entities'
```

### `POST /api/memory-graph/propose`

Ask the local model for relations between the entities of one note; the answers are proposals.

Función: `spike/server/memory_api.py` → `propose_relations`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `memory_id` | string | sí |  |  |
| `provider_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | (mensaje construido al ejecutar) |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |
| `503` | (mensaje construido al ejecutar) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-graph/propose' \
  -H 'Content-Type: application/json' \
  -d '{"memory_id": "string"}'
```

### `GET /api/memory-graph/relations`

Función: `spike/server/memory_api.py` → `graph_relations`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `status` | query | string \| null |  |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph/relations'
```

### `POST /api/memory-graph/relations`

Función: `spike/server/memory_api.py` → `add_relation`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `scope` | string |  | `"global"` |  |
| `source` | string | sí |  |  |
| `label` | string | sí |  |  |
| `target` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-graph/relations' \
  -H 'Content-Type: application/json' \
  -d '{"source": "string", "label": "string", "target": "string"}'
```

### `PATCH /api/memory-graph/relations/{relation_id}`

Función: `spike/server/memory_api.py` → `patch_relation`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `relation_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `status` | "proposed" \| "confirmed" \| "rejected" | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | relation not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/memory-graph/relations/<relation_id>' \
  -H 'Content-Type: application/json' \
  -d '{"status": "proposed"}'
```

### `DELETE /api/memory-graph/relations/{relation_id}`

Función: `spike/server/memory_api.py` → `delete_relation`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `relation_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | relation not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory-graph/relations/<relation_id>'
```

### `GET /api/memory-graph/svg`

Función: `spike/server/memory_api.py` → `memory_graph_svg`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `node` | query | string \| null |  |  |
| `depth` | query | integer |  | `1` |
| `limit` | query | integer |  | `30` |
| `notes` | query | boolean |  | `true` |
| `proposed` | query | boolean |  | `false` |
| `lang` | query | string |  | `"en"` |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-graph/svg'
```

### `POST /api/memory-import`

Función: `spike/server/app.py` → `import_memory`

**Cuerpo**: un objeto JSON que la función lee por su cuenta; sus campos no están en el esquema.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | invalid Content-Length header; invalid memory file: {…}; unknown memory scope '{…}' |
| `413` | the upload is limited to {…} MB |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/memory-import' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### `GET /api/memory-status`

Función: `spike/server/app.py` → `memory_status`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/memory-status'
```

### `PUT /api/memory/{mid}`

Función: `spike/server/app.py` → `update_memory`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `mid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `text` | string \| null |  |  |  |
| `kind` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | memory not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/memory/<mid>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "string"}'
```

### `DELETE /api/memory/{mid}`

Función: `spike/server/app.py` → `delete_memory`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `mid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | memory not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/memory/<mid>'
```
