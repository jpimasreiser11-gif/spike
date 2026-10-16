# Registro de licencias de datos y modelos

Estado inicial, 2026-10-16. Este registro **no autoriza entrenar**: cada artefacto concreto requiere verificación de licencia, versión, procedencia, atribución, PII, filtrado y posible contaminación de evaluaciones.

| Fuente | Categoría | Licencia declarada en fuente oficial | Uso actual | Pendiente |
| --- | --- | --- | --- | --- |
| [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | Modelo base candidato | Apache-2.0 | Investigación únicamente | Pin de revisión, comprobar licencia del artefacto distribuido y GGUF |
| [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | Modelo draft candidato | Apache-2.0 | Investigación únicamente | Compatibilidad speculative decoding y memoria en CPU |

Todos los datasets Tier 1 del plan están **pendientes de auditoría individual y habilitación**; no se han descargado ni utilizado. Queda vetado el uso de respuestas de ChatGPT, Gemini o Claude como datos de entrenamiento, así como contenido peligroso definido en `AGENTS.md`.
