# Referencia de la API: `/api/backup`

Idioma: [English](../en/backup.md) | **Español** · [Índice de la API](README.md)

### `GET /api/backup/export`

Función: `spike/server/backup_api.py` → `export`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `include_models` | query | boolean |  | `false` |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `415` | unsupported content type |
| `422` | la petición no cumple el esquema (validación de FastAPI) |
| `500` | (mensaje construido al ejecutar) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/backup/export'
```

### `POST /api/backup/preview`

Función: `spike/server/backup_api.py` → `preview`

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header |
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `413` | the backup is too large |
| `415` | unsupported content type |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/backup/preview' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `POST /api/backup/restore`

Adds what is missing; replaces existing files only with `overwrite=1` (the UI asks first).

Función: `spike/server/backup_api.py` → `restore`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `overwrite` | query | boolean |  | `false` |

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header |
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `413` | the backup is too large |
| `415` | unsupported content type |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/backup/restore' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```
