# Referencia de la API: `/api/sandbox`

Idioma: [English](../en/sandbox.md) | **Español** · [Índice de la API](README.md)

### `GET /api/sandbox`

The `sandbox` setting and whether this computer has a sandbox for code-running tools (and why not).

Función: `spike/server/app.py` → `sandbox`

**Respuesta**: `200` — object

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/sandbox'
```
