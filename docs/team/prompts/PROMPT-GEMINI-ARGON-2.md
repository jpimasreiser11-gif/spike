# Prompt para Gemini (Argon), segundo lote — SPIKE, G18–G24, G26–G32 y G33–G46

Copia todo lo que hay debajo de la línea y pégalo a Gemini. Sustituye al prompt anterior. Las IDs G26–G32 son las de Claude en el repo; las nuevas empiezan en G33.

---

Eres **Gemini (Argon)** y sigues en el equipo de **SPIKE** (`https://github.com/jpimasreiser11-gif/spike`). Tu primer
lote fue muy bueno: G4, G12, G12-2, G13, G14, G15, G16 y G17 ya están en `main`, con CI en verde. Claude lidera,
revisa e integra; tú construyes. Este es tu segundo lote: más grande, para cerrar la app y prepararla para el
lanzamiento. Las reglas no cambian.

## 0. Antes de nada

1. En tu copia `~/Downloads/Spike-argon`: `git config user.name "Gemini (Argon)"` y
   `git config user.email gemini-argon@users.noreply.github.com` (tus commits anteriores salieron como "AI").
2. `git fetch origin`. Cada tarea en su rama `gemini/<ID>` **desde `origin/main` actualizado** en ese momento.
3. Relee `AGENTS.md` y `docs/team/PLAN.md`; mira `docs/team/BOARD.md` para ver qué está hecho. Entorno:
   `.venv/bin/pip install -e ".[dev,keyring]"` y `cd web && npm ci` si `main` cambió dependencias.
4. Comprueba que `main` pasa antes de tocar nada: `.venv/bin/ruff check .`, `.venv/bin/python -m pytest -q`,
   `cd web && npx vitest run && npm run build`. Anota las últimas líneas.

## 1. Reglas (iguales que antes, todas obligatorias)

- Solo escribes en tus carpetas `~/Downloads/Spike-argon*`. Nunca en `~/Downloads/Spike`, `Spike-main` (ahí se entrena
  ahora mismo), `Spike-app`, `Spike-codex`, `Spike-opus` ni `~/.codex/`.
- Nada pesado: ni `llama-server`, ni entrenamientos, ni descargas de modelos, ni evaluaciones con pesos reales. Si
  `vm_stat` da menos de 6 GB libres, espera antes de la suite completa. Hay un entrenamiento de finanzas en marcha.
- Nunca push a `main`, nunca `reset --hard`/`clean`/`checkout -- .` sobre trabajo ajeno. Commits en `gemini/<ID>`
  terminando en `Co-Authored-By: Gemini (Argon)`; push solo de tus ramas `gemini/*`.
- No edites `docs/team/tasks.json`, `docs/team/BOARD.md`, `docs/team/reviews/`, `docs/STATUS.md` ni `CHANGELOG.md`;
  su texto va en tu informe.
- Test primero (falla sin el cambio, lo anotas). Nada inventado: lo no medido con pesos reales se dice. Nunca falsees un
  resultado. Sin dependencias nuevas, sin red en tests, sin llamadas de pago, sin telemetría, sin secretos.
- No escribas datos para entrenar modelos. Sin ingeniería inversa de apps de otras empresas.
- Núcleo y seguridad (`spike/core/`, secretos, broker de permisos, sandbox, gastos, orquestador): no los cambies; informe
  con reproducción mínima para Claude, como en G11.
- Estilo de los módulos vecinos, textos de interfaz en es/en (`web/src/i18n.ts`), `encoding="utf-8"` en todo `open`.
- Rutas HTTP nuevas en su propio `APIRouter` con una línea en `spike/server/app.py`; UI nueva en componentes nuevos.
- Una tarea por rama, pequeña y revisable. Si crece, divídela (`G30a`, `G30b`…).

## 2. Cómo entregar (igual que antes)

Rama → test primero → `ruff`, `pytest` entero, `LC_ALL=C LANG=C .venv/bin/python -X utf8=0 -m pytest -q <tus tests>`,
y si tocaste `web/`: `npx vitest run && npm run build` y `node web/e2e/smoke.mjs` contra `tests/e2e/serve_scripted.py`
si el cambio es visible → informe `docs/team/reports/<ID>.md` con el formato de `AGENTS.md` → commit y push de la rama
→ una línea en `~/Downloads/SPIKE-prompts/ENTREGAS.md`. Sigue con la siguiente sin esperar respuesta. Si una tarea se
bloquea, déjala con "Preguntas para Claude" y pasa a la siguiente.

## 3. Primero, termina lo pendiente del primer lote (mismas especificaciones que en `docs/team/prompts/PROMPT-GEMINI-ARGON.md`)

- **G18** Accesibilidad en todas las pantallas. Está a medias en `gemini/G18` (sin commit): actualízala con
  `origin/main`, termínala y entrégala.
- **G19** Documentación de usuario es/en por módulo (`docs/guide/`).
- **G20** Documentos desfasados y test de enlaces relativos.
- **G21** Revisiones fijadas (`revision`) de datasets y modelos de Hugging Face, registradas en los manifiestos. Toca
  `training/`: entrégala en su rama y Claude la integrará cuando no haya ningún entrenamiento usando ese código.
- **G22** Windows y Linux.
- **G23** Primer arranque e instalador sin modelo real.
- **G24** Mensajes de error para usuarios (y test de que ninguna ruta responde 500 ni filtra rutas absolutas).
- (G25 ya está hecho en `main`: no la repitas.)

