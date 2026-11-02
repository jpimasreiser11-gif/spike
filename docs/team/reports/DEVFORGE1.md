# DEVFORGE1: planificación en Dev, skills en Forge y entregables revisables

Trabajo de Codex, revisado e integrado por Claude en el Mac sobre main `a2cdc1f`, a petición de joan (2026-11-02).

## Qué añade

- Dev: `--plan`, `/plan [tarea]` y `/act`. El modo plan usa el `read_only` existente del orquestador: el modelo no recibe
  herramientas de edición ni de ejecución aunque esté `--accept-edits`. `/act` solo cambia el modo, no ejecuta nada.
- Dev: `/skills` y `/skill <nombre> <tarea>`, una skill por turno; las desconocidas o desactivadas se rechazan antes de
  llamar al modelo y antes de registrar el turno.
- Forge: selector de hasta tres skills por tarea e importación de ZIP con el endpoint existente.
- Entregables: componente común con descarga, vista previa HTML/SVG en el panel aislado y texto literal, con límite de
  1 MiB también en el stream, UTF-8 estricto y rechazo de respuestas obsoletas.

## Comprobado en esta integración

`ruff check .`: limpio. `pytest`: 2877 passed, 30 skipped. `vitest`: 218 passed. `tsc` y `npm run build`: correctos.
`node web/e2e/smoke.mjs`: `E2E OK`, con proveedores guionizados, no con inferencia real. **Not measured with real weights.**

## Procedencia

Las funciones se escribieron sobre el motor de SPIKE a partir de comportamiento visible y de documentación pública.
La exploración de Codex también analizó con REA dos archivos JavaScript distribuidos con una aplicación comercial. Eso
incumple CONTRIBUTING.md, que limita REA a software propio o autorizado, así que su matriz y sus evidencias no
forman parte de este cambio y no debe repetirse. Claude leyó el código Python y `ArtifactFiles.tsx` antes de integrarlos.

## Pendiente

Sesiones de Dev en la interfaz gráfica, espacio visual unificado de plan, permisos y artefactos, e instalación de skills
desde GitHub. No se afirma equivalencia con ningún producto comercial.
