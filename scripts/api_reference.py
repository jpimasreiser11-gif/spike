"""Write docs/api/{en,es}/*.md from the app's own OpenAPI, so the HTTP reference cannot drift from the code (G37).

Covers `/api`, the OpenAI-compatible `/v1` and `/mcp` (which is outside the OpenAPI schema). Parameters, body fields
and types come from `create_app().openapi()`; the error codes come from FastAPI's declared responses plus a static
scan of each handler (and the `spike.server` helpers it calls) for `HTTPException`, `ApiError` and error responses.
The output is sorted and has no timestamps or versions, so it only changes when the API does.

    python scripts/api_reference.py          # rewrite docs/api
    python scripts/api_reference.py --check  # exit 1 if docs/api is stale (CI)
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import inspect
import json
import re
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spike.cli import build_parser  # noqa: E402

LANGS = ("en", "es")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def default_port() -> int:
    """The port `spike serve` listens on unless told otherwise, read from the CLI parser."""
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return next(a.default for a in sub.choices["serve"]._actions if "--port" in a.option_strings)


BASE = f"http://127.0.0.1:{default_port()}"

T = {
    "en": {
        "lang": "Language: [Español](../es/{page}) | **English** · [API index](README.md)",
        "params": "Parameters", "body": "Body", "response": "Response", "errors": "Errors", "example": "Example",
        "code": "Code", "handler": "Handler", "pcols": ("Name", "In", "Type", "Required", "Default"),
        "fcols": ("Field", "Type", "Required", "Default", "Description"), "ecols": ("Code", "Message"),
        "yes": "yes", "any_json": "Any JSON value; the handler reads it itself.",
        "raw_json": "a JSON object the handler reads itself; its fields are not in the schema.",
        "raw_raw": "the file's bytes (`application/octet-stream`), read by the handler.",
        "validation": "the request does not match the schema (FastAPI validation)",
        "dynamic": "(message built at run time)", "routes": "routes", "area": "Area", "page": "Page",
        "area_title": "API reference: {area}",
    },
    "es": {
        "lang": "Idioma: [English](../en/{page}) | **Español** · [Índice de la API](README.md)",
        "params": "Parámetros", "body": "Cuerpo", "response": "Respuesta", "errors": "Errores", "example": "Ejemplo",
        "code": "Código", "handler": "Función", "pcols": ("Nombre", "En", "Tipo", "Obligatorio", "Por defecto"),
        "fcols": ("Campo", "Tipo", "Obligatorio", "Por defecto", "Descripción"), "ecols": ("Código", "Mensaje"),
        "yes": "sí", "any_json": "Cualquier valor JSON; la función lo lee por su cuenta.",
        "raw_json": "un objeto JSON que la función lee por su cuenta; sus campos no están en el esquema.",
        "raw_raw": "los bytes del archivo (`application/octet-stream`), leídos por la función.",
        "validation": "la petición no cumple el esquema (validación de FastAPI)",
        "dynamic": "(mensaje construido al ejecutar)", "routes": "rutas", "area": "Área", "page": "Página",
        "area_title": "Referencia de la API: {area}",
    },
}

INTRO = {
    "en": """# SPIKE HTTP API reference

Language: [Español](../es/README.md) | **English** · [README](../../../README.md)

Generated from the app's OpenAPI by `python scripts/api_reference.py`; CI runs it with `--check` and fails when these
pages are stale. Do not edit them by hand.

`spike serve` listens on **{base}** (`--host` and `--port` change it). The web app uses `/api`; any OpenAI client can
use `/v1`; MCP clients (Claude Code, Cursor, Codex) can use `/mcp`, or `spike mcp` over stdio.

## Access rules

- `spike serve` refuses any request whose `Host` or `Origin` header names another host (403, against DNS rebinding and
  calls from other sites). `curl` from this computer sends neither problem header.
- Requests that change settings must come from the app's own origin or from a program without an `Origin` header.
- `/v1` and `/mcp`: only programs on this computer, unless SPIKE runs with `SPIKE_API_TOKEN` set; then every request
  needs `Authorization: Bearer $SPIKE_API_TOKEN` (401 without it) and may come from another machine.

## Common errors

Each route lists the codes it declares or raises; these are the usual meanings.

