# ADR 0003 (PROPUESTA) — Selección de base y alternativas

**Estado:** Proposed / sin cambio adoptado. **Fecha:** 2026-10-16.

## Situación

Base planificada: [`Qwen/Qwen3.5-4B`](https://huggingface.co/Qwen/Qwen3.5-4B), Apache-2.0; draft propuesto: [`Qwen/Qwen3.5-0.8B`](https://huggingface.co/Qwen/Qwen3.5-0.8B), Apache-2.0. En su configuración el lenguaje es híbrido Gated DeltaNet/atención completa. La arquitectura introduce riesgos de conversión de LoRA y de memoria/estado de caché. Ninguno de los dos modelos ha sido ejecutado ni evaluado por Spike.

| Candidato | Licencia publicada | Ventaja esperada / límite sin ensayar | Estado |
| --- | --- | --- | --- |
| Qwen3.5-4B | Apache-2.0 | Fiel a la decisión original; requiere probar GGUF, LoRA y RAM | Principal **pendiente de gate** |
| Qwen3.5-0.8B | Apache-2.0 | Draft especulativo opcional; puede perjudicar tokens/s y RAM CPU | Opcional **pendiente de prueba** |
| [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) | Apache-2.0 | Arquitectura anterior; opción ante incompatibilidad híbrida, con evals comparables | **Plan B propuesto** |
| [Gemma 4 E4B](https://ai.google.dev/gemma/docs/core/model_card_4) | Apache-2.0 (Gemma 4) | Nombre E4B no equivale automáticamente a pesos de 4B ni a consumo ≤6 GB; multimodal | **Alternativa no validada** |

## Elección condicional propuesta

1. Continuar investigando Qwen3.5-4B y evitar declarar un ganador por metadatos o tamaño de descarga.
2. Ensayar la versión concreta Q4 del modelo base en un equipo CPU sin GPU dedicada de 16 GB, con contexto fijado, TTFT, RAM pico y formatos de tool calling. Luego comparar con 0.8B opcional, costes de estado y aceptación especulativa.
3. Si falla LoRA/conversión/aislamiento/rendimiento: diseñar ensayo idéntico de Qwen3-4B como Plan B, con autorización de cambio registrada. No trasladar adaptadores entre bases sin entrenamiento y validación propia.
4. No aprobar Gemma 4 E4B sin medir la cuantización exacta, licencia derivada, distribución y modelo+adaptadores dentro de 6 GB. La numeración E4B representa parámetros efectivos según su fabricante, no un presupuesto de RAM certificado.

## Gate y autorización

Queda **pendiente** `PLAN.md` íntegro y ensayo real. Toda sustitución de modelo base o activación del draft exige datos medidos y aprobación expresa de Joan. No hay cambio técnico aplicado.
