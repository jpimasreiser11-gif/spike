# Spike — auditoría de compatibilidad de modelos, inferencia y LoRA (temas relevantes para S1–S4 y S7)

**Fecha de corte:** 2026-10-16 · **Fase:** 0 / preparación · **Dictamen global:** **FAIL / NO GO** para Fase 1.

> **Actualización documental:** el Plan Maestro íntegro está ahora versionado como [PLAN.md](../../PLAN.md), con S1–S7 definidos literalmente en §14. La tabla inmediatamente inferior conserva las **agrupaciones técnicas históricas**, que no equivalen a los IDs normativos de los spikes: S1 = comparación Qwen3.5-4B/Gemma4 E4B; S2 = multi-LoRA y cambio ≤500 ms; S3 = MLX ~200 ejemplos → GGUF LoRA → serving; S4 = licencia, profesor local y descontaminación; S5 = UX/REA; S6 = nombre y marca; S7 = speculative 0.8B y routing embeddings CPU. Usar [matriz corregida](2026-10-16-phase0-gate-matrix.md) como gate. Esta auditoría inicial fue de solo lectura; no descargó pesos ni entrenó adaptadores.

## Resumen ejecutivo y gates

| Área | Evidencia positiva confirmada | Bloqueo para dar PASS de implementación | Gate |
| --- | --- | --- | --- |
| **Investigación A · Licencia y arquitectura** | Los repositorios **Qwen/Qwen3.5-4B** y **Qwen/Qwen3.5-0.8B** publican **Apache-2.0** y configuración `qwen3_5`; son VLM densos con atención híbrida. | Fijar SHA de pesos y GGUF finales; comparar con Gemma 4 E4B según S1. | **PARCIAL DOCUMENTAL** |
| **Investigación B · GGUF y runtime** | Hay GGUF Q4_K_M de Unsloth de 2,74 GB (4B) y 533 MB (0,8B), y `llama-server` local declara funciones adecuadas. | No existe prueba de carga, calidad, latencia, estabilidad ni consumo de la **máquina CPU de 16 GB**. | **NOT RUN** |
| **Investigación C · Multi-LoRA y aislamiento** | `llama-server` documenta varios adaptadores, escalas por petición y `GET/POST /lora-adapters`. | Incidencias KV/cache; S2 exige cero contaminación y cambio ≤500 ms con LoRAs reales. | **NOT RUN (riesgo crítico)** |
| **Investigación D · Fine-tuning y memoria** | MLX-LM tiene `qwen3_5.py`; Unsloth documenta LoRA bf16 para ambos tamaños. | Falta S3 entrenamiento ~200 ejemplos, exportación y recarga real. | **NOT RUN** |

**Decisión de Fase 0:** **GO para seguir investigando, diseñando ensayos y preparando gates; NO GO para pasar a Fase 1**, publicar especialistas o declarar requisitos satisfechos. La fuente íntegra ya está disponible; la aprobación explícita de Joan y las mediciones reales siguen pendientes.

## Evidencia local reproducible: Mac de desarrollo

Comprobado **2026-10-16**, en lectura, desde `/downloads/spike`:

| Dato | Salida observada |
| --- | --- |
| Sistema | `uname -sm` → `Darwin arm64`; `system_profiler SPHardwareDataType` → **Mac Studio, Apple M4 Max, 36 GB** |
| RAM visible | `sysctl -n hw.memsize` → `38654705664` bytes, **36 GiB** |
| CPU | `sysctl -n hw.physicalcpu hw.logicalcpu` → `14` / `14` |
| Runtime presente | `/opt/homebrew/bin/llama-server` y `llama-cli` |
| Versión del binario | `llama-server --version` → `version: 9430 (d48a56eff)`, AppleClang 21.0.0 |
| Flags comprobadas por `--help` | `--lora`, `--lora-scaled`, `--lora-init-without-apply`, `--cache-ram`, `--no-cache-prompt`, `--parallel`, `--mmproj`, `--ctx-size` |
| Paquetes inspeccionados | En **`/usr/bin/python3`**: no constan `mlx`, `mlx-lm`, `unsloth`, `transformers`, `peft` ni `llama-cpp-python`; sí `torch 2.8.0`. Este resultado **no descarta** entornos virtuales ajenos. |
| Máquina objetivo | **16 GB RAM, sin GPU dedicada**: no conectada ni medida en este encargo. |

