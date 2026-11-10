# Referencia de la API: `/api/skills`

Idioma: [English](../en/skills.md) | **Español** · [Índice de la API](README.md)

### `GET /api/skills`

Función: `spike/server/app.py` → `skills`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/skills'
```

### `POST /api/skills/import`

Función: `spike/server/app.py` → `import_skills`

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header |
| `413` | the upload is limited to {…} MB |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/skills/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```

### `GET /api/skills/{name}`

Función: `spike/server/app.py` → `get_skill`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `name` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | skill not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/skills/<name>'
```

### `PUT /api/skills/{name}`

Función: `spike/server/app.py` → `toggle_skill`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `name` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `enabled` | boolean | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | skill not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/skills/<name>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

### `DELETE /api/skills/{name}`

Función: `spike/server/app.py` → `delete_skill`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `name` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | built-in skills can be disabled, not deleted |
| `404` | skill not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/skills/<name>'
```
