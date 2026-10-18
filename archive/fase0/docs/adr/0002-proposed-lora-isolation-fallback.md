# ADR 0002 (PROPUESTA) — Aislamiento de adaptadores LoRA

**Estado:** Proposed / pendiente de confirmación de Joan. **Fecha:** 2026-10-16.

## Contexto

El Plan Maestro v3 elige una instancia `llama-server` con una base 4B compartida, `--lora-init-without-apply` y LoRAs por petición, para respetar los objetivos de RAM. La interfaz existe en el servidor instalado, pero [llama.cpp #26207](https://github.com/ggml-org/llama.cpp/issues/26207) y [#30366](https://github.com/ggml-org/llama.cpp/issues/30366) describen fallos o sospechas de reutilización del estado de caché entre LoRAs. La issue #30366 atribuye un caso a cambios en la configuración global incluso con `--cache-ram 0`; es un informe upstream sin reproducción de Spike. No hay adaptadores locales verificados con los que probar el problema.

## Decisión propuesta, todavía NO aplicada

1. **Principal condicional**: seguir con una sola base y LoRA por petición únicamente después de comprobar para un commit fijo las secuencias A/B/A, baseline/A/baseline y escenarios de concurrencia; no utilizar API global mutable para cambiar adaptadores mientras haya peticiones activas.
2. **Plan B, sujeto a medición**: servir cada adaptador con un proceso aislado, uno activo a la vez en el equipo de 16 GB, reiniciando proceso/contexto al cambiar de especialidad. Mantener la API de orquestación desacoplada para no alterar el contrato de los clientes.
3. Medir RSS combinado, latencia de arranque/swap, TTFT, tokens/s y comportamiento de caché. Si la alternativa empeora los límites obligatorios de RAM o primer token, mantener gate FAIL y volver a Joan con opciones medidas.

## Justificación y consecuencias

La separación por procesos elimina el intercambio involuntario de estado de *ese servidor* entre cambios de adaptador, pero no constituye sandbox de seguridad frente a procesos maliciosos ni garantiza que el adapter GGUF sea compatible. El cambio puede hacer inviable latencia al alternar roles. Solo se adoptará tras pruebas reales y aprobación de Joan porque modifica una decisión vinculante del plan.

## Evidencias y criterios

- Comprobado localmente: `llama-server 9430 (d48a56eff)` reconoce `--lora-init-without-apply`, `--cache-ram`, `--no-cache-prompt`.
- Sin verificar: LoRAs Qwen3.5 entrenados; exportación/recarga GGUF; contaminación real; RAM/TTFT CPU 16 GB.
- Aceptación: 30 alternancias A/B/A y baseline/A/baseline con semillas, modelos y contextos idénticos, repetición en proceso nuevo y trazas JSON enlazadas a commit. Cualquier contaminación reproducible bloquea multi-LoRA por petición.

**Solicitud de decisión futura:** confirmar Plan B solo cuando existan medidas y el fallo del Plan A esté demostrado. Este ADR no cambia la arquitectura actual.
