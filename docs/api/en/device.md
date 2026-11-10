# API reference: `/api/device-lab`

Language: [Español](../es/device.md) | **English** · [API index](README.md)

### `GET /api/device-lab`

What can be chosen. Runs nothing: adb is only looked for on the PATH.

Handler: `spike/server/device_lab_api.py` → `status`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/device-lab'
```

### `GET /api/device-lab/android`

What `adb devices` lists (it starts adb's own background server, as adb always does). No screenshot.

Handler: `spike/server/device_lab_api.py` → `android`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/device-lab/android'
```

### `POST /api/device-lab/android`

Open the URL on a connected Android device and screenshot it; nothing else runs.

Handler: `spike/server/device_lab_api.py` → `android_shot`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `serial` | string |  | `""` |  |
| `open_url` | boolean |  | `true` |  |
| `approved` | boolean |  | `false` |  |
| `url` | string | yes |  |  |
| `allow_hosts` | string[] |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | device_lab_android_approval; request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | device_lab_busy |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/device-lab/android' \
  -H 'Content-Type: application/json' \
  -d '{"url": "string"}'
```

### `POST /api/device-lab/run`

Handler: `spike/server/device_lab_api.py` → `run`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | yes |  |  |
| `profiles` | string[] \| null |  |  |  |
| `custom` | object[] \| null |  |  |  |
| `allow_hosts` | string[] |  |  |  |
| `approved` | boolean |  | `false` |  |
| `android` | object \| null |  |  |  |
| `android.serial` | string |  | `""` |  |
| `android.open_url` | boolean |  | `true` |  |
| `android.approved` | boolean |  | `false` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | device_lab_android_approval; device_lab_approval; request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | device_lab_busy |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/device-lab/run' \
  -H 'Content-Type: application/json' \
  -d '{"url": "string"}'
```
