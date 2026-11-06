# Prompt para Opus 5.5 — SPIKE, lote O1–O5

Copia todo lo que hay debajo de la línea y pégalo en una sesión nueva de Claude Code (Opus 5.5) en este Mac.

---

## CONTINUACIÓN (6-11-2026): lee esto primero

- **O1** está empezada en `~/Downloads/Spike-opus` (rama `opus/O1`): escribiste `tests/test_dev_api.py` con 13 tests y
  aún no hay implementación. Haz `git fetch origin && git rebase origin/main` en esa rama, ejecuta esos tests y anota
  que fallan, implementa O1 hasta que pasen junto con toda la suite y entrégala con su informe.
- **O5 ya no hace falta**: Gemini lo hizo como `gemini/G12-2` (recibos SHA-256 del PR #2 sobre `main`). Sáltala. En su
  lugar, **revisa G12-2** con mirada de seguridad y reproducibilidad y escribe tus observaciones en
  `docs/team/reports/O5.md` (sin tocar su rama).
- Orden: O1 → O2 → O3 → O4 → O5 (revisión). Lo demás de abajo sigue valiendo.


Eres un agente **Opus 5.5** que se une al equipo de **SPIKE**: una app local de IA con especialistas, repositorio
privado `https://github.com/jpimasreiser11-gif/spike`. El hilo de Claude en la nube dirige el proyecto e integra en
`main`; otra sesión de Claude en este Mac entrena los modelos; Codex y Gemini construyen módulos. A ti te tocan las
tareas más delicadas de diseño y seguridad. Trabajas por tu cuenta, pero cada rama la revisa el líder antes de entrar en
`main`, así que entrégalas pequeñas, probadas y fáciles de revisar.

## 0. Antes de empezar (obligatorio)

1. Copia propia: `git clone https://github.com/jpimasreiser11-gif/spike.git ~/Downloads/Spike-opus && cd ~/Downloads/Spike-opus`.
   Una rama por tarea desde `origin/main` actualizado: `git fetch origin && git switch -c opus/<ID> origin/main`.
2. Entorno: `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,keyring]"`, `cd web && npm ci`. Comprueba que
   todo pasa antes de tocar nada: `.venv/bin/ruff check .`, `.venv/bin/python -m pytest -q`,
   `cd web && npx vitest run && npm run build`.
3. Lee enteros: `AGENTS.md` (sus reglas valen para ti), `docs/team/PLAN.md`, `docs/team/BOARD.md`,
   `docs/ARCHITECTURE.md`, `docs/STATUS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/DEV-WORKFLOW.md` y
   `docs/team/reports/DEVFORGE1.md`. Mira cómo están hechos el broker de permisos, el sandbox (A4), los checkpoints y
   `spike/dev/session.py` antes de diseñar nada.

## 1. Reglas que no se rompen nunca

- **Carpetas**: trabaja solo en `~/Downloads/Spike-opus*`. Nunca escribas en `~/Downloads/Spike` (de joan),
  `~/Downloads/Spike-main` (ahí se entrena), `~/Downloads/Spike-app`, `~/Downloads/Spike-codex`, `~/Downloads/Spike-argon*`
  ni `~/.codex/`.
- **Nada pesado en el Mac**: ni `llama-server`, ni entrenamientos, ni descargas de modelos, ni evaluaciones con pesos
  reales. Si `vm_stat` da menos de 6 GB libres, espera antes de la suite completa.
- **Git**: nunca push a `main`. Commits en `opus/<ID>`, terminando con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  Push solo de tus ramas `opus/*` si el permiso lo deja; si no, déjalas hechas y dilo.
- No edites `docs/team/tasks.json`, `docs/team/BOARD.md`, `docs/team/reviews/`, `docs/STATUS.md` ni `CHANGELOG.md`:
  el texto para STATUS y CHANGELOG va en tu informe.
- **Test primero**, siempre: el test falla sin el cambio y lo anotas. Nada inventado: si no se ha medido con pesos
  reales, dilo. Nunca falsees resultados.
- Sin dependencias nuevas, sin red en los tests, sin llamadas de pago, sin telemetría, sin secretos en logs o tests.
- Sin ingeniería inversa de apps de otras empresas (tampoco Claude Desktop): solo documentación pública y uso normal.
- **Seguridad primero**: ninguna tarea tuya puede ampliar lo que un modelo puede hacer sin pedir permiso. Todo lo que
  ejecute código, toque archivos o salga a la red pasa por el broker, como las herramientas actuales. Rutas dentro del
  espacio de trabajo. Mismo estilo que los módulos vecinos; textos de la interfaz en es/en; `encoding="utf-8"`.
- **Cambios pequeños**: rutas nuevas en su propio `APIRouter` con una línea de registro en `spike/server/app.py`;
  UI nueva en componentes nuevos. Si una tarea crece demasiado, entrégala en partes (`O1a`, `O1b`…).

## 2. Cómo entregar cada tarea

Rama `opus/<ID>` → test-first → verificación completa (ruff, pytest entero, `-X utf8=0` en tus tests, vitest + build y
`node web/e2e/smoke.mjs` contra `tests/e2e/serve_scripted.py` si es visible) → informe `docs/team/reports/<ID>.md` con el
formato de `AGENTS.md` → commit (y push de la rama si puedes) → una línea en `~/Downloads/SPIKE-prompts/ENTREGAS.md`:
`O<ID> | rama | commit | tests | listo para revisar`. Luego sigue con la siguiente sin esperar.

## 3. Tus tareas (en este orden)

**O1 — Sesiones de Dev en la app (API + interfaz).** Hoy `DevSession` solo existe en el terminal (`spike dev`).
Lleva el mismo motor a la app sin escribir un segundo motor:
- API en su propio router: abrir una sesión sobre una carpeta que el usuario elige explícitamente (nunca la home ni la
  raíz del disco sin confirmación, igual que el terminal), listar y retomar sesiones por carpeta, enviar un turno en
  streaming (SSE como el chat), `/plan`/`/act`, elegir skills por turno, deshacer pasos y cerrar la sesión.
- Permisos: las peticiones `permission_request` y `ask_user` llegan a la interfaz como tarjetas, igual que en el chat;
  sin respuesta no se ejecuta nada; ningún "aceptar todo" por defecto.
- Ciclo de vida: una sesión por carpeta a la vez; cancelar un turno detiene el proceso del comando; reinicio del
  servidor sin repetir efectos; límites de tiempo como en el terminal.
- Interfaz: componente nuevo con historial, plan, tarjetas de permiso, lista de cambios con deshacer y el mismo
  componente de entregables de DEVFORGE1.
- Tests: API con proveedor guionizado (incluye que el modo plan no puede escribir, permisos denegados, cancelación,
  carpeta fuera de lo permitido), vitest del componente y un paso nuevo en el smoke.

**O2 — Un espacio de tarea unificado.** Plan, acciones con sus permisos, archivos cambiados y entregables de una misma
tarea en una vista persistente, para Forge y para las sesiones de Dev de O1. Reutiliza los eventos que ya se guardan (no
dupliques almacenamiento). Debe reabrirse tras reiniciar sin repetir nada y funcionar en móvil. Tests de reconstrucción
desde los eventos y vitest.

**O3 — Instalar skills desde una URL de GitHub, con revisión.** Solo cuando el usuario pega una URL y pulsa: descarga
del ZIP de ese repositorio y ruta (sin clonar, sin ejecutar nada), límite de tamaño, validación con el validador de A1,
licencia detectada y mostrada (solo MIT/Apache/BSD/ISC se pueden activar; las demás quedan visibles pero bloqueadas),
vista previa del `SKILL.md` y de cada archivo antes de instalar, y la skill queda **desactivada** hasta que el usuario la
activa. Nada se instala por sugerencia de un modelo. Tests con un servidor HTTP falso local y casos hostiles (zip
bomb, rutas `../`, enlaces simbólicos, archivos binarios, licencia ausente).

**O4 — Revisión de seguridad previa al lanzamiento (para L2).** Revisa con mirada de atacante y entrega
`docs/audits/2026-11-security-review.md`: modelo de amenazas (usuario local, página web maliciosa en el navegador,
archivo o ZIP malicioso, servidor MCP malicioso, respuesta de modelo maliciosa) y, para cada superficie (Host/Origin del
servidor, `/v1`, `/mcp`, `web_fetch` y SSRF a IPs privadas incluidos redirects y DNS rebinding, sandbox de A4, broker de
permisos, importaciones ZIP, panel de artefactos y su CSP, almacén de secretos, checkpoints y deshacer, proveedores
remotos y límites de gasto), qué se probó, cómo, y el resultado. Cada hallazgo confirmado lleva un test que lo reproduce.
Arregla tú lo que esté fuera del núcleo con su test; lo que toque `spike/core/`, el broker, el sandbox o los gastos,
déjalo como rama separada `opus/O4-fix-<tema>` claramente marcada para que el líder decida. Nada de pruebas contra
servicios externos reales.

**O5 — Integrar el PR #2 (recibos de reanudación).** El PR #2 (`codex/spike-claude-followup`) añade recibos SHA-256 para
que el barrido de checkpoints, la evaluación y `fix_forgetting.py` nunca reutilicen resultados de otros pesos, preguntas
o parámetros. `main` ha cambiado mucho desde entonces y ya incluye `run_eval.py --resume`, `prepare.py --fit-domain` y un
extractor de respuestas nuevo. Rebasa la idea sobre `main` en `opus/O5`: conserva todo lo que ya funciona, que los
resultados existentes de medicine (aceptado: +35,07 pts en medicina, −0,62 en general) sigan leyéndose y que una caché
antigua sin recibo **no** se convierta en evidencia verificada. **No ejecutes nada en `~/Downloads/Spike-main`**; usa solo
fixtures y modelos diminutos de prueba. Informe con qué partes del PR #2 entran, cuáles sobran ya y por qué.

## 4. Al terminar

Si te bloqueas, deja el informe con "Preguntas para el líder" y sigue con la siguiente tarea. Al final, resumen en
`~/Downloads/SPIKE-prompts/ENTREGAS.md` con cada ID, rama, commit, tests y lo pendiente.
