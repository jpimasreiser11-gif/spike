# SPIKE — colaboración con Claude, 25 de octubre de 2026

## Punto de partida y alcance

Trabajo sobre `main` de `jpimasreiser11-gif/spike`, commit `7a085e5`, en la rama
`codex/spike-claude-followup`. Se consultaron el coordinador del proyecto, el hilo
**Construir SPIKE**, **Análisis de mejoras para SPIKE** y la sesión local de Claude Code
`095e86aa-e19a-413d-9956-e863d26b72bc` (17–21 de octubre). Los mensajes se contrastan
con código y resultados; no se copian conversaciones privadas al repositorio.

La carpeta `/Users/jpima/Downloads/Spike` está en `4a2a872`, sin remoto configurado,
con cambios locales de Studio y producción audiovisual. No es la versión actual del
constructor. Se conserva intacta; no hacer `reset --hard`, `clean` ni copiar sus módulos
encima de `main`. La copia aislada de trabajo está en
`/Users/jpima/.codex/worktrees/spike-claude-followup/Spike`.

Se mantienen las decisiones existentes: FastAPI/SQLite/React, una base compartida,
criterios de aceptación originales, conjuntos de selección separados de aceptación,
medicina antes de finanzas, y una sola tarea pesada a la vez. No se activa el adaptador
rechazado ni se anuncia una mejora de Forge sin nuevas mediciones.

## Cambios entregados

| Archivo | Cambio |
|---|---|
| `training/sweep_checkpoints.py` | Registro atómico `sweep/inputs.json`: SHA-256 de entradas y exportaciones, comprobado antes de reutilizar resultados. Rechaza cambios y cachés antiguas sin identidad demostrable; conserva reanudación con entradas iguales |
| `tests/test_sweep_checkpoints.py` | Nueve casos nuevos de regresión; la interrupción simulada ahora crea primero un registro válido de entradas |
| `tests/e2e/serve_scripted.py` | `close()` en el cliente MCP simulado: el cierre real de FastAPI fallaba al finalizar el smoke |
| `docs/TRAINING.md` | Contrato de reutilización, recuperación y límites de esta comprobación |
| `docs/STATUS.md` | Nota de revisión actual, separada de las mediciones históricas |
| `docs/audits/2026-10-25-project-handoff.md` | Inventario de capacidades, estado de medicina, pruebas y pendientes |
| `docs/CODEX-HANDOFF.md` | Este registro de continuidad |

No se cambiaron recetas, criterios, datasets, pesos, catálogo de adaptadores, modelos
aceptados ni módulos de la aplicación. El cambio del cliente MCP afecta solo al servidor
de pruebas. El entorno `.venv` y `web/node_modules` se instalaron en la copia aislada.
El artefacto generado `web/tsconfig.tsbuildinfo` se restauró a su versión original.

## Validación y evidencias

Los resultados completos están en el [informe de revisión](audits/2026-10-25-project-handoff.md).
Los logs y las 42 capturas están en `outputs/claude-followup/` de esta copia de trabajo
y se entregan como paquete local; no se suben conversaciones ni datos de entrenamiento.

Comandos utilizados desde la raíz de esta copia:

```sh
SPIKE_NO_KEYRING=1 \
SPIKE_LLAMA_SERVER=/opt/homebrew/bin/llama-server \
SPIKE_LLAMA_CPP=/Users/jpima/src/llama.cpp \
SPIKE_CONVERT_PYTHON=/Users/jpima/Downloads/Spike/.venv-train/bin/python \
.venv/bin/python -m pytest -q -ra

.venv/bin/python -m pytest -q tests/test_sweep_checkpoints.py tests/test_fix_forgetting.py
.venv/bin/ruff check .
npm --prefix web test
npm --prefix web run build

# Con tests/e2e/serve_scripted.py escuchando en 8741:
CHROMIUM_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
node web/e2e/smoke.mjs http://127.0.0.1:8741 outputs/claude-followup/screenshots

/Users/jpima/Downloads/Spike/.venv-train/bin/python -m pytest -q \
tests/test_resume.py tests/test_gated_delta_chunked.py tests/test_ramguard.py
```

El smoke usa proveedores simulados y datos desechables. El ciclo completo de apertura
y cierre de FastAPI con el cliente MCP simulado se comprobó después del arreglo.
Las pruebas de MLX se ejecutaron con el entorno original, sin instalar paquetes en él.

## Continuación del plan de Claude

**Actualización de esta entrega:** el segundo lote también protege `fix_forgetting.py` y
la reanudación directa de `run_eval.py`; consulta
[la ampliación de la revisión](audits/2026-10-25-resume-hardening.md). La copia aislada ya
contiene los datos y checkpoints de medicina verificados, con rutas de MLX reubicadas.
El dry-run pasa usando el entorno de entrenamiento existente. No se ha iniciado el barrido.

1. Revisar e integrar esta rama antes del barrido. No mezclar los módulos duplicados de
   Downloads con los de main. Conservar esa copia, sus vídeos y todos los checkpoints.
2. Usar la copia aislada preparada o un checkout equivalente del código integrado. El
   informe de la ampliación contiene el comando exacto y el entorno necesarios; revisar
   otra vez el dry-run si cambian archivos o parámetros antes de arrancar.
3. Revisar cualquier caché previa: estas correcciones no inventan procedencia retrospectiva.
   Conservar resultados antiguos sin recibos; no generarles una identidad nueva ni borrar
   evidencias para eludir una negativa de reanudación.
4. Liberar el runtime de la app antes de iniciar el barrido pesado. Comparar checkpoints
   3200, 6400, 12800 y final 25469 a escala 0,5; ejecutar aceptación solo para el elegido.
5. Si ninguno pasa, seguir la receta ya acordada: replay del modelo base como única
   variable modificada, entrenamiento con RAM guard y nueva evaluación. No relajar los
   criterios para activar medicina; finanzas después, según el plan del constructor.

Esta intervención termina con las correcciones revisables y las pruebas realizadas.
No equivale a completar todos los especialistas ni a autorizar el lanzamiento público.
