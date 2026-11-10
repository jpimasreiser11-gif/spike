# Referencia de la API: `/api/questions`

Idioma: [English](../en/questions.md) | **Español** · [Índice de la API](README.md)

### `POST /api/questions/{question_id}`

The user's answer to a question a specialist asked with `ask_user`; the paused run goes on with it.

Función: `spike/server/app.py` → `answer_question`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `question_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `answer` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | no pending question with this id |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/questions/<question_id>' \
  -H 'Content-Type: application/json' \
  -d '{"answer": "string"}'
```
