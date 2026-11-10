# Referencia de la API: `/api/history`

Idioma: [English](../en/history.md) | **Español** · [Índice de la API](README.md)

### `POST /api/history/search`

Función: `spike/server/history_api.py` → `search`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `query` | string | sí |  |  |
| `scope` | "all" \| "workspace" \| "project" |  | `"all"` |  |
| `project_id` | string \| null |  |  |  |
| `match` | "words" \| "phrase" |  | `"words"` |  |
| `role` | "all" \| "user" \| "assistant" |  | `"all"` |  |
| `after` | number |  | `0` |  |
| `limit` | integer |  | `20` |  |
| `offset` | integer |  | `0` |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); history_filter |
| `404` | project_not_found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/history/search' \
  -H 'Content-Type: application/json' \
  -d '{"query": "string"}'
```
