# Referencia de la API: `/api/device-lab`

Idioma: [English](../en/device.md) | **Español** · [Índice de la API](README.md)

### `GET /api/device-lab`

What can be chosen. Runs nothing: adb is only looked for on the PATH.

Función: `spike/server/device_lab_api.py` → `status`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/device-lab'
```

### `GET /api/device-lab/android`

What `adb devices` lists (it starts adb's own background server, as adb always does). No screenshot.

Función: `spike/server/device_lab_api.py` → `android`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/device-lab/android'
```

### `POST /api/device-lab/android`

Open the URL on a connected Android device and screenshot it; nothing else runs.

Función: `spike/server/device_lab_api.py` → `android_shot`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `serial` | string |  | `""` |  |
| `open_url` | boolean |  | `true` |  |
| `approved` | boolean |  | `false` |  |
| `url` | string | sí |  |  |
| `allow_hosts` | string[] |  |  |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | device_lab_android_approval; request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | device_lab_busy |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/device-lab/android' \
  -H 'Content-Type: application/json' \
  -d '{"url": "string"}'
```

### `POST /api/device-lab/run`

Función: `spike/server/device_lab_api.py` → `run`

**Cuerpo** (`application/json`)

| Campo | Tipo | Obligatorio | Por defecto | Descripción |
|---|---|---|---|---|
| `url` | string | sí |  |  |
| `profiles` | string[] \| null |  |  |  |
| `custom` | object[] \| null |  |  |  |
| `allow_hosts` | string[] |  |  |  |
| `approved` | boolean |  | `false` |  |
| `android` | object \| null |  |  |  |
| `android.serial` | string |  | `""` |  |
| `android.open_url` | boolean |  | `true` |  |
| `android.approved` | boolean |  | `false` |  |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `403` | device_lab_android_approval; device_lab_approval; request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | device_lab_busy |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/device-lab/run' \
  -H 'Content-Type: application/json' \
  -d '{"url": "string"}'
```
