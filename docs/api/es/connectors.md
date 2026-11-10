# Referencia de la API: `/api/connectors`, `/api/connectors-audit`

Idioma: [English](../en/connectors.md) | **Español** · [Índice de la API](README.md)

### `GET /api/connectors`

Función: `spike/server/app.py` → `connectors`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/connectors'
```

### `POST /api/connectors`

Función: `spike/server/app.py` → `add_connector`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `id` | string | sí |  |  |
| `name` | string | sí |  |  |
| `transport` | string |  | `"stdio"` |  |
| `command` | string |  | `""` |  |
| `args` | string[] |  |  |  |
| `url` | string |  | `""` |  |
| `description` | string |  | `""` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | connector not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string", "name": "string"}'
```

### `GET /api/connectors-audit`

Función: `spike/server/app.py` → `connectors_audit`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `limit` | query | integer |  | `100` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/connectors-audit'
```

### `PUT /api/connectors/{cid}`

Función: `spike/server/app.py` → `update_connector`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `enabled` | boolean \| null |  |  |  |
| `policy` | string \| null |  |  |  |
| `secrets` | object \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | connector not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/connectors/<cid>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

### `DELETE /api/connectors/{cid}`

Función: `spike/server/app.py` → `delete_connector`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | connector not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/connectors/<cid>'
```

### `GET /api/connectors/{cid}/view`

Función: `spike/server/app.py` → `connector_view_page`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |
| `uri` | query | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | connector not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/connectors/<cid>/view?uri=<uri>'
```

### `POST /api/connectors/{cid}/view/call`

{"result": CallToolResult}, or {"needs_approval": true} when the tool asks and the user has not allowed it.

Función: `spike/server/app.py` → `connector_view_call`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `view` | string | sí |  |  |
| `name` | string | sí |  |  |
| `arguments` | object |  |  |  |
| `approved` | boolean |  | `false` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | (mensaje construido al ejecutar) |
| `404` | connector not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors/<cid>/view/call' \
  -H 'Content-Type: application/json' \
  -d '{"view": "string", "name": "string"}'
```

### `POST /api/connectors/{cid}/view/event`

What a view did in the app (opened a link, wrote a message, gave context): kept in the audit log.

Función: `spike/server/app.py` → `connector_view_event`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `view` | string | sí |  |  |
| `event` | "open-link" \| "message" \| "model-context" \| "log" \| "display-mode" \| "refused" | sí |  |  |
| `detail` | string |  | `""` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | connector not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors/<cid>/view/event' \
  -H 'Content-Type: application/json' \
  -d '{"view": "string", "event": "open-link"}'
```

### `POST /api/connectors/{cid}/view/read`

Función: `spike/server/app.py` → `connector_view_read`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `view` | string | sí |  |  |
| `uri` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | connector not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/connectors/<cid>/view/read' \
  -H 'Content-Type: application/json' \
  -d '{"view": "string", "uri": "string"}'
```