Comandos de diagnóstico read-only replicables:

```bash
uname -sm
llama-server --version
llama-server --help | grep -E 'lora|spec-draft-model|cache-prompt|cache-ram|mmproj'
# macOS:
sysctl -n hw.memsize hw.physicalcpu hw.logicalcpu
system_profiler SPHardwareDataType
# Linux 16 GB:
free -h
uname -m
command -v llama-server
python3 -m pip show mlx mlx-lm unsloth transformers peft
```

El último `pip show` puede terminar con código distinto de cero si faltan paquetes; es un resultado informativo, no un fallo operativo.

### Scripts reproducibles de preparación S2–S4 (incorporados posteriormente)

Los scripts bajo `scripts/phase0/` funcionan con **Bash + Python 3 estándar**, sin instalaciones, descargas, entrenamiento ni llamadas remotas. Se ejecutan desde la raíz de Spike en **Mac Apple Silicon** y en **Linux CPU 16 GB**. El preflight mide RAM física y CPU del equipo presente, inspecciona `llama-server --version/--help` y enumera dependencias opcionales de S4. **No interpreta 36 GB del Mac como prueba del objetivo de 16 GB.**

```bash
cd /ruta/local/spike
bash -n scripts/phase0/preflight.sh scripts/phase0/smoke_http.sh
bash scripts/phase0/preflight.sh
# Pruebas reproducibles Python stdlib; simulan HTTP SOLO dentro de TEST.
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/phase0 -p 'test_*.py' -v
```

Tras arrancar **por separado** un `llama-server` real con un modelo local legítimo y verificado, la prueba HTTP requiere endpoints `GET /health`, `GET /v1/models` y SSE en `POST /v1/chat/completions`. Comprueba que hay **un modelo declarado por el servidor** y mide **TTFT = instante del primer delta SSE de texto o razonamiento menos instante del POST**, más duración total. No cuenta la conexión TCP ni el primer byte HTTP como token. Use un `--expected-model` igual al ID real publicado por `/v1/models` cuando se busque validar un artefacto concreto. La API no prueba la autenticidad de los pesos: es imprescindible comprobar hashes/procedencia por separado.

**Medición RSS/pico real:** identifica primero el PID que corresponde exactamente a tu `llama-server` ya iniciado (`pgrep -fl llama-server` en Mac o Linux) y pasa `--pid`. El script verifica el nombre del proceso y muestrea cada 100 ms por defecto (`--rss-interval 0.1`). En Linux captura `VmRSS` y `VmHWM` de `/proc/PID/status`; `VmHWM` representa el máximo desde que arrancó el proceso, **incluida** la carga del modelo. En macOS usa `ps -p PID -o rss=`, y el máximo es **solo el pico observado entre muestras**, no un máximo certificado por el kernel. Ambas plataformas excluyen memoria de otros procesos, picos entre muestras y consumo global de GPU/sistema; una carga de 16 GB exige medir **el equipo objetivo**, no el Mac de 36 GB. Sin `--pid`, el JSON deja `memory: null` y no acredita uso de RAM.

