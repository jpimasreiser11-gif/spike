---
name: eval-gate
description: Define, comprueba y documenta los gates de evaluación y benchmarks de Spike sin inventar métricas, tamaños muestrales ni condiciones de aprobación.
---

# Eval gate — Spike

## Cuándo aplicar

Al planificar, ejecutar o revisar una evaluación, benchmark o gate de una fase y de cualquier `Spike <especialidad>`.

## Procedimiento

1. Identifica objetivo, revisión Git, licencia y hash del modelo, cuantización, variante de referencia, prompts/datasets con procedencia y criterios de aceptación **textualmente aprobados**.
2. Mantén evaluación y entrenamiento separados; revisa contaminación, filtrado y pertenencia a los conjuntos vetados antes de cualquier uso de datos.
3. Cuando esté autorizado, evalúa mediante `make eval` y mide mediante `make bench`; preserva las salidas sin editar en `reports/` con hardware, fecha, commit, semilla, versión, RAM pico y configuración relevante.
4. Contrasta el especialista entrenado (LoRA/merge cuando proceda) y su versión cuantizada final con la referencia cuantizada comparable. Una especialidad declarada no equivale a una mejora probada.
5. Verifica el equipo objetivo de 16 GB RAM sin GPU dedicada; los resultados de 36 GB solo indican comportamiento del equipo de desarrollo.
6. Emite **PASS** solo si cada criterio documentado se satisface y la evidencia es reproducible; ante falta o fallo, **PENDING/FAIL** con incidencia en `docs/spikes/` y alternativa verificable.

## Formato de resultado

`gate | criterio exacto y origen | comando | informe | estado | impedimento | siguiente comprobación`.

## Límite

No establece objetivos numéricos no presentes en la fuente disponible ni ejecuta fases, modelos o servicios por iniciativa propia. A falta del `PLAN.md` completo, todo gate dependiente de sus secciones desconocidas queda **PENDING**.
