# Spike — evidencia de preparación

- Fecha: **2026-10-16** (Europa/Madrid)
- Commit evaluado: `c18a263efe3a0062dec52fc9bed6acf92cb72232`
- Plataforma inspeccionada: Mac de desarrollo, macOS arm64. **No es el equipo objetivo sin GPU de 16 GB.**

## Comprobaciones ejecutadas

| Comando | Resultado registrado | Interpretación |
| --- | --- | --- |
| `gh repo view jpimasreiser11-gif/spike --json url,isPrivate,defaultBranchRef` | `isPrivate: true`, rama `main` | Repositorio privado creado |
| `gh run list -R jpimasreiser11-gif/spike --limit 3 --json ...` | `Preparation checks`: `completed`, `success`, ejecución `38875052774`, commit `c18a263` | Solo supera checks de preparación, no product tests |
| `node --version` | `v26.9.0` | Node disponible; Node 22+ objetivo aún no probado en matriz |
| `npm --version` | `11.19.1` | npm disponible |
| `llama-server --version` | `version: 9430 (d48a56eff)`, Darwin arm64 | Binario local presente; arquitectura y LoRA aún no verificados en inferencia |
| `sysctl -n hw.memsize` | `38654705664` bytes, 36 GiB físicos | Invalida usar esta máquina como demostración del límite de 16 GB |
| `llama-server --help` | Incluye `--lora`, `--lora-init-without-apply`, `--cache-ram`, `--no-cache-prompt`, `--spec-draft-model` | Solo disponibilidad de opciones, no demuestra que funcionen correctamente con Qwen3.5 |

## Gates

| Condición | Estado |
| --- | --- |
| Repositorio Git privado | PASS |
| CI básico de preparación | PASS |
| PLAN.md completo disponible | FAIL |
| Inferencia Qwen3.5-4B GGUF validada | NOT RUN |
| Aislamiento multi-LoRA comprobado | NOT RUN |
| Memoria/latencia medidas en 16 GB sin GPU | NOT RUN |
| Entrenamiento y evaluación de especialistas | NOT RUN |

**Advertencia:** este archivo es un registro de preparación. No es `make eval` ni `make bench`, y no justifica afirmaciones comerciales sobre velocidad, memoria o calidad de Spike.
