# Spike — especificación propia de harness para S5

**Fuente:** PLAN.md §§0–2, 6–7, 9, 11, 13–14 · **Fecha:** 2026-10-16. **Estado:** contrato propuesto, sin código procedente de ingeniería inversa.

## Interfaces funcionales previstas

- Daemon Fastify Node 22+ en loopback, compatibilidad OpenAI para chat completions y SSE, lista de modelos, herramientas y fallos tipados; por defecto completamente local.
- CLI Ink/TypeScript con modo interactivo y modo JSON no interactivo, plan, council, permisos, doctor y sesiones reanudables. Nombre de producto Spike decidido en ADR 0001; cambiar el ejecutable histórico nexus requeriría decisión/ADR.
- Planner con salidas JSON restringidas: ID de tarea, dependencies, roles publicados, herramientas autorizadas y DAG acíclico. Si falla validación, router determinista de respaldo y error explícito.
- Router recupera descripciones y propone top-3 vía embeddings locales es/ca/en, sin reentrenar cuando entra un rol nuevo. El planner LoRA organiza herramientas y especialistas reales.
- Inferencia usa una base 4B compartida y adaptadores por petición sujetos a S1–S3, estado de caché aislado; cambios de arquitectura sujetos a ADR.
- RAG y memoria en SQLite local, restricciones por proyecto, citas y linaje; cliente y servidor MCP sometidos a permisos y auditoría.
- Herramientas con modo deny/ask/allow, sandbox de código y terminal, sin exfiltración de secretos ni acceso a red por defecto.

## Contrato de seguridad

Registrar trazas locales con commit, hashes de modelo/LoRA, versión del runtime, hardware, permisos y errores. Redactar secretos y contenido personal; nunca almacenar credenciales en logs. Tratar instrucciones de RAG/MCP/adjuntos como no confiables, separar privilegios y bloquear ejecución si el usuario no autorizó la herramienta. Solo exponer MCP externo cuando haya consentimiento y controles.

## Verificación futura

| Gate | Evidencia |
| --- | --- |
| Streaming | SSE real ordenado, cancelación y propagación de errores |
| Router | >=300 prompts sellados, precisión >=90 % con rol nuevo sin reentrenar |
| Planner | JSON válido >=95 % en ejecuciones reales y DAG acíclico |
| Especialistas | LoRA convertido, evaluado sobre base Q4 final, bootstrap IC95%, regresión <=2 puntos |
| Recursos | Modelos+adaptadores <=6 GB, total <=10 GB, primer token <5 s en CPU 16 GB sin GPU |
| Herramientas | Denegar inyección y privilegios no concedidos, modo air-gapped sin red |
| UI | WCAG AA, teclado, es/ca/en, artefactos con CSP |
| Instalador | Reproducción, SHA-256, desinstalación limpia, coste cero y cero telemetría |

Resultados destinados a publicación solo pueden proceder de make eval y make bench con fecha y commit en reports/. Los mocks únicamente validan contratos y nunca atribuyen capacidad a un modelo.

## Evidencia clean-room

Los requisitos y términos proceden del PLAN.md entregado por Joan. No se ejecutó REA ni se inspeccionaron interfaces propietarias. La investigación futura deberá registrar objetivo autorizado, snapshot, licencia, comportamiento observable, restricciones, autor de la spec y revisión de independencia entre observador e implementador. **S5 no está completado.**