```bash
# Servidor REAL ya iniciado en 127.0.0.1:8080, no lo inicia este script.
# Sustituir 12345 por el PID inspeccionado de ESE servidor.
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:8080 \
  --pid 12345 --rss-interval 0.1 \
  --output reports/phase0/mac-baseline.json

# En la máquina CPU 16 GB, con el servidor de esa máquina ya iniciado:
bash scripts/phase0/preflight.sh
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:8080 \
  --pid 12345 --rss-interval 0.1 \
  --expected-model 'ID_EXACTO_DEVUELTO_POR_V1_MODELS' \
  --output reports/phase0/cpu16-baseline.json

# S3: LoRAs REALES ya cargados en llama-server, diferenciables con
# sentinelas predefinidas por su propia evaluación y mismo prompt A/B/A.
# NO usar ALPHA/BETA salvo que esos LoRAs concretos deban producirlas.
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:8080 \
  --pid 12345 --isolation-a 0 --isolation-b 1 \
  --isolation-prompt 'Contesta con la etiqueta aprendida en tu adaptador.' \
  --expect-a 'ETIQUETA_ESPERADA_A' --expect-b 'ETIQUETA_ESPERADA_B' \
  --output reports/phase0/lora-real-aba.json

# Para confirmar que la prueba falla con servidor AUSENTE:
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:65534 \
  --output reports/phase0/expected-no-server.json
# Salida esperada: exit code 1 y status FAIL / ttft_ms null en JSON.
```

**A/B/A real:** el harness consulta `GET /lora-adapters`, exige los IDs A/B presentes, envía **tres POST secuenciales reales** sobre el mismo servidor con `lora:[{id,scale:1}]` y `cache_prompt:false`, guarda respuestas, hashes y tiempos por paso, y comprueba las sentinelas exclusivas A/B y la igualdad exacta A1=A2. Un fallo deja `status: "FAIL"` y `error` con la causa; un éxito da **`PASS_ABA_SENTINELS_ONLY`**, evidencia limitada a este prompt/seed/servidor y **NO una certificación de aislamiento frente a otros prompts o usuarios**. El entorno también puede rechazar el soporte per-request LoRA; es fallo/incompatibilidad real a documentar. Nunca usa `POST /lora-adapters` global ni cambia adaptadores persistentes.

**Alcance de la evidencia JSON:** guarda fecha UTC, commit Git real (o `null` cuando no existe), dirty state, SO/arquitectura/CPU/RAM, `model_id` reportado por HTTP, parámetros de petición, TTFT real, duración, deltas, RSS sampled peak y `VmHWM` cuando está disponible, vista previa truncada de respuesta, hashes SHA-256 y errores verificables. Los resultados se escriben con apertura exclusiva: **no sobrescribe archivos existentes**, cada repetición usa otro `--output` o un nombre único automático. Si el servidor falta, la respuesta SSE falla, el PID es incorrecto o las sentinelas A/B/A fallan, el comando devuelve **código 1** y estado `FAIL`; sin generación, `ttft_ms` es `null` (nunca se fabrica). En A/B/A los resultados se almacenan en `isolation.steps[*].measurement`.

**TEST vs pruebas reales:** `tests/phase0/test_http_probe.py` levanta un servidor HTTP falso **solo dentro del runner TEST**, en `127.0.0.1`, y escribe resultados exclusivamente en directorios temporales. El CLI pasa `--test-harness`: todo JSON se marca `evidence_kind: "TEST_FAKE_HARNESS_NOT_BENCHMARK"`, los estados comienzan con `TEST_FAKE_` y se prohíbe escribir bajo `reports/`. Las cifras del fake jamás son benchmarks ni justifican un gate. La versión actual de `.github/workflows/ci.yml` incorpora `bash -n`, `py_compile` y `make test` (que ejecuta también esta batería): estas comprobaciones se pueden replicar localmente con `make test` o con el comando `unittest` anterior. No se modificaron el CI ni el Makefile en este encargo. El resultado `PASS_HTTP_SMOKE_ONLY` tampoco acredita calidad, aislamiento global ni 16 GB. S4 se limita a inspección de dependencias; cualquier métrica publicable necesita `make eval` / `make bench`, evidencia en `reports/` y commit fechado según `AGENTS.md`.

**Registro de validación local (2026-10-16):** desde la raíz de Spike, `bash -n scripts/phase0/preflight.sh scripts/phase0/smoke_http.sh` → exit 0; `PYTHONDONTWRITEBYTECODE=1 make test` → **10 tests de gates + 13 tests del harness PASS**, incluidos datos HTTP malformados, contaminación A/B/A TEST y fallo sin servidor. `bash scripts/phase0/preflight.sh` → **PASS de herramientas** en Mac Studio arm64 (14 CPU lógicas, 36 GiB RAM, `llama-server` 9430 `d48a56eff`); no demuestra CPU de 16 GB. En prueba negativa de puerto local sin servidor, salida real **exit 1 / FAIL / TTFT null / modelo null**. **Bloqueos pendientes:** ejecución de RSS de `llama-server` auténtico y A/B/A con LoRAs reales, máquina CPU 16 GB, comprobación de hashes y plan íntegro. Estos tests de protocolo no se registran como benchmark ni certificación de S2–S4.

