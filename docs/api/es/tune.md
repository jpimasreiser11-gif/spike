# Referencia de la API: `/api/tune`

Idioma: [English](../en/tune.md) | **Español** · [Índice de la API](README.md)

### `GET /api/tune`

Función: `spike/server/app.py` → `tune_report`

**Respuesta**: `200` — object \| null

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/tune'
```

### `POST /api/tune`

Función: `spike/server/app.py` → `run_tune`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `quick` | boolean |  | `false` |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/tune' \
  -H 'Content-Type: application/json' \
  -d '{"quick": false}'
```
