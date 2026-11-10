# Referencia de la API: `/api/analytics`

Idioma: [English](../en/analytics.md) | **Español** · [Índice de la API](README.md)

### `POST /api/analytics/report`

An analysis from the chat as a Word or PDF file (the app renders the charts as PNG).

Función: `spike/server/app.py` → `analytics_report`

**Cuerpo**: un objeto JSON que la función lee por su cuenta; sus campos no están en el esquema.

**Respuesta**: `200`

**Errores**

| Código | Mensaje |
|---|---|
| `400` | invalid Content-Length header; invalid report |
| `413` | the upload is limited to {…} MB |
| `501` | error: |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/analytics/report' \
  -H 'Content-Type: application/json' \
  -d '{}'
```
