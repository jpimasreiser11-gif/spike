# Referencia de la API: `/api/design-systems`

Idioma: [English](../en/design.md) | **Español** · [Índice de la API](README.md)

### `GET /api/design-systems`

Función: `spike/server/app.py` → `design_systems`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/design-systems'
```

### `POST /api/design-systems/import`

Función: `spike/server/app.py` → `import_design`

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header |
| `413` | the upload is limited to {…} MB |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/design-systems/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `GET /api/design-systems/{ds_id}`

Función: `spike/server/app.py` → `design_system`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `ds_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | design system not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/design-systems/<ds_id>'
```

### `DELETE /api/design-systems/{ds_id}`

Función: `spike/server/app.py` → `delete_design`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `ds_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | design system not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/design-systems/<ds_id>'
```

### `GET /api/design-systems/{ds_id}/preview`

A sample page in the system's tokens, for the app's isolated preview (not served as a page).

Función: `spike/server/app.py` → `design_preview`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `ds_id` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | design system not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/design-systems/<ds_id>/preview'
```
