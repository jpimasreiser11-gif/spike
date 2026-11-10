# API reference: `/api/finance`

Language: [Español](../es/finance.md) | **English** · [API index](README.md)

### `GET /api/finance`

Handler: `spike/server/app.py` → `finance_info`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/finance'
```

### `POST /api/finance/live/check`

Handler: `spike/server/app.py` → `finance_live_check`

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/live/check'
```

### `PUT /api/finance/live/key`

Handler: `spike/server/app.py` → `finance_live_key`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `exchange` | string | yes |  |  |
| `api_key` | string | yes |  |  |
| `secret` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X PUT 'http://127.0.0.1:8740/api/finance/live/key' \
  -H 'Content-Type: application/json' \
  -d '{"exchange": "string", "api_key": "string", "secret": "string"}'
```

### `DELETE /api/finance/live/key/{exchange}`

Handler: `spike/server/app.py` → `finance_live_key_delete`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `exchange` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X DELETE 'http://127.0.0.1:8740/api/finance/live/key/<exchange>'
```

### `GET /api/finance/live/orders`

Handler: `spike/server/app.py` → `finance_live_orders`

**Response**: `200` — object[]

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/finance/live/orders'
```

### `GET /api/finance/live/orders/{oid}`

Handler: `spike/server/app.py` → `finance_live_order`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `oid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/finance/live/orders/<oid>'
```

### `POST /api/finance/live/orders/{oid}/cancel`

Handler: `spike/server/app.py` → `finance_live_cancel`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `oid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/live/orders/<oid>/cancel'
```

### `POST /api/finance/live/orders/{oid}/confirm`

The user's click on a proposed real order: the only way one reaches the exchange.

Handler: `spike/server/app.py` → `finance_live_confirm`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `oid` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | a confirmation must name the order in the body and the X-Spike-Confirm header |
| `403` | request refused: it comes from another web site; {…} can only be changed on the computer SPIKE runs on |
| `409` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/live/orders/<oid>/confirm' \
  -H 'Content-Type: application/json' \
  -d '{"id": "string"}'
```

### `GET /api/finance/paper`

Handler: `spike/server/app.py` → `finance_paper`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/finance/paper'
```

### `POST /api/finance/paper/orders/{oid}/cancel`

Handler: `spike/server/app.py` → `finance_paper_cancel`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `oid` | path | string | yes |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/paper/orders/<oid>/cancel'
```

### `POST /api/finance/paper/reset`

Handler: `spike/server/app.py` → `finance_paper_reset`

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `cash` | number |  | `10000` |  |
| `quote` | string |  | `"USDT"` |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `400` | (message built at run time) |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/finance/paper/reset' \
  -H 'Content-Type: application/json' \
  -d '{"cash": 10000}'
```
