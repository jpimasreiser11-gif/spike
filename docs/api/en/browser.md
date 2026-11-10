# API reference: `/api/browser`

Language: [Español](../es/browser.md) | **English** · [API index](README.md)

### `GET /api/browser`

Handler: `spike/server/app.py` → `browser_settings`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/browser'
```

### `PUT /api/browser`

What the browser does on a domain without a rule: ask first, or open it.

Handler: `spike/server/app.py` → `put_browser`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `unknown` | "ask" \| "allow" | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/browser' \
  -H 'Content-Type: application/json' \
  -d '{"unknown": "ask"}'
```

### `PUT /api/browser/domains/{domain}`

Allow or block a domain for the browser connector, or remove its rule.

Handler: `spike/server/app.py` → `browser_domain`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `domain` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule` | "allow" \| "deny" \| null | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/browser/domains/<domain>' \
  -H 'Content-Type: application/json' \
  -d '{"rule": "allow"}'
```

### `GET /api/browser/recorder`

Whether View runs, the recording in progress, the replay, and the saved scripts: one poll for the panel.

Handler: `spike/server/view_api.py` → `recorder_status`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/browser/recorder'
```

### `POST /api/browser/recorder/cancel`

Handler: `spike/server/view_api.py` → `recorder_cancel`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/recorder/cancel'
```

### `POST /api/browser/recorder/start`

Handler: `spike/server/view_api.py` → `recorder_start`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string |  | `""` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | (message built at run time); Spike View is not running: turn it on in Settings first |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/recorder/start' \
  -H 'Content-Type: application/json' \
  -d '{"name": ""}'
```

### `POST /api/browser/recorder/stop`

End the recording and keep the script (None when nothing was recorded).

Handler: `spike/server/view_api.py` → `recorder_stop`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | (message built at run time) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/recorder/stop'
```

### `POST /api/browser/replay`

Handler: `spike/server/view_api.py` → `replay_start`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `script` | string | yes |  |  |
| `mode` | "auto" \| "step" |  | `"auto"` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/replay' \
  -H 'Content-Type: application/json' \
  -d '{"script": "string"}'
```

### `POST /api/browser/replay/answer`

Handler: `spike/server/view_api.py` → `replay_answer`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `question` | string | yes |  |  |
| `decision` | string | yes |  |  |
| `value` | string \| null |  |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | the replay is not waiting for that answer |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/replay/answer' \
  -H 'Content-Type: application/json' \
  -d '{"question": "string", "decision": "string"}'
```

### `POST /api/browser/replay/stop`

Handler: `spike/server/view_api.py` → `replay_stop`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/replay/stop'
```

### `GET /api/browser/scripts/{sid}`

The script as the JSON file kept on this computer.

Handler: `spike/server/view_api.py` → `script_get`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `sid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/browser/scripts/<sid>'
```

### `DELETE /api/browser/scripts/{sid}`

Handler: `spike/server/view_api.py` → `script_delete`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `sid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `404` | there is no such script |
| `409` | this script is being replayed: stop the replay first |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/browser/scripts/<sid>'
```

### `POST /api/browser/scripts/{sid}/secret/{n}`

Make a typing step ask for its text when replayed, and drop the text kept in the file.

Handler: `spike/server/view_api.py` → `script_secret`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `sid` | path | string | yes |  |
| `n` | path | integer | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/browser/scripts/<sid>/secret/<n>'
```
