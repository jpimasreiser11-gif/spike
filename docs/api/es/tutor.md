# Referencia de la API: `/api/tutor`

Idioma: [English](../en/tutor.md) | **Español** · [Índice de la API](README.md)

### `GET /api/tutor`

Función: `spike/server/memory_api.py` → `list_topics`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `scope` | query | string \| null |  |  |
| `due` | query | boolean |  | `false` |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/tutor'
```

### `POST /api/tutor`

Función: `spike/server/memory_api.py` → `add_topic`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `name` | string | sí |  |  |
| `scope` | string |  | `"global"` |  |
| `notes` | string |  | `""` |  |
| `mastery` | integer |  | `0` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown memory scope '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/tutor' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `PATCH /api/tutor/{topic_id}`

Función: `spike/server/memory_api.py` → `patch_topic`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `topic_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `name` | string \| null |  |  |  |
| `notes` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | topic not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/tutor/<topic_id>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "string"}'
```

### `DELETE /api/tutor/{topic_id}`

Función: `spike/server/memory_api.py` → `delete_topic`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `topic_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | topic not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/tutor/<topic_id>'
```

### `POST /api/tutor/{topic_id}/review`

Función: `spike/server/memory_api.py` → `review_topic`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `topic_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `grade` | integer | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | topic not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/tutor/<topic_id>/review' \
  -H 'Content-Type: application/json' \
  -d '{"grade": 0}'
```
