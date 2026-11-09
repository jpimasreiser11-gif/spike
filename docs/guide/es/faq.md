# Preguntas frecuentes y solución de problemas (FAQ)

Idioma: **Español** | [English](../en/faq.md) · [Índice de la guía](README.md)

Esta página documenta todas las comprobaciones diagnósticas de `spike doctor` (`spike/cli.py` y `spike/runtime/hardware.py`) y el catálogo de mensajes de error de cara al usuario (G24): **qué significa**, **causa probable** y **qué hacer** para resolverlo sin perder trabajo.

---

## 1. Comprobaciones de `spike doctor`

Ejecuta `.venv/bin/spike doctor` (o `.venv/bin/spike doctor --json` / `--strict`) para diagnosticar el hardware, el motor local `llama-server` y los modelos GGUF instalados.

### `hardware`
- **Qué significa**: Inspecciona el modelo de CPU (`CPU`), los núcleos físicos/lógicos, las instrucciones vectoriales (`cpu_flags`: `avx2`, `avx512f`, `neon`), la memoria RAM total y libre (`RAM`) y el sistema operativo/arquitectura (`OS`, `apple_silicon`).
- **Causa probable**: Ejecución diagnóstica informativa de `spike doctor` o `spike doctor --json`.
- **Qué hacer**: Comprueba que tienes al menos 8 GB de RAM total (recomendado 16 GB) y suficientes GB disponibles antes de arrancar `llama-server`.

### `recommendation`
- **Qué significa**: Calcula la cuantización recomendada (`quant`, por defecto `Q4_K_M` o `Q8_0` con ≥ 32 GB), longitud de contexto (`context`), tipo de caché KV (`kv_cache_type`, `q8_0`), hilos (`threads`) y capas en GPU (`gpu_layers`).
- **Causa probable**: Ajuste conservador automático a partir de la RAM detectada y si hay aceleración Metal en Apple Silicon.
- **Qué hacer**: Usa estos valores como punto de partida seguro o ejecuta `spike tune` / `spike bench` para medir el rendimiento real en tu máquina.

### `llama_server`
- **Qué significa**: Muestra la ruta absoluta al binario local `llama-server` (de llama.cpp) o `not found` si no está instalado ni configurado.
- **Causa probable**: `llama-server` no está en `PATH`, ni en `~/.spike/bin/`, ni en la variable de entorno `SPIKE_LLAMA_SERVER`.
- **Qué hacer**: Ejecuta `./install.sh` (o `.\install.ps1` en Windows), instala `llama.cpp` o define `SPIKE_LLAMA_SERVER=/ruta/a/llama-server`.

### `models`
- **Qué significa**: Lista cada archivo `.gguf` en `~/.spike/models/` junto con su arquitectura (`arch`), peso en disco (`file_gb`), tamaño de caché KV (`kv_cache_gb`) y memoria total estimada (`estimated_total_gb`, que suma `0.5` GB de buffers de cómputo).
- **Causa probable**: Inspección de cabeceras GGUF locales sin cargar los pesos en memoria.
- **Qué hacer**: Verifica que `estimated_total_gb` cabe holgadamente dentro de tu RAM disponible (`available_ram_gb`).

### `Less than 8 GB RAM: expect slow generation; close other apps.`
- **Qué significa**: El equipo tiene menos de 7,5 GB de RAM total detectada.
- **Causa probable**: El modelo base `Qwen3.5-4B Q4_K_M` requiere ~3,6 GiB de memoria anónima residente más el sistema operativo.
- **Qué hacer**: Cierra navegadores y aplicaciones pesadas antes de usar el motor local, reduce el contexto a 4096/8192 en Ajustes › Motor o conecta un proveedor externo.

### `CPU without AVX2 detected: llama.cpp will run, but several times slower.`
- **Qué significa**: En Linux x86_64/AMD64, el procesador no expone la extensión vectorial `avx2` en `/proc/cpuinfo`.
- **Causa probable**: CPU x86 antigua o máquina virtual con passthrough de CPU genérico sin banderas AVX2.
- **Qué hacer**: Si estás en una máquina virtual (KVM/QEMU/Proxmox), activa el tipo de CPU `host` para exponer AVX2; de lo contrario, reduce el contexto.

