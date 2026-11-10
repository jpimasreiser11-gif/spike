# Referencia de la API: `/api/providers`

Idioma: [English](../en/providers.md) | **Español** · [Índice de la API](README.md)

### `GET /api/providers`

Función: `spike/server/app.py` → `providers`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/providers'
```

### `POST /api/providers`

Función: `spike/server/app.py` → `add_provider`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `id` | string \| null |  |  |  |
| `preset` | string \| null |  |  |  |
| `kind` | string \| null |  |  |  |
| `name` | string \| null |  |  |  |
| `base_url` | string \| null |  |  |  |
| `model` | string \| null |  |  |  |
| `api_key` | string \| null |  |  |  |
| `paid` | boolean \| null |  |  |  |
| `allow_paid` | boolean \| null |  |  |  |
| `share_files` | boolean \| null |  |  |  |
| `limits` | object \| null |  |  |  |
| `limits.monthly_tokens` | integer \| null |  |  |  |
| `limits.monthly_cost` | number \| null |  |  |  |
| `limits.price_in` | number \| null |  |  |  |
| `limits.price_out` | number \| null |  |  |  |
| `capabilities` | object \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | base_url must be an http(s) URL; id or preset is required; kind must be one of {…} |
| `409` | provider '{…}' already exists |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/providers' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string"}'
```

### `PATCH /api/providers/{pid}`

Función: `spike/server/app.py` → `patch_provider`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `id` | string \| null |  |  |  |
| `preset` | string \| null |  |  |  |
| `kind` | string \| null |  |  |  |
| `name` | string \| null |  |  |  |
| `base_url` | string \| null |  |  |  |
| `model` | string \| null |  |  |  |
| `api_key` | string \| null |  |  |  |
| `paid` | boolean \| null |  |  |  |
| `allow_paid` | boolean \| null |  |  |  |
| `share_files` | boolean \| null |  |  |  |
| `limits` | object \| null |  |  |  |
| `limits.monthly_tokens` | integer \| null |  |  |  |
| `limits.monthly_cost` | number \| null |  |  |  |
| `limits.price_in` | number \| null |  |  |  |
| `limits.price_out` | number \| null |  |  |  |
| `capabilities` | object \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | base_url must be an http(s) URL |
| `404` | provider not found |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PATCH 'http://127.0.0.1:8740/api/providers/<pid>' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string"}'
```

### `DELETE /api/providers/{pid}`

Función: `spike/server/app.py` → `delete_provider`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | the built-in local provider cannot be removed |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/providers/<pid>'
```

### `POST /api/providers/{pid}/test`

Checks connectivity with the model list endpoint, which no supported provider bills for.

Función: `spike/server/app.py` → `test_provider`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `pid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/providers/<pid>/test'
```
