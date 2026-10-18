---
name: honest-claims
description: Audita toda afirmación de capacidades, velocidad, precisión, coste o mejora sobre Spike antes de incluirla en documentación, demos o comunicación pública.
---

# Honest claims — Spike

## Cuándo aplicar

Antes de formular cualquier afirmación verificable sobre un especialista, modelo, evaluación, benchmark, arquitectura en ejecución o preparación para producción.

## Protocolo

1. Separa **objetivo**, **hipótesis**, **resultado observado** y **resultado validado**. Una configuración YAML, un nombre de especialista o una prueba de humo no constituye un modelo entrenado.
2. Para cifras de rendimiento, exige salida reproducible de `make eval` o `make bench`, guardada bajo `reports/` con fecha, revisión Git, hardware, artefacto de modelo y condiciones de medición. Si falta alguno, etiqueta **SIN VERIFICAR** y omite la cifra pública.
3. Compara siempre contra la versión cuantizada pertinente. No proyectes resultados de una máquina de desarrollo de 36 GB al equipo objetivo de 16 GB sin GPU dedicada.
4. Identifica tamaño muestral, conjunto de evaluación, métricas, variación y límites. No inventes intervalos de confianza, significación ni umbrales ausentes del Plan Maestro completo.
5. Si un gate falla, informa **FAIL**, conserva las pruebas y documenta el bloqueo y el Plan B en `docs/spikes/`. No maquilles resultados negativos.
6. Revisa atribuciones de terceros y afirmaciones de derechos de uso antes de publicar.

## Salida requerida

Un inventario breve `afirmación | tipo | evidencia fechada | límites | decisión (VERIFICADA/PENDIENTE/RECHAZADA)` con rutas locales o enlaces exactos. Sin evidencia suficiente, la publicación queda bloqueada.

## Límite de fase

Durante preparación/Fase 0 solo se audita y redacta. No autoriza empezar Fase 1, entrenar, descargar pesos o distribuir un especialista. `PLAN.md` íntegro sigue pendiente.
