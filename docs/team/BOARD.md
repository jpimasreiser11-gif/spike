# Tablero SPIKE

Generado desde `docs/team/tasks.json` con `python scripts/team/board.py render`; no se edita a mano.

## Resumen

| Quién | pendiente | en curso | en revisión | cambios pedidos | hecha | bloqueada | total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Claude | 8 | 2 | 0 | 0 | 32 | 0 | 42 |
| Codex | 0 | 0 | 0 | 0 | 16 | 0 | 16 |
| Gemini | 0 | 0 | 0 | 0 | 17 | 0 | 17 |
| Opus | 3 | 1 | 0 | 0 | 0 | 0 | 4 |
| Mac | 3 | 2 | 0 | 0 | 4 | 0 | 9 |
| joan | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| **Total** | **17** | **5** | **0** | **0** | **69** | **0** | **91** |

## Fase: equipo

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| A0 | Claude | hecha | Tablero del equipo y trabajador de Codex | - |
| M0 | Mac | hecha | Arrancar a Codex en el Mac | A0 |
| M12 | Mac | hecha | Subir al repo los prompts de Argon y Opus | - |
| G12 | Gemini | hecha | Revisar los PR abiertos de Codex | - |

## Fase: app

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| S1 | Codex | hecha | Rescatar el trabajo de Studio | - |
| A1 | Codex | hecha | Paquete de skills y validadores | - |
| A2 | Codex | hecha | Ecosistema abierto: bench --share, esquemas, compatibilidad | - |
| A3 | Codex | hecha | Analytics: contratos, SQL Guardian, rescate, linaje y previsiones | - |
| A5 | Codex | hecha | Dependency Doctor y Visual Critic | - |
| A8 | Codex | hecha | Lab: comparar modelos y probar proveedores | - |
| A9 | Codex | hecha | Ramas de proyecto, comentarios, conocimiento por especialista y cola de trabajos | - |
| A11 | Codex | hecha | Marketplace de skills y hasta 30 skills | A1 |
| A12 | Codex | hecha | De un Excel a una app (Data-to-Software) | A3 |
| A13 | Codex | hecha | Imagen y voz | - |
| A14 | Codex | hecha | Audio y subtítulos | A13 |
| A15 | Codex | hecha | Investigación: notebook, Paper Rebuilder y mapa de contradicciones | - |
| A16 | Claude | hecha | Geo, grabador del navegador y explorador de arquitectura | - |
| A18 | Claude | hecha | 3D con Blender y juegos con Godot | - |
| A20 | Claude | hecha | Reverse Studio: de una captura propia a código editable | - |
| A21 | Claude | hecha | Device Lab: probar la app en perfiles de móvil, tablet y escritorio | - |
| A22 | Claude | hecha | Visual Workflow Builder: encadenar pasos en un lienzo | - |
| A4 | Claude | hecha | Aislamiento del sistema para python y run_command | - |
| A6 | Claude | hecha | Respuestas fiables: verificado / hipótesis / sin comprobar y citas comprobadas | - |
| A7 | Claude | hecha | Memoria: carpetas elegidas, glosario, progreso del tutor y grafo | - |
| A10 | Claude | hecha | Evolution: estrategia de herramientas, regresión de prompts y adaptador personal | - |
| A17 | Claude | hecha | Parallel Minds y prototipos en paralelo | - |
| A19 | Claude | hecha | Escritorio con un proveedor con computer use | - |
| G4 | Gemini | hecha | Estado real de cada especialista en Ajustes | - |
| G13 | Gemini | hecha | Fiabilidad de Analytics | - |
| G14 | Gemini | hecha | Fiabilidad de proyectos y memoria | - |
| G15 | Gemini | hecha | Fiabilidad de los conectores MCP | - |
| G16 | Gemini | hecha | Fiabilidad de Workflows, Device Lab, Reverse Studio y Geo | - |
| G17 | Gemini | hecha | Auditoría de traducciones | - |
| G18 | Gemini | hecha | Accesibilidad en todas las pantallas | - |
| G19 | Gemini | hecha | Documentación de usuario en español e inglés | - |
| G20 | Gemini | hecha | Revisar documentos desfasados | - |
| G21 | Claude | hecha | Reproducibilidad: revisiones fijadas de datos y modelos | - |
| G22 | Gemini | hecha | Windows y Linux | - |
| G23 | Gemini | hecha | Primer arranque e instalador sin modelo real | - |
| G24 | Gemini | hecha | Mensajes de error para usuarios | - |
| G25 | Claude | hecha | Rendimiento de la interfaz: dividir el bundle | - |
| G26 | Claude | hecha | Segunda división del bundle | G25 |
| G27 | Claude | hecha | Actualizar vite y vitest a sus versiones mayores | - |
| G28 | Gemini | hecha | Cobertura del smoke: vistas que no abre | - |
| G33 | Claude | pendiente | Primer uso guiado | - |
| G34 | Claude | hecha | Copia de seguridad y restauración | - |
| G35 | Claude | pendiente | Paleta de comandos y atajos | - |
| G36 | Claude | hecha | Exportar y borrar todos mis datos | G34 |
| G37 | Claude | hecha | Referencia de la API | - |
| G38 | Claude | hecha | Ayuda de la línea de comandos | - |
| G39 | Claude | hecha | Proyectos de ejemplo | - |
| G40 | Claude | pendiente | Ajustes: revisión completa | - |
| G41 | Claude | pendiente | Diseño móvil | G18 |
| G42 | Claude | hecha | Arranque rápido del servidor | - |
| G43 | Claude | hecha | Registro de errores local | - |
| G44 | Claude | hecha | Consistencia del catálogo de especialistas | - |
| G45 | Claude | pendiente | Humo de los instaladores sin modelo | - |
| G46 | Claude | pendiente | Revisión final de textos | - |
| O1 | Opus | en curso | Sesiones de Spike Dev en la app (API e interfaz) | - |
| O2 | Opus | pendiente | Un espacio de tarea unificado | - |
| O3 | Opus | pendiente | Instalar skills desde una URL de GitHub, con revisión | - |
| O4 | Claude | hecha | Revisión de seguridad previa al lanzamiento (para L2) | - |
| O5 | Opus | pendiente | Revisar la integración del PR #2 | M13 |