| Code | Meaning |
|---|---|
| `400` | The request is not valid for this route (missing or wrong value, unknown item named in the body). |
| `401` | `/v1`, `/mcp`: `SPIKE_API_TOKEN` is set and the request has no valid `Authorization: Bearer` header. |
| `403` | Refused: unknown `Host`/`Origin`, a browser request without a token, or an action the user has not allowed. |
| `404` | The project, chat, file, job or other item named in the path does not exist. |
| `405` | `GET /mcp`: the server sends no messages of its own; use `POST`. |
| `409` | Conflict with the current state: busy, already running, already exists, or expired. |
| `413` | The upload is larger than the limit the message names. |
| `422` | The body or a parameter does not match the schema (FastAPI validation; the answer says which field). |
| `500`, `502` | `/v1`: SPIKE or the upstream provider failed; the error body says why. |

## Areas

| Area | Page | Routes |
|---|---|---|
""",
    "es": """# Referencia de la API HTTP de SPIKE

Idioma: [English](../en/README.md) | **Español** · [README](../../../README.md)

Generada a partir del OpenAPI de la aplicación con `python scripts/api_reference.py`; la CI la ejecuta con `--check`
y falla si estas páginas están desfasadas. No las edites a mano.

`spike serve` escucha en **{base}** (`--host` y `--port` lo cambian). La aplicación web usa `/api`; cualquier cliente
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
""",
}

LIMITS = {
    "en": """
## Limits of this reference

- Error codes come from a static scan of each handler and the `spike.server` helpers it calls by name. A code raised
  deeper (or with a computed status) is not listed; a helper shared by several routes may list a code that one of
  them never reaches.
- Many routes return plain JSON objects without a declared model, so their response is listed as `object`.
""",
    "es": """
## Límites de esta referencia

- Los códigos de error salen de un análisis estático de cada función y de las funciones auxiliares de `spike.server`
  que llama por su nombre. Un código lanzado más adentro (o con un estado calculado) no aparece; una función auxiliar
  compartida puede listar un código que alguna de las rutas no llega a producir.
- Muchas rutas devuelven objetos JSON sin un modelo declarado, así que su respuesta figura como `object`.
""",
}

LANDING = """# API reference / Referencia de la API

- **[English](en/README.md)**
- **[Español](es/README.md)**

