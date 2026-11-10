# Referencia de la API: `/api/finance`

Idioma: [English](../en/finance.md) | **Español** · [Índice de la API](README.md)

### `GET /api/finance`

Función: `spike/server/app.py` → `finance_info`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/finance'
```

### `POST /api/finance/live/check`

Función: `spike/server/app.py` → `finance_live_check`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/live/check'
```

### `PUT /api/finance/live/key`

Función: `spike/server/app.py` → `finance_live_key`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `exchange` | string | sí |  |  |
| `api_key` | string | sí |  |  |
| `secret` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/finance/live/key' \
  -H 'Content-Type: application/json' \
  -d '{"exchange": "string", "api_key": "string", "secret": "string"}'
```

### `DELETE /api/finance/live/key/{exchange}`

Función: `spike/server/app.py` → `finance_live_key_delete`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `exchange` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/finance/live/key/<exchange>'
```

### `GET /api/finance/live/orders`

Función: `spike/server/app.py` → `finance_live_orders`

**Respuesta**: `200` — object[]

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/finance/live/orders'
```

### `GET /api/finance/live/orders/{oid}`

Función: `spike/server/app.py` → `finance_live_order`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `oid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/finance/live/orders/<oid>'
```

### `POST /api/finance/live/orders/{oid}/cancel`

Función: `spike/server/app.py` → `finance_live_cancel`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `oid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/live/orders/<oid>/cancel'
```

### `POST /api/finance/live/orders/{oid}/confirm`

The user's click on a proposed real order: the only way one reaches the exchange.

Función: `spike/server/app.py` → `finance_live_confirm`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `oid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `id` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | a confirmation must name the order in the body and the X-Spike-Confirm header |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/live/orders/<oid>/confirm' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string"}'
```

### `GET /api/finance/paper`

Función: `spike/server/app.py` → `finance_paper`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/finance/paper'
```

### `POST /api/finance/paper/orders/{oid}/cancel`

Función: `spike/server/app.py` → `finance_paper_cancel`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `oid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `404` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/paper/orders/<oid>/cancel'
```

### `POST /api/finance/paper/reset`

Función: `spike/server/app.py` → `finance_paper_reset`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `cash` | number |  | `10000` |  |
| `quote` | string |  | `"USDT"` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/paper/reset' \
  -H 'Content-Type: application/json' \
  -d '{"cash": 10000}'
```
