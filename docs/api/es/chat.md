# Referencia de la API: `/api/chat`

Idioma: [English](../en/chat.md) | **Español** · [Índice de la API](README.md)

### `POST /api/chat`

Función: `spike/server/app.py` → `chat`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `comment_threads` | string[] |  |  |  |
| `message` | string | sí |  |  |
| `conversation_id` | string \| null |  |  |  |
| `mode` | string |  | `"auto"` |  |
| `provider_id` | string \| null |  |  |  |
| `project_id` | string \| null |  |  |  |
| `replace_from` | string \| null |  |  |  |
| `temporary` | boolean |  | `false` |  |
| `response_schema` | object \| null |  |  |  |
| `forge` | object \| null |  |  |  |
| `design_system` | string \| null |  |  |  |
| `view_context` | object[] \| null |  |  |  |
| `skills` | string[] \| null |  |  |  |
| `images` | string[] |  |  |  |
| `parallel_minds` | object \| null |  |  |  |
| `parallel_minds.n` | integer \| null |  |  |  |
| `parallel_minds.picks` | object[] \| null |  |  |  |
| `parallel_minds.picks[].mode` | string \| null |  |  |  |
| `parallel_minds.picks[].provider_id` | string \| null |  |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); Parallel Minds needs a prose answer: it cannot be combined with a Forge blueprint or an answer contract (JSON); a Forge task cannot also have an answer contract; blueprint: {…}; images_private; images_single; replace_from must be a user message of this conversation; replace_from needs an existing conversation; this blueprint saves files, which needs tools: turn them on in Settings; unknown design system '{…}'; unknown mode '{…}'; unknown project '{…}'; unknown provider '{…}'; unknown skill '{…}'; vision_required |
| `403` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/chat' \
  -H 'Content-Type: application/json' \
  -d '{"message": "string"}'
```
