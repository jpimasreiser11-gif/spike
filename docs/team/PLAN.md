# Plan del equipo SPIKE: Claude y Codex

Pedido de joan (2026-10-26): trabajar Claude y Codex juntos, con Claude como jefe, para aprovechar los dos planes Pro;
el plan incluye todas las funciones, modelos y apps; al final, un instalador de un clic para Linux, Mac y Windows con
los modelos; y después, buscar cómo monetizarlo.

## Quién hace qué
| Quién | Papel |
|---|---|
| **Claude (nube, jefe)** | Planifica, reparte, revisa cada rama de Codex y la integra en `main`, mantiene la CI en verde, STATUS y CHANGELOG. Hace lo delicado: seguridad (sandbox, permisos, gastos), orquestador, memoria, Evolution, datos de entrenamiento y medición de los modelos. |
| **Codex (Mac de joan)** | Construye los módulos y funciones con interfaz clara: Studio, skills, ecosistema, Analytics, Lab, proyectos, módulos nuevos, recetas de datos, app de escritorio e instaladores. Una tarea cada vez, cada una en su rama `codex/<id>`. |
| **Claude en el Mac** | Entrena y mide (un trabajo pesado cada vez, sin pasarse de RAM) y mantiene en marcha el trabajador de Codex. |
| **joan** | Solo decisiones que nadie más puede tomar: gastos, publicar (repo público, Hugging Face, anuncios) y la monetización. |

El tablero con todas las tareas y su dueño está en [tasks.json](tasks.json) (vista: [BOARD.md](BOARD.md)).

## Cómo nos comunicamos
Todo pasa por el repositorio, así nada depende de que alguien copie mensajes:
1. Claude escribe las tareas en `docs/team/tasks.json` (en `main`).
2. El trabajador `scripts/team/codex_worker.py` corre en el Mac, toma la siguiente tarea de Codex y lanza
   `codex exec` en una copia propia (`~/Downloads/Spike-codex`), pasa ruff y los tests, y sube la rama `codex/<id>` con
   el informe `docs/team/reports/<ID>.md`. Espera si queda poca RAM libre para no frenar el entrenamiento, y si Codex
   agota su uso, espera y reintenta.
3. Claude revisa cada rama: la integra en `main` (y marca la tarea `hecha`) o escribe `docs/team/reviews/<ID>.md` con
   lo que hay que cambiar y la marca `cambios pedidos`; el trabajador se la devuelve a Codex con la revisión.
4. Las preguntas de Codex van en su informe; las respuestas, en la revisión.

## Fases
1. **App completa** (en paralelo): todo lo del análisis y de IDEAS-JOAN-3 que falta, incluidos los módulos que estaban
   para después (imagen y voz, audio y subtítulos, notebook, Paper Rebuilder, mapa de contradicciones, Geo, grabador,
   explorador de arquitectura, Parallel Minds, prototipos en paralelo, Blender, Godot, escritorio vía proveedor).
   Fuera por decisión: salas de revisión multiusuario y control del escritorio con el modelo local.
2. **Modelos**: arreglar el olvido en medicina (en marcha), luego finanzas y marketing con la receta que pase, recetas
   de datos y entrenamiento de los otros 10 especialistas de uno en uno, router con los 13. Cada uno pasa su criterio
   de aceptación o se queda como perfil de instrucciones; nada se anuncia sin números medidos.
3. **Instalador de un clic con modelos**: app de escritorio (servidor local + ventana nativa con pywebview si está, o el
   navegador), asistente de primer arranque que descarga el modelo base y los especialistas con su SHA-256, y
   instaladores `.dmg` (Mac), `.exe` (Windows, Inno Setup) y AppImage (Linux) hechos en GitHub Actions. Decisión: sin
   firma de pago (cuesta dinero), así que Mac y Windows avisarán al abrir; se documenta cómo abrirlo, y joan decide si
   compra certificados.
4. **Lanzamiento v0.1**: demo real, revisión de seguridad y licencias, notas de versión; repo público, Hugging Face y
   anuncios solo con el OK de joan y desde sus cuentas.
5. **Monetización**: estudio con opciones, lo que permite cada licencia (app, modelo base y cada dataset), costes y
   riesgos; joan elige; luego se implementa.

## Reglas que no cambian
Sin gastos ni llamadas de pago sin permiso; sin secretos en el repo; sin resultados, velocidades ni compatibilidades
inventadas; código escrito no es código probado; nunca entrenar con salidas de Claude, GPT, Gemini o Llama; en el Mac,
un trabajo pesado cada vez y sin pasarse de RAM; nunca tocar la carpeta `~/Downloads/Spike` de joan.
