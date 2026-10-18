---
name: data-license-audit
description: Examina procedencia, licencias, condiciones de entrenamiento, privacidad y restricciones de cada dataset, modelo o fuente externa antes de su posible incorporación a Spike.
---

# Data license audit — Spike

## Cuándo aplicar

Antes de descargar, transformar, entrenar, evaluar, redistribuir o publicar datos, pesos, código o recursos externos.

## Comprobaciones

1. Identifica editor original, URL oficial, revisión fija/hash, licencia exacta y ámbito (dataset, código, pesos y derivados pueden tener condiciones diferentes).
2. Lee la licencia y términos específicos para entrenamiento, evaluación, copia, publicación, redistribución, atribución y uso comercial. Registra restricciones de acceso y obligaciones de notificación.
3. Bloquea contenido `NC`; comprueba compatibilidad de `share-alike`, condiciones de uso de terceros y licencias conflictivas. Una etiqueta Apache/MIT de un repositorio no certifica cada artefacto alojado en él.
4. No uses salidas de ChatGPT, Claude o Gemini como corpus de entrenamiento cuando sus términos lo prohíban. No asumas permiso por disponibilidad pública.
5. Excluye conjuntos de armas, CBRN, síntesis peligrosa, malware o exploits operativos y material de menores, conforme a `AGENTS.md`. Comprueba datos personales, consentimiento, eliminación y minimización.
6. Registra para cada fuente: `tipo | URL | revisión | licencia y texto | uso permitido | PII/seguridad | atribución | compatibilidad | decisión | revisor/fecha` en `DATA_LICENSES.md`.

## Criterio

**APTO** solo con derechos y restricciones verificados para el uso exacto; **PENDIENTE** cuando falte licencia, permiso, revisión o prueba de cumplimiento; **RECHAZADO** ante una prohibición aplicable. No descarga ni integra datos antes de APTO y autorización de fase.

## Límite

Trabajo documental de preparación hasta disponer del Plan Maestro íntegro y los permisos de fase pertinentes.
