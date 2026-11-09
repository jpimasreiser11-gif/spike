# Especialistas, enrutador y modo Multi-mente

Idioma: **Español** | [English](../en/specialists.md) · [Índice de la guía](README.md)

![Especialistas, enrutador y modo Multi-mente](../images/specialists.png)

## Qué hace

SPIKE incluye 13 especialistas de dominio (`Core`, `Code`, `Finance`, `Medicine`, `Law`, `Marketing`, `Science`, `Data`, `Math`, `Education`, `Writing`, `Business`, `Security`) que comparten el mismo modelo base. Un enrutador léxico dirige las consultas claras sin gastar llamadas al modelo (46/50 en el conjunto retenido) y el modo Multi-mente permite que 2 o 3 especialistas deliberen con crítica cruzada antes de sintetizar la respuesta final.

## Cómo se usa paso a paso

1. Deja el selector en **Auto** para que el enrutador léxico elija el especialista adecuado, o selecciona uno manualmente.
2. Para activar **Mentes** (deliberación entre varios especialistas), pulsa el botón **Mentes** en el compositor y elige hasta 3 especialistas (o déjalo en selección automática).
3. Abre **Ajustes › Especialistas** para ver el estado real de cada especialista: si responde hoy como **perfil de instrucciones (β)** sobre el modelo base o con un **adaptador LoRA evaluado y cargado**, además de sus capas activas (instrucciones base, tus instrucciones, instrucciones aprendidas y notas en memoria).
4. En **Ajustes › Especialistas**, puedes añadir instrucciones propias por especialista o asignarle un proveedor concreto.

## Límites reales

- Un adaptador LoRA solo se marca como aceptado cuando supera su puerta de evaluación estadística sin perder conocimiento general (caída máxima permitida: 1,5 puntos en MMLU-Pro general).
- Hoy **Medicina** ha superado su criterio de aceptación (**+35,07 puntos** en 2.318 preguntas de MedMCQA, PubMedQA y MMLU-Pro health; **−0,62 puntos** en conocimiento general; SHA-256 `21caa0a0…`, pendiente de publicación). **Finanzas** (ronda 1 a 768 tokens rechazada por caída de −3,00 en general; ronda 2 en entrenamiento a 1536 tokens) y los demás especialistas responden hoy como **perfiles de instrucciones (β)** sobre el modelo base; consulta [../../SPECIALISTS.md](../../SPECIALISTS.md) y [../../STATUS.md](../../STATUS.md).

## Cómo comprobarlo

- Ejecuta `.venv/bin/python -m pytest -q tests/test_router.py tests/test_minds.py tests/test_specialist_status.py`.
- Ejecuta `cd web && npx vitest run src/specialists.test.tsx`.
