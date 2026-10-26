# SPIKE: contraste del proyecto y los chats, 2026-10-25

## Qué se revisó

Se contrastaron los chats visibles del coordinador de **Spike**, **Construir SPIKE** y
**Análisis de mejoras para SPIKE**, la sesión local de Claude Code del 17–21 de octubre,
`docs/PLAN.md`, `STATUS.md`, `ARCHITECTURE.md`, `TRAINING.md`, las ADR y el código de
`main` (`7a085e5`). Se ejecutó la suite del proyecto y su prueba de navegador. Esta es
una revisión de integración y continuidad, no una certificación exhaustiva de seguridad
ni una nueva evaluación de inteligencia de todos los modelos.

## Hallazgo principal: dos versiones distintas

La copia de Downloads está en `4a2a872` y tiene cambios sin commit (Studio, API reducida,
skills adaptadas y material audiovisual). La versión de Claude en GitHub es posterior:
contiene proyectos, memoria, API, documentos, MCP, Forge, Dev, Design, Analytics,
Creator, Motion y Evolution, con sus propias implementaciones y pruebas.

Por tanto, que una función faltase en Downloads **no significa que Claude no la hubiera
construido**. Tampoco se deben fusionar automáticamente dos motores de proyectos o
dos API. La continuación parte del `main` real, en una copia aislada; los archivos y
vídeos de Downloads permanecen disponibles.

## Inventario y límites

| Área | Evidencia en el main revisado | Qué queda por demostrar o completar |
|---|---|---|
| Motor y especialistas | `runtime/`, `providers/`, catálogo y pruebas reales de llama.cpp; 13 perfiles | No hay adaptador aceptado. El objetivo de 16 GB no implica respuesta rápida a contextos largos |
| Proyectos y memoria | `projects.py`, `memory/`, búsqueda híbrida, reglas, chats temporales y ramas; pruebas API y navegador | Calidad de recuperación con el embedding real y documentos representativos |
| API y MCP | API compatible documentada, cliente y servidor MCP, permisos y MCP Apps | Probar proveedores y aplicaciones externas concretas con sus configuraciones autorizadas |
| Skills y paquetes | Motor, importación, routing y packs; 12 `SKILL.md` en `spike/skills/bundled` | El listado aspiracional de 30 no está íntegramente integrado en este motor; evaluar utilidad y procedencia antes de añadir |
| Artefactos y documentos | DOCX/XLSX/PPTX/PDF, descargas y vista aislada; tests reabren resultados | Calidad de entregables complejos con pesos reales |
| Collective y Forge | Blueprint, roles, verificador y comprobaciones de archivos; evaluaciones guardadas | Las cuatro rondas documentadas no demuestran superioridad frente al modelo solo. No anunciar esa ventaja |
| Dev | CLI, archivos, comandos, permisos y recuperación | Tareas completas con modelos reales y repositorios representativos |
| Design y Creator | Sistemas de diseño, plantillas, artefactos y flujo de Forge | No equivalen a un editor de diseño completo; medir fidelidad y usabilidad |
| Analytics | DuckDB, datos tabulares, SQL, gráficos y reportes; tests de resultados y navegador | Flujos con datos reales más variados, errores y tamaños documentados |
| View | Navegador mediante Playwright MCP y reglas por dominio/acción | Control general del escritorio aplazado; la prueba de upstream MCP real no se repitió aquí |
| Motion | Escenas programadas, render offline, exportación y reproductor; tests reales de render | No es un modelo generativo de vídeo; calidad de escenas creadas por un 4B sin medir |
| Evolution | Correcciones, candidatos, pruebas, versiones, rollback y datos opt-in | Ganancias reales de aprendizaje; auditoría adicional de la identidad de todas las cachés de entrenamiento |
| Finance | Mercado, backtest, simulación y flujo de órdenes con permisos | Las pruebas usan una bolsa simulada. No se conectó ni operó ninguna cuenta real |
| Distribución | CI e instaladores con evidencias históricas en `STATUS.md` | Windows de escritorio, revisión final de licencias/seguridad y publicación autorizada |

Las ampliaciones de 3D, videojuegos, dispositivos y colaboración multiusuario siguen
siendo visión futura. Una pantalla promocional no prueba su implementación.

## Medicina: seguir exactamente el plan de Claude

