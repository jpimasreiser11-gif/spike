# SPIKE — segunda entrega de continuidad, 25–26-10-2026

Esta ampliación continúa el plan de Claude: corregir el olvido de medicina con los
criterios existentes, antes de pasar a finanzas. Añade garantías de recuperación y
prepara los archivos del Mac para el siguiente experimento; no cambia la arquitectura
de la aplicación ni la receta del modelo.

## Cambios comprobados

1. **Evaluación directa.** `evals/run_eval.py --resume` ya no se basa solo en los IDs de
   las preguntas. Comprueba los bytes del modelo y adaptadores, los parámetros, las
   instrucciones del especialista y el contenido real de las preguntas y respuestas
   esperadas. Registra también el build del servidor. Permite añadir otro adaptador
   conservando los grupos válidos; rechaza cambios y registros antiguos sin recibo.
2. **Recuperación sin perder respuestas.** Antes se abría `predictions.jsonl` para
   sobrescribirlo al comenzar una reanudación. Ahora cada grupo terminado se guarda
   mediante sustitución atómica; un fallo en el siguiente grupo conserva los anteriores.
   Un `--out` nuevo no sobrescribe resultados existentes.
3. **Coordinador de entrenamiento.** `fix_forgetting.json` vincula los pasos con los
   archivos utilizados. Antes de saltarse un paso o comunicar aceptación se comprueban
   sus artefactos, incluso si la primera ronda ya está archivada. Se mantienen las
   pruebas de interrupción entre comandos, escrituras y movimientos del archivo.
4. **Servidor y aceptación.** Una interrupción al arrancar el servidor lo cierra.
   El servidor local debe haber cargado los adaptadores solicitados. Pedir aceptación
   sin ningún adaptador ya no devuelve un éxito vacío.

Archivos del segundo lote: `evals/run_eval.py`, `training/fix_forgetting.py`,
`training/spike_train/provenance.py`, `tests/test_eval_resume.py`,
`tests/test_fix_forgetting.py`, `tests/test_llamacpp_integration.py`, y documentación.
Los hashes se calculan por bloques; no se cargan los pesos completos en RAM.

## Pruebas

- Las once regresiones iniciales de la evaluación y las quince del coordinador fallaron
  antes de las correcciones. También se reprodujeron por separado el fallo de cierre,
  el adaptador no cargado y la aceptación vacía.
- Suite completa posterior: **887 passed, 14 skipped**. Son **31 casos más** que en la
  primera entrega; no son 31 mediciones nuevas de calidad de modelos.
- Pruebas de recuperación, coordinador y barrido: **145 passed, 1 skipped** sin activar
  el conversor en ese pase específico. La suite completa sí lo incluyó.
- Prueba nueva con **llama.cpp real**, GGUF diminuto y LoRA: genera, vuelve a abrir el
  servidor y reanuda sin generar de nuevo respuestas ya terminadas.
- Ruff y `git diff --check`: correctos. No se ha modificado la interfaz; sus resultados
  de web, build y E2E de la primera entrega se mantienen como evidencia anterior.

## Medicina preparada en una copia aislada

Se copiaron **133 archivos / 10.919.321.307 bytes lógicos**, mediante clones APFS con
escritura independiente, no enlaces duros ni simbólicos a los archivos originales.
Los hashes coincidieron tras copiar. Se conservaron las fechas de los checkpoints.

Después se modificaron exclusivamente `data` y `adapter_path` en el
`training/data/medicine/mlx_lora.yaml` **de la copia**, porque contenía rutas absolutas
a Downloads. Ahora apuntan a la copia aislada. Los hiperparámetros permanecen iguales;
el archivo original no cambió. La modificación y sus hashes constan en el manifiesto
local de preparación.

El entorno `.venv-train` original ya contiene MLX, mlx-lm, datasets y safetensors, y su
implementación supera `check_mlx_lm()`. No se le instalaron ni actualizaron paquetes.
Desde `/Users/jpima/.codex/worktrees/spike-claude-followup/Spike` se comprobó:

```sh
PATH="/Users/jpima/Downloads/Spike/.venv-train/bin:$PATH" \
SPIKE_LLAMA_SERVER=/opt/homebrew/bin/llama-server \
/Users/jpima/Downloads/Spike/.venv-train/bin/python training/fix_forgetting.py medicine \
  --llama-cpp /Users/jpima/src/llama.cpp \
  --model /Users/jpima/.spike/models/Qwen3.5-4B-Q4_K_M.gguf \
  --python /Users/jpima/Downloads/Spike/.venv-train/bin/python --dry-run
```

El ensayo pasa y muestra el plan completo. Usar el entorno de entrenamiento en `PATH`
es necesario porque los scripts de shell llaman a `python`. El `.venv` de desarrollo
de esta copia no tiene todas las dependencias de entrenamiento.

**El entrenamiento y el barrido reales no se han iniciado.** En la comprobación había
14,27 GB disponibles y 1,78 GB de swap. El RAM guard existente exige 22 GB disponibles
para arrancar entrenamiento: no se redujo ese umbral. La app y su runtime siguen
disponibles. El siguiente paso es integrar/revisar el código y lanzar el experimento
cuando el equipo tenga recursos, manteniendo una sola tarea pesada.

## Límites que permanecen

- Un recibo local no es una firma ni una prueba de calidad científica. No protege frente
  a alguien que modifique deliberadamente tanto los archivos como todos los recibos.
- `--server-url` permite evaluaciones nuevas. Su reanudación se rechaza porque un nombre
  de modelo o build no identifica los pesos de un servidor gestionado externamente.
- Las revisiones remotas y dependencias no quedan todas fijadas. El contenido recuperado
  de las preguntas sí se comprueba antes de reutilizar una evaluación directa.
- `--rescore` es una operación explícita distinta. Los replay aportados antes de iniciar
  el coordinador conservan sus declaraciones originales de procedencia: capturar sus
  hashes no demuestra retrospectivamente qué profesor los generó.
- Medicina continúa rechazada. No se ha instalado ningún adaptador, cambiado ningún
  criterio, conectado una cuenta ni publicado el repositorio.

Logs y manifiestos locales: `outputs/claude-followup/` de la copia aislada. Las evidencias
se añaden al paquete de entrega de Downloads; los pesos y datasets quedan fuera del ZIP
y del PR.
