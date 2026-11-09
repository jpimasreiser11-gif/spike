# Spike Creator, Workflows, Research Workbench y Subtítulos

Idioma: **Español** | [English](../en/creator.md) · [Índice de la guía](README.md)

![Spike Creator, Workflows, Research Workbench y Subtítulos](../images/creator.png)

## Qué hace

Agrupa los estudios de producción guiada de SPIKE: **Creator** (plantillas paso a paso con revisión de plan antes de redactar y **Data Apps** sobre tablas), **Workflows** (flujos reutilizables encadenados con variables `{{var}}`, condiciones y paradas de aprobación), **Research Workbench** (cuadernos con citas verificadas página/párrafo sobre PDFs locales y detección de contradicciones) y **Subtitle Studio** (edición de subtítulos `SRT`/`VTT`, comprobación de velocidad de lectura CPS y transcripción local).

## Cómo se usa paso a paso

1. Pulsa **Creator** en la barra lateral, elige una plantilla (informe ejecutivo, propuesta, lanzamiento, etc.), rellena los campos, genera el **Plan (Blueprint)**, edita las secciones si lo deseas y pulsa **Generar entregable**.
2. Pulsa **Workflows** en la barra lateral para diseñar una cadena de pasos con entradas tipadas, condiciones `if` y archivo de salida opcional; cada paso que escriba en disco respeta el broker de permisos.
3. Pulsa **Research** para crear un cuaderno de investigación a partir de archivos PDF/texto de tu proyecto: SPIKE extrae el texto por página y verifica que cada cita (`[p. X]`) corresponda al documento.
4. Pulsa **Subtítulos** para importar un archivo `.srt` o `.vtt`, corregir tiempos o líneas con exceso de caracteres por segundo (CPS) y exportar el resultado en `.srt` o `.vtt`.

## Límites reales

- La transcripción automática de audio/vídeo en Subtitle Studio requiere `whisper-cli` (`whisper.cpp`) y `ffmpeg` instalados localmente; la importación, edición manual, validación CPS y exportación `SRT`/`VTT` funcionan siempre sin dependencias externas; consulta [../../SUBTITLES.md](../../SUBTITLES.md), [../../WORKFLOWS.md](../../WORKFLOWS.md) y [../../STATUS.md](../../STATUS.md).

## Cómo comprobarlo

- Ejecuta `.venv/bin/python -m pytest -q tests/test_creator.py tests/test_workflows.py tests/test_research_workbench.py tests/test_subtitles.py`.
- Ejecuta `cd web && npx vitest run src/workflowBuilder.test.tsx src/research.test.tsx src/subtitles.test.tsx`.
