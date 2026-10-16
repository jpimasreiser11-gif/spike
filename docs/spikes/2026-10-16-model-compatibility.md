# Spike — auditoría de compatibilidad de modelos, inferencia y LoRA (S1–S4)

**Fecha de corte:** 2026-10-16 · **Fase:** 0 / preparación · **Dictamen global:** **FAIL / NO GO** para Fase 1.

> **Alcance documental:** esta auditoría agrupa como S1–S4 las cuatro líneas de investigación asignadas (licencia/arquitectura, GGUF/inferencia, multi-LoRA/aislamiento y entrenamiento/memoria). **No certifica la correspondencia con S1–S4 del Plan Maestro v3**, que no está disponible completo. El texto recibido del plan termina en §5.2; consultar [gate de fuente](2026-10-16-plan-source-gate.md). Las comprobaciones locales son solo lectura. **No se descargaron pesos, instalaron dependencias, entrenaron adaptadores, iniciaron servidores ni generaron benchmarks.**

## Resumen ejecutivo y gates

| Área | Evidencia positiva confirmada | Bloqueo para dar PASS de implementación | Gate |
| --- | --- | --- | --- |
| **S1 · Licencia y arquitectura** | Los repositorios **Qwen/Qwen3.5-4B** y **Qwen/Qwen3.5-0.8B** publican **Apache-2.0** y configuración `qwen3_5`; son VLM densos con atención híbrida. | Fijar SHA completos de modelos y archivos distribuidos; revisar también licencia de cuantizaciones, atribución y el Plan Maestro íntegro. | **PASS documental parcial / FAIL de liberación** |
| **S2 · GGUF y runtime** | Hay GGUF Q4_K_M de Unsloth de 2,74 GB (4B) y 533 MB (0,8B), y `llama-server` local declara funciones adecuadas. | No existe prueba de carga, calidad, latencia, estabilidad ni consumo de la **máquina CPU de 16 GB**; imágenes requieren projector apropiado. | **FAIL** |
| **S3 · Multi-LoRA y aislamiento** | `llama-server` documenta varios adaptadores, escalas por petición y `GET/POST /lora-adapters`. | Incidencias de reutilización de KV/cache entre configuraciones LoRA; falta ensayo reproducible de aislamiento y de compatibilidad PEFT→GGUF para Qwen3.5. | **FAIL (riesgo crítico)** |
| **S4 · Fine-tuning y memoria** | MLX-LM tiene `qwen3_5.py`; Unsloth documenta LoRA bf16 para ambos tamaños. | No hay MLX-LM/Unsloth instalados en el Python inspeccionado, LoRAs entrenados ni métricas; problemas conocidos de entrenamiento GatedDeltaNet; entrenamiento CPU 16 GB no demostrado. | **FAIL** |

**Decisión de Fase 0:** **GO para seguir investigando, diseñando ensayos y preparando gates; NO GO para pasar a Fase 1**, publicar especialistas o declarar requisitos satisfechos. La aprobación explícita de Joan y el `PLAN.md` completo son bloqueos independientes de cualquier éxito técnico.

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
```

Tras arrancar **por separado** un `llama-server` real con un modelo local legítimo y verificado, la prueba HTTP requiere endpoints `GET /health`, `GET /v1/models` y SSE en `POST /v1/chat/completions`. Comprueba que hay **un modelo real declarado por el servidor** y mide **TTFT = instante del primer delta SSE de texto o razonamiento menos instante del POST**, más duración total. No cuenta la conexión TCP ni el primer byte HTTP como token. Use un `--expected-model` igual al ID real publicado por `/v1/models` cuando se busque validar un artefacto concreto.

```bash
# Servidor REAL ya iniciado en 127.0.0.1:8080, no lo inicia este script.
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:8080 \
  --output reports/phase0/mac-baseline.json

# En la máquina CPU 16 GB, con el servidor de esa máquina ya iniciado:
bash scripts/phase0/preflight.sh
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:8080 \
  --expected-model 'ID_EXACTO_DEVUELTO_POR_V1_MODELS' \
  --output reports/phase0/cpu16-baseline.json

# S3: con LoRAs REALES previamente cargados y autorizados, un ID por petición.
# Ejecutar A, B y A en orden y comparar manualmente los JSON y respuestas.
bash scripts/phase0/smoke_http.sh --lora-id 0 --output reports/phase0/lora-a1.json
bash scripts/phase0/smoke_http.sh --lora-id 1 --output reports/phase0/lora-b.json
bash scripts/phase0/smoke_http.sh --lora-id 0 --output reports/phase0/lora-a2.json

# Para confirmar que la prueba falla con servidor AUSENTE:
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:65534 \
  --output reports/phase0/expected-no-server.json
