# Referencia de la API: `/api/privacy`

Idioma: [English](../en/privacy.md) | **Español** · [Índice de la API](README.md)

### `POST /api/privacy/delete`

Función: `spike/server/backup_api.py` → `delete_all`

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | the confirmation word does not match; ask for a new one |
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `409` | refused: this is not SPIKE's own data folder |
| `415` | unsupported content type |
| `422` | send a JSON object with the confirmation word |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/privacy/delete' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `GET /api/privacy/delete-word`

The word the user must type to confirm deleting everything; single use, valid for 10 minutes.

Función: `spike/server/backup_api.py` → `delete_word`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `lang` | query | string |  | `"en"` |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; your data can only be exported or deleted on the computer SPIKE runs on |
| `415` | unsupported content type |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/privacy/delete-word'
```
