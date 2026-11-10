# Referencia de la API HTTP de SPIKE

Idioma: [English](../en/README.md) | **Español** · [README](../../../README.md)

Generada a partir del OpenAPI de la aplicación con `python scripts/api_reference.py`; la CI la ejecuta con `--check`
y falla si estas páginas están desfasadas. No las edites a mano.

`spike serve` escucha en **http://127.0.0.1:8740** (`--host` y `--port` lo cambian). La aplicación web usa `/api`; cualquier cliente
de OpenAI puede usar `/v1`; los clientes MCP (Claude Code, Cursor, Codex) pueden usar `/mcp`, o `spike mcp` por stdio.
Las descripciones que vienen del código están en inglés.

## Reglas de acceso

- `spike serve` rechaza cualquier petición cuya cabecera `Host` u `Origin` nombre otro equipo (403, contra el DNS
  rebinding y las llamadas desde otras webs). `curl` desde este equipo no envía ninguna de las dos problemáticas.
- Las peticiones que cambian los ajustes deben venir del propio origen de la aplicación o de un programa sin cabecera
  `Origin`.
- `/v1` y `/mcp`: solo programas de este equipo, salvo que SPIKE se arranque con `SPIKE_API_TOKEN`; entonces cada
  petición necesita `Authorization: Bearer $SPIKE_API_TOKEN` (401 sin ella) y puede venir de otro equipo.

## Errores comunes

Cada ruta enumera los códigos que declara o lanza; estos son sus significados habituales.

| Código | Significado |
|---|---|
| `400` | La petición no es válida para esta ruta (valor que falta o es incorrecto, elemento desconocido en el cuerpo). |
| `401` | `/v1`, `/mcp`: `SPIKE_API_TOKEN` está definido y la petición no trae una cabecera `Authorization: Bearer` válida. |
| `403` | Rechazada: `Host`/`Origin` desconocido, petición de navegador sin token o acción que el usuario no ha permitido. |
| `404` | El proyecto, chat, archivo, trabajo u otro elemento de la ruta no existe. |
| `405` | `GET /mcp`: el servidor no envía mensajes propios; usa `POST`. |
| `409` | Conflicto con el estado actual: ocupado, ya en marcha, ya existe o caducado. |
| `413` | La subida supera el límite que indica el mensaje. |
| `422` | El cuerpo o un parámetro no cumple el esquema (validación de FastAPI; la respuesta dice qué campo). |
| `500`, `502` | `/v1`: falló SPIKE o el proveedor de origen; el cuerpo del error explica el motivo. |

## Áreas

| Área | Página | Rutas |
|---|---|---|
| `/api/analytics` | [analytics.md](analytics.md) | 1 |
| `/api/artifact-versions` | [artifact.md](artifact.md) | 3 |
| `/api/backup` | [backup.md](backup.md) | 3 |
| `/api/browser` | [browser.md](browser.md) | 13 |
| `/api/calls` | [calls.md](calls.md) | 2 |
| `/api/chat` | [chat.md](chat.md) | 1 |
| `/api/checkpoints` | [checkpoints.md](checkpoints.md) | 1 |
| `/api/connectors`, `/api/connectors-audit` | [connectors.md](connectors.md) | 9 |
| `/api/conversations` | [conversations.md](conversations.md) | 7 |
| `/api/creator` | [creator.md](creator.md) | 6 |
| `/api/design-systems` | [design.md](design.md) | 5 |
| `/api/desktop` | [desktop.md](desktop.md) | 6 |
| `/api/device-lab` | [device.md](device.md) | 4 |
| `/api/evolution` | [evolution.md](evolution.md) | 22 |
| `/api/finance` | [finance.md](finance.md) | 11 |
| `/api/forge` | [forge.md](forge.md) | 7 |
| `/api/glossary`, `/api/glossary-export`, `/api/glossary-import` | [glossary.md](glossary.md) | 6 |
| `/api/health` | [health.md](health.md) | 1 |
| `/api/history` | [history.md](history.md) | 1 |
| `/api/jobs` | [jobs.md](jobs.md) | 2 |
| `/api/lab` | [lab.md](lab.md) | 4 |
| `/api/media` | [media.md](media.md) | 4 |
| `/api/memory`, `/api/memory-export`, `/api/memory-folders`, `/api/memory-graph`, `/api/memory-import`, `/api/memory-status` | [memory.md](memory.md) | 23 |
| `/api/messages` | [messages.md](messages.md) | 3 |
| `/api/minds` | [minds.md](minds.md) | 1 |
| `/api/pack` | [pack.md](pack.md) | 2 |
| `/api/permissions` | [permissions.md](permissions.md) | 1 |
| `/api/presets` | [presets.md](presets.md) | 1 |
| `/api/privacy` | [privacy.md](privacy.md) | 2 |
| `/api/project-branches`, `/api/projects` | [projects.md](projects.md) | 15 |
| `/api/providers` | [providers.md](providers.md) | 5 |
| `/api/questions` | [questions.md](questions.md) | 1 |
| `/api/research` | [research.md](research.md) | 3 |
| `/api/reverse` | [reverse.md](reverse.md) | 4 |
| `/api/runtime` | [runtime.md](runtime.md) | 3 |
| `/api/samples` | [samples.md](samples.md) | 2 |
| `/api/sandbox` | [sandbox.md](sandbox.md) | 1 |
| `/api/settings` | [settings.md](settings.md) | 2 |
| `/api/setup` | [setup.md](setup.md) | 4 |
| `/api/skills` | [skills.md](skills.md) | 5 |
| `/api/specialist-documents`, `/api/specialists` | [specialists.md](specialists.md) | 2 |
| `/api/subtitles` | [subtitles.md](subtitles.md) | 6 |
| `/api/system` | [system.md](system.md) | 1 |
| `/api/tools` | [tools.md](tools.md) | 1 |
| `/api/tune` | [tune.md](tune.md) | 2 |
| `/api/tutor` | [tutor.md](tutor.md) | 5 |
| `/api/usage` | [usage.md](usage.md) | 1 |
| `/api/workflows` | [workflows.md](workflows.md) | 15 |
| `/api/workspace` | [workspace.md](workspace.md) | 1 |
| `/v1/chat`, `/v1/models` | [v1.md](v1.md) | 2 |
| `/mcp` | [mcp.md](mcp.md) | 2 |

## Límites de esta referencia

- Los códigos de error salen de un análisis estático de cada función y de las funciones auxiliares de `spike.server`
  que llama por su nombre. Un código lanzado más adentro (o con un estado calculado) no aparece; una función auxiliar
  compartida puede listar un código que alguna de las rutas no llega a producir.
- Muchas rutas devuelven objetos JSON sin un modelo declarado, así que su respuesta figura como `object`.
