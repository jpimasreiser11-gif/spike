"""Offline distribution checks, separate from permissive runtime loading of user instruction profiles.

Diagnostics carry stable rule names and bilingual text, never offending input values: validation must not
turn an accidentally committed credential into another leak in CI logs. Body limits match load_skill's cap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from spike.skills.engine import BUNDLED, SkillError, parse_skill

MAX_BODY = 60_000
LICENSES = {"MIT", "Apache-2.0", "BSD", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0", "CC0-1.0", "CC-BY", "CC-BY-4.0"}
MESSAGES = {
    "read": ("Cannot read UTF-8 input", "No se puede leer la entrada UTF-8"),
    "format": ("Invalid format or required fields", "Formato o campos obligatorios incorrectos"),
    "license": ("Missing or unsupported license", "Licencia ausente o no permitida"),
    "tools": ("Unknown or malformed declared tools", "Herramientas declaradas desconocidas o incorrectas"),
    "body": ("Body must contain 1 to 60000 characters", "El cuerpo debe contener de 1 a 60000 caracteres"),
    "secret": ("Possible literal secret; use environment names", "Posible secreto literal; usa nombres de entorno"),
    "transport": ("Invalid transport or launch fields", "Transporte o campos de ejecución incorrectos"),
    "version": ("Downloadable packages need exact versions", "Los paquetes descargables necesitan versiones exactas"),
    "duplicate": ("Duplicate identifier", "Identificador duplicado"),
}
_SECRET = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b|"
    r"(?i:(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_+/=-]{16,})"
)


@dataclass(frozen=True)
class Issue:
    rule: str
    location: str

    def message(self, lang: str = "en") -> str:
        return f"{self.location}: [{self.rule}] {MESSAGES[self.rule][lang == 'es']}"


def has_secret(text: str) -> bool:
    # A verbatim upstream example uses this explicit placeholder, not a credential.
    return bool(_SECRET.search(text.replace("your_api_key_here", "<placeholder>")))


def allowed_license(value: object) -> bool:
    return isinstance(value, str) and value in LICENSES


def known_tools() -> set[str]:
    """Discover declared built-in Tool subclasses without instantiating services or running their code.

    Reading class declarations with AST also covers optional tool modules without importing dependencies,
    creating a workspace, starting a backend or resolving remote connector tools.
    """
    import ast

    names = set()
    package = Path(__file__).parents[1]
    for path in package.rglob("*.py"):
        if "bundled" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id == "Tool" for b in node.bases):
                for stmt in node.body:
                    if (isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "name"
                                                             for t in stmt.targets) and
                            isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
                        names.add(stmt.value.value)
    return names


def validate_skills(paths: list[Path] | None = None) -> list[Issue]:
    """Accept skill folders, SKILL.md files or roots containing skill folders; never silently skip missing input."""
    issues = []
    tools = known_tools()
    for path in paths or [BUNDLED]:
        if path.is_file() and path.name == "SKILL.md":
            folders = [path.parent]
        elif (path / "SKILL.md").is_file():
            folders = [path]
        elif path.is_dir():
            folders = sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
        else:
            folders = []
        if not folders:
            issues.append(Issue("read", path.as_posix()))
        for folder in folders:
            location = (folder / "SKILL.md").as_posix()
            try:
                skill = parse_skill(folder)
                text = (folder / "SKILL.md").read_text(encoding="utf-8")
                front = yaml.safe_load(text.split("---", 2)[1])
                body = skill.body().strip()
            except (SkillError, yaml.YAMLError, OSError, UnicodeError):
                issues.append(Issue("format", location))
                continue
            if not allowed_license(skill.license):
                issues.append(Issue("license", location))
            declared = front.get("allowed-tools", [])
            if isinstance(declared, str):
                declared = declared.replace(",", " ").split()
            if (not isinstance(declared, list) or
                    any(not isinstance(t, str) or t not in tools for t in declared)):
                issues.append(Issue("tools", location))
            if not 1 <= len(body) <= MAX_BODY:
                issues.append(Issue("body", location))
            if has_secret(text):
                issues.append(Issue("secret", location))
            for resource in sorted(folder.rglob("*")):
                if not resource.is_file() or resource.name == "SKILL.md":
                    continue
                resource_location = resource.as_posix()
                if resource.is_symlink() or folder.resolve() not in resource.resolve().parents:
                    issues.append(Issue("read", resource_location))
                    continue
                try:
                    data = resource.read_bytes()
                except OSError:
                    issues.append(Issue("read", resource_location))
                    continue
                if has_secret(data.decode("utf-8", errors="replace")):
                    issues.append(Issue("secret", resource_location))
    return issues
