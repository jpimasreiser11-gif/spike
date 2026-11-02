# SPIKE · Material de lanzamiento para revisión

Estado: preparación, no campaña activa. Público inicial: desarrolladores y usuarios de IA local. Presupuesto nuevo: 0.
Claude revisa capacidades/licencias; Gemini revisa claridad y accesibilidad; Joan aprueba publicar y la oferta comercial.
El calendario se inicia tras aceptar el candidato, no el día de crear este documento.

## Posicionamiento y textos

**Propuesta ES:** «Tu proyecto, tus modelos, resultados que puedes comprobar». SPIKE reúne trabajo con archivos,
programación, análisis y creación en un espacio local configurable, con permisos y resultados editables.
**Propuesta EN:** “Your project. Your models. Results you can check.” A configurable local workspace for coding,
analysis and creation, with reviewable actions and editable outputs.

Esto es posicionamiento propuesto, no evidencia de superioridad. «Más inteligente», «cero errores», «13 modelos
entrenados», «todo funciona con 16 GB» y «número uno de GitHub» no son afirmaciones publicables sin sus pruebas.
Cada anuncio enlaza versión, instrucciones reproducibles, límites y evidencia de la función que muestra.

**Borrador README EN** (integrar solo después de validar las funciones nombradas):

> SPIKE brings your models, tools and project files into one workspace. Start with a reproducible example, inspect
> the changes and keep the editable results. Local and optional remote capabilities depend on your configuration.
> See the tested compatibility matrix, model evaluations and known limitations before installing.

**Apoyo ES:** SPIKE reúne modelos, herramientas y archivos de proyecto. Empieza con un ejemplo reproducible, revisa
los cambios y conserva los resultados editables. Consulta compatibilidad probada, evaluaciones y límites.

**Borrador de anuncio** (reemplazar campos, no publicar así): «Hemos probado [tarea concreta] con SPIKE [versión] en
[hardware]. Aquí están el vídeo sin cortes engañosos, los archivos de ejemplo y cómo repetirlo. Estos son los límites
que encontramos: [límites]. Buscamos ayuda con [issue reproducible y acotada]». CTA: probar una tarea y reportar resultado,
no pedir estrellas sin ofrecer utilidad. No mensajes masivos, compra de estrellas, bots ni promesas de ranking.

## Comparación para orientar la oferta

Fuentes oficiales consultadas el 29 de octubre de 2026; capacidades declaradas por cada producto, no benchmark comparativo.

