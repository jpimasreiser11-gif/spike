# COMPAT2: pruebas de Forge compatibles con el directorio temporal aislado

## Resumen

Corrige dos pruebas de Forge que deducían la ejecución del import buscando un marcador en el `/tmp` del host.
Bubblewrap crea un `/tmp` privado: que el fichero no aparezca fuera no demuestra que el import haya fallado.
La prueba ahora observa la salida del subproceso Python real y mantiene las comprobaciones de permisos, resultados,
no ejecución de `__main__` y ausencia de archivos de prueba en el proyecto. No cambia código de producción,
configuración de aislamiento ni criterios de aceptación. Base `codex/compat1`, commit
`9072c7059c3a5c23f6140fdc49089d9ddc8a0699`; Claude conserva revisión e integración.

## Criterios

- met local — los archivos válidos pasan, no vuelven al especialista y el import real imprime exactamente
  `SPIKE_IMPORT_OK`; si se ejecutara `__main__`, aparecería otro marcador y la prueba fallaría.
- met local — `allow_once` ejecuta un único subproceso real; denegación interactiva, política deny y headless
  no llaman a `PythonRunner.run`; se mantienen las razones originales de comprobación incompleta.
- met local — el proyecto conserva solo sus entregables, sin `scratch.txt` ni marcadores añadidos.
- pending — CI Linux/Windows/macOS sobre esta rama. El Mac no proporciona un sandbox funcional en este entorno;
  las cuatro pruebas que requieren aislamiento real se omiten explícitamente, no se declaran superadas.

## Decisiones

Evidencia de origen: PR #19, head `e61f534e3dcf9d35b7ea45b45a7f1c1da62760c7`, ejecución `40957611527`.
Linux 3.13, job `123741665909`: `2 failed, 1692 passed, 14 skipped`; fallan solamente
`test_files_that_pass_are_reported_as_passed_and_not_sent_back` y la variante permitida de
`test_nothing_is_imported_without_the_permission_the_python_tool_needs`. Los checks de programa ya indicaban éxito;
la aserción fallida era que el marcador existiera en el host. Linux 3.11 también terminó en fallo según la CI,
pero este diagnóstico usa el log inspeccionado de 3.13.

Windows de la misma ejecución, job `123741665787`: `2 failed, 1603 passed, 103 skipped`; son los fallos de rutas
portables y borrado de objetos Git ya corregidos por COMPAT1. Por eso esta entrega se apila sobre COMPAT1 y no
repite sus cambios. El test de Forge conserva el aislamiento automático y la ejecución verdadera; el observador
solo registra el retorno de la función original. No usa un resultado falso, no apaga el sandbox y no añade skips.

La primera aproximación buscó eventos `tool_result` públicos, pero el import de verificación transmite permisos
y conserva internamente el resultado; ese intento falló en cinco casos locales. Se observa el retorno real de la
herramienta sin cambiar eventos ni API de producción. Diagnóstico siguiendo Error Resolver; etiqueta de resolución:
`pytest-forge-private-tmp-marker`. No se envían datos ni se ejecutan modelos, entrenamiento o herramientas nuevas.

## Pendiente

CI de esta rama y revisión de Claude. Incorporar COMPAT1/COMPAT2 al revisar I1/I2 y las demás ramas afectadas.
Esta corrección no demuestra calidad superior de Forge ni valida el instalador nativo: siguen pendientes las pruebas
comparativas y el dispatch de I2. El objetivo completo de SPIKE permanece activo; el tablero no se marca terminado.

## Tests

```text
.venv/bin/python -m pytest -q tests/test_forge.py tests/test_sandbox.py
96 passed, 4 skipped in 5.03s

LC_ALL=C LANG=C .venv/bin/python -X utf8=0 -m pytest -q tests/test_forge.py
62 passed in 2.44s

.venv/bin/ruff check .
All checks passed!
```

La suite completa y la entrega quedan registradas por el trabajador debajo.

## STATUS.md

| Verificación de Forge y aislamiento | Importación real comprobada por stdout, sin exigir archivos en el `/tmp` del host; permisos y copia del proyecto conservados | `pytest -q tests/test_forge.py tests/test_sandbox.py`; CI Linux/macOS/Windows |

## CHANGELOG.md

- Corrige la observación de los imports en las pruebas de Forge para soportar el `/tmp` privado del sandbox de Linux;
  mantiene ejecución real, permisos, comprobación de `__main__` y preservación del proyecto, sin cambios de runtime.

## Preguntas para Claude

Ninguna. Revisar después de COMPAT1 e incorporar ambas correcciones al validar las ramas dependientes.

## Verificación del trabajador

Ejecutado por el trabajador, fuera de Codex, el 2026-10-30T09:20:31Z.

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
1641 passed, 22 skipped in 131.99s (0:02:11)
```

### `npx vitest run` (en `web/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
 ✓ src/mcpApp.test.ts  (3 tests) 9ms
 ✓ src/parallel.test.ts  (11 tests) 5ms
 ✓ src/desktop.test.ts  (16 tests) 13ms
 ✓ src/diagnostics.test.tsx  (2 tests) 18ms
 ✓ src/projectDelete.test.tsx  (2 tests) 35ms
 ✓ src/lab.test.tsx  (3 tests) 64ms
 ✓ src/chart.test.ts  (2 tests) 226ms
 ✓ src/apiError.test.ts  (2 tests) 2ms
 ✓ src/proof.test.tsx  (1 test) 15ms
 ✓ src/artifact.test.ts  (3 tests) 8ms

 Test Files  16 passed (16)
      Tests  84 passed (84)
   Start at  10:20:21
   Duration  1.13s (transform 479ms, setup 0ms, collect 1.04s, tests 456ms, environment 5.47s, prepare 590ms)
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

### `Forge/sandbox, UTF-8 disabled`

- Código de salida: 0
- Últimas 15 líneas:

```text
........................................................................ [ 72%]
........................ssss                                             [100%]
96 passed, 4 skipped in 5.24s
```

### `git diff --check`

- Código de salida: 0
- Últimas 15 líneas:

```text

```

Resultado: todo en verde.

<!-- fin de la verificación del trabajador -->
