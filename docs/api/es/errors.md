# Referencia de la API: `/api/errors`

Idioma: [English](../en/errors.md) | **Español** · [Índice de la API](README.md)

### `GET /api/errors`

Función: `spike/server/errors_api.py` → `errors`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `limit` | query | integer |  | `200` |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/errors'
```

### `DELETE /api/errors`

Función: `spike/server/errors_api.py` → `clear`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/errors'
```

### `GET /api/errors/report`

The text for "copy as issue": the browser copies it; nothing leaves this computer from here.

Función: `spike/server/errors_api.py` → `report`

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/errors/report'
```
