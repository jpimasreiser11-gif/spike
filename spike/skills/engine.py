"""Skills in the Agent Skills format: a folder with SKILL.md (YAML front matter `name`, `description`) and
optional resources.

Small local models get skills chosen for them: a lexical router matches the request against each skill's
keywords and description, and the chosen skill's body goes into the system prompt within a token budget.
API models see only names and descriptions and load what they need with the `load_skill` tool.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from spike.core.context import estimate_tokens
from spike.tools.base import Tool, ToolResult

BUNDLED = Path(__file__).with_name("bundled")
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MIN_SCORE = 2.0  # one keyword, or two words of the description
STOPWORDS = set(["a", "al", "algo", "and", "are", "as", "at", "be", "by", "con", "como", "cual", "cuál", "de", "del", "el", "en", "es", "esta", "este", "for", "from", "how", "i", "in", "is", "it", "la", "las", "los", "me", "mi", "my", "no", "of", "on", "or", "para", "por", "que", "qué", "se", "si", "sin", "su", "the", "this", "to", "tu", "un", "una", "uno", "use", "used", "using", "what", "when", "with", "y", "you", "your"])


class SkillError(ValueError):
    """An invalid skill; the message says which rule it breaks."""


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", _norm(text)) if len(w) >= 3 and w not in STOPWORDS}


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if value is not None and not isinstance(value, list):
        raise SkillError("routing metadata must be a string or list")
    return [str(v).strip() for v in value or [] if str(v).strip()]


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str  # "bundled" | "user"
    license: str = ""
    specialists: list[str] = field(default_factory=list)  # empty = any specialist
    keywords: list[str] = field(default_factory=list)

    def body(self) -> str:
        text = (self.path / "SKILL.md").read_text(encoding="utf-8")
        return text.split("---", 2)[2].lstrip("\n") if text.startswith("---") else text

    def resources(self) -> list[str]:
        return sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob("*")
                      if p.is_file() and p.name != "SKILL.md" and not p.name.startswith("LICENSE"))

    def read(self, relative: str) -> str:
        target = (self.path / relative).resolve()
        if self.path.resolve() not in target.parents or not target.is_file():
            raise SkillError(f"'{relative}' is not a file of skill '{self.name}'")
        return target.read_text(encoding="utf-8", errors="replace")

    def public(self, enabled: bool = True) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "source": self.source, "license": self.license,
                "specialists": self.specialists, "keywords": self.keywords, "resources": self.resources(),
                "enabled": enabled}


def parse_skill(folder: Path, hints: dict[str, Any] | None = None, source: str = "user") -> Skill:
    path = folder / "SKILL.md"
    if not path.is_file():
        raise SkillError(f"{folder.name}: SKILL.md not found")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:  # e.g. saved as Windows-1252 by an old editor
        raise SkillError(f"{folder.name}: SKILL.md must be saved as UTF-8 ({exc.reason} at byte {exc.start})") from exc
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        raise SkillError(f"{folder.name}: SKILL.md must start with YAML front matter between --- lines")
    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"{folder.name}: invalid front matter: {exc}") from exc
    if not isinstance(front, dict):
        raise SkillError(f"{folder.name}: front matter must be a mapping")
    name, description = str(front.get("name") or ""), str(front.get("description") or "").strip()
    if not name:
        raise SkillError(f"{folder.name}: 'name' is required")
    if not NAME.match(name) or len(name) > 64:
        raise SkillError(f"{folder.name}: 'name' must be lowercase letters, digits and hyphens (max 64)")
    if name != folder.name:
        raise SkillError(f"{folder.name}: 'name' must match the folder name")
    if not description or len(description) > 1024:
        raise SkillError(f"{name}: 'description' is required (max 1024 characters)")
    meta = front.get("metadata") if isinstance(front.get("metadata"), dict) else {}
    hints = hints or {}
    license_ = str(front.get("license") or "")
    if license_.lower().startswith("complete terms in") or not license_:
        found = next((p.name for p in sorted(folder.glob("LICENSE*"))), "")
        license_ = _license_name(folder / found) if found else license_
    return Skill(name=name, description=description, path=folder, source=source, license=license_,
                 specialists=_list(meta.get("spike-specialists") or hints.get("specialists")),
                 keywords=_list(meta.get("spike-keywords") or hints.get("keywords")))


def _license_name(path: Path) -> str:
    head = path.read_text(encoding="utf-8", errors="replace")[:200]
    for marker, name in (("Apache License", "Apache-2.0"), ("MIT License", "MIT")):
        if marker in head:
            return name
    return path.name


class SkillLibrary:
    def __init__(self, roots: list[tuple[Path, str]]):
        self.roots = roots
        self.errors: list[str] = []
        self._skills: dict[str, Skill] = {}
        # optional tie-break (Evolution EV3): (ranked [(score, name)], specialist, text) -> names in the order to use
        self.prefer: Callable[[list[tuple[float, str]], str, str], list[str]] | None = None
        self.reload()

    def reload(self) -> None:
        skills: dict[str, Skill] = {}
        self.errors = []
        for root, source in self.roots:  # later roots (user skills) override earlier ones (bundled)
            if not root.is_dir():
                continue
            hints_file = root / "bindings.yaml"
            hints = yaml.safe_load(hints_file.read_text(encoding="utf-8")) or {} if hints_file.is_file() else {}
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                try:
                    skill = parse_skill(folder, hints.get(folder.name), source)
                except SkillError as exc:
                    self.errors.append(str(exc))
                    continue
                skills[skill.name] = skill
        self._skills = skills

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def available(self, specialist: str, disabled: set[str] | None = None) -> list[Skill]:
        return [s for s in self.all() if s.name not in (disabled or set())
                and (not s.specialists or specialist in s.specialists)]

    def score(self, skill: Skill, text: str) -> float:
        norm, words = _norm(text), _words(text)
        total = 0.0
        for kw in skill.keywords:
            k = _norm(kw)
            if (" " in k and k in norm) or k in words:
                total += 2.0
        total += len(words & (_words(skill.description) | _words(skill.name.replace("-", " "))) - set(map(_norm, skill.keywords)))
        return total

    def select(self, text: str, specialist: str, disabled: set[str] | None = None, k: int = 1) -> list[Skill]:
        scored = [(self.score(s, text), s.name, s) for s in self.available(specialist, disabled)]
        ranked = sorted((x for x in scored if x[0] >= MIN_SCORE), key=lambda x: (-x[0], x[1]))
        if self.prefer is not None and len(ranked) > 1:  # may only reorder skills that already scored: never adds one
            by_name = {name: skill for _, name, skill in ranked}
            order = [n for n in self.prefer([(score, name) for score, name, _ in ranked], specialist, text) if n in by_name]
            ranked = [(0.0, n, by_name[n]) for n in order] + [x for x in ranked if x[1] not in order]
        return [s for _, _, s in ranked[:k]]


def skill_prompt(skill: Skill, budget_tokens: int) -> str:
    """The skill as a system prompt section, cut to the budget."""
    head = f"# Skill: {skill.name}\nFollow this skill for the current request.\n\n"
    body = skill.body().strip()
    if estimate_tokens(head + body) <= budget_tokens:
        return head + body
    note = "\n\n[…skill truncated to fit the context window]"
    keep = max(0, int((budget_tokens - estimate_tokens(head + note)) * 3.5))
    while keep and estimate_tokens(head + body[:keep] + note) > budget_tokens:
        keep = int(keep * 0.95)
    return head + body[:keep].rstrip() + note


def catalog_prompt(skills: list[Skill]) -> str:
    lines = [f"- {s.name}: {s.description}" for s in skills]
    return ("# Available skills\nWhen one fits the request, call load_skill with its name before answering and "
            "follow it.\n" + "\n".join(lines))


class LoadSkill(Tool):
    name = "load_skill"
    description = "Load the instructions of a skill by name, or one of its files with `file`."
    parameters = {"type": "object", "properties": {
        "name": {"type": "string", "description": "skill name from the list of available skills"},
        "file": {"type": "string", "description": "optional: a file of the skill, as listed after loading it"},
    }, "required": ["name"]}
    risk = "read"
    default_policy = "allow"

    def __init__(self, skills: list[Skill]):
        self.skills = {s.name: s for s in skills}

    async def run(self, args: dict[str, Any]) -> ToolResult:
        skill = self.skills.get(str(args.get("name", "")))
        if skill is None:
            return ToolResult(ok=False, content=f"error: unknown skill; available: {', '.join(sorted(self.skills))}")
        if args.get("file"):
            try:
                return ToolResult(ok=True, content=skill.read(str(args["file"]))[:60_000])
            except SkillError as exc:
                return ToolResult(ok=False, content=f"error: {exc}")
        files = skill.resources()
        listing = ("\n\nFiles of this skill (load them with `file`): " + ", ".join(files)) if files else ""
        return ToolResult(ok=True, content=skill.body()[:60_000] + listing)
