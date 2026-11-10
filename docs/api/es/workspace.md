# Referencia de la API: `/api/workspace`

Idioma: [English](../en/workspace.md) | **Español** · [Índice de la API](README.md)

### `GET /api/workspace/files/{path}`

Files the tools wrote outside a project (documents, pages), offered as downloads.

Función: `spike/server/app.py` → `get_workspace_file`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `path` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | the path is outside the workspace |
| `404` | file not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/workspace/files/<path>'
```
