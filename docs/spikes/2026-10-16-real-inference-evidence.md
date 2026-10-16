# Spike F0 — evidencia de ejecución real GGUF en CPU

**Fecha:** 2026-10-16. **Gate global:** **NO GO**. Todas las pruebas se efectuaron únicamente en el Mac de desarrollo (Apple M4 Max, **36 GiB**, macOS arm64) con `--n-gpu-layers 0`. **No son pruebas sobre el equipo CPU 16 GiB de §1.** GGUF/SHAs fijados en [manifest](2026-10-16-f0-model-artifacts.json); pesos locales excluidos del Git.

## Hallazgo técnico de runtime — S1

`llama-server` **b9430** (`d48a56eff`) **abortó con exit -6** al cargar un GGUF real de Qwen3.5-0.8B, SHA correcto:

- [FAIL normal](../../reports/phase0/cpu-bench-20261016T201632890388Z.json) en modo `--fit on`.
- [FAIL con `--fit off`](../../reports/phase0/cpu-bench-20261016T201709223052Z.json).
- Log privado local: `GGML_ASSERT(state->ne[0] == S_v)` en `ggml_gated_delta_net`, contexto recurrente. Causa exacta no demostrada; ni la tarjeta del modelo ni el SHA invalidan por sí mismos los pesos. Los archivos `.llama.log` contienen rutas del Mac, por privacidad permanecen fuera del Git.

Se actualizó Homebrew **llama.cpp 0.7.0**, build 11669 / commit `620d2225c` (con sus dependencias necesarias). No se cambiaron las bases seleccionadas ni se instaló software de pago. Con esta revisión, los mismos pesos Qwen3.5 cargan en CPU y sirven completions HTTP/SSE reales. Es **una mitigación verificada en el Mac**, no un gate en Linux CPU16.

## Ejecuciones reales verificables

Para cada ensayo: modelo GGUF existente con SHA256 contrastado con LFS oficial; servidor iniciado solo en loopback, `--n-gpu-layers 0`, `--ctx-size 2048`, ocho hilos, un slot y cero caché RAM; `--reasoning off` en el último grupo; cinco peticiones sintéticas de código conocido, sin datos del usuario, y RSS muestreado por proceso. Se registra fecha UTC, commit de Spike y estado `git_dirty`. Las salidas de los experimentos no constituyen evaluación estadística de dominio.

| Modelo / configuración | Referencia JSON | Qué se observó |
| --- | --- | --- |
| Qwen3.5-0.8B Q4, thinking habilitado por defecto | [primer servidor funcional](../../reports/phase0/cpu-bench-20261016T202045783676Z.json) | SSE real, pero sin texto visible en límite corto (los deltas pertenecían al canal de razonamiento); no válido como respuesta de usuario. |
| Qwen3.5-0.8B Q4, `--reasoning off` | [respuestas visibles](../../reports/phase0/cpu-bench-20261016T202149932148Z.json) | Cinco completions visibles reales, TTFT/duración/RSS medidos. |
| Qwen3.5-4B Q4, `--reasoning off` | [primer ensayo](../../reports/phase0/cpu-bench-20261016T202258052688Z.json) | Cinco completions reales; RAM de proceso y tiempos en Mac36. |
| Qwen3.5-4B + draft Qwen3.5-0.8B | [spec inicial](../../reports/phase0/cpu-bench-20261016T202407503531Z.json) | SSE/TTFT reales, diferencia de RSS observada; muestra pequeña. |
| Qwen3.5-4B Q4 sin draft desde `make bench` | [baseline](../../reports/phase0/cpu-bench-20261016T202454264439Z.json) | Cinco completions reales, con conteo de tokens del servidor si disponible. |
| Qwen3.5-4B + draft Qwen3.5-0.8B desde `make bench` | [spec repetido](../../reports/phase0/cpu-bench-20261016T203008648269Z.json) | Cinco completions reales con `usage.completion_tokens` del SSE y latencias. |

### Comparación S7: observación, NO prueba de aceleración

Los hashes de texto visible de los cinco pares baseline/spec coinciden. **Las duraciones observadas con speculative no superaron a las del baseline en estos ensayos**. La memoria RSS observada cambió mucho entre repeticiones y tampoco sirve para atribuir diferencia causal. Descargas externas en paralelo, presión de memoria, calentamiento y CPU scheduling son confundidores; se precisan A/B alternados con servidores revisados, múltiples repeticiones bajo carga controlada, contexto fijo, conteo de tokens comparable y objetivo CPU16. No activar speculative en producto ni declarar aceleración por estos datos. El Plan B es **servir sin speculative** si se confirma ausencia de beneficio.

### S1 — control Gemma 4 E4B base vs instruction-tuned

La primera cuantización candidata `mradermacher/gemma-4-E4B-GGUF` deriva de `google/gemma-4-E4B` **base**, sin ajuste de instrucciones. El ensayo real [Gemma base](../../reports/phase0/cpu-bench-20261016T203246764286Z.json) respondió de forma inconsistente a las cinco instrucciones de prueba y llegó a errar una multiplicación sencilla. Esto **no es una comparativa justa de calidad** contra Qwen3.5 preparado para chat. Tras comprobar su SHA y archivar el JSON se eliminó únicamente el GGUF base descargado en esta ejecución para liberar espacio. Se identificó `mradermacher/gemma-4-E4B-it-GGUF` con SHA oficial diferenciado para comparación posterior. Ninguno de los dos ensayos (incluso cuando se complete el instruct) sustituye una evaluación S1 autorizada en 16 GiB.

