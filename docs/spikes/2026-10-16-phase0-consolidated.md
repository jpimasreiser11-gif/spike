# Spike — informe consolidado de preparación y Fase 0

**Fecha:** 2026-10-16 · **Estado de Fase 0:** **NO GO / gates abiertos** · **Fase 1:** no autorizada.

## 1. Fuente verificable, repositorio y alcance

El repositorio existente y privado es [`jpimasreiser11-gif/spike`](https://github.com/jpimasreiser11-gif/spike), sincronizado localmente en el Mac de desarrollo, rama `main`. Histórico comprobado antes de esta revisión: commit `c18a263efe3a0062dec52fc9bed6acf92cb72232` (preparación), commit `d3703931e86be40123d346ab54032b942bbe2991` (auditoría y preflight), y [GitHub Actions run 38876647080](https://github.com/jpimasreiser11-gif/spike/actions/runs/38876647080) completada satisfactoriamente en `d370393`. Esta revisión conserva ambos commits y no crea otro proyecto.

**Actualización de la fuente (2026-10-16):** Joan facilitó el Plan Maestro v3 íntegro y ya se comprobó su presencia como [`PLAN.md`](../../PLAN.md) en el checkout (`§§0–17`, incluidas las especificaciones literales S1–S7 en §14 y clean-room en §13). El [informe histórico de recuperación](2026-10-16-plan-source-gate.md) describe correctamente el **bloqueo anterior**, que ahora queda **RESUELTO solo como fuente documental**. Ningún gate experimental se supera por haber recibido el texto. Se mantienen íntegramente los criterios originales y la necesidad de aprobación expresa para Fase 1.

La implementación **se limita intencionalmente a preparación y herramientas de verificación de Fase 0**. No hay daemon, CLI, Studio Web, Specialist Factory ejecutable, pesos LoRA, repositorio público ni versión instalable. Estos componentes siguen formando parte de la meta v1.0, pero su construcción espera gate y aprobación de Fase 1.

## 2. Trabajo real completado

- `AGENTS.md`, `GEMINI.md`, `.github/workflows/ci.yml`, `.agent/skills/` (seis documentos originales), registro `THIRD_PARTY.md` y auditoría de cuatro upstream en [`supply-chain-audit.md`](../skills/2026-10-16-supply-chain-audit.md). Solo `frontend-design` de Anthropic está copiada como texto con licencia en `/skills`; no se ha demostrado activación. Las demás integraciones externas no han pasado auditoría exhaustiva para ejecutar hooks, instaladores, API o MCP.
- Auditoría técnica Qwen, GGUF, llama.cpp, speculative decoding y MLX-LM/Unsloth: [`model-compatibility.md`](2026-10-16-model-compatibility.md). Se han documentado incidencias de upstream de KV/LoRA, conversión y entrenamiento sin presentarlas como fallos reproducidos en Spike. **Nota de correspondencia:** sus epígrafes de trabajo "S1–S4" no coinciden con los **spikes §14** del Plan ya recuperado; utilizar como referencia normativa la [matriz corregida](2026-10-16-phase0-gate-matrix.md).
- `scripts/phase0/preflight.sh`: CPU, SO, RAM física y flags/runtime instalados; `smoke_http.sh` + `http_probe.py`: conexión **solo loopback**, health/model ID, respuesta SSE, TTFT real, métricas de duración, comprobación opcional LoRA A/B/A, más `rss_monitor.py` para RSS con PID real. Pruebas con HTTP fake pertenecen exclusivamente a `tests/`, están claramente etiquetadas `TEST_FAKE_*` y no se guardan como benchmarks.
- `scripts/phase0/hash_artifacts.py`: huellas SHA-256 de ficheros ya disponibles localmente (sin descarga), sin certificar automáticamente la licencia o la identidad del modelo. `paired_bootstrap.py`: prueba estadística por pares sobre etiquetas binarias de modelos finales cuantizados; es un validador matemático de entradas aportadas y no ejecuta modelos ni aprueba publicaciones. `gate_report.py` y `make eval` **registran el estado de los gates** y no conceden PASS cuando faltan datos.
- **S5:** ya se prepararon especificaciones **originales** [`docs/spec/ux-spec.md`](../spec/ux-spec.md) y [`docs/spec/harness-spec.md`](../spec/harness-spec.md) extraídas del propio Plan, con alcances de Studio/harness, estado y pruebas futuras. **No proceden de observar productos externos con REA y no cumplen todavía el entregable con evidencia de §13.**
- **S7:** [`scripts/phase0/s7_readiness.py`](../../scripts/phase0/s7_readiness.py) y [documentación](2026-10-16-s7-readiness.md) preparan comparación AB/BA de servidores locales ya arrancados y rutas de embeddings; los tests `TEST_FAKE_*` solo validan protocolos. El clasificador de centroides **no** implementa el top-3 + Planner de §2 ni acredita aceleración o routing del §1.
- ADR 0001 conserva la decisión **Spike** y `Spike + especialidad`. ADR [0002](../adr/0002-proposed-lora-isolation-fallback.md) y [0003](../adr/0003-proposed-model-fallback.md) son **PROPUESTAS**; no se cambia silenciosamente el diseño aprobado.
- [`DATA_LICENSES.md`](../../DATA_LICENSES.md) clasifica fuentes de los ocho Tier 1; [`specialist-feasibility.md`](2026-10-16-specialist-feasibility.md) especifica gates cuantizados, bootstrap pareado, prevención de contaminación, PII y restricciones de seguridad. La matriz no representa ocho especialistas efectivamente entrenados.

## 3. Evidencias ejecutadas y su límite

| Operación | Salida comprobada | Interpretación |
| --- | --- | --- |
| `git fetch origin --prune; git rev-parse HEAD; git rev-parse origin/main` | Mismo SHA `d3703931…` al comienzo de esta ejecución | Trabajo previo sincronizado |
| `gh repo view jpimasreiser11-gif/spike --json url,isPrivate` | Privado `true`; rama `main` | Acceso y privacidad del repositorio confirmados |
| `gh run list ...` | Dos workflows `Preparation checks` en success en `c18a263`, `d370393` | CI inicial, anterior a nuevos tests |
| `bash scripts/phase0/preflight.sh` | Mac Studio Apple M4 Max, **36 GiB**, 14 CPU lógicas, `llama-server` build `9430 (d48a56eff)` y opciones presentes | Confirma herramientas, no objetivo CPU 16 GB |
| `make test` | **25 tests PASS** (12 gate/licencias/estadística/hashing, 13 HTTP/LoRA/RSS) | Verifica el harness; los mocks no son inferencias reales |
| `make eval` | Código distinto de 0; `PHASE0 BLOCKED`; JSON `reports/phase0/gate-audit-*.json` | FAIL cerrado por plan y medidas ausentes; target limitado a inventario de Fase 0 |
| `make bench BENCH_URL=http://127.0.0.1:65534` | Código distinto de 0; `URLError: Connection refused`; JSON `reports/phase0/http-smoke-*.json` | Control negativo real; `ttft_ms=null`, no inventado |
| Inspección `/downloads` de `*.gguf` | Ningún peso encontrado | No se ha probado ningún modelo local |

**Las cifras `25 tests` y `36 GiB` corresponden al corte histórico del harness y no a modelos Spike.** Los JSON antiguos reflejan su momento original, anterior a la incorporación completa de `PLAN.md`. Las ejecuciones nuevas de la siguiente sección se registran por separado. Los criterios cuantitativos del Plan Maestro siguen exigiendo `make bench` y `make eval` completos sobre modelos reales y hardware de referencia.

## 4. Revisiones de modelos verificadas documentalmente

La consulta de solo lectura a la API oficial de Hugging Face, realizada el 2026-10-16, devolvió las siguientes **revisiones Git de repositorios**, con `cardData.license=apache-2.0`:

| Artefacto | Revisión (`sha`, no hash de pesos) |
| --- | --- |
| `Qwen/Qwen3.5-4B` | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` |
| `Qwen/Qwen3.5-0.8B` | `2fc06364715b967f1860aea9cf38778875588b17` |
| `Qwen/Qwen3-4B` (Plan B) | `1cfa9a7208912126459214e8b04321603b3df60c` |
| `unsloth/Qwen3.5-4B-GGUF` | `e87f176479d0855a907a41277aca2f8ee7a09523` |
| `unsloth/Qwen3.5-0.8B-GGUF` | `6ab461498e2023f6e3c1baea90a8f0fe38ab64d0` |

No se descargaron modelos para verificar checksums de bytes, memoria, conversión ni calidad. Los tamaños GGUF de los repositorios son metadatos de proveedores, no mediciones propias. La compatibilidad de LoRA de la arquitectura híbrida y la utilidad del borrador especulativo en CPU **permanecen no demostradas**.

## 5. Gates reales S1–S7 según §14, y riesgos

Correspondencia **literalmente cotejada** con [`PLAN.md` §14](../../PLAN.md). La F0 (semanas 1–2 en el calendario estimado) exige **demostrar base, serving, entrenamiento y datos**; ningún test sintético, flag presente ni fichero de documentación satisface los gates por sí mismo:

| Gate | Estado | Evidencia / bloqueo |
| --- | --- | --- |
| **S1 — Qwen3.5-4B vs Gemma 4 E4B** | **NOT RUN** | Comparación de evals, tokens/s y RAM de versiones cuantizadas en CPU **16 GB sin GPU**; Qwen documentado, Gemma alternativa sin datos comparables; ningún modelo ejecutado |
| **S2 — multi-LoRA `llama.cpp`** | **NOT RUN** | Cambio de adaptador **≤500 ms** y **sin contaminación entre peticiones**, pruebas A/B/A y caches; harness y flags documentados, pero no hay LoRAs reales ni medición de cambio |
| **S3 — MLX-LM 4B → GGUF LoRA → S2** | **NOT RUN** | Ensayo de ~200 ejemplos legales, checkpoint verdadero, conversión GGUF y carga funcional en `llama.cpp`; MLX/Unsloth investigados, ruta no validada |
| **S4 — datos 0 €, profesor local, descontaminación** | **PENDING / NOT RUN** | Registro de licencias de candidatos ampliado, sin corpus habilitado ni velocidad del teacher local medida; sin exclusión train/eval ejecutada ni gastos del experimento documentados |
| **S5 — UX REA de objetivos permitidos** | **PENDING / NOT RUN** | Condiciones de §13, clean-room y **dos specs propias ya escritas** (`docs/spec/ux-spec.md` y `docs/spec/harness-spec.md`); auditoría estática REA, pero falta evidencia de objetivo observado autorizado y validación |
| **S6 — cinco nombres en plan, Spike elegido por Joan** | **NOMBRE DECIDIDO; DISPONIBILIDAD PENDING** | ADR 0001 ratifica Spike; pendiente disponibilidad GitHub/HF/npm/PyPI/dominio gratuito y revisión marcaria antes de distribuir, sin reabrir elección de nombre |
| **S7 — draft 0.8B + router embeddings CPU** | **NOT RUN** | Herramientas y tests fake de [S7 readiness](2026-10-16-s7-readiness.md) preparados, sin resultados reales. Baseline vs especulación, acceptance/tokens/s/TTFT/RSS CPU16; routing top-3+Planner, **≥90%** acierto en ≥300 prompts con roles nuevos y planes JSON **≥95%** siguen pendientes |
| Licencias de cada muestra | **PENDING** | Fuentes y restricciones documentadas; ningún dataset aprobado para entrenar |
| Ocho especialistas Tier 1 | **0/8** | Sin LoRAs, sin benchmark pareado ni IC 95 % real |
| Hardware objetivo y privacidad offline | **NOT RUN** | Mac 36 GiB distinto de CPU 16 GB; ningún daemon/instalador/proceso real de producción |
| Fuente de verdad del Plan | **RESUELTO (documental)** | `PLAN.md` completo presente y §§13–17 contrastados, incluido mapeo exacto de §14 |
| Gate global de Fase 0 | **FAIL/OPEN** | Ensayos reales S1–S7 sin acreditar; F1 exige aprobación explícita de Joan aun si F0 se completase |

## 6. Plan B sin adopción automática

**LoRA:** si la prueba A/B/A reproduce contaminación del estado KV/caché, proponer un proceso `llama-server` aislado por especialista, con uno activo a la vez y reinicio controlado, sujeto a medir latencia y RAM. El coste del cambio es la recarga de pesos y estado; **no se afirma** que supere los objetivos de memoria o velocidad. Ver ADR 0002.

**Modelo:** S1 **exige** comparar Qwen3.5-4B con `Gemma 4 E4B`, y elegir solo con calidad/tokens/s/RAM reales en CPU 16 GB; si la arquitectura híbrida impide entrenamiento, conversión o aislamiento confiable, el §16 contempla **Gemma 4 E4B o Qwen3-4B** como alternativas. ADR 0003 propone otro Plan B sin adoptarlo: cambios futuros requieren datos y decisión registrada. Draft 0.8B se investiga aparte en **S7** solo tras baseline medido.

**Entrenamiento:** el paso de S3 con **~200 ejemplos** prueba viabilidad técnica mínima y no equivale al ajuste completo de **5k–20k ejemplos por rol** de §5.2. Ante problemas MLX-LM/GatedDeltaNet, documentar fallos y presentar un plan medible y licenciado; no transferir mejoras del 0.8B como evidencia de un 4B. Ninguna propuesta modifica la selección de modelos sin ADR aprobado.

## 7. Ejecución siguiente desde el Mac o un equipo Linux de 16 GB

Desde el checkout existente:

```bash
cd ~/Downloads/spike
git pull --ff-only
make test
make preflight
# Requiere iniciar manualmente un llama-server REAL con un GGUF ya legítimamente disponible:
make bench BENCH_URL=http://127.0.0.1:8080
# Con PID de llama-server y servidor iniciado: captura RAM además de TTFT:
bash scripts/phase0/smoke_http.sh --url http://127.0.0.1:8080 --pid 12345
# Reemplaza 12345 por el PID REAL que hayas comprobado; fallará si no es llama-server.
# Para registrar SHA-256 de un GGUF local real ya disponible:
python3 scripts/phase0/hash_artifacts.py --file /ruta/real/modelo.gguf
make eval
```

**Resultados esperados mientras falten los artefactos:** `preflight` comprueba herramientas; `bench` falla si no hay servidor; `hash_artifacts.py` falla si no existe el fichero; `eval` no puede aprobar un gate sin datos de modelo. Estos comandos son **opciones para ventanas futuras autorizadas, no se ejecutaron en esta revisión**. No es necesario instalar, pagar, ejecutar notebooks ni descargar pesos para verificar la documentación. Para **S2** (no S3), la secuencia A/B/A, modo test controlado y muestreo RSS están descritos en [`model-compatibility.md`](2026-10-16-model-compatibility.md).

## 8. Decisiones y aportaciones necesarias de Joan (una única consulta agrupada)

1. **Fuente: resuelta.** Se dispone de [`PLAN.md`](../../PLAN.md) íntegro. No es preciso volver a solicitarlo; cotejado §14 y ámbitos de S5 §13.
2. **Ensayos aún pendientes:** preparar cuando estén autorizados y licenciados modelos, datos y herramientas; medir S1 en CPU16, S2 adaptadores reales ≤500 ms sin contaminación, S3 LoRA MLX-LM→GGUF, S4 teacher/dedupe y licencias, S5 UX autorizado, S7 draft/embeddings CPU; conservar evidencia de `make eval`/`make bench` fechada y vinculada a commit.
3. **Aprobación:** verificar los gates exactos y obtener autorización expresa de Joan antes de Fase 1. ADR 0002/0003 siguen propuestas de contingencia sin adopción automática.

**Dictamen:** preparación técnica ampliada y CI comprobable; **Fase 0 abierta / NO GO para Fase 1**. Spike mantiene íntegro su objetivo v1.0 de ocho especialistas, pero todavía no hay modelos ni producto listos para distribuir y no se anuncian métricas hipotéticas como verificadas.

## 9. Reconciliación posterior con el PLAN.md íntegro y validación adicional (2026-10-16)

- **Fuente:** `PLAN.md` §§0–17 presente con SHA-256 `35647b3dd974c5a3fd0a2cd23e5b20be9509d8ddf460cf9e8cc0395fd9c2a7de`, almacenado en `PLAN.sha256`. Se añaden instrucciones de agente y verificación de integridad en CI. No es una ejecución de modelos.
- **S4:** `scripts/phase0/decontam_check.py` realiza chequeos de colisión exacta por hash o familia entre manifiestos ya autorizados; valida campos y derechos, conserva fallo explícito. **No detecta paráfrasis ni contaminación pretraining** y no se ha usado sobre datasets reales.
- **S5:** se crearon [especificación UX](../spec/ux-spec.md) y [especificación de harness](../spec/harness-spec.md), derivadas de los requisitos del Plan. REA no se ha ejecutado y no existe evidencia de observación limpia; S5 permanece **NOT RUN/PENDING**.
- **S7:** `scripts/phase0/s7_readiness.py` ofrece ensayos reales contra servidores **previamente iniciados** para comparar baseline/draft y valorar embeddings CPU a partir de un conjunto etiquetado; [protocolo S7](2026-10-16-s7-readiness.md). Se han probado rutas negativas y parsers solo con fixtures `TEST_FAKE`; ningún throughput ni mejora de Qwen3.5 ha sido demostrado.
- **Tests automatizados:** `make test` ejecutó **44/44 tests PASS** en Mac de desarrollo (18 de gates/datos/estadística y 26 de HTTP/RSS/S7); estos tests no cargan pesos ni constituyen benchmarks de modelo.
- **Nuevo `make eval`:** el inventario [JSON](../../reports/phase0/gate-audit-20261016T101004766854Z.json) devolvió `SOURCE_PRESENT_HASH_VERIFIED` para fuente y `NOT_VERIFIED` para S1–S7; **exit distinto de cero** y Fase 1 bloqueada. Git HEAD durante la ejecución: `c65284087b5940adcb49b21628728cabe441629c` (cambios posteriores aún en el árbol de trabajo; revisar `git_dirty`).
- **Nuevo ensayo negativo S7:** [JSON](../../reports/phase0/s7-compare-20261016T101004840655Z-32520.json) demuestra `FAIL`, sin servidor compatible en los puertos solicitados. La prueba negativa no aporta tiempos ni resultados inferidos. La comprobación de S4 con manifiesto inexistente también devuelve error explícito.

**La incorporación del plan resuelve exclusivamente el bloqueo documental.** S1, S2, S3, S4, S5 y S7 exigen ejecución adicional en condiciones exactas; S6 mantiene el nombre seleccionado Spike con comprobación de disponibilidad pendiente. **Fase 0 NO GO; Fase 1 sin autorización.**
