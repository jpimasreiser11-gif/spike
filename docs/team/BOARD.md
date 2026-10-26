# Tablero SPIKE

Generado desde `docs/team/tasks.json` con `python scripts/team/board.py render`; no se edita a mano.

## Resumen

| Quién | pendiente | en curso | en revisión | cambios pedidos | hecha | bloqueada | total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Claude | 8 | 1 | 0 | 0 | 5 | 0 | 14 |
| Codex | 18 | 0 | 0 | 0 | 0 | 0 | 18 |
| Mac | 5 | 1 | 0 | 0 | 0 | 0 | 6 |
| joan | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| **Total** | **34** | **2** | **0** | **0** | **5** | **0** | **41** |

## Fase: equipo

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| A0 | Claude | hecha | Tablero del equipo y trabajador de Codex | - |
| M0 | Mac | pendiente | Arrancar a Codex en el Mac | A0 |

## Fase: app

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| S1 | Codex | pendiente | Rescatar el trabajo de Studio | - |
| A1 | Codex | pendiente | Paquete de skills y validadores | - |
| A2 | Codex | pendiente | Ecosistema abierto: bench --share, esquemas, compatibilidad | - |
| A3 | Codex | pendiente | Analytics: contratos, SQL Guardian, rescate, linaje y previsiones | - |
| A5 | Codex | pendiente | Dependency Doctor y Visual Critic | - |
| A8 | Codex | pendiente | Lab: comparar modelos y probar proveedores | - |
| A9 | Codex | pendiente | Ramas de proyecto, comentarios, conocimiento por especialista y cola de trabajos | - |
| A11 | Codex | pendiente | Marketplace de skills y hasta 30 skills | A1 |
| A12 | Codex | pendiente | De un Excel a una app (Data-to-Software) | A3 |
| A13 | Codex | pendiente | Imagen y voz | - |
| A14 | Codex | pendiente | Audio y subtítulos | A13 |
| A15 | Codex | pendiente | Investigación: notebook, Paper Rebuilder y mapa de contradicciones | - |
| A16 | Codex | pendiente | Geo, grabador del navegador y explorador de arquitectura | - |
| A18 | Codex | pendiente | 3D con Blender y juegos con Godot | - |
| A4 | Claude | hecha | Aislamiento del sistema para python y run_command | - |
| A6 | Claude | hecha | Respuestas fiables: verificado / hipótesis / sin comprobar y citas comprobadas | - |
| A7 | Claude | hecha | Memoria: carpetas elegidas, glosario, progreso del tutor y grafo | - |
| A10 | Claude | hecha | Evolution: estrategia de herramientas, regresión de prompts y adaptador personal | - |
| A17 | Claude | en curso | Parallel Minds y prototipos en paralelo | - |
| A19 | Claude | pendiente | Escritorio con un proveedor con computer use | - |

## Fase: modelos

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| M1 | Mac | en curso | Medicina: arreglar el olvido (fix_forgetting) | - |
| M2 | Claude | pendiente | Decidir medicina con los números y elegir la receta | M1 |
| M3 | Mac | pendiente | Entrenar finanzas con la receta que pase | M2 |
| M4 | Mac | pendiente | Entrenar marketing | M3 |
| M5 | Codex | pendiente | Recetas de datos: derecho, ciencia, matemáticas, código y datos | - |
| M6 | Codex | pendiente | Recetas de datos: educación, escritura, negocio, seguridad y core | M5 |
| M7 | Claude | pendiente | Verificar licencias y conteos de las recetas nuevas | M5, M6 |
| M8 | Mac | pendiente | Entrenar los 10 especialistas restantes, de uno en uno | M4, M7 |
| M9 | Claude | pendiente | Router con los 13 especialistas | M8 |

## Fase: instalador

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| I1 | Codex | pendiente | App de escritorio: lanzador y asistente de modelos | - |
| I2 | Codex | pendiente | Instaladores de un clic y publicación | I1 |
| I3 | Claude | pendiente | Probar los instaladores en máquinas limpias con el modelo real | I2 |
| I4 | joan | pendiente | Opcional: certificados de firma | - |

## Fase: lanzamiento

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| L1 | Mac | pendiente | Grabar la demo real | M2 |
| L2 | Claude | pendiente | Revisión final de seguridad y licencias y notas de versión | I3, L1 |
| L3 | joan | pendiente | Aprobar: repo público, Hugging Face y anuncio | L2 |

## Fase: negocio

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| N1 | Claude | pendiente | Estudio de monetización | L2 |
| N2 | joan | pendiente | Elegir cómo monetizar | N1 |
| N3 | Claude | pendiente | Implementar la monetización elegida | N2 |
