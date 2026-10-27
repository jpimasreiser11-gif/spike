"""Opt-in local skill marketplace: bounded JSON indexes and hash-pinned ZIPs, with no remote defaults.

Only workspace-local inputs and destinations are accepted. Nothing in a pack is executed. Install stages
all folders, runs the same checks as ``spike skills validate``, and refuses existing names before publishing.
The index describes homogeneous-license packs; it is a trust choice, not a signature or a sandbox for prompts.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from spike.skills.engine import NAME, parse_skill
from spike.skills.validation import allowed_license, validate_skills

MAX_BYTES = 50 * 1024**2
MAX_INDEX = 1024**2
MAX_ENTRIES = 2000
MESSAGES = {
    "input": ("Invalid local marketplace input", "Entrada local del marketplace incorrecta"),
    "path": ("Paths must stay inside the workspace", "Las rutas deben permanecer dentro del proyecto"),
    "sha256": ("sha256 mismatch; installation refused", "sha256 incorrecto; instalación rechazada"),
    "permission": ("Permission required: pass --yes", "Permiso necesario: usa --yes"),
    "validation": ("Skill pack failed validation", "El paquete de skills no supera la validación"),
    "exists": ("A skill already exists; installation refused", "Una skill ya existe; instalación rechazada"),
    "missing": ("Unknown pack identifier", "Identificador de paquete desconocido"),
}


class MarketplaceError(ValueError):
    """Stable, bilingual diagnostics that do not echo untrusted content or filesystem paths."""

    def __init__(self, rule: str):
        self.rule = rule
        super().__init__(MESSAGES[rule][0])

    def message(self, lang: str = "en") -> str:
        return MESSAGES[self.rule][lang == "es"]


def _inside(path: Path, workspace: Path) -> Path:
    resolved, root = path.resolve(), workspace.resolve()
    if resolved == root or root not in resolved.parents:
        raise MarketplaceError("path")
    return resolved


def _relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise MarketplaceError("path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise MarketplaceError("path")
    return path


def read_index(index: Path, workspace: Path) -> list[dict[str, str]]:
    """Read an explicitly supplied index; package paths are relative to its directory, within the workspace."""
    try:
        index = _inside(index, workspace)
        if index.stat().st_size > MAX_INDEX:
            raise MarketplaceError("input")
        raw = json.loads(index.read_text(encoding="utf-8"))
        packs = raw.get("packs") if isinstance(raw, dict) else None
        if not isinstance(packs, list) or len(packs) > 1000:
            raise MarketplaceError("input")
        seen = set()
        for pack in packs:
            if (not isinstance(pack, dict) or set(pack) != {"id", "license", "sha256", "path"} or
                    not all(isinstance(v, str) for v in pack.values()) or
                    not NAME.fullmatch(pack["id"]) or len(pack["id"]) > 64 or pack["id"] in seen or
                    not allowed_license(pack["license"]) or not re.fullmatch(r"[a-fA-F0-9]{64}", pack["sha256"])):
                raise MarketplaceError("input")
            seen.add(pack["id"])
            _inside(index.parent / _relative(pack["path"]), workspace)
        return packs
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, MarketplaceError):
            raise
        raise MarketplaceError("input") from None


def install(index: Path, pack_id: str, destination: Path, workspace: Path, *, approved: bool = False) -> list[str]:
    """Install only after explicit approval, integrity verification and complete offline distribution validation.

    Existing folders are never replaced. A failed publication removes only the folders published by this call;
    validation failures do not create the destination. Temporary extraction is confined to the workspace.
    """
    if not approved:
        raise MarketplaceError("permission")
    try:
        destination = _inside(destination, workspace)
        packs = read_index(index, workspace)
        pack = next((p for p in packs if p["id"] == pack_id), None)
        if pack is None:
            raise MarketplaceError("missing")
        source = _inside(index.resolve().parent / _relative(pack["path"]), workspace)
        with source.open("rb") as stream:
            blob = stream.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise MarketplaceError("input")
        if hashlib.sha256(blob).hexdigest() != pack["sha256"].lower():
            raise MarketplaceError("sha256")
        with tempfile.TemporaryDirectory(dir=workspace.resolve(), prefix=".skills-") as temp:
            staging = Path(temp)
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_BYTES:
                    raise MarketplaceError("input")
                seen = set()
                for info in infos:
                    path = _relative(info.filename.rstrip("/") if info.is_dir() else info.filename)
                    mode = stat.S_IFMT(info.external_attr >> 16)
                    if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.filename in seen:
                        raise MarketplaceError("input")
                    seen.add(info.filename)
                    target = staging.joinpath(*path.parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(info))
            folders = sorted(staging.iterdir())
            if not folders or any(not f.is_dir() for f in folders) or validate_skills(folders):
                raise MarketplaceError("validation")
            names = [parse_skill(f).name for f in folders]
            if any(parse_skill(f).license != pack["license"] for f in folders):
                raise MarketplaceError("validation")
            if any((destination / n).exists() or (destination / n).is_symlink() for n in names):
                raise MarketplaceError("exists")
            destination.mkdir(parents=True, exist_ok=True)
            published = []
            try:
                for folder in folders:
                    final = destination / folder.name
                    # mkdir reserves each name without replacing a concurrent installation.
                    final.mkdir()
                    published.append(final)
                    for resource in folder.iterdir():
                        shutil.move(str(resource), final)
            except OSError:
                for final in published:
                    shutil.rmtree(final)
                raise
            return names
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        if isinstance(exc, MarketplaceError):
            raise
        raise MarketplaceError("input") from None