Generated by `python scripts/api_reference.py` from the app's OpenAPI; `--check` runs in CI. /
Generada por `python scripts/api_reference.py` a partir del OpenAPI de la aplicación; `--check` se ejecuta en la CI.
"""

# /v1/chat/completions reads its JSON body itself and /mcp is outside the schema: their bodies are described here.
V1_BODY = [
    ("model", "string", True, "`spike-auto`, `spike-<specialist>` or `<provider>/<model>` (see `GET /v1/models`)",
     "`spike-auto`, `spike-<especialista>` o `<proveedor>/<modelo>` (ver `GET /v1/models`)"),
    ("messages", "object[]", True, "`role` (`system`, `user`, `assistant`, `tool`) and `content` (text)",
     "`role` (`system`, `user`, `assistant`, `tool`) y `content` (texto)"),
    ("stream", "boolean", False, "answer as server-sent events", "responder como eventos SSE"),
    ("stream_options.include_usage", "boolean", False, "add a usage chunk at the end of a stream",
     "añadir el uso de tokens al final del stream"),
    ("tools", "object[]", False, "function tools of the client; the model's calls go back to the client",
     "herramientas de función del cliente; las llamadas vuelven al cliente"),
    ("tool_choice", "string", False, "`none` drops the tools", "`none` descarta las herramientas"),
    ("response_format", "object", False, "`{\"type\": \"json_object\"}` or `json_schema` with a `schema`",
     "`{\"type\": \"json_object\"}` o `json_schema` con un `schema`"),
    ("temperature", "number", False, "", ""),
    ("top_p", "number", False, "", ""),
    ("max_tokens", "integer", False, "also `max_completion_tokens`", "también `max_completion_tokens`"),
    ("stop", "string \\| string[]", False, "", ""),
    ("n", "integer", False, "only 1 is supported", "solo se admite 1"),
]
V1_EXAMPLE = {"model": "spike-auto", "messages": [{"role": "user", "content": "Hello"}]}

MCP_BODY = [
    ("jsonrpc", "\"2.0\"", True, "", ""),
    ("id", "integer \\| string", False, "without it the message is a notification: answer `202`, no body",
     "sin él el mensaje es una notificación: respuesta `202` sin cuerpo"),
    ("method", "string", True, "`initialize`, `ping`, `tools/list` or `tools/call`",
     "`initialize`, `ping`, `tools/list` o `tools/call`"),
    ("params.name", "string", False, "`tools/call`: `ask_spike` or `spike_<specialist>`",
     "`tools/call`: `ask_spike` o `spike_<especialista>`"),
    ("params.arguments.question", "string", False, "`tools/call`: the question (required by every tool)",
     "`tools/call`: la pregunta (obligatoria en todas las herramientas)"),
    ("params.arguments.specialist", "string", False, "`ask_spike`: a specialist id, or `auto`",
     "`ask_spike`: un id de especialista, o `auto`"),
    ("params.arguments.context", "string", False, "material to answer about", "material sobre el que responder"),
]
MCP_EXAMPLE = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
MCP_NOTE = {
    "en": "JSON-RPC 2.0 over Streamable HTTP with JSON answers. Protocol errors come back with HTTP 200 and a JSON-RPC "
          "`error`: `-32700` invalid JSON (HTTP 400), `-32600` not a JSON-RPC 2.0 message, `-32601` unknown method, "
          "`-32602` bad `arguments` or unknown tool.",
    "es": "JSON-RPC 2.0 sobre Streamable HTTP con respuestas JSON. Los errores del protocolo vuelven con HTTP 200 y un "
          "`error` JSON-RPC: `-32700` JSON no válido (HTTP 400), `-32600` no es un mensaje JSON-RPC 2.0, `-32601` "
          "método desconocido, `-32602` `arguments` incorrectos o herramienta desconocida.",
}
SUPPLEMENT = {("POST", "/v1/chat/completions"): (V1_BODY, V1_EXAMPLE), ("POST", "/mcp"): (MCP_BODY, MCP_EXAMPLE)}


# ---------------------------------------------------------------------------------------------- app and routes
def build_app(home: Path):
    from spike.server.app import create_app
    from spike.server.state import AppState

    return create_app(AppState(home=Path(home)))


def flat_routes(routes):
    for route in routes:
        if hasattr(route, "original_router"):  # FastAPI's included routers keep their own route list
            yield from flat_routes(route.original_router.routes)
        elif hasattr(route, "endpoint"):
            yield route


def area_of(path: str, bases: set[str]) -> str:
    if path.startswith("/v1"):
        return "v1"
    if path.startswith("/mcp"):
        return "mcp"
    base = path.split("/")[2].split("-")[0]
    return base + "s" if base + "s" in bases else base


# ---------------------------------------------------------------------------------------------- schema → text
def cell(text: Any) -> str:
    """One table cell: one line, pipes escaped, and `<name>` kept visible outside code spans (not read as HTML)."""
    parts = " ".join(str(text).split()).replace("|", "\\|").split("`")
    return "`".join(p if i % 2 else p.replace("<", "&lt;").replace(">", "&gt;") for i, p in enumerate(parts))


def resolve(schema: dict, comps: dict) -> dict:
    while "$ref" in schema:
        schema = comps.get(schema["$ref"].split("/")[-1], {})
    return schema


def type_of(schema: dict | None, comps: dict) -> str:
    schema = resolve(schema or {}, comps)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            seen: list[str] = []
            for option in schema[key]:
                text = type_of(option, comps)
                if text not in seen:
                    seen.append(text)
            return " | ".join(seen)
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(kind)
    if kind == "array":
        item = type_of(schema.get("items"), comps)
        return f"({item})[]" if " | " in item else f"{item}[]"
    if kind == "string" and schema.get("format") == "binary" or schema.get("contentMediaType"):
        return "file"
    if kind == "string" and schema.get("format"):
        return f"string ({schema['format']})"
    if kind == "object" or "properties" in schema or "additionalProperties" in schema:
        return "object"
    return kind or "any"


def expandable(schema: dict, comps: dict) -> tuple[str, dict] | None:
    """The object schema under a property worth expanding into dotted rows, and the suffix its rows take."""
    schema = resolve(schema, comps)
    options = [resolve(o, comps) for o in schema.get("anyOf", [])]
    options = [o for o in options if o.get("type") != "null"]
    if len(options) == 1:
        schema = options[0]
    if schema.get("properties"):
        return ".", schema
    if schema.get("type") == "array":
        item = resolve(schema.get("items") or {}, comps)
        if item.get("properties"):
            return "[].", item
    return None


def field_rows(schema: dict, comps: dict, lang: str, prefix: str = "", depth: int = 0) -> list[str]:
    schema = resolve(schema, comps)
    required = set(schema.get("required", []))
    rows = []
    for name, prop in schema.get("properties", {}).items():
        target = resolve(prop, comps)
        default = f"`{json.dumps(prop['default'], ensure_ascii=False)}`" if "default" in prop else ""
        description = prop.get("description") or target.get("description") or ""
        rows.append(f"| `{prefix}{name}` | {cell(type_of(prop, comps))} | {T[lang]['yes'] if name in required else ''}"
                    f" | {cell(default)} | {cell(description)} |")
        sub = expandable(prop, comps)
        if sub and depth < 2:
            rows += field_rows(sub[1], comps, lang, f"{prefix}{name}{sub[0]}", depth + 1)
    return rows


def example(schema: dict, comps: dict, depth: int = 0) -> Any:
    schema = resolve(schema or {}, comps)
    if schema.get("default") is not None:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf"):
        options = [o for o in schema.get(key, []) if resolve(o, comps).get("type") != "null"]
        if options:
            return example(options[0], comps, depth)
    kind = schema.get("type")
    if kind == "array":
        return [example(schema.get("items") or {}, comps, depth + 1)] if depth < 3 else []
    if kind == "string":
        return "string"
    if kind in ("integer", "number"):
        return 0
    if kind == "boolean":
        return False
    props = schema.get("properties") or {}
    if not props or depth >= 3:
        return {}
    keys = [k for k in props if k in schema.get("required", [])] or ([next(iter(props))] if depth == 0 else [])
    return {k: example(props[k], comps, depth + 1) for k in keys}


# ---------------------------------------------------------------------------------------------- errors
def _status(node: ast.Call) -> int | None:
    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
    value = None
    if name in ("HTTPException", "ApiError") and node.args:
        value = node.args[0]
    for kw in node.keywords:
        if kw.arg == "status_code":
            value = kw.value
    if name in ("HTTPException", "ApiError", "JSONResponse", "Response", "PlainTextResponse") and \
            isinstance(value, ast.Constant) and isinstance(value.value, int) and value.value >= 400:
        return value.value
    return None


def _message(node: ast.Call, dynamic: str, scope: dict) -> str:
    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
    candidates = [kw.value for kw in node.keywords if kw.arg in ("detail", "message", "content")]
    if name in ("HTTPException", "ApiError") and len(node.args) > 1:
        candidates.insert(0, node.args[1])
    elif name not in ("HTTPException", "ApiError") and node.args:
        candidates.insert(0, node.args[0])
    for value in candidates:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.JoinedStr):
            return "".join(p.value if isinstance(p, ast.Constant) else _inline(p.value, scope) for p in value.values)
        strings = [n.value for n in ast.walk(value) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        if strings and not isinstance(value, ast.Name):
            return max(strings, key=len)
    return dynamic if candidates else ""


def _inline(node: ast.expr, scope: dict) -> str:
    """A module constant inside an f-string (`{TOKEN_ENV}`) is shown by its value; anything else as `{…}`."""
    if isinstance(node, ast.Name) and isinstance(scope.get(node.id), str) and node.id.isupper():
        return scope[node.id]
    return "{…}"


def raised(fn, dynamic: str, seen: set | None = None, depth: int = 0) -> set[tuple[int, str]]:
    """(status, message) pairs a handler raises or returns, following the spike.server helpers it calls by name."""
    seen = set() if seen is None else seen
    if fn in seen or depth > 4:
        return set()
    seen.add(fn)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return set()
    scope = dict(getattr(fn, "__globals__", {}))
    for name, cell_ in zip(fn.__code__.co_freevars, fn.__closure__ or (), strict=False):
        with contextlib.suppress(ValueError):  # a cell not filled yet
            scope[name] = cell_.cell_contents
    out: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        status = _status(node)
        if status:
            out.add((status, _message(node, dynamic, scope)))
        if isinstance(node.func, ast.Name):
            target = scope.get(node.func.id)
            module = getattr(target, "__module__", "") or ""
            if inspect.isfunction(target) and (module.startswith("spike.server") or module == fn.__module__):
                out |= raised(target, dynamic, seen, depth + 1)
    return out


def raw_body(endpoint) -> str | None:
    """How a handler without a declared body reads one itself: "json", "raw" bytes, or None."""
    try:
        source = inspect.getsource(endpoint)
    except (OSError, TypeError):
        return None
    if any(m in source for m in ("request.json()", "json.loads(await read_body", "json.loads(await request.body")):
        return "json"
    if any(m in source for m in ("read_body(", "spool(request", "request.stream()", "request.body()")):
        return "raw"
    return None


# ---------------------------------------------------------------------------------------------- one route
def table(cols: tuple[str, ...], rows: list[str]) -> str:
    return "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n" + "\n".join(rows) + "\n"


def shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def curl(method: str, path: str, params: list[dict], body: tuple[str, Any] | None) -> str:
    url = re.sub(r"\{(\w+)(:\w+)?\}", r"<\1>", path)
    query = [f"{p['name']}=<{p['name']}>" for p in params if p.get("in") == "query" and p.get("required")]
    lines = ["curl -s" + ("" if method == "GET" else f" -X {method}") + " " +
             shell_quote(BASE + url + ("?" + "&".join(query) if query else ""))]
    lines += [f"-H {shell_quote(p['name'] + ': <' + p['name'] + '>')}" for p in params
              if p.get("in") == "header" and p.get("required")]
    if body:
        kind, value = body
        if kind == "multipart":
            lines += [f"-F {shell_quote(k + '=' + ('@path/to/file' if v is None else str(v)))}" for k, v in value]
        elif kind == "raw":
            lines += ["-H 'Content-Type: application/octet-stream'", "--data-binary @path/to/file"]
        else:
            lines += ["-H 'Content-Type: application/json'",
                      f"-d {shell_quote(json.dumps(value, ensure_ascii=False))}"]
    return " \\\n  ".join(lines)


def multipart_example(schema: dict, comps: dict) -> list[tuple[str, Any]]:
    schema = resolve(schema, comps)
    props = schema.get("properties", {})
    keys = [k for k in props if k in schema.get("required", [])] or list(props)[:1]
    return [(k, None if type_of(props[k], comps).startswith("file") else example(props[k], comps, 1)) for k in keys]


def render_route(lang: str, method: str, path: str, op: dict, comps: dict, endpoint) -> str:
    t = T[lang]
    out = [f"### `{method} {path}`\n"]
    description = op.get("description") or ""
    if description:
        out.append("\n\n".join(" ".join(p.split()) for p in description.split("\n\n")) + "\n")
    if endpoint is not None:
        source = inspect.getsourcefile(endpoint) or ""
        try:
            where = Path(source).resolve().relative_to(ROOT).as_posix()
        except ValueError:
            where = endpoint.__module__
        out.append(f"{t['handler']}: `{where}` → `{endpoint.__name__}`\n")
    params = op.get("parameters", [])
    if params:
        rows = []
        for p in params:
            schema = p.get("schema", {})
            default = f"`{json.dumps(schema['default'], ensure_ascii=False)}`" if "default" in schema else ""
            rows.append(f"| `{p['name']}` | {p.get('in', '')} | {cell(type_of(schema, comps))} | "
                        f"{t['yes'] if p.get('required') else ''} | {cell(default)} |")
        out.append(f"**{t['params']}**\n\n" + table(t["pcols"], rows))
    body = None
    supplement = SUPPLEMENT.get((method, path))
    content = (op.get("requestBody") or {}).get("content", {})
    if supplement:
        rows = [f"| `{name}` | {kind} | {t['yes'] if req else ''} |  | {cell(en if lang == 'en' else es)} |"
                for name, kind, req, en, es in supplement[0]]
        out.append(f"**{t['body']}** (`application/json`)\n\n" + table(t["fcols"], rows))
        body = ("json", supplement[1])
    elif content:
        media = sorted(content)[0]
        schema = content[media].get("schema", {})
        rows = field_rows(schema, comps, lang)
        out.append(f"**{t['body']}** (`{media}`)\n\n" + (table(t["fcols"], rows) if rows else t["any_json"] + "\n"))
        body = ("multipart", multipart_example(schema, comps)) if media.startswith("multipart/") else \
            ("json", example(schema, comps))
    elif method in ("POST", "PUT", "PATCH") and endpoint is not None and raw_body(endpoint):
        kind = raw_body(endpoint)
        out.append(f"**{t['body']}**: {t['raw_' + kind]}\n")
        body = (kind, {}) if kind == "json" else ("raw", None)
    responses = op.get("responses", {})
    ok = sorted(code for code in responses if code.startswith("2"))
    if ok:
        schema = (responses[ok[0]].get("content", {}).get("application/json") or {}).get("schema")
        kind = type_of(schema, comps) if schema else ""
        out.append(f"**{t['response']}**: `{ok[0]}`" + (f" — {cell(kind)}" if kind and kind != "any" else "") + "\n")
    errors: dict[int, set[str]] = {}
    for status, message in raised(endpoint, t["dynamic"]) if endpoint is not None else ():
        errors.setdefault(status, set()).add(message)
    if "422" in responses:
        errors.setdefault(422, set()).add(t["validation"])
    if errors:
        rows = [f"| `{code}` | {cell('; '.join(sorted(m for m in errors[code] if m)) or '—')} |"
                for code in sorted(errors)]
        out.append(f"**{t['errors']}**\n\n" + table(t["ecols"], rows))
    out.append(f"**{t['example']}**\n\n```bash\n{curl(method, path, params, body)}\n```\n")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------- pages
def operations(app) -> list[tuple[str, str, dict, Any]]:
    schema = app.openapi()
    routes = list(flat_routes(app.routes))
    by_id = {getattr(r, "unique_id", None): r.endpoint for r in routes}
    ops = [(method.upper(), path, op, by_id.get(op.get("operationId")))
           for path, methods in schema.get("paths", {}).items() for method, op in methods.items()]
    for route in routes:  # /mcp is outside the OpenAPI schema
        if route.path == "/mcp":
            for method in sorted(route.methods or ()):
                ops.append((method, route.path, {}, route.endpoint))
    return sorted(ops, key=lambda o: (o[1], METHODS.index(o[0]) if o[0] in METHODS else len(METHODS), o[0]))


def render(app) -> dict[str, str]:
    """Every page under docs/api, keyed by its path relative to docs/api."""
    comps = app.openapi().get("components", {}).get("schemas", {})
    ops = operations(app)
    bases = {p.split("/")[2].split("-")[0] for _, p, _, _ in ops if p.startswith("/api/")}
    areas: dict[str, list] = {}
    for op in ops:
        areas.setdefault(area_of(op[1], bases), []).append(op)
    order = sorted(a for a in areas if a not in ("v1", "mcp")) + [a for a in ("v1", "mcp") if a in areas]
    pages = {"README.md": LANDING}
    for lang in LANGS:
        t = T[lang]
        index = [INTRO[lang].replace("{base}", BASE).rstrip("\n")]
        for area in order:
            prefix = ", ".join(sorted({"/".join(path.split("/")[:3]) for _, path, _, _ in areas[area]}))
            index.append(f"| `{prefix.replace(', ', '`, `')}` | [{area}.md]({area}.md) | {len(areas[area])} |")
            body = [f"# {t['area_title'].format(area='`' + prefix.replace(', ', '`, `') + '`')}\n", t["lang"].format(page=f"{area}.md") + "\n"]
            if area == "mcp":
                body.append(MCP_NOTE[lang] + "\n")
            body += [render_route(lang, method, path, op, comps, endpoint) for method, path, op, endpoint in areas[area]]
            pages[f"{lang}/{area}.md"] = "\n".join(body).rstrip() + "\n"
        pages[f"{lang}/README.md"] = "\n".join(index) + "\n" + LIMITS[lang]
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if docs/api is stale")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "api", help="folder to write (default docs/api)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:  # Windows: the app keeps its SQLite files open
        pages = render(build_app(Path(home)))
    present = {p.relative_to(args.out).as_posix() for p in args.out.glob("**/*.md")} if args.out.exists() else set()
    if args.check:
        stale = sorted({name for name, text in pages.items() if not (args.out / name).is_file()
                        or (args.out / name).read_text(encoding="utf-8") != text} | (present - pages.keys()))
        if stale:
            print("API reference is stale / Referencia de la API desactualizada: python scripts/api_reference.py",
                  *stale, sep="\n  ")
            return 1
        return 0
    for name in present - pages.keys():
        (args.out / name).unlink()
    for name, text in pages.items():
        (args.out / name).parent.mkdir(parents=True, exist_ok=True)
        (args.out / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
