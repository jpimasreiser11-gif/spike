"""MCP Apps (SEP-1865, spec 2026-01-26): a connector tool can name a `ui://` resource, an HTML page the app shows
next to the tool's result. SPIKE renders it in a sandboxed iframe with an opaque origin (it cannot reach SPIKE's
storage, cookies or API) under a Content Security Policy built here from the domains the server declared, keeping
only public https origins. The page talks to SPIKE with JSON-RPC over postMessage; what it asks the server for
(tools/call, resources/read) goes through `ConnectorManager.app_call` / `app_read`, which only allow the tools and
resources of the same connector, apply the tool's permission policy and write every call to an audit log."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import time
from pathlib import Path
from typing import Any

from spike.connectors.mcp import APP_MIME

MAX_HTML = 2 * 1024 * 1024
MAX_RESULT = 256 * 1024  # a result passed to a view (the model sees only its text, as before)
MAX_DOMAINS = 20
AUDIT_MAX = 1024 * 1024
VISIBILITY = ("model", "app")
ORIGIN = re.compile(r"^(https|wss)://(\*\.)?([a-z0-9-]+\.)+[a-z]{2,63}(:\d{1,5})?$")


class AppError(ValueError):
    pass


def tool_ui(spec: dict[str, Any]) -> tuple[str | None, list[str]]:
    """(the ui:// resource a tool's results are shown in, who may call it: "model", "app" or both)."""
    meta = spec.get("_meta") if isinstance(spec.get("_meta"), dict) else {}
    ui = meta.get("ui") if isinstance(meta.get("ui"), dict) else {}
    uri = ui.get("resourceUri") or meta.get("ui/resourceUri")  # the flat key is the deprecated form
    uri = uri if isinstance(uri, str) and uri.startswith("ui://") and len(uri) <= 512 else None
    visibility = ui.get("visibility")
    if not isinstance(visibility, list) or not visibility:
        return uri, list(VISIBILITY)
    return uri, [v for v in VISIBILITY if v in visibility]


def _public_origin(value: Any, schemes: tuple[str, ...]) -> str | None:
    if not isinstance(value, str):
        return None
    origin = value.strip().lower().rstrip("/")
    if not ORIGIN.match(origin) or origin.split("://")[0] not in schemes:
        return None
    host = origin.split("://", 1)[1].split(":")[0].removeprefix("*.")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # addresses (127.0.0.1, 192.168.x.x…) never: a view must not reach this computer or the LAN
    except ValueError:
        return origin


def clean_csp(csp: Any) -> tuple[dict[str, list[str]], list[str]]:
    """The declared domains SPIKE accepts (public https/wss origins, wildcard subdomains allowed) and the ones it
    dropped."""
    out: dict[str, list[str]] = {}
    dropped: list[str] = []
    csp = csp if isinstance(csp, dict) else {}
    for key, schemes in (("connectDomains", ("https", "wss")), ("resourceDomains", ("https",)),
                         ("frameDomains", ("https",)), ("baseUriDomains", ("https",))):
        given = csp.get(key) if isinstance(csp.get(key), list) else []
        kept = []
        for value in given[:MAX_DOMAINS]:
            origin = _public_origin(value, schemes)
            if origin and origin not in kept:
                kept.append(origin)
            elif not origin:
                dropped.append(str(value)[:200])
        dropped += [str(v)[:200] for v in given[MAX_DOMAINS:]]
        if kept:
            out[key] = kept
    return out, dropped


def csp_policy(csp: dict[str, list[str]]) -> str:
    """The view's policy: the spec's restrictive default, widened only by the accepted domains. No 'self' (the
    view's origin is opaque), no forms, no plugins."""
    res = " ".join(csp.get("resourceDomains", []))
    connect = " ".join(csp.get("connectDomains", [])) or "'none'"
    frames = " ".join(csp.get("frameDomains", [])) or "'none'"
    base = " ".join(csp.get("baseUriDomains", [])) or "'none'"
    return "; ".join(f"{k} {v}".strip() for k, v in (
        ("default-src", "'none'"), ("script-src", f"'unsafe-inline' {res}"), ("style-src", f"'unsafe-inline' {res}"),
        ("img-src", f"data: blob: {res}"), ("font-src", f"data: {res}"), ("media-src", f"data: blob: {res}"),
        ("connect-src", connect), ("frame-src", frames), ("object-src", "'none'"), ("base-uri", base),
        ("form-action", "'none'")))


def resource_from(uri: str, result: dict[str, Any]) -> dict[str, Any]:
    """The view from a resources/read result: the HTML, its accepted CSP, the policy and a hash for review."""
    contents = [c for c in result.get("contents") or [] if isinstance(c, dict) and c.get("uri") == uri]
    if not contents:
        raise AppError(f"the server returned nothing for {uri}")
    item = contents[0]
    if (item.get("mimeType") or "").replace(" ", "").lower() != APP_MIME:
        raise AppError(f"{uri} is not an MCP App page (its type is '{item.get('mimeType')}')")
    if isinstance(item.get("text"), str):
        html = item["text"]
    elif isinstance(item.get("blob"), str):
        try:
            html = base64.b64decode(item["blob"], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise AppError(f"{uri}: unreadable content") from exc
    else:
        raise AppError(f"{uri} has no content")
    if len(html.encode()) > MAX_HTML:
        raise AppError(f"{uri} is larger than {MAX_HTML // 1024**2} MB")
    meta = (item.get("_meta") or {}).get("ui") if isinstance(item.get("_meta"), dict) else None
    meta = meta if isinstance(meta, dict) else {}
    csp, dropped = clean_csp(meta.get("csp"))
    return {"uri": uri, "html": html, "csp": csp, "dropped": dropped, "policy": csp_policy(csp),
            "prefers_border": meta.get("prefersBorder") if isinstance(meta.get("prefersBorder"), bool) else None,
            "permissions": {},  # camera, microphone, location and clipboard are never granted
            "sha256": hashlib.sha256(html.encode()).hexdigest()}


def result_for_view(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """The CallToolResult a view gets (content, structuredContent, isError, _meta), or a note when too large."""
    if not isinstance(raw, dict):
        return None
    out = {k: raw[k] for k in ("content", "structuredContent", "isError", "_meta") if k in raw}
    if len(json.dumps(out, ensure_ascii=False, default=str)) > MAX_RESULT:
        text = [c for c in out.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
        out = {"content": text[:1] or [{"type": "text", "text": "(result too large for the view)"}],
               "isError": bool(raw.get("isError")), "_meta": {"spike/truncated": True}}
        if len(json.dumps(out, ensure_ascii=False)) > MAX_RESULT:
            out = {"content": [{"type": "text", "text": "(result too large for the view)"}],
                   "isError": bool(raw.get("isError")), "_meta": {"spike/truncated": True}}
    return out


class AuditLog:
    """Every call a view makes through SPIKE, one JSON line each, in `$SPIKE_HOME/connectors/apps-audit.jsonl`
    (the previous megabyte is kept as `.1`)."""

    def __init__(self, path: Path):
        self.path = path

    def write(self, **entry: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > AUDIT_MAX:
            self.path.replace(self.path.with_suffix(".jsonl.1"))
        line = json.dumps({"time": round(time.time(), 3), **entry}, ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line[:8000] + "\n")

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        out = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
