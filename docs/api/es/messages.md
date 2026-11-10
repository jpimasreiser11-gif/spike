# Referencia de la API: `/api/messages`

Idioma: [English](../en/messages.md) | **Español** · [Índice de la API](README.md)

### `POST /api/messages/{mid}/escalate`

The user clicked "ask <provider>" on a low-confidence answer: the one place a second opinion is sent. The message is the question; the provider's guard still applies (paid calls, monthly limits, files withheld).

Función: `spike/server/app.py` → `escalate`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `mid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `provider_id` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `403` | (mensaje construido al ejecutar) |
| `404` | (mensaje construido al ejecutar) |
| `409` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |
| `502` | (mensaje construido al ejecutar) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/messages/<mid>/escalate' \
  -H 'Content-Type: application/json' \
  -d '{"provider_id": "string"}'
```

### `POST /api/messages/{mid}/learn`

Save, reword or dismiss the rule proposed from a correction, or undo what a message saved to memory.

Función: `spike/server/app.py` → `learn`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `mid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `action` | "save" \| "dismiss" \| "undo" | sí |  |  |
| `text` | string \| null |  |  |  |
| `memory` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/messages/<mid>/learn' \
  -H 'Content-Type: application/json' \
  -d '{"action": "save"}'
```

### `POST /api/messages/{mid}/route`

The user retries this question with another specialist: a route correction the router learns from.

Función: `spike/server/app.py` → `route_correction`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `mid` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `specialist` | string | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/messages/<mid>/route' \
  -H 'Content-Type: application/json' \
  -d '{"specialist": "string"}'
```