| Alternativa | Lo que ya ofrece según su documentación | Qué debe demostrar SPIKE |
|---|---|---|
| [Jan](https://docs.jan.ai/desktop/quickstart) | App local, modelos, herramientas web; documentación de proyectos, MCP y Cowork en preview | Menos pasos hasta un resultado revisable en una tarea concreta, medidos con usuarios |
| [Open WebUI](https://docs.openwebui.com/features/) | Múltiples proveedores, archivos, conocimiento y herramientas dentro del espacio de chat | Flujo de trabajo y recuperación más útiles para el público elegido, sin atribuir exclusividad a MCP o RAG |
| [AnythingLLM](https://anythingllm.com/) | Asistente local y privado, aplicación de escritorio gratuita y opciones de producto complementarias | Instalación reproducible y entrega de artefactos con pruebas, evaluadas en la misma tarea |

No se han ensayado estos productos en este estudio; no hay ganadores ni precios comparados inventados. «Local» y
«multi-modelo» por sí solos no son diferenciadores suficientes: es una inferencia de la coincidencia de funciones.

## Oferta elegida y validación económica

| Capa | Contenido | Condición |
|---|---|---|
| Community | Todas las capacidades locales ya prometidas y formatos abiertos | No retirar funciones existentes ni bloquear exportación para forzar pago |
| Pro (hipótesis) | Flujos profesionales nuevos mantenidos, extras de comodidad y actualizaciones de esos extras | Definir entregable y mantenimiento concreto, verificar licencias y demanda antes de cobrar |
| Servicios | Instalación acompañada, formación, soporte e integraciones a medida | Alcance y presupuesto aprobados caso por caso; acceso mínimo y datos bajo control del cliente |

Hipótesis internas para entrevistas, **no precios de venta**: Pro 9/19/29 € por mes, instalación guiada 99/199/299 €,
formación con propuesta cerrada después de conocer necesidad. Validar alternativas de pago único y servicio sin
suscripción. Preguntar por la última tarea y herramientas pagadas antes de enseñar una cifra; no interpretar un
«me gusta» como intención de compra. No se ha entrevistado ni contactado a nadie.

Plan de aprendizaje: Joan recluta voluntarios explícitos; cinco desarrolladores y cinco usuarios de IA local realizan
una tarea propia no sensible. Registrar consentimiento y poder borrar notas. Medir tiempo hasta primer resultado útil,
dónde necesitan ayuda, repetición de uso tras siete días y petición concreta de un extra. Después presentar tres
ofertas acotadas; documentar rechazos y alternativas, sin afirmar que diez entrevistas representan el mercado.

Hoja de costes a rellenar con mediciones: minutos de soporte por instalación × coste/hora, mantenimiento mensual,
distribución/almacenamiento, posibles tarifas de pago, impuestos aplicables, soporte de cada SO y llamadas opcionales.
Sin intermediación de API por defecto: claves propias con costes visibles. Margen por cliente = ingreso neto menos
costes variables medidos; punto de equilibrio = coste fijo / contribución positiva por cliente. Si no hay datos, el
resultado queda pendiente. Sin contratar nube, anuncios, certificados, modelos ni pasarelas automáticamente.

Auditoría previa de Claude: licencia Apache-2.0 de la app; licencia exacta de cada peso/adaptador, dataset, skill,
fuente tipográfica y recurso audiovisual; procedencia, restricciones y avisos que distribuir. La licencia de la app no
resuelve la de sus componentes. Facturación posterior a oferta aprobada: compras, renovación, cancelación, reembolso,
webhooks repetidos, errores y recuperación primero en modo de prueba. Cobros y cuentas comerciales bajo Joan.

## Producción audiovisual

Master: 180 s, 1920×1080, 30 fps, diez capítulos. Capítulos: visión general (12 s); modelos (18); Collective (18);
proyectos/memoria (18); Forge/Dev (18); Design/Creator (18); Analytics/investigación (18); View/MCP (18); Motion (18);
Lab/Evolution/ecosistema (24). Diez stills y clips reutilizables de 10 s; promos 30/60 s y recortes verticales se montan
con planos elegidos, sin acelerar la voz para encajar. Un tutorial independiente cubre detalles que no caben en 3 minutos.

Archivos editables en proyecto Remotion separado del motor, voz española separada, subtítulos ES/EN, fuentes de cada
captura y versión de la app. Cactus original, crema #FDFDFA, menta #E3FADA, verde #88D445, verde oscuro #052E1E. Capturas
reales solo del candidato comprobado, datos de ejemplo, puntero legible y acciones completas. Nada de simular una UI
terminada con imágenes generadas. Futuro: «Visión del producto»; corte acelerado: «Secuencia acelerada ×N».

[Remotion](https://www.remotion.dev/docs/license/pricing) declara licencia gratuita para particulares y empresas de
hasta tres personas, sujeta a condiciones. Antes del render comercial confirmar la elegibilidad del operador real,
incluidos los casos de trabajo para terceros; no deducir tamaño de empresa del número de agentes. Si no corresponde,
Joan decide o se usa otro motor autorizado. No se ha comprado licencia ni habilitado render en nube.

Control antes de exportar: tiempo real de narración natural; pronunciación de SPIKE, Forge, Dev y MCP; nada de textos
cortados, flashes o UI diminuta; misma voz/identidad; subtítulos sincronizados con audio definitivo, no tiempos estimados;
música propia/licenciada si se añade. Reproducir completo master, cada clip y cada recorte. Los fotogramas bonitos no
prueban ni funcionalidad ni aprobación. El render pesado espera a que el trabajo de medicina deje los recursos libres.

## Calendario orgánico de 30 días

Días relativos a lanzamiento autorizado. Cada fila es un borrador de trabajo, no una tarea programada ni un mensaje enviado.

| Día | Pieza / trabajo | Canal propuesto | Evidencia o medida |
|---|---|---|---|
| 1 | README y demo reproducible de una tarea | GitHub | Instalación y artefacto con versión |
| 2 | Tutorial de instalación macOS | Vídeo/docs | Primer resultado en equipo limpio |
| 3 | Tutorial Windows y aviso de instalador sin firma | Vídeo/docs | Instalación final real |
| 4 | Tutorial Linux y dependencias | Vídeo/docs | AppImage probado |
| 5 | Dev: edición, tests y deshacer | Vídeo corto | Archivos antes/después |
| 6 | Resolver primer lote de fallos de instalación | Issues | Fallos reproducidos/resueltos |
| 7 | Resumen de límites conocidos | Discussions | Lista honesta, sin eliminar fallos |
| 8 | CSV → gráfico e informe editable | Vídeo | Datos y cálculo verificable |
| 9 | Proyectos: exportar e importar | Tutorial | Round trip sin pérdidas |
| 10 | Skills: instalación, origen y permisos | Docs | Ejemplo pequeño ejecutable |
| 11 | Responder una necesidad real de comunidad | Comunidad compatible | Ayuda útil, reglas del foro |
| 12 | Crear issues pequeños con reproducción | GitHub | Criterio de aceptación y mentor |
| 13 | Memoria: corregir, borrar y comprobar | Vídeo | Dato de prueba realmente borrado |
| 14 | Revisar retorno de voluntarios | Notas internas | Repetición a siete días, sin telemetría oculta |
| 15 | Comparación honesta modelo solo / Forge | Informe | Calidad, tiempo y consumo; también pérdidas |
| 16 | Creator: documento y presentación editables | Tutorial | Abrir resultados en lectores reales |
| 17 | Conector MCP con denegación de permiso | Vídeo | Acción denegada no ejecutada |
| 18 | Resolver issues antes de nuevas promesas | GitHub | Defectos cerrados con pruebas |
| 19 | Publicar caso aportado con consentimiento | Comunidad | Datos autorizados y reproducción |
| 20 | Explicar benchmark y sus límites | Docs | Configuración exacta, no cifras generales |
| 21 | Sesión de preguntas voluntaria | Discussions | Preguntas reales y respuestas enlazadas |
| 22 | Motion: fuente editable junto al vídeo | Vídeo/tutorial | Render y licencia comprobados |
| 23 | Investigación: cita correcta y cita rechazada | Tutorial | Fragmentos de origen |
| 24 | Guía de contribución ES/EN | GitHub | Instalación de desarrollo probada |
| 25 | Revisar accesibilidad con Gemini | App/docs | Teclado, foco y estados de error |
| 26 | Entrevistas sobre extras Pro/servicios | Voluntarios | Problema y disposición, no cobro |
| 27 | Presentar hipótesis económica a Claude | Documento interno | Costes reales y licencias pendientes |
| 28 | Corregir tutoriales según preguntas | Docs | Menos bloqueos observados |
| 29 | Recap de mejoras y agradecimientos autorizados | GitHub/comunidad | Contribuciones y resultados verificables |
| 30 | Evaluar y decidir siguiente ciclo | Equipo | Instalaciones, retorno, tareas y contribuciones |

[GitHub recomienda etiquetas como `good first issue`](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/encouraging-helpful-contributions-to-your-project-with-labels)
para descubrir oportunidades accesibles. Preparar ejemplos: corregir un mensaje ES/EN con reproducción, completar una
prueba de formato exportado, documentar una dependencia comprobada. No crear issues vacíos para aparentar actividad.

Métricas sin telemetría nueva: instalaciones declaradas con salida de doctor redactada, tareas completadas con artefacto
voluntario, retorno de participantes consentidos, contribuciones aceptadas, tiempo hasta reproducir errores. Estrellas
son una señal secundaria; descargas no equivalen a instalaciones exitosas. Ningún ranking está garantizado.
