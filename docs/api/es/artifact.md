# Referencia de la API: `/api/artifact-versions`

Idioma: [English](../en/artifact.md) | **Español** · [Índice de la API](README.md)

### `POST /api/artifact-versions`

Función: `spike/server/workspace_api.py` → `version`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `title` | string | sí |  |  |
| `content` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/artifact-versions' \
  -H 'Content-Type: application/json' \
  -d '{"title": "string", "content": "string"}'
```

### `GET /api/artifact-versions/{aid}/comments`

Función: `spike/server/workspace_api.py` → `comments`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `aid` | path | string | sí |  |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/artifact-versions/<aid>/comments'
```

### `POST /api/artifact-versions/{aid}/comments`

Función: `spike/server/workspace_api.py` → `comment`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `aid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `line` | integer | sí |  |  |
| `text` | string | sí |  |  |
| `parent` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/artifact-versions/<aid>/comments' \
  -H 'Content-Type: application/json' \
  -d '{"line": 0, "text": "string"}'
```
