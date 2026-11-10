# Referencia de la API: `/api/lab`

Idioma: [English](../en/lab.md) | **Español** · [Índice de la API](README.md)

### `POST /api/lab/execute`

Función: `spike/server/lab_api.py` → `execute`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `quote_id` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | invalid_cases; invalid_target; one_probe_target |
| `403` | provider_blocked |
| `409` | changed_quote; expired_quote |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/lab/execute' \
  -H 'Content-Type: application/json' \
  -d '{"quote_id": "string"}'
```

### `POST /api/lab/preview`

Función: `spike/server/lab_api.py` → `preview`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `kind` | "compare" \| "probe" |  | `"compare"` |  |
| `prompt` | string |  | `""` |  |
| `cases` | object[] |  |  |  |
| `cases[].prompt` | string | sí |  |  |
| `cases[].expected` | string \| null |  |  |  |
| `targets` | object[] | sí |  |  |
| `targets[].specialist` | string |  | `"core"` |  |
| `targets[].provider_id` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | invalid_cases; invalid_target; one_probe_target |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/lab/preview' \
  -H 'Content-Type: application/json' \
  -d '{"targets": [{}]}'
```

### `GET /api/lab/runs`

Función: `spike/server/lab_api.py` → `runs`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/lab/runs'
```

### `GET /api/lab/runs/{run_id}/export`

Función: `spike/server/lab_api.py` → `export`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `run_id` | path | string | sí |  |

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `404` | unknown_run |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/lab/runs/<run_id>/export'
```
