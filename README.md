# Spike

Sistema local de especialistas de IA en preparación. **Estado: Fase 0; no disponible como producto funcional.**

El objetivo declarado es ejecutar un orquestador y especialistas llamados `Spike finance`, `Spike medicine`, etc. sobre un ordenador de 16 GB de RAM sin GPU dedicada, con inferencia offline y coste cero. Estos objetivos aún **no se han medido ni demostrado**.

La fuente de verdad es el [`PLAN.md` íntegro](PLAN.md) (§§0–17, entregado por Joan el 2026-10-16). `AGENTS.md` y `GEMINI.md` recogen las reglas obligatorias. La arquitectura, pesos, entrenamientos y métricas no están publicados.

Todo especialista que alcance distribución futura deberá superar su gate sobre el modelo cuantizado final. No se publicarán cifras de rendimiento sin datos fechados y vinculados a un commit en `reports/`.

## Preparación y Fase 0

- [Informe consolidado y gates](docs/spikes/2026-10-16-phase0-consolidated.md)
- [Auditoría de Qwen3.5, LoRA, entrenamiento y ensayos](docs/spikes/2026-10-16-model-compatibility.md)
- [Ocho especialistas: licencias y evaluación futura](docs/spikes/2026-10-16-specialist-feasibility.md)
- [S7: ensayo de speculative decoding y routing por embeddings](docs/spikes/2026-10-16-s7-readiness.md)
- [F0: evidencia real de Qwen/Gemma y embeddings en CPU](docs/spikes/2026-10-16-real-inference-evidence.md)
- [S5: especificaciones UX y harness originales](docs/spec/ux-spec.md)

En macOS o Linux con Bash, Python 3 y `llama-server` ya instalado:

```bash
make test       # tests del harness, sin descargas ni pesos
make preflight  # CPU, RAM física, flags, versiones; no carga modelos
make eval       # Fase 0: inventario de gates, falla mientras falte evidencia
make bench      # prueba HTTP con llama-server ya iniciado; falla si no existe
```

Los targets `eval`/`bench` actuales son **diagnósticos de Fase 0**, no benchmarks completos para publicación. Los scripts no entrenan ni descargan modelos. La Fase 1 requiere la aprobación expresa de Joan y el `PLAN.md` íntegro.
