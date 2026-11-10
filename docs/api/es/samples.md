# Referencia de la API: `/api/samples`

Idioma: [English](../en/samples.md) | **Español** · [Índice de la API](README.md)

### `GET /api/samples`

Función: `spike/server/samples_api.py` → `samples`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `lang` | query | string |  | `"en"` |

**Respuesta**: `200` — object[]

**Errores**

| Código | Mensaje |
|---|---|
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s 'http://127.0.0.1:8740/api/samples'
```

### `POST /api/samples/{sample_id}/import`

Función: `spike/server/samples_api.py` → `import_sample`

**Parámetros**

| Nombre | En | Tipo | Obligatorio | Por defecto |
|---|---|---|---|---|
| `sample_id` | path | string | sí |  |
| `lang` | query | string |  | `"en"` |

**Respuesta**: `200` — object

**Errores**

| Código | Mensaje |
|---|---|
| `400` | (mensaje construido al ejecutar) |
| `404` | unknown_sample |
| `422` | la petición no cumple el esquema (validación de FastAPI) |

**Ejemplo**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/samples/<sample_id>/import'
```
