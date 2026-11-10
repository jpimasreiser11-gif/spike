# Referencia de la API: `/api/creator`

Idioma: [English](../en/creator.md) | **Español** · [Índice de la API](README.md)

### `POST /api/creator/blueprint`

A template filled with the user's answers: a Forge blueprint to review, its skills and design flag.

Función: `spike/server/app.py` → `creator_blueprint`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `template` | string | sí |  |  |
| `fields` | object |  |  |  |
| `lang` | string |  | `"es"` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/blueprint' \
  -H 'Content-Type: application/json' \
  -d '{"template": "string"}'
```

### `POST /api/creator/data-app`

Función: `spike/server/data_app_api.py` → `create`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `file` | string | sí |  |  |
| `project_id` | string \| null |  |  |  |
| `lang` | string |  | `"es"` |  |
| `title` | string |  | `""` |  |
| `approved` | boolean |  | `false` |  |
| `labels` | object \| null |  |  |  |
| `labels.search` | string | sí |  |  |
| `labels.propose` | string | sí |  |  |
| `labels.hint` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | data_app_invalid |
| `403` | data_app_approval |
| `404` | data_app_project |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/data-app' \
  -H 'Content-Type: application/json' \
  -d '{"file": "string"}'
```

### `POST /api/creator/data-app/{sid}/approve`

Función: `spike/server/data_app_api.py` → `approve`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `sid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `token` | string | sí |  |  |
| `approved` | boolean |  | `false` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | data_app_invalid |
| `403` | data_app_approval |
| `409` | data_app_conflict; data_app_expired |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/data-app/<sid>/approve' \
  -H 'Content-Type: application/json' \
  -d '{"token": "string"}'
```

### `POST /api/creator/data-app/{sid}/preview`

Función: `spike/server/data_app_api.py` → `preview`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `sid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `edits` | object[] | sí |  |  |
| `edits[].row` | integer | sí |  |  |
| `edits[].column` | integer | sí |  |  |
| `edits[].value` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | data_app_invalid |
| `409` | data_app_conflict; data_app_expired |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/creator/data-app/<sid>/preview' \
  -H 'Content-Type: application/json' \
  -d '{"edits": [{"row": 0, "column": 0, "value": "string"}]}'
```

### `GET /api/creator/data-files`

Función: `spike/server/app.py` → `creator_data_files`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `project_id` | query | string \| null |  |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `404` | project not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/creator/data-files'
```

### `GET /api/creator/templates`

Función: `spike/server/app.py` → `creator_templates`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `lang` | query | string |  | `"es"` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/creator/templates'
```
