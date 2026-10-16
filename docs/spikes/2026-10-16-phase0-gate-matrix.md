# Fase 0 — matriz de gates preliminar

**Fecha:** 2026-10-16. **Carácter:** preparatorio, no sustituye los criterios específicos S1–S7 que faltan en `PLAN.md`.

| Elemento del plan conocido | Evidencia exigible para PASS | Estado actual |
| --- | --- | --- |
| S1, elección de base Qwen3.5-4B | Modelo y revisión fijos, licencia comprobada, GGUF disponible, generación real con formato de tools y thinking/non-thinking, memoria medida en 16 GB CPU | OPEN: licencia y familia confirmadas, resto pendiente |
| S2–S4, herramientas/inferencia/entrenamiento | Probar scripts exactos de la versión íntegra del plan y guardar logs, commits/hashes, tiempos y picos de memoria; distinguir Mac 36 GB de CPU 16 GB | OPEN: recuperar descripción exacta S2–S4 |
| S5 | Descripción y criterios íntegros desde PLAN.md | BLOCKED: sección ausente |
| S6, nombre y marca | Nombre y formato por decisión expresa; realizar comprobación de marca y riesgos de distribución | OPEN: nombre Spike aprobado, marca pendiente |
| S7 | Descripción y criterios íntegros desde PLAN.md | BLOCKED: sección ausente |
| Auditoría de modelos | Licencia exacta de cada artefacto, hash/revisión y derecho de redistribución | IN PROGRESS |
| LoRA por petición | Prueba con dos adaptadores reales, selección A/B/A, cachés habilitadas/deshabilitadas, ausencia de mezcla de contexto y concurrencia | NOT RUN |
| Draft 0.8B | Verificar compatibilidad de tokenizer/arquitectura, aceptación y tokens/s comparados con base sola en CPU | NOT RUN |
| Entrenamiento MLX-LM | LoRA en arquitectura híbrida real, conversión GGUF, salida reproducible con hash y prueba sobre cuantización final | NOT RUN |
| Hardware objetivo | RSS/working set total del servidor+UI+modelo ≤10 GB; modelos+adaptadores ≤6 GB; primer token <5 s, usando 16 GB sin GPU | NOT RUN |
| Skills/MCP externos | Pinned commit, inspección de licencia, SKILL.md, scripts y efecto de instalación | IN PROGRESS |
| Coste del flujo | Registro de infraestructura y artefactos sin servicios de pago | OPEN |

## Riesgo conocido del aislamiento entre LoRAs

`llama.cpp` documenta `--lora-init-without-apply`, el campo LoRA por petición y `--cache-ram`, pero existen reportes públicos recientes de contaminación por reutilización de KV entre adaptadores (véase [issue #26207](https://github.com/ggml-org/llama.cpp/issues/26207) y [issue #30129](https://github.com/ggml-org/llama.cpp/issues/30129)). Antes de habilitar múltiples especialistas deben comprobarse estos casos sobre un commit determinado de llama.cpp. Una mitigación candidata es desactivar temporalmente la caché RAM, pero su efecto sobre latencia y calidad debe medirse en el equipo objetivo. **No se declara resuelto el problema.**

## Protocolo previsto de evidencias futuras

1. Registrar hash del modelo base, GGUF y cada adaptador, commit de Spike y versión de llama.cpp.
2. Ejecutar el mismo conjunto congelado con base cuantizada y cada especialista cuantizado, con seeds, temperatura, decodificación y hardware iguales.
3. Para gates de mejora, bootstrap pareado con IC del 95 %; para regresión, MMLU o equivalente con techo de dos puntos.
4. Reservar 300+ prompts etiquetados para routing: medir precisión con especialistas añadidos sin reentrenar; JSON válido en ejecución, no solo en tests sintácticos.
5. Evaluar rechazos sensibles legítimos (<3 %) por separado de solicitudes peligrosas, que deben seguir bloqueadas según la política.
6. Registrar resultados en `reports/` por fecha y commit con `make eval` y `make bench` cuando ambos se hayan implementado.

Estas son **especificaciones de pruebas**, no resultados experimentales. La Fase 0 continúa en FAIL/OPEN hasta incorporar el plan y ejecutar las verificaciones.
