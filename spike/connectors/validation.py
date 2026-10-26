"""Check curated connector definitions offline without starting a server, installing packages or reading env.

Only npx/uvx downloads have package pins; a hosted endpoint and a preinstalled executable cannot honestly
be assigned a reproducible package version. Those cases still need explicit license and launch metadata.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import yaml

from spike.skills.validation import Issue, allowed_license, has_secret

CATALOG = Path(__file__).with_name("catalog.yaml")
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
PIN = re.compile(r"(?:@[a-z0-9_.-]+/)?[a-zA-Z0-9_.-]+(?:@|==)\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\Z")


def _launcher(command: object) -> str:
    """Recognize downloadable launchers even when a catalog uses a Windows or absolute executable path."""
    name = str(command).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return re.sub(r"\.(?:cmd|exe)$", "", name)


def _https(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
                and not any(re.search(r"token|key|secret|password", k, re.I) for k, _ in parse_qsl(parsed.query)))
    except ValueError:
        return False


def validate_connectors(path: Path = CATALOG) -> list[Issue]:
    issues = []
    location = path.as_posix()
    try:
        text = path.read_text(encoding="utf-8")
        entries = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError):
        return [Issue("read", location)]
    if not isinstance(entries, list) or not entries:
        return [Issue("format", location)]
    if has_secret(text):
        issues.append(Issue("secret", location))
    seen = set()
    for index, raw in enumerate(entries):
        loc = f"{location}#{index + 1}"  # don't echo user-provided names or values into logs
        if not isinstance(raw, dict):
            issues.append(Issue("format", loc))
            continue
        required = ("id", "name", "description", "license", "source", "transport")
        if (any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in required) or
                not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", str(raw.get("id", ""))) or
                not _https(raw.get("source"))):
            issues.append(Issue("format", loc))
        cid = str(raw.get("id", ""))
        if cid in seen:
            issues.append(Issue("duplicate", loc))
        seen.add(cid)
        license_ = raw.get("license")
        # Historical catalog entries document the package and repository's different licenses.
        documented_mit = license_ == "MIT (package README); the repository licenses new contributions as Apache-2.0"
        installed_only = license_ == "proprietary (not redistributed; SPIKE only starts the CLI you installed)"
        if not (allowed_license(license_) or documented_mit or
                (installed_only and raw.get("transport") == "stdio" and _launcher(raw.get("command")) not in ("npx", "uvx"))):
            issues.append(Issue("license", loc))
        transport = raw.get("transport")
        if transport == "http":
            if not _https(raw.get("url")):
                issues.append(Issue("transport", loc))
        elif transport == "stdio":
            command, args = raw.get("command"), raw.get("args", [])
            if (not isinstance(command, str) or not command.strip() or not isinstance(args, list) or
                    any(not isinstance(a, str) for a in args)):
                issues.append(Issue("transport", loc))
            elif _launcher(command) in ("npx", "uvx"):
                # The first positional argument is the downloaded package, never a later pinned-looking flag.
                package = next((a for a in args if not a.startswith("-")), "")
                if not PIN.fullmatch(package):
                    issues.append(Issue("version", loc))
                if any(a in ("--package", "-p", "--with", "--from") or a.startswith(("--package=", "--with=", "--from="))
                       for a in args):
                    issues.append(Issue("version", loc))
        else:
            issues.append(Issue("transport", loc))
        args = raw.get("args", [])
        if isinstance(args, list):
            for arg in args:
                if isinstance(arg, str) and re.match(r"--?(?:api[-_]?key|token|password|secret)(?:=|$)", arg, re.I):
                    issues.append(Issue("secret", loc))
        secrets = raw.get("secrets", [])
        names = set()
        if not isinstance(secrets, list):
            issues.append(Issue("secret", loc))
            secrets = []
        for secret in secrets:
            if (not isinstance(secret, dict) or not isinstance(secret.get("name"), str) or
                    not ENV_NAME.fullmatch(secret["name"]) or
                    set(secret) - {"name", "label", "url", "optional"}):
                issues.append(Issue("secret", loc))
            else:
                names.add(secret["name"])
        for field in ("headers", "env"):
            values = raw.get(field, {})
            if not isinstance(values, dict):
                issues.append(Issue("secret", loc))
                continue
            for key, value in values.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    issues.append(Issue("secret", loc))
                    continue
                refs = re.findall(r"\{([^{}]+)\}", value)
                sensitive = bool(re.search(r"authorization|cookie|token|key|secret|password", key, re.I))
                if (any(r not in names | {"workspace", "data"} for r in refs) or
                        (sensitive and (not refs or any(r not in names for r in refs))) or
                        (sensitive and value not in [f"{{{n}}}" for n in names] +
                         [f"Bearer {{{n}}}" for n in names])):
                    issues.append(Issue("secret", loc))
    return issues
