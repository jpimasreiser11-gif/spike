# COMPAT1: compatibilidad de Windows, borrado de proyectos y sincronización del smoke

## Resumen

Corrige los dos fallos de Windows observados en las PR #14 y #15 y la carrera de sincronización del chat que bloqueó el smoke de #14. Los benchmarks guardan rutas portables; el borrado de un proyecto puede eliminar objetos Git de solo lectura y comunica los errores antes de borrar su registro y sus conversaciones. El diálogo permite reintentar tras un error y bloquea solicitudes duplicadas. El smoke espera al control Enviar antes de continuar y prueba el borrado confirmado de un proyecto con archivos.

Base: `origin/main` en `91e7113293b8911f5a6d34c932ade211c8344f5e`. Rama `codex/compat1`. Trabajo solicitado por joan al continuar las mejoras; no es una asignación nueva inventada en el tablero. No depende del código de A14 ni DEV1: Claude puede revisar e integrar esta corrección primero.

## Criterios

- Cumplido localmente: ruta del modelo serializada con `as_posix()`; el contrato existente de `test_share_benchmark_never_writes_the_private_report` sigue siendo estricto.
- Cumplido localmente: un objeto de Git de solo lectura se reintenta dentro del proyecto; `test_project_cleanup.py` reproduce el callback de Windows y prueba también un árbol real. La comprobación de Windows CI sigue pendiente para esta rama.
- Cumplido localmente: si el sistema rechaza el borrado, la API responde 409 y conserva metadatos y conversaciones; un segundo intento puede terminar (`test_failed_delete_preserves_project_and_allows_retry`).
- Cumplido localmente: el diálogo muestra el error y vuelve a pedir confirmación; no emite un segundo DELETE ni guarda mientras el borrado está pendiente (`projectDelete.test.tsx`).
- Los resultados finales de Ruff, la suite Python, UTF-8 desactivado, Vitest, build y smoke se adjuntan en la sección automática del trabajador. Cualquier código no cero significa pendiente, no aceptación.

## Decisiones

- Fallos observados: PR #15, ejecución CI `40756236615`, job Windows `123055786418`, dos tests fallidos: `test_share_benchmark_never_writes_the_private_report` y `test_a_project_builds_in_its_own_folder_and_its_repository_is_not_one_of_its_files`. PR #14, ejecución `40754458583`, mismo par de fallos de Windows y timeout del smoke al enviar el segundo mensaje del chat ramificado.
- Se añadió una demora de transporte configurable al servidor **de pruebas**, después del evento SSE `done` y antes de EOF. Con 400 ms el smoke original falló de forma reproducible. El smoke corregido espera al control Enviar para enviar, reintentar, editar y navegar entre chats; conserva envío por Enter, conteos y comprobaciones originales. CI usa esa demora para cubrir la regresión. No cambia el protocolo ni la ejecución del chat de producción.
- El cliente MCP simulado implementa `close` para cerrar limpiamente. El smoke espera a que lleguen las opciones del proveedor antes de comprobar sus restricciones de escritorio, como las ramas A13/A14: no se cambian los permisos de escritorio.
- `shutil.rmtree` usa `onerror` por compatibilidad con Python 3.11. Solo un `PermissionError` de unlink/remove/rmdir permite añadir permiso de escritura al elemento dentro del proyecto y reintentar; otros fallos se propagan como `ProjectError`. No usa `ignore_errors=True`.
- El borrado valida también la ruta resuelta del proyecto: una junction de Windows que salga de la raíz no debe llegar a `rmtree`. Una prueba que emula esa resolución falló antes del guard y pasa después; no sustituye la prueba real de Windows.
- Se mantiene el contrato de confirmación de borrado. El informe y los cambios están en la copia del trabajador; no se toca la carpeta original, los modelos, el entrenamiento, el tablero ni STATUS/CHANGELOG. Sin nuevas dependencias ni llamadas a proveedores.

## Pendiente

- Revisión e integración de Claude. La CI de las ramas A14 y DEV1 no cambia por subir esta rama; tendrán que incorporar el arreglo al integrarse.
- Validación real en Windows mediante la CI de esta rama: los tests locales de callbacks de Windows no equivalen a ejecutar Windows.
- El borrado de archivos no es una transacción: si falla después de borrar algunos, no recupera esos archivos. Conserva metadatos y conversaciones para reintentar; no promete restauración. Los archivos que otra aplicación mantiene abiertos pueden seguir requiriendo cerrar esa aplicación.

