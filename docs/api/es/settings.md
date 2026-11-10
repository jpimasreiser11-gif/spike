# Referencia de la API: `/api/settings`

Idioma: [English](../en/settings.md) | **Español** · [Índice de la API](README.md)

### `GET /api/settings`

Función: `spike/server/app.py` → `get_settings`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/settings'
```

### `PUT /api/settings`

Función: `spike/server/app.py` → `put_settings`

**Cuerpo** (`application/json`)

Cualquier valor JSON; la función lo lee por su cuenta.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/settings' \
  -H 'Content-Type: application/json' \
  -d '{}'
```
