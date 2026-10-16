# Spike — instrucciones obligatorias para agentes

Proyecto de Joan. El nombre aprobado del sistema es **Spike** y sus modelos se denominan `Spike <especialidad>` (por ejemplo, `Spike Finance`).

## Fuente de verdad y límites

`PLAN.md` completo es la fuente de verdad. **Actualmente falta en este checkout**: el texto recibido termina dentro del apartado 5.2 del Plan Maestro v3. No reconstruir ni inventar las secciones restantes; solicitar la fuente íntegra. No avanzar a Fase 1 sin el visto bueno explícito de Joan, conforme a su instrucción más reciente. Los cambios de arquitectura deben documentarse en `docs/adr/` y confirmarse si alteran decisiones vinculantes.

## Reglas de §0 del Plan Maestro v3

1. **Nada sin medir**: toda cifra pública sale de `make eval` / `make bench` y se conserva en `reports/`, con fecha y commit.
2. **Gates**: cada fase termina con criterios verificables. Ante fallo, detener la fase, documentar en `docs/spikes/` y proponer Plan B; jamás maquillar resultados.
3. **Coste 0 €**: usar solo herramientas, datos y cómputo gratuitos. Reportar cualquier servicio de pago como bloqueo.
4. **Equipo objetivo: 16 GB RAM sin GPU dedicada**. El Mac de desarrollo de 36 GB no demuestra cumplimiento de este límite.
5. **Clean-room** ante productos de terceros: no copiar código, assets, fuentes, iconos, textos, nombres ni marcas. Solo reutilizar código legítimamente licenciado con atribución y límites explícitos.
6. **Licencias y procedencia**: registrar fuentes en `DATA_LICENSES.md`, excluir entrenamiento con salidas prohibidas por términos de servicio (ChatGPT, Claude, Gemini), evitar NC y comprobar share-alike.
7. **Datasets vetados**: armas, CBRN, síntesis peligrosa, malware/exploits operativos y material de menores. Mejorar respuesta a consultas legítimas sin debilitar seguridad.
8. **Auditoría previa a skill/MCP**: fijar commit, leer `SKILL.md` y scripts; rechazar ejecución o descargas no explicadas.
9. **Calidad**: commits convencionales, PR pequeños, pruebas en cada módulo y CI verde antes de fusionar.
10. **Dudas**: un solo mensaje agrupado para Joan; nunca suponer datos o resultados.

## Flujo de desarrollo

Para cada módulo: diseño y plan, desarrollo guiado por tests, revisión y comprobación antes de declarar un gate PASS. El protocolo de skills descrito en el Plan Maestro v3 se aplica tras la auditoría de cada dependencia. Preservar cualquier trabajo ajeno; nunca reiniciar el repositorio para ocultar errores.

## Entrega de fase

Informar sobre cambios realizados, comandos y salidas verificables, tabla PASS/FAIL, riesgos pendientes y siguiente paso. Los ocho roles Tier 1 exigen LoRAs entrenados y mejoras estadísticas sobre sus versiones cuantizadas antes de publicar; un rol declarado en YAML no cuenta como modelo validado.
