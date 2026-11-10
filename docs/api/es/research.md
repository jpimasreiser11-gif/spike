# Referencia de la API: `/api/research`

Idioma: [English](../en/research.md) | **Español** · [Índice de la API](README.md)

### `POST /api/research/analyze`

Función: `spike/server/research_api.py` → `analyze`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `preview_id` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | unknown_provider |
| `403` | (mensaje construido al ejecutar) |
| `404` | unknown_project |
| `409` | changed_preview; expired_preview |
| `422` | invalid_analysis; la petición no cumple el esquema (validación de FastAPI) |
| `502` | analysis_failed |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/research/analyze' \
  -H 'Content-Type: application/json' \
  -d '{"preview_id": "string"}'
```

### `GET /api/research/notebooks/{conversation_id}`

Función: `spike/server/research_api.py` → `export_notebook`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `conversation_id` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_conversation |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/research/notebooks/<conversation_id>'
```

### `POST /api/research/preview`

Función: `spike/server/research_api.py` → `preview`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `kind` | "paper" \| "contradictions" | sí |  |  |
| `paths` | string[] | sí |  |  |
| `project_id` | string \| null |  |  |  |
| `provider_id` | string \| null |  |  |  |
| `language` | "es" \| "en" |  | `"es"` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid_sources; unknown_provider |
| `404` | unknown_project |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/research/preview' \
  -H 'Content-Type: application/json' \
  -d '{"kind": "paper", "paths": ["string"]}'
```