### `CPU only: context set to 8K because long prompts are slow without a GPU; raise it in Settings if your CPU is fast.`
- **Qué significa**: Sin aceleración GPU (`gpu_layers == 0`), SPIKE fija la ventana recomendada en 8192 tokens aunque tengas 16 GB o más de RAM.
- **Causa probable**: En una CPU de 4 núcleos, un prompt de 32K cabe en RAM (3,6 GiB anónimos) pero tarda ~1,5 h hasta la primera palabra, mientras que 8K mantiene tiempos utilizables.
- **Qué hacer**: Mantén 8192 tokens en equipos solo CPU, o súbelo manualmente en Ajustes › Motor si cuentas con una CPU de muchos núcleos o GPU.

### `downloaded without a SHA-256 check`
- **Qué significa**: El manifiesto junto al archivo `.gguf` indica `unverified: true` (`[downloaded without a SHA-256 check]`).
- **Causa probable**: El modelo se descargó con `--allow-unverified` o desde un origen que no publicó hash SHA-256 verificable.
- **Qué hacer**: Vuelve a descargar el modelo oficial verificado ejecutando `spike models pull qwen3.5-4b` para comprobar su suma SHA-256.

### `No local models yet. Run: spike models pull`
- **Qué significa**: `spike doctor` no encontró ningún archivo `.gguf` en `~/.spike/models/`.
- **Causa probable**: Acabas de instalar SPIKE y aún no has descargado el modelo base.
- **Qué hacer**: Ejecuta `spike models pull qwen3.5-4b` en el terminal o completa el asistente de primer arranque en la aplicación.

### `no local model (run: spike models pull)`
- **Qué significa**: Fallo en modo estricto (`spike doctor --strict`): código de salida `1` porque falta el modelo local.
- **Causa probable**: Un script o instalador invocó `spike doctor --strict` (sin `--no-model-check`) antes de descargar los pesos.
- **Qué hacer**: Ejecuta `spike models pull qwen3.5-4b` o pasa `--no-model-check` si solo deseas verificar el binario `llama-server`.

### `llama-server was not found (install llama.cpp or set SPIKE_LLAMA_SERVER)`
- **Qué significa**: Fallo en modo estricto (`spike doctor --strict`): código de salida `1` porque no se encontró el ejecutable `llama-server`.
- **Causa probable**: `llama-server` no está instalado en el sistema ni en `~/.spike/bin/`.
- **Qué hacer**: Instala `llama.cpp` (`brew install llama.cpp` en macOS o `./install.sh`) o exporta `SPIKE_LLAMA_SERVER` apuntando al binario.


---

## 2. Mensajes de error de la interfaz y de la API (G24)

Cada código o mensaje devuelto por el servidor se traduce en la interfaz indicando qué ocurrió y la acción recomendada (sin exponer trazas internas ni rutas absolutas del sistema):

