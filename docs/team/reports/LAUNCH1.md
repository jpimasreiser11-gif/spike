# LAUNCH1: proyecto Remotion separado y diez referencias de montaje

## Resumen

Entrega pedida por Joan: proyecto audiovisual editable en `marketing/video`, separado del motor. Registra 25
composiciones: master de 180 s horizontal 1080p, variante de textos/subtítulos EN con voz ES, promos 30/60 s, vertical
30 s, diez clips de 10 s y diez stills. Guiones y prompts de dirección por escena, voz larga y corta separadas,
subtítulos ES/EN, etiquetas de visión/aceleración y preflight offline. Se han generado diez referencias PNG y una
previsualización vertical; son composiciones de montaje con huecos explícitos para capturas, no pantallas verificadas.

## Criterios

- Cumplido: fuente Remotion compilable, 25 composiciones reconocidas por el motor con resolución y duración previstas.
- Cumplido: diez referencias renderizadas individualmente y galería local; cactus original copiado sin modificar,
  fuentes locales y colores de identidad. Inspección visual de inicio, Dev, cierre y vertical.
- Cumplido: subtítulos provisionales exportables (26 SRT), guion español y traducción inglesa; textos cortos propios para
  clips y promociones, sin acelerar narración larga. No hay voz final grabada.
- Cumplido: tests de duración, cobertura de capítulos, paths, estado de evidencia, metadatos y aprobación; el preflight
  final rechaza correctamente el material actual por falta de capturas, voz, tiempos definitivos y revisión de licencia.
- Cumplido: dependencias aisladas y fijadas; `marketing` fuera del sdist y del runtime de SPIKE. Avisos en THIRD_PARTY.
- No cumplido aún: master final, diez vídeos completos, voz de producción, sincronización fina, tutorial grabado,
  demos de candidato integrado ni revisión humana completa de todos los clips. No se publica ni activa servicio.

## Decisiones