El resultado registrado de la primera ronda sigue siendo **rechazado**: mejora en medicina
de 31,92 puntos, pero pérdida de 7,62 puntos en general frente al máximo de 1,5. No se
han modificado criterios, pesos, catálogo ni decisión. Estas cifras proceden de los
resultados existentes; no se volvió a ejecutar esa evaluación.

La comprobación de solo lectura del Mac confirmó:

- Existen el GGUF base, el conversor de llama.cpp y los checkpoints.
- Los SHA-256 de `train.jsonl` y `valid.jsonl` coinciden con el `run.json` original.
- Los cuatro candidatos predeterminados corresponden a pasos **3200, 6400, 12800**
  y **25469 a escala 0,5**. Ninguno se ha evaluado en esta intervención.
- Había un `llama-server` de la app ya activo. No se lanzó entrenamiento ni otro
  trabajo pesado de producción; las integraciones usan modelos diminutos de prueba.

Próximo orden: integrar la corrección; preparar una copia coherente del código actual
con los datos/checkpoints originales preservados; revisar `fix_forgetting.py --dry-run`;
liberar el runtime de la app antes del barrido; mantener las suites de selección separadas
de aceptación. Solo si el barrido no acepta nada, seguir la única modificación de receta
de Claude: replay del modelo base, preparación, entrenamiento bajo RAM guard y nuevo
barrido. Finanzas después de corregir el olvido, marketing después de finanzas.

## Corrección implementada y validación

El barrido reutilizaba exportaciones y resultados por nombre. Se reprodujo con **8 pruebas
fallidas**: cambiar un checkpoint, configuración del adaptador, modelo base, receta,
suites, run record, GGUF exportado o retirar el registro de procedencia dejaba reutilizar
el resultado. Ahora guarda y comprueba hashes antes de reutilizarlo. Conserva los resultados
y rechaza entradas distintas; permite reanudar entradas idénticas y añadir candidatos.
Los hashes se calculan sin cargar el GGUF completo en memoria.

Una novena regresión cubre `mlx_lora.yaml`, usado como fuente alternativa del número
de iteraciones. También se corrigió el cliente MCP simulado del servidor E2E: le faltaba
`close()` y provocaba un error al cerrar la app. Se verificó el ciclo real de FastAPI
después de añadirlo; no se cambió el cliente MCP de producción.

| Comprobación ejecutada en este Mac | Resultado |
|---|---|
| Copia antigua de Downloads, antes de cambios | 114 passed, 2 skipped |
| Main de Claude antes de corregir | 844 passed, 17 skipped |
| Main + corrección, con llama-server y conversor reales habilitados | **856 passed, 14 skipped** |
| Barrido y recuperación de olvido, después del último cambio | **115 passed, 1 skipped** |
| MLX: resume, delta chunked y RAM guard, entorno original sin modificar | **49 passed** |
| Vitest | **27 passed** |
| TypeScript + Vite | Compilación correcta |
| Smoke completo de navegador, servidor y datos de prueba aislados | **E2E OK**, 42 capturas |
| Cierre de FastAPI con el MCP simulado, después del arreglo | Correcto |
| Ruff | Correcto |

Las 49 pruebas de MLX incluyen algunas de RAM guard presentes en la suite general;
no se suman como si fueran pruebas todas diferentes. Los skips restantes corresponden
a plataformas Linux/PowerShell no presentes, al MCP de Playwright externo y a los módulos
MLX que se ejecutaron por separado. No se afirma haber repetido la CI de todos los sistemas.

Los logs, capturas y el preflight están en `outputs/claude-followup/` de esta copia de
trabajo. El paquete de evidencias es local y no incluye conversaciones, credenciales,
datasets ni pesos.

## Pendientes detectados que no debe ocultar la corrección

1. La comprobación de identidad de `run_eval.py --resume` y del registro de pasos de
   `fix_forgetting.py` se amplió en el [segundo lote](2026-10-25-resume-hardening.md).
   Los recibos locales no convierten cualquier caché en evidencia certificada.
2. Un ID de repositorio de Hugging Face no fija por sí solo una revisión remota.
   Conviene fijar también las revisiones de modelos/datasets y las dependencias de
   cada evaluación para reproducibilidad estricta.
3. Varias partes antiguas de `PLAN.md` y `STATUS.md` conservan estados anteriores
   (por ejemplo, recuentos de tests o publicación pendiente del primer push). La
   documentación más reciente del mismo archivo y los resultados tienen prioridad.
4. Mantener el repositorio privado hasta la decisión de lanzamiento; preparar una
   demostración de la app real independiente del vídeo de visión del producto.
