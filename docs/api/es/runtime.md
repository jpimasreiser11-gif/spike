# Referencia de la API: `/api/runtime`

Idioma: [English](../en/runtime.md) | **Español** · [Índice de la API](README.md)

### `GET /api/runtime`

Función: `spike/server/app.py` → `runtime_status`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/runtime'
```

### `POST /api/runtime/start`

Función: `spike/server/app.py` → `runtime_start`

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/runtime/start'
```

### `POST /api/runtime/stop`

Función: `spike/server/app.py` → `runtime_stop`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/runtime/stop'
```
