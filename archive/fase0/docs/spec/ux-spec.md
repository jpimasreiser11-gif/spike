# Spike Studio — especificación UX original para S5

**Fuente:** PLAN.md §§1, 6, 8, 13–14 · **Fecha:** 2026-10-16 · **Estado:** especificación original pendiente de investigación REA y validación. No contiene código, textos ni assets extraídos de productos ajenos.

## Experiencia de usuario

Studio permite hablar con el modelo local y elegir especialistas solo si sus adaptadores han superado su gate. Por defecto no necesita cuenta ni red. Toda salida a proveedores externos requiere decisión explícita. La interfaz jamás dice que un modelo está activo si falta su GGUF o LoRA.

Los estados navegables son:

1. **Primer arranque / sin modelos:** diagnóstico de hardware, RAM, red y pesos instalados, con mensaje específico cuando falta un modelo; enlace a información de licencia y hash antes de obtenerlo voluntariamente.
2. **Preparado:** nueva conversación, selector Auto (predeterminado), Manual (roles publicados), Council (cola según RAM disponible), selección de proyecto e historial local.
3. **Planificación:** DAG inspeccionable con lista accesible de pasos, especialistas, verificadores y permisos de herramientas antes de ejecutar acciones que exigen confirmación.
4. **Ejecutando:** respuesta SSE, rol utilizado, estado de cada herramienta, cancelación, latencia y RSS reales cuando exista instrumentación. Mostrar errores de adaptador, memoria, licencia o conexión con causa verificable.
5. **Resultado:** citas de Knowledge Pack y procedencia, razonamiento plegable, artefactos Markdown, HTML, SVG, Mermaid, código, CSV y gráficos; selector vista previa/código/descarga, iframe sin privilegios con CSP.
6. **Gestión:** catálogo de roles con licencia, estado, evaluaciones reales y pesos; memoria, Knowledge Packs, permisos MCP y configuración de proveedor solo bajo opt-in.

## Navegación y restricciones

| Panel | Contenido | Regla de seguridad |
| --- | --- | --- |
| Conversación | Mensajes, adjuntos, historial, modo, especialista | Datos en el dispositivo por defecto |
| Plan y Swarm Visualizer | DAG y lista de pasos, verificación, rol | Mostrar acciones pendientes antes de ejecutarlas |
| Catálogo | Ocho Tier 1, estado, pesos, licencia y report de evaluación | Sin afirmar que un rol no entrenado existe |
| Knowledge Packs | Documentos indexados y citas verificables | Licencias por fuente y exclusión de PII |
| Bench | Informes fechados ligados a commit/modelo/hardware | Ocultar métricas inexistentes |
| Ajustes | política off/standard/strict, herramientas allow/ask/deny, red, keychain | Sin telemetría ni proveedores remotos por defecto |

## Diseño y accesibilidad

Objetivos obligatorios: es/ca/en, claro/oscuro, WCAG AA, navegación por teclado, foco visible, lector de pantalla y movimiento reducido. El DAG siempre tiene alternativa textual. El rendimiento local inferior a 1,5 segundos es un objetivo por medir sobre hardware representativo. La paleta, el logo SVG y fuentes OFL serán propios; ningún asset de terceros se copia. UI y componentes de seguridad quedan para F5 después del gate.

## Criterios de prueba futuros

Primer inicio sin modelo; modo air-gapped; Auto/Manual/Council; OOM; cancelación SSE; consentimiento de herramienta; fallo MCP; denegación de acceso a red; adjuntos con prompt injection; sandbox de artefactos maliciosos; teclado e idiomas; reporte falso bloqueado; recuperación tras cerrar. E2E con modelo fake prueba la interfaz, y debe diferenciarse de inferencia real.

## Estado S5

Este documento se ha derivado exclusivamente de los requisitos propios de PLAN.md. S5 solicita UX **con REA** aplicado a objetivos autorizados y separación clean-room. REA no está operativo porque el instalador, dependencias y efectos aún no han superado la auditoría integral. Por ello falta obtener evidencia de observación autorizada y S5 sigue **NOT RUN/PENDING**.
