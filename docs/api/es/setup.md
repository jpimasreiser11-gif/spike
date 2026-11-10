# Referencia de la API: `/api/setup`

Idioma: [English](../en/setup.md) | **Español** · [Índice de la API](README.md)

### `GET /api/setup`

Función: `spike/server/setup_api.py` → `status`

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/setup'
```

### `POST /api/setup/download`

Función: `spike/server/setup_api.py` → `download`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `specialists` | string[] |  |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | Adapter unavailable |
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |
| `409` | Installation busy or insufficient resources |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/setup/download' \
  -H 'Content-Type: application/json' \
  -d '{"specialists": ["string"]}'
```

### `POST /api/setup/import`

Función: `spike/server/setup_api.py` → `import_local_model`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `path` | string | sí |  |  |
| `sha256` | string \| null |  |  |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | message |
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |
| `409` | Installation busy |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/setup/import' \
  -H 'Content-Type: application/json' \
  -d '{"path": "string"}'
```

### `POST /api/setup/quit`

Función: `spike/server/setup_api.py` → `quit_app`

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `403` | Local same-origin JSON request required |
| `404` | Launcher only |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/setup/quit'
```
