# Referencia de la API: `/api/pack`

Idioma: [English](../en/pack.md) | **Español** · [Índice de la API](README.md)

### `GET /api/pack/export`

Función: `spike/server/app.py` → `pack_export`

**Respuesta**: `200`

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/pack/export'
```

### `POST /api/pack/import`

Función: `spike/server/app.py` → `pack_import`

**Cuerpo**: los bytes del archivo (`application/octet-stream`), leídos por la función.

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar); invalid Content-Length header; invalid specialist in pack: {…} |
| `413` | the upload is limited to {…} MB |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/pack/import' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @path/to/file
```
