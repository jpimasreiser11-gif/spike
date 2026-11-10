# Referencia de la API: `/api/conversations`

Idioma: [English](../en/conversations.md) | **Español** · [Índice de la API](README.md)

### `GET /api/conversations`

Función: `spike/server/app.py` → `conversations`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/conversations'
```

### `POST /api/conversations`

Función: `spike/server/app.py` → `new_conversation`

**Cuerpo** (`application/json`)

Cualquier valor JSON; la función lo lee por su cuenta.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/conversations' \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "string"}'
```

### `GET /api/conversations/{cid}`

Función: `spike/server/app.py` → `get_conversation`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | conversation not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/conversations/<cid>'
```

### `PATCH /api/conversations/{cid}`

Función: `spike/server/app.py` → `patch_conversation`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `title` | string \| null |  |  |  |
| `mode` | string \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | conversation not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/conversations/<cid>' \
  -H 'Content-Type: application/json' \
  -d '{"title": "string"}'
```

### `DELETE /api/conversations/{cid}`

Función: `spike/server/app.py` → `delete_conversation`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/conversations/<cid>'
```

### `POST /api/conversations/{cid}/branch`

A copy of the chat up to (not including) one of the user's messages, so an edit can go on in its own chat and the original stays as it was. Undo stays with the original chat's steps.

Función: `spike/server/app.py` → `branch_conversation`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `before` | string | sí |  |  |
| `title` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | 'before' must be a user message of this conversation |
| `404` | conversation not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/conversations/<cid>/branch' \
  -H 'Content-Type: application/json' \
  -d '{"before": "string"}'
```

### `GET /api/conversations/{cid}/proof`

The chat with every recorded step, its model calls and file checksums, as a verifiable zip.

Función: `spike/server/app.py` → `proof_package`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |
| `include` | query | string \| null |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | Unknown proof section / Sección de prueba desconocida |
| `404` | conversation not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/conversations/<cid>/proof'
```