## Tests

Antes del arreglo: las dos pruebas nuevas del diálogo fallaron (error no mostrado y solicitud duplicable); la simulación del objeto de Git dejaba el archivo sin borrar; el smoke con EOF retrasado agotó el tiempo de espera. Después: 75 pruebas enfocadas de proyectos, prototipos y ecosistema pasaron, además de las dos pruebas del diálogo y el build. La verificación completa final se adjunta abajo por el trabajador.

## STATUS.md

| Proyectos y compatibilidad | Rutas portables de benchmarks; borrado confirmado, objetos Git de solo lectura, error recuperable y smoke con EOF retrasado | `pytest -q tests/test_project_cleanup.py tests/test_projects.py tests/test_prototypes.py tests/test_ecosystem.py`; `cd web && npx vitest run`; CI e2e |

## CHANGELOG.md

- Serializar la ruta de modelo de los benchmarks con separadores portables.
- Reintentar el borrado de objetos Git de solo lectura y conservar el registro del proyecto y sus chats cuando la eliminación de archivos falla; mostrar el error y permitir un reintento confirmado.
- Esperar al final efectivo del envío en las pruebas de navegador y cubrir la carrera con demora de EOF en CI.

## Preguntas para Claude

Ninguna. Revisar e integrar antes de revalidar A14/DEV1, manteniendo sus bases y dependencias correspondientes.

## Verificación del trabajador

Ejecutado por el trabajador, fuera de Codex, el 2026-10-29T08:20:05Z.

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
....sssssssss.s......................................................... [ 47%]
........................................................................ [ 52%]
........................................................................ [ 56%]
........................................................................ [ 60%]
........................................................................ [ 65%]
........................................................................ [ 69%]
..................................ssss.................................. [ 73%]
........................................................................ [ 78%]
........................................................................ [ 82%]
........................................................................ [ 86%]
s....................................................................... [ 91%]
........................................................................ [ 95%]
........................................................................ [ 99%]
.....                                                                    [100%]
1641 passed, 22 skipped in 135.54s (0:02:15)
```

### `npx vitest run` (en `web/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
 ✓ src/parallel.test.ts  (11 tests) 4ms
 ✓ src/desktop.test.ts  (16 tests) 13ms
 ✓ src/visualChecks.test.ts  (2 tests) 43ms
 ✓ src/projectDelete.test.tsx  (2 tests) 24ms
 ✓ src/diagnostics.test.tsx  (2 tests) 29ms
 ✓ src/lab.test.tsx  (3 tests) 49ms
 ✓ src/chart.test.ts  (2 tests) 155ms
 ✓ src/apiError.test.ts  (2 tests) 2ms
 ✓ src/proof.test.tsx  (1 test) 15ms
 ✓ src/artifact.test.ts  (3 tests) 8ms

 Test Files  16 passed (16)
      Tests  84 passed (84)
   Start at  09:19:09
   Duration  935ms (transform 361ms, setup 0ms, collect 920ms, tests 365ms, environment 3.33s, prepare 498ms)
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
dist/assets/index-B5R2D1Ta.css                              47.01 kB │ gzip:   9.73 kB
dist/assets/isString-DCn3LAjH.js                             2.15 kB │ gzip:   1.09 kB
dist/assets/vega-interpreter-BAYmwApn.js                     5.11 kB │ gzip:   2.05 kB
dist/assets/index-BhpfY6kh.js                              262.83 kB │ gzip:  84.81 kB
dist/assets/vega.module-BJsxS-54.js                        524.51 kB │ gzip: 185.90 kB
dist/assets/index-DHQ-Wc2c.js                              618.93 kB │ gzip: 193.24 kB
✓ built in 1.22s
```

### `LC_ALL=C LANG=C .venv/bin/python -X utf8=0 -m pytest -q tests/test_project_cleanup.py tests/test_projects.py tests/test_prototypes.py tests/test_ecosystem.py`

- Código de salida: 0
- Últimas 15 líneas:

```text
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 10.87s
```

### `Browser smoke with SPIKE_E2E_STREAM_END_DELAY=0.4`

- Código de salida: 0
- Últimas 15 líneas:

```text
/Users/jpima/Downloads/Spike-codex/tests/fixtures/out/.team-qa/COMPAT1/20261029-091924
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
