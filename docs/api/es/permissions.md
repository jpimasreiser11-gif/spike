# Referencia de la API: `/api/permissions`

Idioma: [English](../en/permissions.md) | **Español** · [Índice de la API](README.md)

### `POST /api/permissions/{request_id}`

Función: `spike/server/app.py` → `decide`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `request_id` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `decision` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | no pending permission request with this id |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/permissions/<request_id>' \
  -H 'Content-Type: application/json' \
  -d '{"decision": "string"}'
```
