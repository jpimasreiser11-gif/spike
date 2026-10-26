# Equipo SPIKE: Claude y Codex

SPIKE lo construyen dos agentes: **Claude** (el líder, en la nube) y **Codex CLI** (el trabajador, en el Mac del dueño). No
se hablan: coordinan solo con archivos en el repositorio y con git. Solo Python estándar, sin dependencias nuevas.

## El flujo

1. Claude escribe `docs/team/PLAN.md` y el tablero `docs/team/tasks.json` y los sube a `main`.
2. El trabajador (`codex_worker.py`), en el Mac, hace `git fetch`, lee el tablero **de `origin/main`** y toma la siguiente
   tarea de `codex`: primero las que están en `changes` (cambios pedidos), luego las `todo`, en el orden del archivo y
   solo si todo lo que declaran en `depends` está `done`.
3. Prepara la rama `codex/<id>` (`todo`: desde `origin/main`; `changes`: desde `origin/codex/<id>` más un merge de
   `origin/main`), ejecuta `codex exec --sandbox workspace-write` con la tarea como prompt (en español), verifica **fuera de
   Codex** (`ruff`, la suite completa de `pytest` y, si cambió `web/`, `vitest` y `npm run build`), añade el resultado al
   informe `docs/team/reports/<ID>.md`, hace commit y `git push -u origin codex/<id>`.
4. Claude revisa la rama. Si pide cambios escribe `docs/team/reviews/<ID>.md`, pone la tarea en `changes` en `main` y el
   trabajador la retoma con ese texto en el prompt. Si está bien, Claude integra la rama en `main` y la marca `done`.

**El trabajador nunca empuja a `main`** (solo ramas `codex/*`), no edita el tablero, nunca ejecuta `git reset --hard`,
`git clean` ni `git checkout -- .` en su copia y no borra nada fuera de su directorio de estado.

## El tablero

```
python scripts/team/board.py check                 # valida docs/team/tasks.json (sale con 1 si hay problemas)
python scripts/team/board.py render                # escribe docs/team/BOARD.md (vista en español; no se edita a mano)
python scripts/team/board.py render --check        # sale con 1 si BOARD.md no está al día (lo usa CI)
python scripts/team/board.py next --owner codex    # la siguiente tarea de ese dueño, en JSON (sale con 3 si no hay)
python scripts/team/board.py show X1               # una tarea, en JSON
```

Cada tarea: `id` (`^[A-Z]{1,2}\d{1,3}$`, único), `owner` (`claude`, `codex`, `mac`, `joan`), `status` (`todo`, `doing`,
`review`, `changes`, `done`, `blocked`), `phase`, `title`, `depends` (ids existentes, sin ciclos), `paths`, `spec` y `accept`
(lista no vacía de criterios). `check` imprime cada problema que encuentra.

## El trabajador (en el Mac)

`--repo` es una copia de git (worktree o clon) **solo para Codex**, por ejemplo `~/Downloads/Spike-codex`, con `origin`
apuntando al repositorio.

```
python scripts/team/codex_worker.py setup --repo ~/Downloads/Spike-codex     # una vez: .venv y web/node_modules si faltan
nohup python scripts/team/codex_worker.py run --repo ~/Downloads/Spike-codex >/dev/null 2>&1 &    # desacoplado
python scripts/team/codex_worker.py status                                   # qué hace y qué hizo (JSON)
python scripts/team/codex_worker.py stop                                     # termina en el próximo paso
```

Opciones de `run`: `--codex RUTA` (si no, la variable `SPIKE_CODEX`, si no `codex` en el `PATH`; sin Codex sale con
código 2), `--once` (una tarea y termina), `--poll SEGUNDOS` (espera si no hay nada, 900), `--state DIR` (por defecto
`~/.spike-team`), `--min-free-gb` (4) y `--timeout SEGUNDOS` (Codex se mata a las 3 h, 10800).
`setup` crea `.venv` con `python3.13`, `3.12` o `3.11` (o `--python`) y ejecuta `pip install -e ".[dev]"`; si hay
`web/package.json` y falta `web/node_modules`, ejecuta `npm ci` en `web/`.

