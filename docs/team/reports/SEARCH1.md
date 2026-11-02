# SEARCH1: búsqueda local de conversaciones y salto al mensaje

## Resumen

Añade búsqueda de títulos y mensajes guardados, incluso chats fuera del límite de 200 de la barra lateral. Filtros por
proyecto, autor, fecha y palabras/frase; resultados con fragmentos resaltados y apertura del mensaje en su proyecto.
Diálogo nativo en español e inglés, teclado y móvil. La búsqueda no usa modelos ni incluye chats temporales.

## Criterios

- Búsqueda local y privada: `test_search_is_local_persistent_only_and_uncached`, sin peticiones a proveedores.
- Historial antiguo, frases y filtros: `tests/test_history.py`, incluido un chat desplazado por 205 posteriores.
- Índice coherente: migración/reapertura/VACUUM, edición, reintento, borrado, ramas e importación probados.
- Interfaz: `web/src/history.test.tsx` cubre solicitudes explícitas, respuestas obsoletas, errores y paginación.
- Flujo completo: smoke Chromium comprueba cambio de proyecto, foco en mensaje, Escape y pantalla de 390 px.

## Decisiones

Mejora elegida por Codex a petición directa de joan de seguir mejorando el producto; SEARCH1 es un identificador local
de entrega, **no una asignación inventada del tablero de Claude**. Rama `codex/search1` desde main `91e7113`.
Se mantiene una API y componente separados. FTS5 ya existe en SPIKE; ninguna dependencia añadida. La migración es atómica
y utiliza claves enteras estables. La búsqueda recupera mensajes existentes, no modifica la memoria ni el orquestador.
La API usa POST y no-store. El detalle técnico y los límites están en `docs/HISTORY-SEARCH.md`.

El trabajador normal se detuvo para evitar cambios simultáneos de rama. Esta sesión implementó directamente; la entrega
usa el verificador, commit, push e informe del trabajador mediante un coordinador local, sin lanzar otra sesión de modelo.
Se incluyen dos arreglos de fixtures ya presentes en otras ramas pendientes: cierre del MCP simulado y espera a que se
carguen los proveedores de escritorio antes de comprobarlos. No cambian capacidades de producto.

## Pendiente

Revisión e integración de Claude. No es búsqueda semántica ni búsqueda de archivos; no hay permisos multiusuario nuevos.
No se han medido millones de mensajes ni plataformas Windows/Linux reales. El índice ocupa espacio adicional y su
borrado lógico no garantiza borrado forense. No se ha modificado la carpeta original de joan ni los entrenamientos.
No se modifica el tablero, STATUS ni CHANGELOG.

## Tests

Resultados finales del trabajador y de las comprobaciones adicionales al pie. Las primeras ejecuciones de las pruebas
nuevas fallaron por ausencia de la implementación; después pasaron las pruebas enfocadas. Las pruebas con UTF-8
desactivado: `23 passed`. El smoke completo inicial: `E2E OK`; se repite tras el ajuste de restauración del foco.

## STATUS.md

| Búsqueda local de conversaciones | Migración, filtros, borrados, importación y salto al mensaje; sin llamadas a modelos | `pytest -q tests/test_history.py tests/test_history_server.py`; `npx vitest run src/history.test.tsx`; smoke Chromium |

## CHANGELOG.md

- Añade búsqueda local de conversaciones por palabras/frase, proyecto, autor y fecha, con acceso al mensaje y diálogo
  accesible por teclado en español e inglés; excluye chats temporales y mantiene el índice tras edición/importación/borrado.

## Preguntas para Claude

Ninguna. Revisar e integrar como mejora solicitada por joan, sin marcar tareas del tablero ajenas como terminadas.

## Verificación del trabajador

Ejecutado por el trabajador, fuera de Codex, el 2026-10-28T09:25:09Z.

### `.venv/bin/ruff check .`

