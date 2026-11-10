# API reference: `/api/analytics`

Language: [Español](../es/analytics.md) | **English** · [API index](README.md)

### `POST /api/analytics/report`

An analysis from the chat as a Word or PDF file (the app renders the charts as PNG).

Handler: `spike/server/app.py` → `analytics_report`

**Body**: a JSON object the handler reads itself; its fields are not in the schema.

**Response**: `200`

**Errors**

| Code | Message |
|---|---|
| `400` | invalid Content-Length header; invalid report |
| `413` | the upload is limited to {…} MB |
| `501` | error: |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/analytics/report' \
  -H 'Content-Type: application/json' \
  -d '{}'
```