### Qué protege

- **Copia limpia**: si la copia tiene cambios sin confirmar cuando va a empezar una tarea, **se niega** y dice por qué
  (`--once` sale con 5; en bucle lo anota en `worker.log` y lo vuelve a mirar en la siguiente pasada). No toca esos cambios.
- **Un solo trabajador por directorio de estado**: `worker.lock` guarda el pid; si ese pid ya no existe, el candado se
  considera viejo y se reemplaza. Un segundo trabajador sale con 4.
- **Memoria**: el Mac también entrena modelos. Antes de lanzar Codex y antes de cada comando de verificación espera,
  mirando cada 60 s, mientras la RAM libre esté por debajo de `--min-free-gb` (macOS: `vm_stat`, páginas libres + inactivas
  + especulativas; Linux: `MemAvailable`; otra plataforma: no espera). Lo anota una vez en el registro.
- **Red**: `git fetch` y `git push` se reintentan 4 veces con esperas de 2, 4, 8 y 16 s.
- **Límite de uso de Codex** (salida con error que menciona `rate limit`, `usage limit`, `429` o `try again`): no hace
  commit, anota `rate_limited`, espera 30 min (o lo que diga `try again in 2 hours 30 minutes`, con tope de 6 h) y repite la
  misma tarea sobre lo que Codex dejó a medias. Con `--once` anota y termina.

### Directorio de estado (`~/.spike-team`)

| Archivo | Contenido |
|---|---|
| `state.json` | por tarea: `id`, `status_on_board`, `branch`, `head_sha`, `pushed_utc`, `result`, `review_sha`; tarea en curso; motivo si está bloqueado |
| `worker.log` | una línea por paso, con hora UTC |
| `worker.lock` | pid del trabajador en marcha |
| `STOP` | lo crea `stop`; el trabajador lo borra al terminar |
| `prompt-<ID>.md`, `last-<ID>.md`, `codex-<ID>.log` | el prompt enviado, el último mensaje de Codex y su salida |

`result` es uno de: `ok`, `verify_failed` (la verificación falló: se sube igual para que Claude lo vea), `no_changes`,
`failed` (Codex falló o pasó el tiempo: se guardan las últimas 40 líneas y lo que dejó queda en un commit local `WIP`, sin
subir, para que la copia quede limpia), `rate_limited`, `conflict` (el merge de `main` en la rama revisada chocó: se aborta
y lo resuelve Claude), `push_failed` (red: solo se repite el push) y `push_rejected`.

Una tarea ya subida no se vuelve a hacer mientras el tablero muestre el mismo estado y el mismo archivo de revisión (el
sha del blob de `docs/team/reviews/<ID>.md` en `origin/main`); un estado nuevo o una revisión nueva la hacen elegible otra
vez. Una tarea `failed` tampoco se reintenta hasta que cambie el tablero o la revisión.

### Cómo pararlo

`python scripts/team/codex_worker.py stop` crea `STOP`: el trabajador termina cuando está esperando o entre tareas; una tarea
en curso se acaba antes (Codex no se interrumpe a medias). Con `kill <pid>` (pid en `status`) también termina limpio y
detiene a Codex y a sus procesos hijos.

## Pruebas

`pytest -q tests/test_team.py`: sin red y sin Codex real. Usa repositorios git en un directorio temporal (un origen bare, el
clon del líder y el del trabajador) y un Codex falso. Los comandos de verificación se sustituyen con la variable de entorno
`SPIKE_TEAM_VERIFY` (una línea de comando que se ejecuta una vez en la copia en lugar de `ruff`, `pytest`, `vitest` y la
compilación); es solo para pruebas. Los comandos de verificación reales llevan `SPIKE_NO_KEYRING=1` para que el Mac no
pida acceso al llavero.