**Gemma 4 E4B-it sí se ensayó después.** El GGUF instruction-tuned `mradermacher/gemma-4-E4B-it-GGUF` (Git `0c4da2b7f0f73effb8c8dd194da2f8d58680125a`, SHA-256 de archivo `e5555564868766605415f0e1401feac79c9327333c051521934c90aea67df897`, Apache-2.0 publicada) se descargó, verificó y generó cinco completions reales en CPU. Se comparó con Qwen3.5-4B Q4 en el mismo Mac con prompts sintéticos idénticos, ocho hilos, contexto 2048 y razonamiento apagado. Esta muestra no está aleatorizada y no constituye evaluación con IC ni evidencia de hardware 16 GiB.

| S1: cinco solicitudes de diagnóstico con `make bench` | Qwen3.5-4B Q4 | Gemma 4 E4B-it Q4 |
| --- | ---: | ---: |
| Fuente | [JSON](../../reports/phase0/cpu-bench-20261016T202454264439Z.json) | [JSON](../../reports/phase0/cpu-bench-20261016T204406396649Z.json) |
| TTFT mediana | 276.876 ms | 355.517 ms |
| Duración total mediana | 537.242 ms | 799.688 ms |
| RSS pico muestreado del proceso | 5,852,397,568 bytes | 4,784,832,512 bytes |

**Interpretación limitada:** Qwen registró menor latencia en estas cinco peticiones; Gemma-it registró menor RSS muestreado. La prueba no controla completamente la presión de memoria o temperatura del Mac, ni compensa longitudes de respuestas diferentes. Ambos produjeron la respuesta correcta al cálculo 17 × 23. Ningún criterio de calidad general ni la RAM de la máquina objetivo está certificado. **S1 permanece NO GO**.

### S7 — modelos de embeddings en CPU

El candidato multilingüe `cstr/multilingual-e5-small-GGUF` SHA verificado **no cargó** en llama.cpp 0.7.0: [JSON de error](../../reports/phase0/embedding-smoke-20261016T204042799135Z.json) y log local `bert model needs to define token type count`. Ese error no demuestra que la arquitectura E5 sea inviable con otros conversores o revisiones.

El candidato oficial `nomic-ai/nomic-embed-text-v1.5-GGUF` Q4_K_M SHA verificado **sí cargó en CPU**: [JSON real](../../reports/phase0/embedding-smoke-20261016T204140962247Z.json). Produjo tres vectores de 768 dimensiones. La mayor similitud observada entre dos preguntas financieras que entre finanzas y código es únicamente un diagnóstico de interfaz y dimensión, **no un test de ≥300 ejemplos ni validación multilingüe es/ca/en**. Nomic no reemplaza por decisión automática al modelo embedding multilingüe previsto; elegir y validar ese modelo sigue siendo un gate abierto.

### Resultados que NO se han demostrado

- S1: existe comparación exploratoria real Qwen/Gemma 4 E4B-**it** en el mismo Mac, pero faltan evaluación de calidad autorizada con confianza estadística y el equipo objetivo CPU 16 GiB.
- S2: no hay LoRAs 4B entrenados/cargados, ni conmutaciones reales ≤500 ms ni test de contaminación con cachés; [instrumentación](2026-10-16-s2-readiness.md) preparada.
- S3: MLX-LM no se encontró en Python inspeccionado; ninguna LoRA entrenada/exportada. El generador determinista de fixtures de 200 ejemplos es **NO TRAIN** por procedencia de plantillas redactadas con asistente; no sirve como dataset lícito de fine-tuning sin dictamen independiente.
- S4: políticas/derechos y detector de near-duplicates [documentados](2026-10-16-s4-readiness.md), pero faltan corpus licenciados, profesor local auditado de tamaño planificado y ejecución real de descontaminación.
- S5: REA no activado ni usado con objetivos autorizados; specs originales ya existen, sin evidencia de observación.
- S6: nombre Spike definitivamente elegido; marca y disponibilidad externas no certificadas.
- S7: no hay validación de routing embeddings CPU en ≥300 prompts, top-3 más Planner o 16 GiB; speculative no ha acreditado ganancia.

**En ningún caso estas medidas equivalen a una v1.0**, ni permiten pasar a F1 sin cerrar el gate técnico y obtener la aprobación exigida.

## Cómo reproducir con pesos previamente disponibles

```bash
cd ~/Downloads/spike
make test
make preflight
make bench BENCH_MODEL=models/qwen35/Qwen3.5-4B-Q4_K_M.gguf \
  BENCH_SHA256=00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4 \
  BENCH_REPOSITORY=unsloth/Qwen3.5-4B-GGUF \
  BENCH_REVISION=e87f176479d0855a907a41277aca2f8ee7a09523 BENCH_RUNS=5
```

El `Makefile` invoca `run_cpu_benchmark.py` con modelo local, compara el checksum antes de abrir el servidor y lo detiene siempre al acabar. Los informes se almacenan en `reports/phase0/`. Si no existe un modelo, no hay backend, falla el hash o se supera el tiempo, el comando sale distinto de cero y registra `FAIL`. Las comprobaciones en CPU16 deberán repetirse y no heredan automáticamente el PASS del Mac36.
