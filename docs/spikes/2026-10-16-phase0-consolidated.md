# Spike — informe consolidado de preparación y Fase 0

**Fecha:** 2026-10-16 · **Estado de Fase 0:** **NO GO / gates abiertos** · **Fase 1:** no autorizada.

## 1. Fuente verificable, repositorio y alcance

El repositorio existente y privado es [`jpimasreiser11-gif/spike`](https://github.com/jpimasreiser11-gif/spike), sincronizado localmente en el Mac de desarrollo, rama `main`. Histórico comprobado antes de esta revisión: commit `c18a263efe3a0062dec52fc9bed6acf92cb72232` (preparación), commit `d3703931e86be40123d346ab54032b942bbe2991` (auditoría y preflight), y [GitHub Actions run 38876647080](https://github.com/jpimasreiser11-gif/spike/actions/runs/38876647080) completada satisfactoriamente en `d370393`. Esta revisión conserva ambos commits y no crea otro proyecto.

**Hallazgo determinante:** no existe `PLAN.md` íntegro en el checkout, el remoto, las carpetas accesibles del Mac, la biblioteca de conversación ni los resultados pertinentes de Google Drive. La fuente textual entregada termina dentro de §5.2; el contenido vinculante literal de S1–S7 y §17 no puede cotejarse en su totalidad. Se documentó en [`plan-source-gate.md`](2026-10-16-plan-source-gate.md). No se ha generado un falso `PLAN.md` reconstruido.

La implementación **se limita intencionalmente a preparación y herramientas de verificación de Fase 0**. No hay daemon, CLI, Studio Web, Specialist Factory ejecutable, pesos LoRA, repositorio público ni versión instalable. Estos componentes siguen formando parte de la meta v1.0, pero su construcción espera gate y aprobación de Fase 1.

## 2. Trabajo real completado

- `AGENTS.md`, `GEMINI.md`, `.github/workflows/ci.yml`, `.agent/skills/` (seis documentos originales), registro `THIRD_PARTY.md` y auditoría de cuatro upstream en [`supply-chain-audit.md`](../skills/2026-10-16-supply-chain-audit.md). Solo `frontend-design` de Anthropic está copiada como texto con licencia en `/skills`; no se ha demostrado activación. Las demás integraciones externas no han pasado auditoría exhaustiva para ejecutar hooks, instaladores, API o MCP.
- Auditoría técnica Qwen, GGUF, llama.cpp, speculative decoding y MLX-LM/Unsloth: [`model-compatibility.md`](2026-10-16-model-compatibility.md). Se han documentado incidencias de upstream de KV/LoRA, conversión y entrenamiento sin presentarlas como fallos reproducidos en Spike.
- `scripts/phase0/preflight.sh`: CPU, SO, RAM física y flags/runtime instalados; `smoke_http.sh` + `http_probe.py`: conexión **solo loopback**, health/model ID, respuesta SSE, TTFT real, métricas de duración, comprobación opcional LoRA A/B/A, más `rss_monitor.py` para RSS con PID real. Pruebas con HTTP fake pertenecen exclusivamente a `tests/`, están claramente etiquetadas `TEST_FAKE_*` y no se guardan como benchmarks.
- `scripts/phase0/hash_artifacts.py`: huellas SHA-256 de ficheros ya disponibles localmente (sin descarga), sin certificar automáticamente la licencia o la identidad del modelo. `paired_bootstrap.py`: prueba estadística por pares sobre etiquetas binarias de modelos finales cuantizados; es un validador matemático de entradas aportadas y no ejecuta modelos ni aprueba publicaciones. `gate_report.py` y `make eval` inventarían el estado sin conceder PASS cuando faltan datos.
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

**Las cifras `25 tests` y `36 GiB` provienen de ejecución en el entorno de desarrollo.** No son precisión ni velocidad de un especialista. Las evidencias JSON se crearon sobre el commit base `d370393…`, antes de registrar los cambios presentes en este informe. Los criterios de rendimiento cuantitativo del Plan Maestro requieren futuras corridas completas de `make bench` y `make eval` sobre modelos finales y hardware de referencia.

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

## 5. Gates S1–S7 y riesgos

La correspondencia exacta de etiquetas S1–S7 con tareas está pendiente de `PLAN.md` íntegro. Se conservan **temas tentativos** de la auditoría previa, sin inventar texto normativo:

| Gate | Estado | Evidencia / bloqueo |
| --- | --- | --- |
| **S1 — base candidata** | DOCUMENTAL PARCIAL / **NO GO** | Qwen3.5-4B y licencia publicada verificadas; sin GGUF ejecutado en CPU 16 GB ni LoRA real cuantizado |
| **S2 — inferencia/GGUF** | **NOT RUN** | CLI `llama-server` disponible y scripts reales; faltan pesos aprobados y benchmark |
| **S3 — multi-LoRA/cache** | **NOT RUN** | API documentada, test harness A/B/A listo; faltan LoRAs entrenados, cambios de estado y pruebas con caché real |
| **S4 — entrenamiento** | **NOT RUN** | MLX/Unsloth documentados, sin entrenamiento ni exportación real verificados |
| **S5 — fuente íntegra no disponible** | **BLOCKED** | Alcance/criterios literales desconocidos; mapa de riesgos documental cuando es posible |
| **S6 — nombre Spike** | Nombre **DECIDIDO**, gate legal **OPEN** | Decisión no se reabre; búsqueda formal de marca pendiente antes de publicación |
| **S7 — fuente íntegra no disponible** | **BLOCKED** | Criterios literales desconocidos; licencias, distribución y viabilidad se estudian sin reconstruir S7 |
| Licencias de cada muestra | **PENDING** | Fuentes y restricciones documentadas; ningún dataset aprobado para entrenar |
| Ocho especialistas Tier 1 | **0/8** | Sin LoRAs, sin benchmark pareado ni IC 95 % real |
| Hardware objetivo y privacidad offline | **NOT RUN** | Mac 36 GiB distinto de CPU 16 GB; ningún daemon/instalador/proceso real de producción |
| Gate global de Fase 0 | **FAIL/OPEN** | PLAN íntegro + ensayos reales + aprobación de Joan pendientes |

## 6. Plan B sin adopción automática

**LoRA:** si la prueba A/B/A reproduce contaminación del estado KV/caché, proponer un proceso `llama-server` aislado por especialista, con uno activo a la vez y reinicio controlado, sujeto a medir latencia y RAM. El coste del cambio es la recarga de pesos y estado; **no se afirma** que supere los objetivos de memoria o velocidad. Ver ADR 0002.

**Modelo:** conservar Qwen3.5-4B como candidato principal hasta una prueba real; si su arquitectura híbrida impide entrenamiento, conversión o aislamiento confiable, ensayar `Qwen3-4B` con la misma evaluación y pedir confirmación para sustituirlo. `Gemma 4 E4B` permanece alternativa documental, sin equivalencia de RAM comprobada. Draft 0.8B solo tras una comparación medida con la inferencia sin especulación. Ver ADR 0003.

**Entrenamiento:** ante problemas MLX-LM/GatedDeltaNet, documentar intentos y ensayar una configuración menor libre y autorizada; no transferir mejoras del 0.8B como evidencia de un 4B. Ninguna propuesta modifica la selección de modelos sin ADR aprobado.

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

**Resultados esperados mientras falten los artefactos:** `preflight` comprueba herramientas; `bench` falla si no hay servidor; `hash_artifacts.py` falla si no existe el fichero; `eval` indica explícitamente que el gate de fase está bloqueado. No es necesario instalar, pagar, ejecutar notebooks ni descargar pesos para estas verificaciones. Para S3, los comandos completos de secuencia A/B/A, modo test controlado y muestreo RSS están en [`model-compatibility.md`](2026-10-16-model-compatibility.md).

## 8. Decisiones y aportaciones necesarias de Joan (una única consulta agrupada)

1. **Fuente:** adjuntar el `PLAN.md` íntegro para comprobar S1–S7 y el resto de secciones que faltan tras §5.2.
2. **Ensayos:** cuando exista una copia licenciada y local del GGUF 4B, ejecutar en el Mac los comandos anteriores con el servidor real y proporcionar los JSON; repetir en hardware real de 16 GB RAM sin GPU dedicada cuando esté disponible. Sin ese equipo no se puede certificar el objetivo de producción.
3. **Aprobación:** estudiar los gates completos una vez recogida la evidencia y autorizar expresamente Fase 1 si procede. ADR 0002/0003 quedan como propuestas de contingencia, sin necesidad de elegir Plan B ahora.

**Dictamen:** preparación técnica ampliada y CI comprobable; **Fase 0 abierta / NO GO para Fase 1**. Spike mantiene íntegro su objetivo v1.0 de ocho especialistas, pero todavía no hay modelos ni producto listos para distribuir y no se anuncian métricas hipotéticas como verificadas.
