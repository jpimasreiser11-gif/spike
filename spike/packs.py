"""Installing skills from a zip, and packs: custom specialists + user skills + custom connectors in one zip,
never with secrets."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from spike.projects import ProjectError, clean_path
from spike.skills.engine import NAME, SkillError, parse_skill

FORMAT, VERSION = "spike-pack", 1
MAX_BYTES = 50 * 1024**2
MAX_ENTRIES = 2000


def _open(blob: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ProjectError("not a zip archive") from exc
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_BYTES:
        raise ProjectError("the archive is too large")
    return archive


def install_skills(archive: zipfile.ZipFile, skills_dir: Path, prefix: str = "") -> list[str]:
    """Install every skill folder found under `prefix` (a folder with SKILL.md, or SKILL.md at the top)."""
    entries: list[tuple[PurePosixPath, zipfile.ZipInfo]] = []
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        entries.append((clean_path(info.filename[len(prefix):]), info))
    if not entries:
        return []
    skills_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=skills_dir, prefix=".incoming-") as tmp:
        staging = Path(tmp)
        single = any(path.as_posix() == "SKILL.md" for path, _ in entries)
        for path, info in entries:
            target = staging.joinpath("_single" if single else "", *path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
        if single:  # SKILL.md at the top: the folder takes the skill's own name
            try:
                name = _front_name(staging / "_single")
            except SkillError as exc:
                raise ProjectError(str(exc)) from exc
            (staging / "_single").rename(staging / name)
            folders = [staging / name]
        else:
            folders = [p for p in staging.iterdir() if p.is_dir()]
        parsed = []
        for folder in folders:
            try:
                parsed.append(parse_skill(folder, source="user"))
            except SkillError as exc:
                raise ProjectError(str(exc)) from exc
        for skill in parsed:
            final = skills_dir / skill.name
            if final.exists():
                shutil.rmtree(final)
            shutil.move(str(skill.path), final)
        return [s.name for s in parsed]


def _front_name(folder: Path) -> str:
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    try:
        name = str((yaml.safe_load(text.split("---", 2)[1]) or {}).get("name") or "")
    except (yaml.YAMLError, IndexError) as exc:
        raise SkillError("SKILL.md must start with YAML front matter") from exc
    if not NAME.match(name):
        raise SkillError("'name' must be lowercase letters, digits and hyphens")
    return name


def install_skills_zip(blob: bytes, skills_dir: Path) -> list[str]:
    with _open(blob) as archive:
        names = install_skills(archive, skills_dir)
    if not names:
        raise ProjectError("no skill found in the archive (expected <name>/SKILL.md)")
    return names


def export_pack(custom_specialists: list[dict[str, Any]], custom_connectors: list[dict[str, Any]],
                user_skills: list[Path]) -> bytes:
    connectors = [{k: v for k, v in c.items() if k != "headers"} for c in custom_connectors]
    manifest = {"format": FORMAT, "version": VERSION, "specialists": custom_specialists, "connectors": connectors,
                "skills": sorted(p.name for p in user_skills)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        for folder in user_skills:
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    z.write(f, f"skills/{folder.name}/{f.relative_to(folder).as_posix()}")
    return buf.getvalue()


def read_pack(blob: bytes, skills_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Validate the pack, install its skills, and return (manifest, installed skill names)."""
    with _open(blob) as archive:
        try:
            manifest = json.loads(archive.read("pack.json"))
        except (KeyError, ValueError) as exc:
            raise ProjectError("the archive has no valid pack.json") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ProjectError("not a SPIKE pack (format/version)")
        for info in archive.infolist():
            if info.filename != "pack.json" and not info.is_dir() and not info.filename.startswith("skills/"):
                raise ProjectError(f"unexpected entry '{info.filename}'")
        skills = install_skills(archive, skills_dir, prefix="skills/")
    return manifest, skills
