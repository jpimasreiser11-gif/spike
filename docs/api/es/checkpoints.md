# Referencia de la API: `/api/checkpoints`

Idioma: [English](../en/checkpoints.md) | **Español** · [Índice de la API](README.md)

### `POST /api/checkpoints/{cp_id}/undo`

Put back the files one tool call changed, and mark that step as undone in its chat.

Función: `spike/server/app.py` → `undo_step`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `cp_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `force` | boolean |  | `false` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/checkpoints/<cp_id>/undo' \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'
```