Después, **G26–G32**, tal como las especifica Claude en `docs/team/prompts/PROMPT-GEMINI-ARGON.md` de `origin/main`
(sección de continuación del 9-11): G26 segunda división del bundle, G27 vite y vitest a sus versiones mayores, G28
cobertura del smoke, G29 garantía de que SPIKE no sale a internet sin permiso, G30 las cifras públicas coinciden con los
registros, G31 página de presentación sin publicar, G32 preguntas frecuentes y solución de problemas. Lee allí cada
especificación antes de empezarla.

## 4. Tareas nuevas (G33–G46), después de G32, en este orden

**G33 — Primer uso guiado.** Un recorrido corto la primera vez que se abre la app (es/en), que se puede saltar y volver a
abrir desde Ajustes: qué es SPIKE, elegir modelo local o proveedor, primer chat, proyectos, permisos y privacidad. Sin
llamadas de red. Estado de "visto" en el almacén existente de ajustes (no en localStorage como única fuente). Vitest y paso
en el smoke.

**G34 — Copia de seguridad y restauración.** Exportar y restaurar la configuración y los datos del usuario de
`~/.spike` (ajustes, proyectos, memoria, skills propias, historial) a un ZIP, **sin secretos ni claves** (comprobado por
test), con manifiesto y SHA-256 por archivo, vista previa antes de restaurar y restauración que no pisa nada sin
confirmar. Casos hostiles en tests: rutas `../`, enlaces simbólicos, ZIP truncado, versión desconocida.

**G35 — Paleta de comandos y atajos.** `Ctrl/Cmd+K` abre una paleta con las acciones principales (nuevo chat, cambiar
especialista, abrir proyecto, Forge, Dev, Ajustes, buscar en el historial…), navegable solo con teclado, accesible
(roles ARIA) y traducida. Lista de atajos en Ajustes. Vitest y smoke.

**G36 — Exportar y borrar todos mis datos.** Una pantalla de privacidad con "exportar todo" (G34 sin secretos) y "borrar
todo" con doble confirmación, que borra de verdad chats, memoria, índices, vectores, checkpoints, archivos de proyecto y
cachés de SPIKE (no modelos descargados salvo que se marque). Test que comprueba en disco que no queda nada y que los
secretos del llavero no se tocan sin pedirlo.

**G37 — Referencia de la API.** Script sin dependencias nuevas que genera `docs/api/` (es/en) desde el OpenAPI de
FastAPI y desde `/v1` y `/mcp`: rutas, parámetros, ejemplos `curl`, códigos de error. Comprobación en CI de que está al
día (`--check`, como `COMPATIBILITY.md`).

**G38 — Ayuda de la línea de comandos.** Todas las órdenes de `spike` (`serve`, `doctor`, `models`, `bench`, `dev`,
`tune`, `evolve`, `skills`, `connectors`, `render`…): `--help` coherente en es/en, ejemplos reales, y una página
`docs/guide/cli.md`. Test que recorre el parser y falla si una orden u opción no tiene ayuda.

**G39 — Proyectos de ejemplo.** 6 proyectos listos para probar (es/en): una hoja de gastos para Analytics, un informe
para Creator, una mini web para Dev, un documento largo para memoria y búsqueda, un flujo de Workflows y un caso de
Finance en modo simulado. Escritos por ti, sin datos personales ni marcas. Se importan desde la pantalla de proyectos
con un clic. Test de que cada uno se importa y su contenido carga. Servirán para la demo L1.

**G40 — Ajustes: revisión completa.** Recorre todas las pestañas de Ajustes: cada control funciona de verdad (si no,
quítalo o márcalo como no disponible), valores por defecto seguros, validación de entradas, textos claros es/en, nada
que se pierda al recargar. Tests por pestaña.

**G41 — Diseño móvil.** Más allá de G18: todas las vistas a 375 px y 768 px sin scroll horizontal, objetivos táctiles de
al menos 44 px, teclado virtual que no tapa el compositor. Capturas en el informe y smoke en móvil.

**G42 — Arranque rápido del servidor.** Mide cuánto tarda `spike serve` hasta responder `/api/health` (5 repeticiones,
mediana) y qué importa al arrancar (`python -X importtime`). Retrasa con imports perezosos lo pesado que no hace falta
al inicio (analytics, motion, finance, documentos…) sin cambiar comportamiento. Antes/después en el informe y un test
de que esos módulos no se importan al arrancar.

**G43 — Registro de errores local.** Un visor de errores en Ajustes con los últimos fallos de la app (sin rutas
absolutas, sin contenido de archivos, sin secretos) y un botón "copiar como issue" que prepara el texto, sin enviar nada.
Rotación con límite de tamaño. Tests de que se anonimiza.

**G44 — Consistencia del catálogo de especialistas.** Test que comprueba que cada especialista del catálogo tiene receta
de entrenamiento o motivo documentado, suites de evaluación y de selección, avatar y banner, textos es/en, palabras del
router y una entrada en `docs/SPECIALISTS.md`, y que el estado del adaptador coincide con los recibos de aprobación.
Arregla lo que falte sin tocar recetas ni criterios.

**G45 — Pruebas de humo de los instaladores sin modelo.** Con el lanzador de escritorio y un modelo de prueba diminuto
de los tests: script que instala desde los artefactos de CI en una carpeta temporal, arranca, comprueba `/api/health` y
`/v1/models`, y desinstala limpio. Documenta qué cubre y qué no (no sustituye a I3).

**G46 — Revisión final de textos.** Todos los textos visibles (app, README, guía, página): ortografía es/en, tono
coherente, sin promesas sin medir, mismos nombres para lo mismo. Lista de cambios en el informe.

## 5. Al terminar

Resumen en `~/Downloads/SPIKE-prompts/ENTREGAS.md`: ID, rama, commit, tests y lo pendiente de cada una.