| Código / Mensaje del servidor | Qué significa, causa probable y qué hacer (mensaje en la app) |
|---|---|
| `reverse_authorization` | Confirma que la referencia es tuya o que tienes permiso para usarla. |
| `reverse_vision_required` | Una imagen necesita un proveedor con visión. Elige otro proveedor o usa la dirección de una página en este ordenador. |
| `reverse_url` | Solo se abren páginas en este ordenador: http(s) en localhost o 127.0.0.1, sin usuario ni contraseña. |
| `reverse_path` | Elige un archivo .html que exista dentro del proyecto o del espacio de trabajo, con ruta relativa y sin enlaces simbólicos. |
| `reverse_image_size` | La imagen debe medir entre 64 y 4096 píxeles por lado. |
| `reverse_browser_missing` | No hay navegador para leer la página: instala Playwright y un Chromium, o define SPIKE_CHROMIUM. |
| `reverse_capture_failed` | No se pudo abrir la página. Comprueba que el servidor local está en marcha y que la dirección responde. |
| `reverse_invalid_output` | El modelo no devolvió una página HTML. Prueba de nuevo o con otro proveedor. |
| `reverse_failed` | El proveedor o el navegador fallaron. No se ha guardado nada. |
| `reverse_busy` | Ya hay una generación en curso. |
| `reverse_expired` | La vista previa caducó o ya se usó. Vuelve a empezar. |
| `reverse_changed` | El proveedor o el proyecto cambió después de la vista previa. Vuelve a empezar. |
| `reverse_files_blocked` | Este proveedor externo no puede recibir tus archivos. Permítelo en Ajustes › Proveedores. |
| `reverse_provider_blocked` | El proveedor está bloqueado por el permiso de pago o por un tope mensual. Revisa Ajustes › Proveedores. |
| `reverse_context` | La petición no cabe en el contexto del modelo. |
| `reverse_file_missing` | El archivo ya no existe. |
| `reverse_unknown_project` | El proyecto ya no existe. |
| `reverse_unknown_provider` | El proveedor ya no existe. |
| `subtitles_invalid` | Subtítulos no válidos: revisa tiempos, solapamientos, texto y límites. |
| `subtitles_limit` | El archivo supera los límites: 10 minutos, 250 MB, 1000 segmentos o resolución 4096 × 2160. |
| `subtitles_unsupported` | Solo texto plano: no se admiten estilos ni posiciones de subtítulos. |
| `subtitles_split` | Para dividir se necesitan dos palabras y al menos dos milisegundos. |
| `subtitles_path` | Elige una ruta relativa sin enlaces simbólicos dentro del proyecto. |
| `subtitles_source` | No se encuentra un archivo multimedia compatible en esa ruta. |
| `subtitles_whisper` | Falta whisper-cli. Instala whisper.cpp por tu cuenta y configura el modelo en Voz. |
| `subtitles_ffmpeg` | Falta ffmpeg. La edición SRT/VTT sigue disponible. |
| `subtitles_ffprobe` | Falta ffprobe para comprobar el vídeo o audio. |
| `subtitles_wav` | Se requiere audio de hasta 10 minutos; para WAV directo usa mono PCM16 a 16 kHz. |
| `subtitles_command` | El programa local falló o agotó su tiempo. Comprueba modelos, códecs y libass para incrustar subtítulos. |
| `subtitles_video` | Necesitas un vídeo y subtítulos cuyos tiempos estén dentro de su duración. |
| `device_lab_approval` | Confirma que Device Lab puede abrir la página en un navegador sin ventana. |
| `device_lab_android_approval` | Confirma el uso de adb antes de tocar el dispositivo Android. |
| `device_lab_url` | Escribe una dirección http:// o https:// sin espacios ni usuario. |
| `device_lab_host` | Esa dirección no está en este ordenador. Usa localhost, 127.0.0.1 o [::1], o permite el host para esta ejecución. |
| `device_lab_hosts` | Los hosts permitidos son nombres o direcciones IP sueltos: sin esquema, puerto, ruta ni comodines. |
| `device_lab_profile` | Elige al menos un perfil de la lista. |
| `device_lab_custom` | Perfil propio no válido: nombre de hasta 40 caracteres, ancho y alto de 200 a 4000 px, escala de 1 a 4. |
| `device_lab_browser` | Device Lab necesita Playwright y un Chromium (pip install 'spike-ai[motion]' y python -m playwright install chromium, o SPIKE_CHROMIUM). |
| `device_lab_android` | El número de serie del dispositivo Android no es válido o adb devolvió demasiados datos. |
| `device_lab_busy` | Device Lab ya está probando otra página. Espera a que termine. |
| `subtitles_approval` | Confirma la operación local antes de ejecutarla. |
| `file path leaves the project or uses a symbolic link` | La ruta sale del proyecto o usa un enlace simbólico. |
| `too many project notes to export` | Hay demasiadas notas de proyecto para exportar. |
| `invalid project notes or note budget exceeded` | Las notas de proyecto no son válidas o superan el límite. |
| `invalid project note (kind/text)` | Nota de proyecto no válida (tipo o texto). |
| `project notes need a memory store` | Las notas de proyecto necesitan un almacén de memoria. |
| `design system not found` | No se encontró el sistema de diseño. Actualiza la lista o selecciona otro en Diseño. |
| `skill not found` | No se encontró la skill. Actualiza la lista de skills o comprueba su nombre. |
| `built-in skills can be disabled, not deleted` | Las skills integradas no se pueden borrar; desactívalas con su interruptor en Ajustes › Skills. |
| `not a zip archive` | El archivo no es un paquete ZIP válido. Selecciona un archivo .zip. |
| `not a SPIKE project archive (zip)` | El archivo no es un paquete de proyecto de SPIKE (.zip). Exporta un proyecto desde SPIKE e inténtalo de nuevo. |
| `connector not found` | No se encontró el conector. Actualiza la lista en Ajustes › Conectores. |
| `id or preset is required` | Indica un identificador o elige una plantilla de proveedor antes de guardar. |
| `base_url must be an http(s) URL` | La dirección del proveedor debe empezar por http:// o https://. Corrige la URL e inténtalo de nuevo. |
| `provider not found` | No se encontró el proveedor. Revisa Ajustes › Proveedores o selecciona otro proveedor. |
| `the built-in local provider cannot be removed` | El proveedor local integrado no se puede eliminar; puedes cambiar el proveedor por defecto en Ajustes. |
| `request refused: it comes from another web site` | Petición rechazada porque procede de otro sitio web. Usa la interfaz abierta directamente en este ordenador. |
| `a confirmation must name the order in the body and the X-Spike-Confirm header` | Falta la confirmación de la orden. Confirma la orden desde su tarjeta en el chat o en Finanzas. |
| `no open order with that id` | No hay ninguna orden abierta con ese identificador. Actualiza la cartera simulada. |
| `no such order` | No existe esa orden. Actualiza la lista de órdenes en Finanzas. |
| `save an API key for the chosen exchange first` | No hay clave de API guardada para este exchange. Guarda primero la clave en Ajustes › Finanzas. |
| `invalid report` | El informe de datos no es válido. Revisa los bloques de la consulta y vuelve a exportarlo. |
| `format must be docx or pdf` | El formato del informe debe ser Word (docx) o PDF. Elige uno de esos dos formatos. |
| `an image is not valid base64` | Una imagen del informe está dañada. Vuelve a generar el gráfico e inténtalo de nuevo. |
| `invalid Content-Length header` | La cabecera de tamaño de la subida no es válida. Vuelve a enviar el archivo. |
| `project not found` | El proyecto ya no existe. Selecciona otro proyecto o crea uno nuevo. |
| `file not found` | El archivo no existe. Comprueba el nombre o actualiza la lista de archivos del proyecto. |
| `invalid file path` | La ruta del archivo no es válida. Usa una ruta relativa dentro del proyecto, sin «..» ni enlaces simbólicos. |
| `invalid file path: a .git folder is not part of a project's files` | No se pueden guardar archivos dentro de una carpeta .git. Elige otra ruta dentro del proyecto. |
| `project is not a branch` | Este proyecto no es una rama. Crea primero una rama del proyecto para compararla o fusionarla. |
| `conversation not found` | La conversación ya no existe. Selecciona otra en la barra lateral o abre un chat nuevo. |
| `Unknown proof section / Sección de prueba desconocida` | Sección del paquete de pruebas desconocida. Selecciona solo las secciones disponibles y vuelve a exportar. |
| `'before' must be a user message of this conversation` | Solo se puede ramificar desde un mensaje tuyo de esta conversación. Elige un mensaje de usuario. |
| `message not found` | No se encontró el mensaje en esta conversación. Recarga el chat e inténtalo de nuevo. |
| `item not found` | El elemento de Evolución ya no existe. Actualiza la lista. |
| `failure not found` | No se encontró el registro de fallo. Actualiza la pestaña de fallos en Evolución. |
| `an optimisation is already running` | Ya hay una optimización de instrucciones en curso. Espera a que termine o cancélala antes de iniciar otra. |
| `job cancelled` | La tarea se canceló. Puedes volver a iniciarla cuando quieras. |
| `not found` | El recurso solicitado no existe. Actualiza la vista e inténtalo de nuevo. |
| `turn on “Use my corrections to retrain” in Settings → Evolution first` | Activa primero «Usar mis correcciones para reentrenar» en Ajustes › Evolución. |
| `turn on the personal adapter in Settings → Evolución first` | Activa primero el adaptador personal en Ajustes › Evolución. |
| `that chat is not marked` | Esa conversación no estaba marcada para el adaptador personal. Actualiza la lista. |
| `that example is not in the personal set` | Ese ejemplo ya no forma parte del conjunto personal. Actualiza la lista en Evolución. |
| `the previous adapter file is gone` | El archivo del adaptador anterior ya no está en el disco. Instala de nuevo el adaptador aceptado. |
| `memory not found` | La nota de memoria ya no existe. Actualiza la lista en Memoria. |
| `folder not found` | La carpeta indexada ya no está registrada. Actualiza la lista en Memoria › Carpetas. |
| `that folder does not exist or cannot be read` | Esa carpeta no existe o no se puede leer. Comprueba la ruta y los permisos en este ordenador. |
| `that path is not a folder` | La ruta indicada es un archivo, no una carpeta. Escribe la ruta de una carpeta. |
| `choose a folder, not a whole disk` | No se puede indexar el disco entero. Elige una carpeta concreta dentro de tus documentos. |
| `SPIKE's own data folder cannot be indexed` | La carpeta interna de datos de SPIKE no se puede indexar. Elige otra carpeta. |
| `entry not found` | El término del glosario ya no existe. Actualiza el glosario. |
| `topic not found` | El tema de estudio ya no existe. Actualiza la lista en Tutor. |
| `relation not found` | La relación del grafo ya no existe. Actualiza el grafo de memoria. |
| `no pending permission request with this id` | Esta solicitud de permiso ya se respondió o caducó. Continúa en la conversación. |
| `no pending question with this id` | Esta pregunta ya se respondió o caducó. Continúa en la conversación. |
| `No local model configured. Download one with `spike models pull` or set it in Settings.` | No hay ningún modelo local configurado. Descarga uno con `spike models pull` o selecciónalo en Ajustes. |
| `llama-server not found. Install llama.cpp (e.g. `brew install llama.cpp`) or set SPIKE_LLAMA_SERVER.` | No se encontró llama-server. Instala llama.cpp (`brew install llama.cpp`) o define SPIKE_LLAMA_SERVER. |
| `a tuning run is already in progress` | Ya hay un ajuste del motor local en curso. Espera a que termine. |
| `Parallel Prototypes saves files, which needs tools: turn them on in Settings` | Dos enfoques en paralelo guarda archivos y necesita herramientas: actívalas en Ajustes. |
| `each approach must save at least one file (a step with 'deliverables')` | Cada enfoque debe guardar al menos un archivo entregable. Añade un entregable en cada plan. |
| `no such prototype run` | Esa ejecución de prototipos ya no existe. Abre otra o inicia una nueva. |
| `this run is still building` | Esta ejecución de prototipos aún se está construyendo. Espera a que termine antes de descartarla. |
| `Parallel Minds needs a prose answer: it cannot be combined with a Forge blueprint or an answer contract (JSON)` | Mentes en paralelo necesita una respuesta en texto: desactiva el plan de Forge o el contrato JSON. |
| `Parallel Minds runs 2 to 4 minds` | Mentes en paralelo ejecuta entre 2 y 4 mentes. Elige entre 2 y 4 en el selector. |
| `replace_from needs an existing conversation` | Para editar y reenviar un mensaje hace falta una conversación existente. Envía un mensaje nuevo. |
| `replace_from must be a user message of this conversation` | Solo puedes editar y reenviar un mensaje tuyo de esta conversación. |
| `a Forge task cannot also have an answer contract` | Una tarea de Forge no puede combinarse con un contrato JSON. Desactiva uno de los dos. |
| `this blueprint saves files, which needs tools: turn them on in Settings` | Este plan de Forge guarda archivos y necesita herramientas: actívalas en Ajustes. |
| `data_app_expired` | La sesión de la tabla caducó o ya se aplicó. Vuelve a generar la aplicación desde Creador. |
| `data_app_conflict` | El archivo original cambió en el disco desde que se abrió la vista previa. Vuelve a abrir el archivo. |
| `data_app_approval` | Confirma la operación antes de crear la aplicación o guardar cambios en el archivo. |
| `data_app_project` | El proyecto seleccionado ya no existe. Elige otro proyecto. |
| `data_app_invalid` | El archivo o los cambios propuestos no son válidos. Revisa que el archivo sea CSV, TSV, JSON o Excel dentro del proyecto. |
| `describe what the task is` | Escribe qué tarea quieres que realice en el escritorio antes de empezar. |
| `no pending desktop action with this id` | Esta acción de escritorio ya se respondió o terminó. Continúa en el panel de escritorio. |
| `screenshot not found` | La captura de pantalla ya no está disponible. Solo se conservan durante la tarea activa. |
| `Desktop actions are off. Turn them on in Settings → Desktop.` | Las acciones de escritorio están desactivadas. Actívalas primero en Ajustes › Escritorio. |
| `history_filter` | Los filtros de búsqueda no son válidos. Revisa la consulta y el ámbito seleccionado. |
| `project_not_found` | El proyecto seleccionado para la búsqueda ya no existe. Elige otro ámbito. |
| `invalid_target` | Selecciona entre 1 y 4 combinaciones válidas de especialista y proveedor en Lab. |
| `invalid_cases` | Los casos de prueba de Lab no son válidos. Usa una lista JSON con prompt y expected opcional. |
| `one_probe_target` | La sonda de capacidades prueba un único objetivo cada vez. Deja solo un objetivo seleccionado. |
| `expired_quote` | El presupuesto de Lab caducó o ya se usó. Pulsa Vista previa de nuevo antes de ejecutar. |
| `changed_quote` | La configuración del proveedor cambió desde la vista previa. Calcula una nueva vista previa en Lab. |
| `provider_blocked` | El proveedor está bloqueado por el permiso de pago o por un límite mensual. Revisa Ajustes › Proveedores. |
| `unknown_run` | La ejecución de Lab ya no existe. Selecciona otra en el historial de Lab. |
| `Launcher only` | Esta acción solo está disponible desde el lanzador de escritorio de SPIKE. |
| `Adapter unavailable` | Uno de los adaptadores seleccionados aún no está disponible para descargar. Desmárcalo e inténtalo de nuevo. |
| `Installation busy or insufficient resources` | Ya hay una descarga en curso o falta espacio en disco o memoria RAM libre. Libera espacio e inténtalo de nuevo. |
| `Local same-origin JSON request required` | Esta acción requiere una petición local desde la propia ventana de SPIKE. |
| `Spike View is not running: turn it on in Settings first` | Spike View no está en marcha. Activa el navegador en Ajustes › Conectores primero. |
| `Spike View is not running` | Spike View no está en marcha. Activa el navegador en Ajustes › Conectores primero. |
| `this script is being replayed: stop the replay first` | Este guion se está reproduciendo ahora mismo. Detén la reproducción antes de borrarlo. |
| `there is no such script` | El guion de navegador ya no existe. Actualiza la lista de guiones. |
| `the replay is not waiting for that answer` | La reproducción ya no espera esa respuesta. Consulta el estado actual del guion. |
| `unknown specialist` | El especialista indicado no existe. Elige un especialista del catálogo. |
| `job not found` | La tarea en segundo plano ya terminó o no existe. Actualiza la cola de tareas. |

