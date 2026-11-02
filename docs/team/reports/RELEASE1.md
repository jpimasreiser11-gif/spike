# RELEASE1: inventario de alcance y comprobación offline del lanzamiento

## Resumen

Entrega solicitada por Joan para ejecutar el plan de completar, comprobar y preparar SPIKE. Añade un inventario v1 con
120 referencias de conversación/requisitos agrupadas en 98 funciones (95 de lanzamiento, dos excluidas y monetización
aplazada), recorridos concretos por plataforma, registro de pruebas y un comprobador offline con informes JSON,
Markdown y HTML consultable. Los resultados simulados y los checks de otra revisión no acreditan el candidato.
Incluye diagnóstico de coordinación para Claude/Gemini y borradores de posicionamiento, campaña orgánica de 30 días y
monetización Community + Pro opcional + servicios. No se publica ni se modifica el tablero o los criterios de modelos.

## Criterios

- Cumplido: todas las 60 ideas y las propuestas anteriores se conservan con fuentes; `test_committed_catalog...` y
  validación estructural rechazan referencias desconocidas o sin mapear.
- Cumplido: críticos exigen tres ejecuciones reales independientes por plataforma, mismo candidato/modelo/configuración;
  tests rechazan simulaciones, commits viejos, repetición de artefactos, cambio de configuración y fallo posterior.
- Cumplido: hashes, rutas acotadas sin symlinks, límites y revisión posterior por Claude/Joan; no invoca comandos,
  proveedores ni publicaciones. Pruebas de integridad y aprobación caducada/negativa.
- Cumplido: HTML offline accesible con búsqueda, filtro, tabla desplazable y contenido escapado; smoke Chromium usa
  teclado y viewport móvil, cero peticiones externas. Es una herramienta de revisión del equipo, no una pantalla de SPIKE.
- Cumplido: coordinación, propuesta económica y calendario preparado con fuentes oficiales; no se contrató ni publicó.
- No cumplido globalmente: producto terminado, entrenamientos aceptados, todas las PR integradas, instaladores finales
  con pesos, vídeos definitivos ni recorridos completos reales. Esos requisitos siguen visibles en el inventario.

## Decisiones

Rama apilada sobre COMPAT1 (`9072c7059c3a5c23f6140fdc49089d9ddc8a0699`) para conservar la corrección Windows ya probada.
PR base `codex/compat1`; integrar COMPAT1 primero. No nuevos paquetes ni cambios de runtime. `evidence.json` empieza
vacío: no convertir pruebas históricas ni simuladas en aprobaciones de un candidato que aún no está integrado.
Los registros prueban coherencia e integridad, no autenticidad. Los aprobadores humanos contrastan las fuentes.
El catálogo es trazabilidad del alcance, no autoridad de asignación; el tablero de Claude sigue siendo la referencia.

## Pendiente

Claude: revisar esta entrega, reconciliar PR/tablero y confirmar decisiones de alcance. Medicina sigue en preparación
sin logs nuevos desde el 26; diagnóstico y reanudación corresponden a Claude en el Mac. No se tocó entrenamiento.
Gemini: entregar G1 para revisión antes de continuar G2; revisión visual y de errores sobre la versión integrada.
Capturas del producto, narración y render final esperan candidato probado, revisión de licencias y recursos disponibles.
Joan mantiene aprobación final y publicación. El plan de campaña no es una automatización activa.

## Tests

Tests escritos primero: fallaron al importar el módulo inexistente; luego 43 pruebas específicas pasaron. El worker
adjunta abajo los resultados completos de esta entrega, incluido modo no UTF-8 y smoke offline del informe.

## STATUS.md

| Preparación de lanzamiento (RELEASE1): inventario versionado, 120 referencias / 98 funciones, recorridos y gate offline; críticos con tres repeticiones, hashes y revisiones; informe HTML consultable | Tests de estructura, resultados simulados/antiguos, fallos, artefactos y decisiones; navegador offline. No acredita todavía un lanzamiento real | `pytest tests/test_release_readiness.py`; `python scripts/release/readiness.py check --revision <SHA>` |

## CHANGELOG.md

- Añadido inventario y comprobador offline de evidencia de lanzamiento con reportes JSON/Markdown/HTML, rechazo de
  evidencias insuficientes y seguimiento explícito de promesas, exclusiones y decisiones pendientes.
- Preparados coordinación de integraciones/medicina, calendario orgánico y estudio inicial de oferta sin publicar ni cobrar.

## Preguntas para Claude

Confirmar asignación/alcance de Device Lab, Reverse Studio y Visual Workflow Builder, conservados como promesas pendientes.
Revisar propuestas económicas; sus precios son hipótesis de entrevistas y no una oferta aprobada.

## Verificación del trabajador

Ejecutado por el trabajador, fuera de Codex, el 2026-10-29T13:48:46Z.

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
....sssssssss.s......................................................... [ 46%]
........................................................................ [ 50%]
........................................................................ [ 54%]
........................................................................ [ 59%]
........................................................................ [ 63%]
........................................................................ [ 67%]
........................................................................ [ 71%]
.....ssss............................................................... [ 76%]
........................................................................ [ 80%]
........................................................................ [ 84%]
...........................................s............................ [ 88%]
........................................................................ [ 92%]
........................................................................ [ 97%]
................................................                         [100%]
1684 passed, 22 skipped in 124.41s (0:02:04)
```

### `npx vitest run` (en `web/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
 ✓ src/mcpApp.test.ts  (3 tests) 8ms
 ✓ src/visualChecks.test.ts  (2 tests) 43ms
 ✓ src/parallel.test.ts  (11 tests) 4ms
 ✓ src/projectDelete.test.tsx  (2 tests) 28ms
 ✓ src/diagnostics.test.tsx  (2 tests) 18ms
 ✓ src/lab.test.tsx  (3 tests) 53ms
 ✓ src/chart.test.ts  (2 tests) 230ms
 ✓ src/apiError.test.ts  (2 tests) 2ms
 ✓ src/proof.test.tsx  (1 test) 15ms
 ✓ src/artifact.test.ts  (3 tests) 7ms

 Test Files  16 passed (16)
      Tests  84 passed (84)
   Start at  14:48:41
   Duration  1.08s (transform 480ms, setup 0ms, collect 984ms, tests 439ms, environment 5.22s, prepare 585ms)
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
✓ built in 1.18s
```

### `non-UTF-8 release tests`

- Código de salida: 0
- Últimas 15 líneas:

```text
...........................................                              [100%]
43 passed in 0.07s
```

### `catalog structure and source coverage`

- Código de salida: 0
- Últimas 15 líneas:

```text
Valid / Valido: source coverage and record structure
```

### `generate HTML review report`

- Código de salida: 0
- Últimas 15 líneas:

```text

```

### `offline browser report smoke`

- Código de salida: 0
- Últimas 15 líneas:

```text
RELEASE REPORT E2E OK: 98 rows, filters, keyboard, mobile scroll, no external requests
```

### `git diff --check`

- Código de salida: 0
- Últimas 15 líneas:

```text

```

Resultado: todo en verde.

<!-- fin de la verificación del trabajador -->