## Compatibilidad de modelos para S1 · Identidad, licencia, arquitectura y procedencia

Fuentes primarias:

- [Qwen3.5-4B — ficha oficial](https://huggingface.co/Qwen/Qwen3.5-4B), [LICENSE](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE), [config.json](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/config.json).
- [Qwen3.5-0.8B — ficha oficial](https://huggingface.co/Qwen/Qwen3.5-0.8B), [LICENSE](https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/main/LICENSE), [config.json](https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/main/config.json).

Ambas fichas declaran **Apache License 2.0** (derechos de copia, modificación y redistribución condicionados a avisos/licencia); archivos `LICENSE` atribuyen Copyright 2026 Alibaba Cloud. No sustituye revisar los términos y archivos precisos de cada derivado ni datos de entrenamiento propios. Registrar hashes, créditos y el artefacto efectivamente usado en `DATA_LICENSES.md` antes de cualquier distribución.

| Propiedad comprobada en `config.json` de Qwen | 4B (principal propuesto) | 0.8B (draft propuesto) |
| --- | --- | --- |
| `architectures` | `Qwen3_5ForConditionalGeneration` | Igual |
| `model_type` exterior / texto | `qwen3_5` / `qwen3_5_text` | Igual |
| Modalidades declaradas | Texto + encoder visual (imagen / vídeo) | Igual |
| Capas de lenguaje | **32** | **24** |
| Ancho oculto | **2560** | **1024** |
| Patrón de capas | 3 `linear_attention` + 1 `full_attention`, repetido 8 veces | Igual, repetido 6 veces |
| Gated DeltaNet + atención completa | Sí | Sí |
| `num_attention_heads` / `num_key_value_heads` | **16 / 4** | **8 / 2** |
| `max_position_embeddings` | **262144** | **262144** |
| `tie_word_embeddings` | `true` | `true` |

**Precisión arquitectónica:** estos dos tamaños son modelos **densos**, no debe inferirse que incluyen Mixture-of-Experts porque la familia Qwen3.5 también ofrece variantes MoE grandes. Los pesos de lenguaje y vision encoder hacen que tamaño de GGUF y memoria total no equivalgan a `parámetros × bits/8` de modo exacto. La ventana teórica de 262144 tokens **no** es una configuración realista verificada para 16 GB.

**Proveniencia pendiente:** congelar revisión completa (no `main` mutable), verificar hashes SHA-256 después de cualquier descarga aprobada, licencia de quantizer y referencia al original. Los nombres de los GGUF de Unsloth indican el origen, pero todavía no constituyen un control de cadena de suministro end-to-end.

## GGUF, `llama-server` y speculative decoding (S1, S2 y S7)

Fuentes del distribuidor: [Unsloth GGUF 4B (árbol)](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/tree/main), [Unsloth GGUF 0.8B (árbol)](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/tree/main), [documentación servidor llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [decodificación especulativa](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).

**Metadatos publicados de archivos; son tamaños en disco, NO mediciones de RAM ni benchmarks propios:**

| Artefacto | 4B | 0.8B |
| --- | ---: | ---: |
| `Q4_K_M.gguf` | **2,74 GB** | **533 MB** |
| `UD-Q4_K_XL.gguf` | **2,91 GB** | **559 MB** |
| `BF16.gguf` | **8,42 GB** | **1,52 GB** |
| `mmproj-F16.gguf` (solo para visión, asociado al mismo tamaño) | **672 MB** | **205 MB** |

Suma nominal de **dos** archivos Q4_K_M de lenguaje: ~3,27 GB en disco; para usar imagen en ambos, añadir ~0,88 GB de proyectores. La memoria al servir incluye además estados de GatedDeltaNet/atención, KV, logits, buffers temporales, adaptadores, paralelismo y sistema operativo. No deducir que la suma de ficheros demuestra que cabe en 16 GB. Para Spike inicialmente **texto solo**; activar visión exige nuevo ensayo y projector del modelo exacto.

**Estado del draft 0.8B:** hay soporte documentado en llama.cpp para `--spec-draft-model` y `--spec-type draft-simple`; la incidencia [#20039](https://github.com/ggml-org/llama.cpp/issues/20039) recoge que la incompatibilidad inicial con Qwen3.5 se solucionó y usuarios probaron 0.8B con otro tamaño de Qwen3.5, con ganancias y regresiones según hardware. **No hay prueba de aceleración específica del par 4B/0.8B sobre CPU 16 GB**. Primero ensayar 4B sin especulación; solo mantener draft si la salida es compatible y aporta mejora neta reproducible. El coste de tener dos contextos también puede perjudicar latencia y RAM.

Secuencia preparada **para una futura ventana aprobada de pruebas**, cuando los GGUF legítimos ya estén disponibles bajo rutas locales; los comandos **no incluyen flags HF que descarguen automáticamente pesos**:

```bash
# CPU x86_64/ARM64 con 16 GB; ejecutar el modelo principal solo.
llama-server -m /ruta/local/Qwen3.5-4B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 2048 --parallel 1 --n-gpu-layers 0 \
  --cache-ram 0 --no-cache-prompt --no-mmproj

# Segunda ejecución separada: principal + draft, solo después del baseline.
llama-server -m /ruta/local/Qwen3.5-4B-Q4_K_M.gguf \
  --spec-draft-model /ruta/local/Qwen3.5-0.8B-Q4_K_M.gguf \
  --spec-type draft-simple \
  --host 127.0.0.1 --port 8080 --ctx-size 2048 \
  --parallel 1 --n-gpu-layers 0 --spec-draft-ngl 0 \
  --cache-ram 0 --no-cache-prompt --no-mmproj

# Mac M4 Max (misma prueba, sin asumir equivalencia con CPU 16 GB):
llama-server -m /ruta/local/Qwen3.5-4B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 --ctx-size 2048 \
  --parallel 1 --n-gpu-layers all \
  --cache-ram 0 --no-cache-prompt --no-mmproj
```

Antes de ejecutar, cotejar cada flag con `llama-server --help` del **binario concreto**, registrar SHA del ejecutable y de ambos GGUF y dejar en `reports/` la salida y los parámetros. En Linux de 16 GB se exige medición de **RSS/pico**, estado `oom-killer`, tokens/s y TTFT de un prompt fijo repetido; ejecutar baseline y draft con mismo contexto, límites y hardware. Pueden medirse con `/usr/bin/time -v` en Linux y `/usr/bin/time -l` en macOS, anotando las diferencias en métricas expuestas. No activar contextos masivos sin medir. La prueba de CPU no se sustituye por una cifra del Mac.

## Multi-LoRA, conversiones y riesgo de contaminación entre roles (S2 y S3)

La [API oficial del servidor](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) documenta la carga de varios adaptadores mediante `--lora`, el endpoint `GET /lora-adapters`, `POST /lora-adapters` y un campo `lora` por petición con `id` y `scale`. **Esto verifica la existencia de interfaz**, pero no la corrección ni el aislamiento para Spike.

**Incidencias de upstream a fecha de corte:**

1. [#26207 — caché de prompt entre LoRAs](https://github.com/ggml-org/llama.cpp/issues/26207): el autor observó salidas contaminadas al reutilizar prefijos con escalas de adaptadores distintas. Se trata de informe de tercero, **no** reproducido localmente.
2. [#28674 — estado inicial y `lora: []`](https://github.com/ggml-org/llama.cpp/issues/28674), abierto 2026-09-09: en builds probadas `--lora-init-without-apply` mantenía escalas 1.0, y una lista vacía no las desactivaba. No asumir que un valor omitido o `[]` implica especialista neutro.
3. [#30366 — KV de slot tras escala global](https://github.com/ggml-org/llama.cpp/issues/30366), abierto 2026-10-12: denuncia reutilización de KV anterior después de `POST /lora-adapters`, incluso con `--cache-ram 0`. Está marcado `bug-unconfirmed` en GitHub; **no** extrapolar automáticamente a build local `9430`, pero es bloqueo de seguridad funcional hasta ensayar.
4. [#18466 — varios LoRAs y fallo de reserva](https://github.com/ggml-org/llama.cpp/issues/18466): informe de crash al cargar múltiples adaptadores. No es prueba de que ocurra en Qwen3.5 o en la versión local.

La **conversión de LoRA PEFT/Unsloth a GGUF** requiere revisar específicamente los tensores de GatedDeltaNet y el vocabulario del modelo base. Es incorrecto asumir que un `adapter_model.safetensors` sirve como LoRA GGUF o formato MLX directamente. [MLX-LM `load_adapters`](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/tuner/utils.py) espera su estructura propia; la [issue #1119](https://github.com/ml-explore/mlx-lm/issues/1119) documenta incompatibilidades de claves, nombres y transposición PEFT↔MLX. **No se ha validado un camino de exportación que conserve comportamiento**.

**Control recomendado mientras el aislamiento no pase:** ejecutar **un proceso `llama-server` distinto por especialista**, con adaptador fijado al inicio y cachés/contextos independientes, limitar la escucha a `127.0.0.1` y no usar `POST /lora-adapters` global para cambiar de usuario/rol. Esto es una propuesta de aislamiento lógico y de estado, **no una prueba de seguridad fuerte frente a un adversario**. Si el límite de 16 GB impide procesos concurrentes, arranque/paro secuencial y medición del coste, con una API que valide el rol antes de construir la solicitud. No afirmar multi-LoRA simultáneo viable hasta una prueba real.

Prueba de aceptación futura para S3 (requiere **dos LoRAs reales autorizados y verificados**, inexistentes hoy): fijar prompts y seeds, comparar salida de rol A después de B contra A en proceso nuevo; repetir 30 alternancias de roles, con y sin `cache_prompt: false`, con claves/IDs explícitos y contexto idéntico. Registrar identificador de proceso, adaptador activo, respuesta y hashes de prefijo; **cualquier salida influida por el adaptador previo o mezcla imprevista → FAIL**. Además comparar baseline sin adaptador y errores de tipo de LoRA. Prohibido usar adaptadores ficticios como prueba de éxito.

## MLX-LM, Unsloth y entrenamiento con recursos finitos (S3; datos S4)

- **MLX-LM:** el repositorio oficial incorpora [`mlx_lm/models/qwen3_5.py`](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/models/qwen3_5.py) y [guía LoRA/QLoRA](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md). Esto avala soporte de código para la arquitectura en versiones actuales, **sin validar** el entorno instalado ni `load()`/gradientes con estos pesos concretos.
- **Riesgo del entrenamiento Mac:** [issue MLX-LM #1956 del 2026-10-08](https://github.com/ml-explore/mlx-lm/issues/1956) describe que entrenar GatedDeltaNet usa una ruta secuencial de operaciones porque el kernel de inferencia no implementa backward (VJP). Muestra degradación significativa con más capas entrenadas y problemas prácticos de tiempos. Son medidas de terceros, no de Spike.
- **Unsloth:** su [guía Qwen3.5](https://unsloth.ai/docs/models/qwen3.5/fine-tune) documenta afinado LoRA bf16 de 0.8B y 4B, incluidos notebooks gratuitos. Publica requerimientos orientativos de **3 GB de VRAM** (0.8B) y **10 GB VRAM** (4B) para bf16 LoRA. **VRAM CUDA ≠ RAM CPU**: esas cifras no demuestran ajuste en la máquina objetivo. La propia guía desaconseja QLoRA 4 bits de Qwen3.5 por desviaciones de cuantización superiores a lo habitual; analizar caso a caso.
- **Unsloth en Mac:** soporte de plataforma y estudio publicados no certifican que un mismo comando de entrenamiento CUDA/Unsloth funcione en Apple Silicon sin cambios. Verificar backend y versiones de MLX/Unsloth antes de elegir pipeline; evitar instalar scripts remotos sin auditoría de commit y dependencias por `AGENTS.md`.
- **LoRA vs inferencia:** cualquier especialista distribuible debe evaluarse en su **GGUF final cuantizado** frente al mismo base cuantizado, bajo datasets y protocolo aprobados; mejorar loss de entrenamiento no satisface ese gate. Tampoco un YAML o la existencia de checkpoint demuestra especialización.

Diagnóstico read-only del framework **solo después de auditarlo e instalarlo explícitamente en un entorno separado**; no se ha ejecutado:

```bash
python3 -m pip show mlx mlx-lm unsloth transformers peft
python3 -c 'import importlib.metadata as m; print(m.version("mlx-lm"))'
python3 -c 'import mlx_lm.models.qwen3_5; print("Módulo Qwen3.5 importable")'
python3 -m mlx_lm.lora --help
```

**Plan B del entrenamiento:** si la formación de 4B es demasiado lenta o inviable en Mac, demostrar primero un ensayo **pequeño y medible** sobre 0.8B u otra alternativa aprobada, sin convertir la mejora de ese modelo en prueba indirecta del 4B. Los notebooks gratuitos están sujetos a cupos y disponibilidad de terceros; coste monetario cero no significa ejecución garantizada ni reproducible. En el destino de 16 GB se exige **inferencia**, no asumir que puede entrenarse.

## Criterios concretos para levantar los bloqueos

| Test pendiente | Evidencia necesaria | Resultado actual |
| --- | --- | --- |
| Integridad/uso legal | SHA completos fijos del original, GGUF, projector si aplica, licencia Apache-2.0 y terceros revisadas; `DATA_LICENSES.md` actualizado | **FAIL / pendiente** |
| Inferencia principal en 16 GB CPU | Arranque real Q4, ejecución offline, memoria pico, TTFT, tokens/s, errores/OOM y calidad base; evidencias `reports/` con fecha/commit | **FAIL / sin prueba** |
| Draft en 16 GB CPU | Comprobar compatibilidad y salida frente al 4B, tasa aceptación y diferencia de tiempo **end-to-end** con memoria pico | **FAIL / sin prueba** |
| LoRA funcional | Adaptador realmente entrenado, licencia y SHA, exportación íntegra PEFT/MLX→GGUF, misma tarea y checkpoints reproducibles | **FAIL / no hay adaptadores** |
| Aislamiento de especialistas | Matriz A/B/A por proceso o varios procesos y control de caché; cero contaminación observable en tests predefinidos | **FAIL / sin prueba; bugs reportados** |
| Formación/validación de especialistas | `make eval` y `make bench`, mejora estadística vs el base cuantizado, métricas con fecha y commit en `reports/`, CI y evaluación separada | **FAIL / no implementado** |
| Autorización de fase | `PLAN.md` íntegro y visto bueno explícito de Joan | **FAIL / bloqueante** |

### Acciones siguientes permitidas dentro de Fase 0

1. Recuperar el `PLAN.md` completo y cotejar la correspondencia real de S1–S4 y límites vinculantes.
2. Fijar revisiones SHA completas y auditar dependencias/archivos **sin ejecutar instaladores**; añadir la procedencia de cada variante en `DATA_LICENSES.md`.
3. Diseñar harness de pruebas (prompts permitidos, aislamiento A/B/A, latencia/RSS) y criterios de calidad cuantitativos **antes** de descargar/trabajar con pesos.
4. Solicitar aprobación expresa de transición **después** de que los gates exigidos por el plan y Joan sean comprobables; mientras tanto mantener estado **Fase 0**.

**Fuentes y fecha:** enlaces originales citados en cada sección, consultados el **2026-10-16**. Las incidencias de GitHub son avisos documentados, no vulnerabilidades localmente reproducidas. Los tamaños de archivos GGUF son metadatos publicados por terceros; no mediciones de memoria del proyecto.
