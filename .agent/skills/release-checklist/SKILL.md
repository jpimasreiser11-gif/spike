---
name: release-checklist
description: Verifica controles de licencias, evaluación, coste, seguridad, CI, aprobación y reproducibilidad antes de declarar un entregable de Spike listo para publicar.
---

# Release checklist — Spike

## Cuándo aplicar

Antes de crear una release, ofrecer una demo con afirmaciones de rendimiento, integrar un especialista o dar por cerrada una fase.

## Lista de revisión

- [ ] `PLAN.md` completo recibido; requisitos y gates aplicables identificados sin reconstrucciones.
- [ ] Fase autorizada explícitamente, con decisión/ADR cuando corresponda.
- [ ] Cambios limitados y revisados; pruebas del módulo y CI verde, con commits convencionales cuando se autoricen commits.
- [ ] Cada dependencia, skill y MCP externos tiene procedencia, pin, licencia y scripts auditados antes de activación.
- [ ] `DATA_LICENSES.md` registra modelos/datasets y atribuciones sin material vetado ni fuentes prohibidas.
- [ ] Evidencias originales de `make eval` y `make bench` fechadas y vinculadas a commit en `reports/`.
- [ ] LoRA real entrenado, modelo final cuantizado medido y ganancia respecto a referencia verificada para cada especialista anunciado.
- [ ] Se ha probado el equipo objetivo de 16 GB sin GPU dedicada, uso offline y coste cero, sin extrapolar resultados del Mac de desarrollo.
- [ ] Se han revisado seguridad, privacidad, clean-room y comprobaciones de funcionamiento y regresión.
- [ ] Límites y fallos conocidos publicados; gates fallidos tienen informe en `docs/spikes/` y Plan B.

## Dictamen

Deja una tabla `control | evidencia | PASS/FAIL/PENDING` y detén la publicación ante cualquier bloqueo obligatorio. Esta skill es una lista de revisión: no concede permisos, no ejecuta comandos y no sustituye la aprobación expresa para pasar de Fase 0 a Fase 1.