---

## 3. Preguntas frecuentes (FAQ)

### ¿SPIKE envía mis archivos o conversaciones a internet?
No. Por defecto todo ocurre en `127.0.0.1` usando `spike-local` y SQLite en `~/.spike/`. Ninguna ruta hace llamadas externas salvo cuando tú pides explícitamente descargar un modelo, usar `web_fetch` (bajo permiso) o conectar un proveedor remoto. Comprobado automáticamente en `tests/test_no_network_g29.py`.

### ¿Por qué un especialista aparece con la etiqueta `β` (perfil de instrucciones)?
Porque ningún especialista se anuncia como superior al modelo base hasta que su adaptador LoRA supera su puerta de aceptación estadística sin perder conocimiento general (caída máxima de 1,5 puntos en MMLU-Pro general). Hoy **Medicina** ha superado su criterio (+35,07 puntos en medicina, −0,62 en general); los demás responden como perfiles de instrucciones sobre el modelo base.

### ¿Qué hago si una descarga de modelo se corta a mitad?
Vuelve a ejecutar `spike models pull qwen3.5-4b` o pulsa reintentar en el asistente de primer arranque: SPIKE reanuda la descarga desde el archivo parcial `.part` usando cabeceras HTTP `Range` y verifica el hash SHA-256 completo al terminar.
