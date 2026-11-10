# Referencia de la API: `/api/specialist-documents`, `/api/specialists`

Idioma: [English](../en/specialists.md) | **Español** · [Índice de la API](README.md)

### `POST /api/specialist-documents`

Función: `spike/server/workspace_api.py` → `document`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `specialist` | string | sí |  |  |
| `filename` | string | sí |  |  |
| `text` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); unknown specialist |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/specialist-documents' \
  -H 'Content-Type: application/json' \
  -d '{"specialist": "string", "filename": "string", "text": "string"}'
```

### `GET /api/specialists`

Función: `spike/server/app.py` → `specialists`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/specialists'
```
