# Referencia de la API: `/api/minds`

Idioma: [English](../en/minds.md) | **Español** · [Índice de la API](README.md)

### `POST /api/minds/estimate`

What Parallel Minds would cost for this message, shown before the user sends it. Calls no model.

Función: `spike/server/app.py` → `minds_estimate`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `n` | integer \| null |  |  |  |
| `picks` | object[] \| null |  |  |  |
| `picks[].mode` | string \| null |  |  |  |
| `picks[].provider_id` | string \| null |  |  |  |
| `message` | string |  | `""` |  |
| `mode` | string |  | `"auto"` |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |
| `conversation_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); Parallel Minds needs a prose answer: it cannot be combined with a Forge blueprint or an answer contract (JSON); unknown mode '{…}'; unknown provider '{…}' |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/minds/estimate' \
  -H 'Content-Type: application/json' \
  -d '{"n": 0}'
```
