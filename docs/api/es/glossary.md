# Referencia de la API: `/api/glossary`, `/api/glossary-export`, `/api/glossary-import`

Idioma: [English](../en/glossary.md) | **Español** · [Índice de la API](README.md)

### `GET /api/glossary`

Función: `spike/server/memory_api.py` → `list_glossary`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `q` | query | string \| null |  |  |
| `limit` | query | integer |  | `1000` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/glossary'
```

### `POST /api/glossary`

Función: `spike/server/memory_api.py` → `add_glossary`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `term` | string | sí |  |  |
| `translation` | string | sí |  |  |
| `lang` | string |  | `""` |  |
| `note` | string |  | `""` |  |
| `scope` | string |  | `"global"` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/glossary' \
  -H 'Content-Type: application/json' \
  -d '{"term": "string", "translation": "string"}'
```

### `GET /api/glossary-export`

Función: `spike/server/memory_api.py` → `export_glossary`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string |  | `"global"` |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/glossary-export'
```

### `POST /api/glossary-import`

Función: `spike/server/memory_api.py` → `import_glossary`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string |  | `"global"` |

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header; unknown memory scope '{…}' |
| `413` | the upload is limited to {…} MB |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/glossary-import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `PUT /api/glossary/{entry_id}`

Función: `spike/server/memory_api.py` → `update_glossary`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `entry_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `term` | string \| null |  |  |  |
| `translation` | string \| null |  |  |  |
| `lang` | string \| null |  |  |  |
| `note` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | entry not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/glossary/<entry_id>' \
  -H 'Content-Type: application/json' \
  -d '{"term": "string"}'
```

### `DELETE /api/glossary/{entry_id}`

Función: `spike/server/memory_api.py` → `delete_glossary`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `entry_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | entry not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/glossary/<entry_id>'
```