# Salida esperada: exit code 1 y status FAIL / ttft_ms null en JSON.
```

**Alcance de la evidencia JSON:** guarda fecha UTC, commit Git real (o `null` cuando no existe), dirty state, SO/arquitectura/CPU/RAM, `model_id` realmente devuelto por HTTP, parámetros de petición, TTFT real, duración, recuento de deltas, vista previa truncada de la respuesta visible, hashes SHA-256 de respuesta visible y de razonamiento, y error verificable. Los resultados anteriores se escriben con apertura exclusiva: **no se sobrescriben archivos existentes**, así que cada repetición requiere otro `--output` (o dejar que genere nombre único en `reports/phase0/`). Si el servidor no existe o la generación no envía un delta y el marcador `[DONE]`, el script sale con **código 1**, guarda `status: "FAIL"` y `ttft_ms: null`; jamás calcula tiempos ficticios.

El resultado `PASS_HTTP_SMOKE_ONLY` solo prueba que se recibió una respuesta SSE real; **no certifica** calidad, rendimiento estadístico, memoria pico, aislamiento multi-LoRA ni compatibilidad 16 GB. Para S3 la opción `--lora-id` solicita un adaptador por petición, pero no demuestra que se aplicara ni que no hubiera contaminación: comparar A/B/A exige adaptadores reales, respuesta y evaluación controlada adicional. Para S4 el preflight solo detecta paquetes instalados. Las métricas publicables siguen requiriendo `make eval` / `make bench`, `reports/` y commit fechado según `AGENTS.md`.

## S1 · Identidad, licencia, arquitectura y procedencia

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

## S2 · GGUF, `llama-server` y speculative decoding

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

## S3 · Multi-LoRA, conversiones y riesgo de contaminación entre roles

La [API oficial del servidor](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) documenta la carga de varios adaptadores mediante `--lora`, el endpoint `GET /lora-adapters`, `POST /lora-adapters` y un campo `lora` por petición con `id` y `scale`. **Esto verifica la existencia de interfaz**, pero no la corrección ni el aislamiento para Spike.

**Incidencias de upstream a fecha de corte:**

1. [#26207 — caché de prompt entre LoRAs](https://github.com/ggml-org/llama.cpp/issues/26207): el autor observó salidas contaminadas al reutilizar prefijos con escalas de adaptadores distintas. Se trata de informe de tercero, **no** reproducido localmente.
2. [#28674 — estado inicial y `lora: []`](https://github.com/ggml-org/llama.cpp/issues/28674), abierto 2026-09-09: en builds probadas `--lora-init-without-apply` mantenía escalas 1.0, y una lista vacía no las desactivaba. No asumir que un valor omitido o `[]` implica especialista neutro.
3. [#30366 — KV de slot tras escala global](https://github.com/ggml-org/llama.cpp/issues/30366), abierto 2026-10-12: denuncia reutilización de KV anterior después de `POST /lora-adapters`, incluso con `--cache-ram 0`. Está marcado `bug-unconfirmed` en GitHub; **no** extrapolar automáticamente a build local `9430`, pero es bloqueo de seguridad funcional hasta ensayar.
4. [#18466 — varios LoRAs y fallo de reserva](https://github.com/ggml-org/llama.cpp/issues/18466): informe de crash al cargar múltiples adaptadores. No es prueba de que ocurra en Qwen3.5 o en la versión local.

La **conversión de LoRA PEFT/Unsloth a GGUF** requiere revisar específicamente los tensores de GatedDeltaNet y el vocabulario del modelo base. Es incorrecto asumir que un `adapter_model.safetensors` sirve como LoRA GGUF o formato MLX directamente. [MLX-LM `load_adapters`](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/tuner/utils.py) espera su estructura propia; la [issue #1119](https://github.com/ml-explore/mlx-lm/issues/1119) documenta incompatibilidades de claves, nombres y transposición PEFT↔MLX. **No se ha validado un camino de exportación que conserve comportamiento**.

**Control recomendado mientras el aislamiento no pase:** ejecutar **un proceso `llama-server` distinto por especialista**, con adaptador fijado al inicio y cachés/contextos independientes, limitar la escucha a `127.0.0.1` y no usar `POST /lora-adapters` global para cambiar de usuario/rol. Esto es una propuesta de aislamiento lógico y de estado, **no una prueba de seguridad fuerte frente a un adversario**. Si el límite de 16 GB impide procesos concurrentes, arranque/paro secuencial y medición del coste, con una API que valide el rol antes de construir la solicitud. No afirmar multi-LoRA simultáneo viable hasta una prueba real.

Prueba de aceptación futura para S3 (requiere **dos LoRAs reales autorizados y verificados**, inexistentes hoy): fijar prompts y seeds, comparar salida de rol A después de B contra A en proceso nuevo; repetir 30 alternancias de roles, con y sin `cache_prompt: false`, con claves/IDs explícitos y contexto idéntico. Registrar identificador de proceso, adaptador activo, respuesta y hashes de prefijo; **cualquier salida influida por el adaptador previo o mezcla imprevista → FAIL**. Además comparar baseline sin adaptador y errores de tipo de LoRA. Prohibido usar adaptadores ficticios como prueba de éxito.

## S4 · MLX-LM, Unsloth y entrenamiento con recursos finitos

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
