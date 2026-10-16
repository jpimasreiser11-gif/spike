# Spike S2 — prueba reproducible de multi-LoRA

**Estado:** Fase 0, gate S2 **FAIL / pendiente de LoRAs y servidores reales** (2026-10-16).

Según el Plan Maestro v3 (§2 y §14), S2 exige latencia de cambio de adaptador de **500 ms o menos** y ausencia de contaminación. Esta herramienta mide **TTFT HTTP observable**, que incluye cola, red local, prefill, inferencia y otros trabajos. **No se puede deducir el tiempo real de activación del LoRA a partir de TTFT**, porque el endpoint de chat no proporciona un acuse independiente de cambio. El campo switch_gate_500ms queda explícitamente **NOT_VERIFIABLE_NO_INDEPENDENT_ADAPTER_SWITCH_ACK**, incluso si el proxy TTFT parece favorable.

## Requisitos de ejecución real

Dos servidores llama-server, **ya iniciados**, con el **mismo modelo base** (ID exacto publicado en /v1/models). El primero carga dos LoRAs reales A y B con IDs verificables en GET /lora-adapters; el segundo sirve únicamente la base, publica lista de LoRAs vacía y está aislado en otro proceso/PID y puerto. Los dos servidores deben ofrecer GET /health y generación SSE mediante POST /v1/chat/completions. Se exigen PIDs diferentes en modo real, y se muestrea RSS con el monitor del proyecto; no se inicia, instala ni descarga nada.

Elegir antes de ejecutar un prompt para el que la base, A y B produzcan tres **sentinelas exclusivas** verdaderas y reproducibles. Los nombres del ejemplo siguiente son marcadores que se deben reemplazar, no resultados inventados.

    cd /ruta/local/spike
    pgrep -fl llama-server

    bash scripts/phase0/smoke_http.sh \
      --url http://127.0.0.1:8080 \
      --s2-isolated-url http://127.0.0.1:8081 \
      --expected-model 'ID_EXACTO_DEL_MISMO_MODELO_BASE' \
      --pid 12345 --s2-isolated-pid 12346 \
      --s2-a 0 --s2-b 1 --s2-rounds 30 \
      --s2-prompt 'Devuelve solo tu etiqueta aprendida.' \
      --s2-expect-a 'ETIQUETA_A' \
      --s2-expect-b 'ETIQUETA_B' \
      --s2-expect-base 'ETIQUETA_BASE' \
      --max-tokens 64 --timeout 60 \
      --output reports/phase0/s2-multilora-real.json

La selección de A o B se realiza **por POST**, indicando una lista de un adaptador (id, scale=1). En la base del proceso multi-LoRA se envía **explícitamente una lista vacía de LoRAs**, que puede no desactivar adaptadores en algunos builds: el test fallará si la salida no coincide con la base aislada. El proceso aislado recibe la misma lista vacía. Los parámetros seed=42, temperature=0 y cache_prompt=false se conservan. No se utiliza POST /lora-adapters para modificar el estado global.

## Protocolo, métricas y límites

Cada ronda incluye **siete POST**: referencia base aislada, luego **A1/B/A2**, y **base1/A/base2** sobre el proceso multi-LoRA. El mínimo obligatorio de **30 rondas** produce 210 POST y **120 transiciones observadas**: 30 de cada tipo A→B, B→A, base→A y A→base. Se verifican sentinelas exclusivas, igualdad A1=A2, base1=base2=base aislada y consistencia de las respuestas a través de las rondas. Las respuestas reales se registran mediante hash SHA-256 y vista previa truncada; una contaminación o diferencia produce exit 1 y FAIL, preservando las muestras ya obtenidas.

Por transición, los campos client_ttft_proxy_ms y client_total_response_ms proceden de generación SSE real. En el resumen hay medianas por rol y por transición, máximo observado, memoria RSS muestreada de ambos PIDs, y diferencia de TTFT respecto a la mediana del servidor base aislado. En Linux puede existir VmHWM desde el inicio del proceso; en macOS el pico RSS solo es el máximo muestreado y puede perder ráfagas. La identidad de los dos PIDs se verifica, pero **no se autentica independientemente qué PID posee cada puerto HTTP**.

Si el servidor emite un evento SSE final con usage.completion_tokens, la medición conserva **completion_tokens_reported**, **completion_tokens_source=server_sse_usage** y **end_to_end_completion_tokens_per_second** calculado con el tiempo total de la petición. Esta última magnitud **incluye TTFT** y, por tanto, **no es velocidad pura de decodificación**. Cuando no hay evento usage, los tres campos permanecen **null**: nunca se estiman tokens a partir del número de fragmentos SSE o caracteres generados.

Se conservan los campos de conclusión:

    switch_ack_ms: null
    switch_gate_500ms: NOT_VERIFIABLE_NO_INDEPENDENT_ADAPTER_SWITCH_ACK
    isolation_gate: SENTINEL_ONLY_NOT_CERTIFIED

Un ensayo completado devuelve estado **OBSERVED_S2_PROXY_ONLY**, nunca PASS del gate de activación LoRA. Un TTFT inferior a 500 ms no demuestra el objetivo del plan. Una prueba con sentinelas estables tampoco certifica aislamiento general para cualquier prompt. Para verificar el gate real harán falta instrumentación interna con evento/acuse de activación de adaptador, pruebas con adaptadores genuinos y el hardware objetivo **CPU sin GPU dedicada y 16 GB RAM**. Medidas obtenidas en el Mac de 36 GB no sustituyen esa validación. Si falla el aislamiento, el Plan Maestro contempla GGUF fusionados con swap como plan alternativo.

## Pruebas automáticas y evidencia

    cd /ruta/local/spike
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/phase0 -p 'test_http_probe.py' -v
    PYTHONDONTWRITEBYTECODE=1 make test

Los tests usan servidores HTTP **falsos solo dentro de TEST**, con bandera --test-harness, salida JSON etiquetada TEST_FAKE_HARNESS_NOT_BENCHMARK y bloqueo de escritura bajo reports/. La simulación valida **el parser y el protocolo**; sus latencias no se consideran rendimiento de modelos. Comprueban las 210 peticiones, 120 transiciones, la lista de LoRAs por petición, SSE usage presente/ausente, el rechazo de menos de 30 rondas, servidores ausentes, LoRAs no cargados, contaminación base y cambios entre rondas, además de la compatibilidad con los scripts existentes.

El registro JSON conserva timestamp UTC, commit y dirty state Git, SO/CPU/RAM del cliente, IDs de modelo declarados, configuración, cada muestra de petición y estados de error. Los resultados se escriben con apertura exclusiva y jamás se sobrescriben. Según AGENTS.md, las cifras públicas definitivas deben salir de los gates evaluados mediante make eval/make bench, con evidencia fechada, commit y licencias verificadas. No se ha reclamado ningún benchmark de Qwen ni PASS de S2.

**Validación local de la herramienta, 2026-10-16:** el comando de unittest limitado a test_http_probe.py completó **23/23 pruebas**; el comando make test completó **72/72 pruebas** (36 tests de gates y 36 de phase0); parseo AST de los dos archivos Python y git diff --check también pasaron. Estas cifras describen únicamente tests de software: no hay evidencia nueva de modelos reales ni del gate de 500 ms. La suite de los otros módulos puede cambiar por trabajo paralelo y debe volverse a ejecutar antes de cualquier integración.