- Código de salida: 0
- Últimas 15 líneas:

```text
All checks passed!
```

### `.venv/bin/python -m pytest -q`

- Código de salida: 0
- Últimas 15 líneas:

```text
...........................sssssssss.s.................................. [ 47%]
........................................................................ [ 51%]
........................................................................ [ 56%]
........................................................................ [ 60%]
........................................................................ [ 64%]
........................................................................ [ 68%]
............................................ssss........................ [ 73%]
........................................................................ [ 77%]
........................................................................ [ 81%]
........................................................................ [ 86%]
..........s............................................................. [ 90%]
........................................................................ [ 94%]
........................................................................ [ 99%]
...............                                                          [100%]
1651 passed, 22 skipped in 128.11s (0:02:08)
```

### `npx vitest run` (en `web/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
 ✓ src/desktop.test.ts  (16 tests) 14ms
 ✓ src/parallel.test.ts  (11 tests) 7ms
 ✓ src/visualChecks.test.ts  (2 tests) 46ms
 ✓ src/diagnostics.test.tsx  (2 tests) 42ms
 ✓ src/history.test.tsx  (6 tests) 93ms
 ✓ src/lab.test.tsx  (3 tests) 84ms
 ✓ src/chart.test.ts  (2 tests) 226ms
 ✓ src/apiError.test.ts  (2 tests) 2ms
 ✓ src/proof.test.tsx  (1 test) 16ms
 ✓ src/artifact.test.ts  (3 tests) 8ms

 Test Files  16 passed (16)
      Tests  88 passed (88)
   Start at  10:24:33
   Duration  1.06s (transform 462ms, setup 0ms, collect 1.00s, tests 562ms, environment 4.62s, prepare 578ms)
```

### `npm run build` (en `web/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
dist/assets/inter-latin-400-normal-gitzw0hO.woff            31.20 kB
dist/assets/inter-latin-ext-500-normal-CIS2RHJS.woff2       31.76 kB
dist/assets/inter-latin-500-normal-deR1Tlfd.woff            31.77 kB
dist/assets/inter-latin-600-normal-B5cFAncS.woff            31.78 kB
dist/assets/inter-latin-ext-600-normal-BnYJhD27.woff2       31.97 kB
dist/assets/inter-latin-ext-400-normal-C1t-h-pH.woff        42.88 kB
dist/assets/inter-latin-ext-500-normal-UMdmhHu2.woff        43.84 kB
dist/assets/inter-latin-ext-600-normal-CAF0vJDd.woff        43.98 kB
dist/assets/index-DenxJXPZ.css                              49.12 kB │ gzip:  10.10 kB
dist/assets/isString-DCn3LAjH.js                             2.15 kB │ gzip:   1.09 kB
dist/assets/vega-interpreter-BAYmwApn.js                     5.11 kB │ gzip:   2.05 kB
dist/assets/index-BhpfY6kh.js                              262.83 kB │ gzip:  84.81 kB
dist/assets/vega.module-BJsxS-54.js                        524.51 kB │ gzip: 185.90 kB
dist/assets/index-BCfo7Uo_.js                              626.43 kB │ gzip: 195.64 kB
✓ built in 1.20s
```

### `LC_ALL=C LANG=C .venv/bin/python -X utf8=0 -m pytest -q tests/test_history.py tests/test_history_server.py`

- Código de salida: 0
- Últimas 15 líneas:

```text
.......................                                                  [100%]
23 passed in 0.62s
```

### `Chromium full smoke (scripted providers, temporary home)`

- Código de salida: 0
- Últimas 15 líneas:

```text
/Users/jpima/Downloads/Spike-codex/tests/fixtures/out/.team-qa/SEARCH1/20261028-102438
E2E OK

server stopped -15
```

### `git diff --check`

- Código de salida: 0
- Últimas 15 líneas:

```text

```

Resultado: todo en verde.

<!-- fin de la verificación del trabajador -->
