# API reference: `/api/sandbox`

Language: [Español](../es/sandbox.md) | **English** · [API index](README.md)

### `GET /api/sandbox`

The `sandbox` setting and whether this computer has a sandbox for code-running tools (and why not).

Handler: `spike/server/app.py` → `sandbox`

**Response**: `200` — object

**Example**

```bash
curl -s 'http://127.0.0.1:8740/api/sandbox'
```
