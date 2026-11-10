# Referencia de la API: `/api/calls`

Idioma: [English](../en/calls.md) | **Español** · [Índice de la API](README.md)

### `GET /api/calls`

Función: `spike/server/app.py` → `calls`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `limit` | query | integer |  | `200` |
| `remote` | query | boolean |  | `false` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/calls'
```

### `DELETE /api/calls`

Función: `spike/server/app.py` → `clear_calls`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/calls'
```
