# Referencia de la API: `/api/browser`

Idioma: [English](../en/browser.md) | **Español** · [Índice de la API](README.md)

### `GET /api/browser`

Función: `spike/server/app.py` → `browser_settings`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/browser'
```

### `PUT /api/browser`

What the browser does on a domain without a rule: ask first, or open it.

Función: `spike/server/app.py` → `put_browser`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `unknown` | "ask" \| "allow" | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/browser' \
  -H 'Content-Type: application/json' \
  -d '{"unknown": "ask"}'
```

### `PUT /api/browser/domains/{domain}`

Allow or block a domain for the browser connector, or remove its rule.

Función: `spike/server/app.py` → `browser_domain`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `domain` | path | string | sí |  |

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `rule` | "allow" \| "deny" \| null | sí |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/browser/domains/<domain>' \
  -H 'Content-Type: application/json' \
  -d '{"rule": "allow"}'
```

### `GET /api/browser/recorder`

Whether View runs, the recording in progress, the replay, and the saved scripts: one poll for the panel.

Función: `spike/server/view_api.py` → `recorder_status`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/browser/recorder'
```

### `POST /api/browser/recorder/cancel`

Función: `spike/server/view_api.py` → `recorder_cancel`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/recorder/cancel'
```

### `POST /api/browser/recorder/start`

Función: `spike/server/view_api.py` → `recorder_start`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `name` | string |  | `""` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | (mensaje construido al ejecutar); Spike View is not running: turn it on in Settings first |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/recorder/start' \
  -H 'Content-Type: application/json' \
  -d '{"name": ""}'
```

### `POST /api/browser/recorder/stop`

End the recording and keep the script (None when nothing was recorded).

Función: `spike/server/view_api.py` → `recorder_stop`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | (mensaje construido al ejecutar) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/recorder/stop'
```

### `POST /api/browser/replay`

Función: `spike/server/view_api.py` → `replay_start`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `script` | string | sí |  |  |
| `mode` | "auto" \| "step" |  | `"auto"` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/replay' \
  -H 'Content-Type: application/json' \
  -d '{"script": "string"}'
```

### `POST /api/browser/replay/answer`

Función: `spike/server/view_api.py` → `replay_answer`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `question` | string | sí |  |  |
| `decision` | string | sí |  |  |
| `value` | string \| null |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | the replay is not waiting for that answer |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/replay/answer' \
  -H 'Content-Type: application/json' \
  -d '{"question": "string", "decision": "string"}'
```

### `POST /api/browser/replay/stop`

Función: `spike/server/view_api.py` → `replay_stop`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/replay/stop'
```

### `GET /api/browser/scripts/{sid}`

The script as the JSON file kept on this computer.

Función: `spike/server/view_api.py` → `script_get`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `sid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/browser/scripts/<sid>'
```

### `DELETE /api/browser/scripts/{sid}`

Función: `spike/server/view_api.py` → `script_delete`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `sid` | path | string | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | there is no such script |
| `409` | this script is being replayed: stop the replay first |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/browser/scripts/<sid>'
```

### `POST /api/browser/scripts/{sid}/secret/{n}`

Make a typing step ask for its text when replayed, and drop the text kept in the file.

Función: `spike/server/view_api.py` → `script_secret`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `sid` | path | string | sí |  |
| `n` | path | integer | sí |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/scripts/<sid>/secret/<n>'
```
