# SPIKE Dev: saved sessions / sesiones guardadas

Dev can list and reopen a specific conversation in a project folder. It reads the existing local history;
listing does not initialize the application, contact a provider, start a model or create a session database.

```sh
spike dev ./my-project --sessions
spike dev ./my-project --sessions --limit 20 --offset 20
spike dev ./my-project --resume <full-session-ID>
spike dev ./my-project --continue
```

`--sessions` lists the most recently updated conversations **in this folder**, including their full ID, time in UTC,
recorded specialist, message count and a short preview of the first user request. Defaults: 20 per page; `--limit`
accepts 1–100 and `--offset` is non-negative. IDs break equal-time ties. The listing contains project text: review it
before sharing terminal output. Assistant answers are not included in previews; control characters are neutralized.

The interactive terminal also offers `/sessions` for its first page and prints the current session ID at startup.
Use the CLI pagination flags for more pages. `--resume` requires the full ID of a conversation in the selected folder;
an unknown or foreign-folder ID is an error, not a new conversation. `--continue` chooses the latest local session,
even when more than 200 conversations in other folders were updated afterwards. When no previous session exists,
`--continue` still starts a new one, as before.

Listing is separate from execution. Combining `--sessions` with `--print`, `--start-local`, `--accept-edits` or a
provider override is rejected. `--limit` and `--offset` only apply to listing. `--continue`, `--resume` and `--sessions`
are mutually exclusive. A missing database produces an empty list; an unreadable/incompatible database produces an
error without repair, overwrite or migration by the listing code.

## Qué recupera y qué conserva

`--resume ID` recupera los mensajes guardados y su marcado de privacidad. Los nuevos mensajes se añaden a esa sesión.
Los archivos del proyecto siguen en su estado actual: reabrir un chat antiguo **no restaura una versión del código**,
no reproduce herramientas ni reanuda una operación que estaba ejecutándose.

Se mantienen las reglas existentes de Dev: el especialista es `code` por defecto o el indicado con `--specialist`;
el proveedor depende de los enlaces/configuración actuales o de `--provider`. La fila del historial muestra el
especialista registrado originalmente, no una promesa de cuál responderá ahora. La cabecera de la sesión muestra
el especialista/proveedor actual. Ninguna selección de proveedor ni permiso temporal antiguo se activa al recuperar
el historial. Las políticas actuales y opciones explícitas como `--accept-edits` siguen aplicándose.

`/undo` conserva su comportamiento anterior: alcanza los checkpoints de todas las sesiones de la carpeta, no solo los
del chat reabierto. Los comandos de shell no tienen deshacer general. No uses reabrir sesiones como sustituto de Git.

Las carpetas se identifican por su ruta resuelta. Mover o renombrar un proyecto no traslada automáticamente su historial.
Se siguen reconociendo los títulos con rutas nativas de Windows existentes y las nuevas rutas se guardan con `/`.
El formato de la base y los contratos de la app web no cambian. La lectura SQLite conserva visibilidad del WAL y cierra
su conexión al terminar; una copia incompleta de una base activa no se trata como un historial válido.

## Verification

```sh
.venv/bin/python -m pytest -q tests/test_dev_history.py tests/test_dev.py
LC_ALL=C LANG=C .venv/bin/python -X utf8=0 -m pytest -q tests/test_dev_history.py
```

Tests use temporary folders/databases and a scripted provider, including an actual CLI subprocess listing Unicode
history without creating app state. They cover exact folder selection, pagination, more than 200 unrelated chats,
private history, continuation into the chosen conversation, invalid options, read errors and terminal controls.
No training, model downloads or paid calls. **Not measured with real weights**; this is a Dev terminal feature,
not a claim of complete parity with other coding agents or a new Forge/web interface.