## Fase: modelos

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| M1 | Mac | hecha | Medicina: arreglar el olvido (fix_forgetting) | - |
| M2 | Claude | hecha | Decidir medicina con los números y elegir la receta | M1 |
| M3 | Mac | en curso | Entrenar finanzas con la receta que pase | M2 |
| M4 | Mac | pendiente | Entrenar marketing | M3 |
| M5 | Codex | hecha | Recetas de datos: derecho, ciencia, matemáticas, código y datos | - |
| M6 | Codex | hecha | Recetas de datos: educación, escritura, negocio, seguridad y core | M5 |
| M7 | Claude | hecha | Verificar licencias y conteos de las recetas nuevas | M5, M6 |
| M8 | Mac | pendiente | Entrenar los 10 especialistas restantes, de uno en uno | M4, M7 |
| M9 | Claude | hecha | Router con los 13 especialistas | M8 |
| M11 | Mac | hecha | Medicina: registrar el adaptador aceptado e instalarlo | M2 |
| M13 | Claude | hecha | Integrar la procedencia de evaluaciones (PR #2, rama gemini/G12-2) | - |
| M14 | Claude | en curso | Lector de respuestas: '**Final Answer Selection:** E' y el texto de la opción | M3 |
| M15 | Mac | en curso | Medicina: ficha de Hugging Face del adaptador aceptado (sin publicar) | M11 |

## Fase: models

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| M10 | Claude | hecha | Ciencia y Datos: semillas y destilación verificada (sin dataset con licencia válida) | M7 |

## Fase: instalador

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| I1 | Codex | hecha | App de escritorio: lanzador y asistente de modelos | - |
| I2 | Codex | hecha | Instaladores de un clic y publicación | I1 |
| I3 | Claude | hecha | Probar los instaladores en máquinas limpias con el modelo real | I2 |
| I4 | joan | pendiente | Opcional: certificados de firma | - |

## Fase: lanzamiento

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| G29 | Gemini | hecha | Garantía de que SPIKE no sale a internet sin permiso | - |
| G30 | Gemini | hecha | Las cifras públicas coinciden con los registros | - |
| G31 | Claude | pendiente | Página de presentación (sin publicar) | - |
| G32 | Gemini | hecha | Preguntas frecuentes y solución de problemas | G19, G24 |
| L1 | Mac | pendiente | Grabar la demo real | M2 |
| L2 | Claude | en curso | Revisión final de seguridad y licencias y notas de versión | I3, L1 |
| L3 | joan | pendiente | Aprobar: repo público, Hugging Face y anuncio | L2 |

## Fase: negocio

| ID | Quién | Estado | Tarea | Depende de |
|---|---|---|---|---|
| N1 | Claude | hecha | Estudio de monetización | L2 |
| N2 | joan | pendiente | Elegir cómo monetizar | N1 |
| N3 | Claude | pendiente | Implementar la monetización elegida | N2 |
