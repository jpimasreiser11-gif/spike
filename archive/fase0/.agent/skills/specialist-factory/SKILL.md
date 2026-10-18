---
name: specialist-factory
description: Prepara las especificaciones reproducibles de los especialistas Spike, respetando la aprobación de fases, hardware de 16 GB, derechos de datos y evaluación posterior a la cuantización.
---

# Specialist factory — Spike

## Cuándo aplicar

Al diseñar la ficha o el proceso futuro para un `Spike <especialidad>` y revisar su preparación técnica.

## Ficha obligatoria

- Especialidad y propósito autorizado; límites y casos fuera de ámbito.
- Base y draft candidatos: URL, versión y licencia; comprobar compatibilidad antes de combinarlos.
- Fuentes de datos con veredicto documentado en `DATA_LICENSES.md`.
- Entrenamiento real previsto y su trazabilidad: configuración LoRA, semilla, coste proyectado, hardware, hashes de artefactos.
- Cuantización final y comparación contra la versión cuantizada de referencia.
- Restricciones y mediciones sobre 16 GB de RAM sin GPU dedicada, operación offline y coste cero.
- Gates exactos, pruebas de regresión y evidencias de `make eval` / `make bench` en `reports/`.

## Procedimiento de preparación

1. Escribe diseño y dependencias, marcando qué puntos siguen sin poder verificarse por la ausencia de `PLAN.md` íntegro.
2. Revisa riesgos de licencia, contaminación de benchmarks y filtrado de datos antes de proponer ejecuciones.
3. No llames "modelo disponible" a una ficha, un prompt, una ruta de orquestación, un adaptador vacío ni un artefacto inexistente.
4. Reserva entrenamiento, descargas, ejecución o implementación para la fase aprobada. Documenta bloqueos y alternativas sin consumir servicios de pago.
5. Para distribución futura exige pesos reales, LoRA y cuantización documentadas, benchmark reproducible y gate aprobatorio.

## Salida

Especificación revisable con `READY FOR REVIEW / BLOCKED`, referencias locales y lista de verificaciones pendientes. Ninguna ficha por sí misma concede aprobación de Fase 1.
