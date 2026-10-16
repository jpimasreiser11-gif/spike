# Spike S7 — herramientas de ensayo de speculative decoding y routing local

**2026-10-16 · Fase 0 · Gate S7: FAIL / SIN EVIDENCIA DE MODELOS REALES.**

Esta nota aplica la definición de **§14 de `PLAN.md` completo**: S7 = speculative decoding del modelo principal Qwen3.5-4B con borrador **Qwen3.5-0.8B** y routing por embeddings en CPU. La arquitectura (§2) pide recuperación por descripciones de especialistas (top-3) seguida de decisión del Planner; la métrica §1 exige posteriormente **≥90 % en 300+ prompts etiquetados** sin reentrenar el orquestador al añadir roles. El script de aquí mide **un clasificador de centroides** para valorar viabilidad técnica del embedding; **no implementa ni valida top-3 + Planner**, la calidad definitiva del router ni el gate de §1.

## Archivos y garantías

- `scripts/phase0/s7_readiness.py`: CLI Python **stdlib** con subcomandos `compare` y `route`. Reutiliza el parser SSE de `http_probe.py` y el muestreador `rss_monitor.py`.
- `tests/phase0/test_s7_readiness.py`: HTTP de prueba simulado **exclusivamente dentro de TEST**. Se etiqueta `TEST_FAKE_NOT_BENCHMARK`, solo escribe JSON en directorios temporales y prohíbe guardar fake bajo `reports/`.
- Solo conecta a **`http://127.0.0.1:PUERTO` o `http://[::1]:PUERTO`**; desactiva proxies. No usa nube, no descarga, no instala paquetes, no arranca ni detiene servidores, no carga pesos ni adapta modelos. Los archivos JSON se escriben con apertura exclusiva; no sobrescriben existentes.
- El JSON registra hora UTC, SHA de commit, estado de árbol Git, SO/RAM del host, endpoints/IDs de modelo indicados por los servidores y errores exactos; el resultado no suplanta `make bench` / `make eval` ni autoriza publicación.

## S7a — comparar dos servidores ya iniciados (baseline/draft)

Requisitos previos: dos procesos **ya arrancados por separado**, en puertos diferentes y con el **mismo modelo principal**. Uno debe ser un servidor de Qwen3.5-4B sin especulación y otro de Qwen3.5-4B usando `--spec-draft-model` con el **Qwen3.5-0.8B local aprobado**. El script **no los inicia**. Comprueba `GET /health`, `GET /v1/models` en ambos, exige ID idéntico (introducido en `--model-id`) y ejecuta POST SSE repetidos con el **mismo prompt, temperatura 0, seed 42 y max_tokens**. Alterna orden AB/BA en rondas pares e impares para reducir sesgo temporal.

```bash
cd /ruta/a/spike
# Verificar que existen ambos procesos, sus flags y los IDs vía el servidor:
pgrep -fl llama-server

# Sintaxis real: --output y --timeout son opciones GLOBALES ANTES del subcomando.
python3 scripts/phase0/s7_readiness.py \
  --output reports/phase0/s7-paired-real.json --timeout 60 \
  compare \
  --baseline-url http://127.0.0.1:8080 \
  --draft-url http://127.0.0.1:8081 \
  --model-id 'ID_EXACTO_EN_AMBOS_V1_MODELS' \
  --baseline-pid 12345 --draft-pid 12346 \
  --rounds 4 --max-tokens 64 \
  --prompt 'Explain in two sentences why reproducibility matters.'
```

Sustituir **ambos PID** por procesos locales reales. Si se indican, el programa comprueba que se llaman `llama-server`, exige que el PID draft muestre la opción `--spec-draft-model` y que baseline no la muestre, y mide **RSS/pico por proceso** (Mac: `ps rss`; Linux: `VmRSS` y `VmHWM` desde el arranque). Si se omiten PID, `process_evidence` es `null`: el script puede medir TTFT/duración HTTP, pero **no verifica siquiera la configuración speculative**. La identificación del proceso por PID no demuestra que ese PID sirva precisamente el puerto indicado; el hash del comando queda guardado para auditoría. El nombre y el hash reales del borrador GGUF se deben auditar manualmente: un flag `--spec-draft-model` no verifica la procedencia ni que sea 0.8B.

Se registra **TTFT** del primer fragmento SSE de contenido/razonamiento, duración total por solicitud, mediana por brazo y cociente observacional baseline/draft. `summary.proof_of_acceleration` es **siempre `false`**: diferencias de longitud de salida, aceptación de borradores, efectos térmicos, estado del servidor, concurrencia, variaciones de CPU, caché o asignación de memoria requieren un estudio más amplio. Las muestras no establecen aceleración del draft, ni equivalencia de tokens, ni que el límite de 16 GB se cumpla. Comparar después en **CPU de 16 GB sin GPU** con los modelos reales y hashes fijados; publicar solo mediante los gates del plan.

La comparación también comprueba igualdad del **hash SHA-256 de la respuesta visible por pareja de rondas**. Si alguna salida visible baseline/draft difiere, conserva las muestras observadas pero devuelve **FAIL**, porque tiempos sobre distintas respuestas no son directamente comparables. La igualdad por sí sola no valida equivalencia de secuencias de tokens ocultos ni los beneficios del speculative decoding.

Si falta un servidor, el modelo ID difiere, el SSE está incompleto o la memoria no puede medirse con los PID aportados: **exit 1**, `status=FAIL`, `error` motivado; nunca se crean números faltantes. Los JSON completos llevan `status=OBSERVED_PAIR_NOT_CERTIFIED` y evidencia de memoria opcional. No son benchmarks aprobados.

## S7b — routing por embeddings local con dataset etiquetado