Apilada sobre RELEASE1 (#17), base `b85b41156c74ab97204b317fc7739a21e93f1f9d`. Todas las escenas empiezan como visión
hasta tener evidencia del candidato. La última escena cierra con identidad e invitación a conocer el proyecto, sin
premios, rankings, métricas o funciones falsamente demostradas. Remotion es una herramienta externa de producción,
expresamente solicitada, no una dependencia nueva de la app. No se compró licencia ni servicio.

El preflight valida metadatos y hashes; no decodifica ni verifica duraciones físicas de los medios. La revisión exige
medirlos y reproducir completos los resultados. Ninguna marca de revisión es una firma ni sustituye aprobación de Joan.
Solo se renderizaron fotogramas ligeros de previsualización, sin lanzar un render largo concurrente con medicina.

## Pendiente

Claude: revisión e integración primero de COMPAT1 y RELEASE1. Seleccionar candidato y evidencias para cada captura.
Gemini: revisar legibilidad, controles, estados y subtítulos de la interfaz final. Mac: grabar recorridos reales cuando
medicina deje recursos disponibles. Producción: incorporar audio, capturas, tiempos reales y derechos; reproducción
completa de todas las salidas antes de pedir a Joan autorización de publicación. El calendario está en RELEASE1.

## Tests

Tests de timeline escritos primero fallaron por módulo ausente; 15 pruebas de Node pasan tras implementación.
TypeScript, preflight de borrador, bundle, 25 composiciones y generación de diez PNG pasaron localmente.
Construido sdist real con hatchling 1.33.0 (backend ya declarado, aislado en salida de pruebas): sin `marketing/`. El worker
adjunta las comprobaciones finales de código/app y producción. El rechazo de `--final` es el resultado esperado.

## STATUS.md

| Preparación audiovisual LAUNCH1: proyecto Remotion separado, 25 composiciones, diez referencias, guiones/prompts y subtítulos ES/EN | Tests de timeline/preflight, TypeScript, bundle y listado real de composiciones; diez PNG de montaje generados. Sin voz/capturas/vídeo final | `cd marketing/video && npm test && npm run check && npm run preflight` |

## CHANGELOG.md

- Preparado proyecto de producción Remotion independiente con master, diez clips/referencias, promos y vertical;
  guiones, instrucciones de captura, subtítulos provisionales y validación de medios antes del render final.

## Preguntas para Claude

Ninguna que impida revisar esta entrega. Materiales y validación del candidato siguen pendientes del orden acordado.

## Verificación del trabajador

Ejecutado por el trabajador, fuera de Codex, el 2026-10-29T15:38:37Z.

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
1684 passed, 22 skipped in 128.52s (0:02:08)
```

### `npx vitest run` (en `web/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
 ✓ src/parallel.test.ts  (11 tests) 4ms
 ✓ src/mcpApp.test.ts  (3 tests) 14ms
 ✓ src/desktop.test.ts  (16 tests) 14ms
 ✓ src/projectDelete.test.tsx  (2 tests) 26ms
 ✓ src/diagnostics.test.tsx  (2 tests) 20ms
 ✓ src/lab.test.tsx  (3 tests) 56ms
 ✓ src/chart.test.ts  (2 tests) 226ms
 ✓ src/apiError.test.ts  (2 tests) 2ms
 ✓ src/proof.test.tsx  (1 test) 15ms
 ✓ src/artifact.test.ts  (3 tests) 7ms

 Test Files  16 passed (16)
      Tests  84 passed (84)
   Start at  16:38:28
   Duration  1.10s (transform 457ms, setup 0ms, collect 1.03s, tests 447ms, environment 5.04s, prepare 576ms)
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
✓ built in 1.23s
```

### `npm test (video)` (en `marketing/video/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
> spike-launch-video@0.1.0 test
> node --test test/*.test.mjs

✔ ten chapters fill 180 seconds at 30 fps exactly (0.772209ms)
✔ promo30: no gaps, no overlap and correct duration (0.070541ms)
✔ promo60: no gaps, no overlap and correct duration (0.039792ms)
✔ vertical30: no gaps, no overlap and correct duration (0.046125ms)
✔ scene01: no gaps, no overlap and correct duration (0.040458ms)
✔ scene10: no gaps, no overlap and correct duration (0.0405ms)
✔ unknown variants do not silently produce a different video (0.072416ms)
✔ asset paths must be local and portable (0.065875ms)
✔ draft subtitles are ordered and bounded for both languages and variants (0.9285ms)
✔ publication preflight refuses missing footage and unreviewed narration (0.119667ms)
✔ verified claim requires candidate and evidence; captions and voice cannot overrun (0.195083ms)
✔ invalid source structure, duplicate IDs and remote paths fail (0.165875ms)
✔ promo final preflight checks its own clip narration, not the master track (0.049291ms)
✔ every chapter points to real inventory IDs and keeps separate clip copy (0.375583ms)
✔ text flags do not count as editorial approval and empty voice copy is rejected (0.081584ms)
ℹ tests 15
ℹ suites 0
ℹ pass 15
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 89.626666
```

### `TypeScript (video)` (en `marketing/video/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
> spike-launch-video@0.1.0 check
> tsc --noEmit
```

### `Bundle (video)` (en `marketing/video/`)

- Código de salida: 0
- Últimas 15 líneas:

```text
> spike-launch-video@0.1.0 bundle
> remotion bundle src/index.tsx --out-dir=out/bundle

Bundling 6%
Bundling 19%
Bundling 64%
Bundling 70%
Bundling 75%
Bundling 80%
Bundling 85%
Bundling 91%
Bundling 98%
○ /Users/jpima/Downloads/Spike-codex/marketing/video/out/bundle
```

### `Production checks; final preflight must refuse incomplete media`

- Código de salida: 0
- Últimas 15 líneas:

```text
DRAFT PREFLIGHT OK: placeholder capture, no final audio; not ready for release

license: eligibility review missing
captions: timing review missing
01: capture: missing reviewed media
01: voice: master audio not reviewed
01: captions: es must have locked timings
01: captions: en must have locked timings
02: capture: missing reviewed media
02: voice: master audio not reviewed
02: captions: es must have locked timings
02: captions: en must have locked timings
03: capture: missing reviewed media
03: voice: master audio not reviewed
03: captions: es must have locked timings
03: captions: en must have locked timings
04: capture: missing reviewed media
04: voice: master audio not reviewed
04: captions: es must have locked timings
04: captions: en must have locked timings
05: capture: missing reviewed media
05: voice: master audio not reviewed
05: captions: es must have locked timings
05: captions: en must have locked timings
06: capture: missing reviewed media
06: voice: master audio not reviewed
06: captions: es must have locked timings
06: captions: en must have locked timings
07: capture: missing reviewed media
07: voice: master audio not reviewed
07: captions: es must have locked timings
07: captions: en must have locked timings
08: capture: missing reviewed media
08: voice: master audio not reviewed
08: captions: es must have locked timings
08: captions: en must have locked timings
09: capture: missing reviewed media
09: voice: master audio not reviewed
09: captions: es must have locked timings
09: captions: en must have locked timings
10: capture: missing reviewed media
10: voice: master audio not reviewed
10: captions: es must have locked timings
10: captions: en must have locked timings

Wrote 26 SRT files. Draft timing is not synchronized final narration.

Bundling code        ━                  6%
Bundling code        ━━━                19%
Bundling code        ━━━━━━━━━╸         54%
Bundling code        ━━━━━━━━━━━╸       65%
Bundling code        ━━━━━━━━━━━━╸      71%
Bundling code        ━━━━━━━━━━━━━╸     76%
Bundling code        ━━━━━━━━━━━━━━╸    81%
Bundling code        ━━━━━━━━━━━━━━━╸   87%
Bundling code        ━━━━━━━━━━━━━━━━╸  92%
Bundling code        ━━━━━━━━━━━━━━━━━╸ 98%
Bundling code        ━━━━━━━━━━━━━━━━━━ 100%
Bundled code         ━━━━━━━━━━━━━━━━━━ 482ms

The following compositions are available:

Spike-Master                30      1920x1080      5400 (180.00 sec)
Spike-Master-EN-Captions    30      1920x1080      5400 (180.00 sec)
Spike-30                    30      1920x1080      900 (30.00 sec)
Spike-60                    30      1920x1080      1800 (60.00 sec)
Spike-Vertical-30           30      1080x1920      900 (30.00 sec)
Spike-Scene-01              30      1920x1080      300 (10.00 sec)
Spike-Scene-02              30      1920x1080      300 (10.00 sec)
Spike-Scene-03              30      1920x1080      300 (10.00 sec)
Spike-Scene-04              30      1920x1080      300 (10.00 sec)
Spike-Scene-05              30      1920x1080      300 (10.00 sec)
Spike-Scene-06              30      1920x1080      300 (10.00 sec)
Spike-Scene-07              30      1920x1080      300 (10.00 sec)
Spike-Scene-08              30      1920x1080      300 (10.00 sec)
Spike-Scene-09              30      1920x1080      300 (10.00 sec)
Spike-Scene-10              30      1920x1080      300 (10.00 sec)
Spike-Reference-01                  1920x1080      Still
Spike-Reference-02                  1920x1080      Still
Spike-Reference-03                  1920x1080      Still
Spike-Reference-04                  1920x1080      Still
Spike-Reference-05                  1920x1080      Still
Spike-Reference-06                  1920x1080      Still
Spike-Reference-07                  1920x1080      Still
Spike-Reference-08                  1920x1080      Still
Spike-Reference-09                  1920x1080      Still
Spike-Reference-10                  1920x1080      Still

Reference 01: PNG exists, 299186 bytes
Reference 02: PNG exists, 294643 bytes
Reference 03: PNG exists, 290049 bytes
Reference 04: PNG exists, 298002 bytes
Reference 05: PNG exists, 303263 bytes
Reference 06: PNG exists, 302242 bytes
Reference 07: PNG exists, 299772 bytes
Reference 08: PNG exists, 295591 bytes
Reference 09: PNG exists, 294944 bytes
Reference 10: PNG exists, 306460 bytes
SDIST OK: 724 entries, separate production project excluded
LAUNCH CHECKS OK: 25 compositions, 10 reference PNGs, 26 draft SRTs, final preflight correctly blocked
```

### `git diff --check`

- Código de salida: 0
- Últimas 15 líneas:

```text

```

Resultado: todo en verde.

<!-- fin de la verificación del trabajador -->
