# Referencia de la API: `/api/jobs`

Idioma: [English](../en/jobs.md) | **Español** · [Índice de la API](README.md)

### `GET /api/jobs`

Función: `spike/server/workspace_api.py` → `jobs`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/jobs'
```

### `POST /api/jobs/{jid}/cancel`

Función: `spike/server/workspace_api.py` → `cancel`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `jid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | job not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/jobs/<jid>/cancel'
```