Se necesita un tercer servidor de embeddings **ya iniciado** y su ID real en `GET /v1/models`, con `POST /v1/embeddings` funcional. El dataset **no se genera automáticamente**, debe revisarse licencia/procedencia, no contener PII prohibida y disponer de etiquetas y separación train/test. Formato JSON de entrada de ejemplo puramente ilustrativo (texto inventado; **no es un dataset de evaluación aprobado ni sirve para un gate**):

```json
{
  "license_review": "approved",
  "held_out": true,
  "examples": [
    {"id": "f1", "text": "Solicito presupuesto anual.", "label": "finance", "split": "train"},
    {"id": "f2", "text": "Balance trimestral y gastos.", "label": "finance", "split": "train"},
    {"id": "f3", "text": "Contabilizar ingresos.", "label": "finance", "split": "test"},
    {"id": "m1", "text": "Revisar un protocolo clínico general.", "label": "medicine", "split": "train"},
    {"id": "m2", "text": "Interpretación general de anatomía.", "label": "medicine", "split": "train"},
    {"id": "m3", "text": "Conceptos básicos de salud.", "label": "medicine", "split": "test"}
  ]
}
```

El campo `license_review: approved` es una **declaración del responsable**, no auditoría automática. El script exige al menos 2 etiquetas, 2 train y 1 test por etiqueta, IDs y textos únicos, `held_out: true`, vectors numéricos finitos no nulos de dimensión fija y dataset ≤1 MB / ≤500 filas. La evaluación calcula centroides normalizados **solo de train**, asigna cada test por similitud coseno y publica accuracy, macro recall, dimensiones, latencia mediana por HTTP y predicciones por ID. Rechaza duplicados de texto incluso entre train y test, pero no puede detectar paráfrasis, filtraciones externas ni datos previamente memorizados.

```bash
# Servidor embeddings ya listo, con modelo local y dataset auditado:
python3 scripts/phase0/s7_readiness.py \
  --output reports/phase0/s7-routing-real.json --timeout 60 \
  route \
  --endpoint http://127.0.0.1:8090 \
  --model-id 'ID_EMBEDDINGS_EN_V1_MODELS' \
  --embedding-pid 12347 \
  --dataset /ruta/local/dataset-routing-auditado.json
```

Si se indica `--embedding-pid`, se exige PID `llama-server`, presencia de `--n-gpu-layers 0` (o forma CLI equivalente) y muestreo RSS con pico observado. Si se omite, no hay evidencia de CPU ni RSS. Incluso con flag GPU=0, no puede probarse la **vinculación PID↔puerto** ni descartar todas las optimizaciones de hardware; el registro `cpu_execution_verified: false` permanece honesto. Para satisfacer el objetivo de §1 hacen falta 300+ prompts manualmente etiquetados, varios idiomas reales, especialistas nuevos, top-3 y Planner completo, y evaluación independiente de esta técnica sencilla.

Si dataset falta, esquema/licencia no conforme, embeddings inválidos o el endpoint no funciona, **exit 1 / FAIL** y `result=null`. Los casos completados devuelven `status=OBSERVED_EMBEDDING_ROUTING_NOT_CERTIFIED`; métricas sin prueba estadística de eficacia productiva.

## Verificación local y CI

```bash
cd /ruta/a/spike
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/phase0 -p 'test_s7_*.py' -v
PYTHONDONTWRITEBYTECODE=1 make test
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast, pathlib; ast.parse(pathlib.Path("scripts/phase0/s7_readiness.py").read_text())'
```

Los tests de `test_s7_readiness.py` simulan únicamente el protocolo: 2 servidores locales TEST independientes, respuesta SSE, corpus sintético TEST, comportamiento de errores y selección determinista de centroides; comprueban además rechazo de URLs remotas, ausencia de servidor/dataset, modelo distinto, **respuestas baseline/draft divergentes**, contaminación train/test, vector vacío/no finito, protección contra sobrescritura y `reports/`, y validación de flags CPU/draft. **No hay inferencia real de Qwen, tests de speculative decoding real ni resultado de rendimiento CPU 16 GB**. El `Makefile` ya integra `tests/phase0/` en `make test`; no se edita CI ni archivos ajenos.

**Inventario read-only del Mac en esta sesión:** `pgrep -fl llama-server` no mostró ningún proceso `llama-server`. `lsof -nP -iTCP -sTCP:LISTEN` mostró procesos `ollama` en `127.0.0.1:11434` y `127.0.0.1:56104`, que **no acreditan** la presencia de los dos servidores configurados para el mismo modelo ni el endpoint de embeddings requerido. No se hizo petición a esos procesos ni se ha reclamado evidencia de modelos reales. El estado S7 se mantiene pendiente.

| Comprobación S7 | Evidencia local al crear herramientas | Estado de gate |
| --- | --- | --- |
| Parser SSE/medición y comparación AB/BA | Solo mocks TEST; comprobable por unittest | **PASS infraestructura TEST** |
| Qwen3.5-4B frente a Qwen3.5-4B + borrador 0.8B | No hay servidores reales ni pesos del par cargados en este encargo | **FAIL / pendiente** |
| Memoria/latencia y ganancia en CPU 16 GB | No se ha ejecutado máquina objetivo con modelos | **FAIL / pendiente** |
| Endpoint embeddings / corpus etiquetado auditado | Parser/routing probados con vectores ficticios TEST | **FAIL / pendiente** |
| Routing top-3 + Planner y ≥90 % en ≥300 prompts | No implementado ni medido aquí | **FAIL / pendiente** |
| Autorización de Fase 1 | Sujeta a todos los gates y aprobación explícita de Joan | **FAIL / bloqueado** |
