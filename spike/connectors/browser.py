"""Browser guard (Spike View, C1) for the Playwright connector: SPIKE reviews each browser call before it runs.

- Opening a page: only http(s) pages; a domain the user blocked is refused, an allowed one opens without asking,
  any other one asks (or opens, if the user chose "allow other domains"). A rule for example.com covers its
  subdomains. Blocked domains are also passed to the browser (`--blocked-origins`) when the connector starts, so
  links and requests inside pages are refused too (a domain blocked while the browser runs reaches it at the next
  start); Playwright MCP says that list is not a security boundary.
- Submitting a form (typing with submit, pressing Enter, clicking a button that sends, buys, signs in, deletes or
  publishes), uploading or dropping files and running code in the page always ask, every time.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from spike.tools.base import Review

CONNECTOR = "playwright"
DEFAULT: dict[str, Any] = {"domains": {}, "unknown": "ask"}  # domain -> "allow" | "deny"; unknown: "ask" | "allow"
SUBMIT_KEYS = {"enter", "numpadenter"}
DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)*")
REF = re.compile(r"[a-z]?\d+|ref=\w+", re.I)  # a snapshot reference such as e12
SUBMIT_WORDS = re.compile(
    r"\b(submit|send|enviar|envía|envia|mandar|pay|pagar|buy|comprar|purchase|checkout|order|pedido|reservar|book|"
    r"confirm|confirmar|sign\s*in|log\s*in|login|iniciar\s+sesi[oó]n|acceder|entrar|sign\s*up|register|registr\w*|"
    r"subscribe|suscrib\w*|delete|eliminar|borrar|remove|publish|publicar|post|transfer\w*|apply|solicitar|"
    r"accept|aceptar|save|guardar)\b", re.I)
ALWAYS_ASK = {
    "browser_file_upload": "sends files from your computer to the page",
    "browser_drop": "drops files or data into the page",
    "browser_evaluate": "runs code in the page",
    "browser_run_code_unsafe": "runs code in the browser",
}


def host_of(url: str) -> str | None:
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    return host.lower().rstrip(".") if host else None


def rule_for(host: str, domains: dict[str, str]) -> tuple[str, str] | None:
    """(domain, rule) of the most specific rule covering this host (example.com covers www.example.com)."""
    parts = host.split(".")
    for i in range(len(parts)):
        candidate = ".".join(parts[i:])
        if candidate in domains:
            return candidate, domains[candidate]
    return None


def site_of(host: str) -> str:
    """The domain a new rule is saved for: the host without a leading www."""
    return host[4:] if host.startswith("www.") else host


def clean(value: Any) -> dict[str, Any]:
    """Validated browser settings: `domains` (domain -> "allow" | "deny") and `unknown` ("ask" | "allow")."""
    if not isinstance(value, dict) or set(value) - {"domains", "unknown"}:
        raise ValueError("browser settings take 'domains' and 'unknown'")
    unknown = value.get("unknown", "ask")
    if unknown not in ("ask", "allow"):
        raise ValueError("'unknown' must be ask or allow")
    domains = value.get("domains") or {}
    if not isinstance(domains, dict):
        raise ValueError("'domains' must map a domain to allow or deny")
    out = {}
    for domain, rule in domains.items():
        name = site_of(str(domain).strip().lower().rstrip("."))
        if not DOMAIN.fullmatch(name):
            raise ValueError(f"'{domain}' is not a domain")
        if rule not in ("allow", "deny"):
            raise ValueError(f"the rule for {name} must be allow or deny")
        out[name] = rule
    return {"domains": out, "unknown": unknown}


def _open(url: str, settings: dict[str, Any]) -> Review:
    scheme = urlsplit(url.strip()).scheme.lower()
    if url.strip() == "about:blank":
        return Review("allow")
    host = host_of(url)
    if scheme not in ("http", "https") or not host:
        return Review("deny", f"only web pages (http or https) can be opened, not '{url[:80]}'", code="scheme")
    found = rule_for(host, settings.get("domains") or {})
    if found and found[1] == "deny":
        return Review("deny", f"you blocked {found[0]}", domain=found[0], code="blocked")
    if found and found[1] == "allow":
        return Review("allow", domain=found[0])
    if settings.get("unknown") == "allow":
        return Review("allow", domain=site_of(host))
    return Review("ask", f"opens {site_of(host)}", domain=site_of(host), code="open")


def review(remote: str, args: dict[str, Any], settings: dict[str, Any]) -> Review | None:
    """SPIKE's decision on one Playwright call, or None to leave it to the connector's policy."""
    if remote == "browser_navigate":
        return _open(str(args.get("url") or ""), settings)
    if remote == "browser_tabs" and args.get("url"):
        return _open(str(args["url"]), settings)
    if remote in ALWAYS_ASK:
        return Review("ask", ALWAYS_ASK[remote], once=True, code=remote.removeprefix("browser_"))
    if remote == "browser_type" and (args.get("submit") or str(args.get("text") or "").endswith("\n")):
        return Review("ask", "types and submits a form", once=True, code="type_submit")
    if remote == "browser_press_key" and str(args.get("key") or "").lower() in SUBMIT_KEYS:
        return Review("ask", "presses Enter, which may submit a form", once=True, code="enter")
    if remote == "browser_click":
        element, target = str(args.get("element") or "").strip(), str(args.get("target") or "").strip()
        if SUBMIT_WORDS.search(element) or SUBMIT_WORDS.search(target):
            return Review("ask", f"clicks “{(element or target)[:80]}”, which may submit a form", once=True,
                          code="click_submit")
        if not element and REF.fullmatch(target):
            return Review("ask", "clicks an element it did not describe, which may submit a form", once=True,
                          code="click_unnamed")
    if remote == "browser_handle_dialog" and args.get("accept"):
        return Review("ask", "accepts a dialog of the page", once=True, code="dialog")
    return None


def blocked_origins(settings: dict[str, Any]) -> list[str]:
    """Patterns for Playwright MCP's --blocked-origins covering each blocked domain and its subdomains, on any
    scheme and port (a bare host matches the default ports, `scheme://host:*` any other)."""
    out = []
    for domain, rule in sorted((settings.get("domains") or {}).items()):
        if rule == "deny":
            for host in (domain, f"*.{domain}"):
                out += [host, f"http://{host}:*", f"https://{host}:*"]
    return out
