"""Installing skills from a zip, and packs: custom specialists + user skills + custom connectors in one zip,
never with secrets."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from spike.projects import ProjectError, clean_path
from spike.runtime.urls import strip_url_secrets
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
    if len(infos) > MAX_ENTRIES or sum(max(0, i.file_size) for i in infos) > MAX_BYTES:
        raise ProjectError("the archive is too large")
    return archive


def _is_os_metadata(path: PurePosixPath) -> bool:
    return "__MACOSX" in path.parts or (
        bool(path.parts) and (path.parts[-1] == ".DS_Store" or path.parts[-1].startswith("._"))
    )


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, budget: list[int]) -> bytes:
    chunks: list[bytes] = []
    try:
        with archive.open(info) as stream:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                budget[0] -= len(chunk)
                if budget[0] < 0:
                    raise ProjectError("the archive is too large")
                chunks.append(chunk)
    except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError, OSError) as exc:
        raise ProjectError("corrupted zip entry") from exc
    return b"".join(chunks)


def install_skills(
    archive: zipfile.ZipFile, skills_dir: Path, prefix: str = "", *, _budget: list[int] | None = None
) -> list[str]:
    """Install every skill folder found under `prefix` (a folder with SKILL.md, or SKILL.md at the top)."""
    budget = [MAX_BYTES] if _budget is None else _budget
    entries: list[tuple[PurePosixPath, zipfile.ZipInfo]] = []
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        rel = clean_path(info.filename[len(prefix):])
        if _is_os_metadata(rel):
            continue
        entries.append((rel, info))
    if not entries:
        return []
    skills_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=skills_dir, prefix=".incoming-") as tmp:
        staging = Path(tmp)
        single = any(path.as_posix() == "SKILL.md" for path, _ in entries)
        for path, info in entries:
            target = staging.joinpath("_single" if single else "", *path.parts)
            data = _read_entry(archive, info, budget)
            if path.name == "SKILL.md" and data.startswith(b"\xef\xbb\xbf"):
                data = data[3:]
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ProjectError(f"conflicting archive entry '{path.as_posix()}'")
                target.write_bytes(data)
            except OSError as exc:
                raise ProjectError(f"conflicting archive path '{path.as_posix()}'") from exc
        if single:  # SKILL.md at the top: the folder takes the skill's own name
            try:
                name = _front_name(staging / "_single")
            except SkillError as exc:
                raise ProjectError(str(exc)) from exc
            if (staging / "_single") != (staging / name):
                (staging / "_single").replace(staging / name)
            folders = [staging / name]
        else:
            folders = sorted(p for p in staging.iterdir() if p.is_dir())
        parsed = []
        for folder in folders:
            try:
                parsed.append(parse_skill(folder, source="user"))
            except SkillError as exc:
                raise ProjectError(str(exc)) from exc
        seen: set[str] = set()
        for skill in parsed:
            if skill.name in seen:
                raise ProjectError(f"duplicate skill '{skill.name}' in archive")
            seen.add(skill.name)
        for skill in parsed:
            final = skills_dir / skill.name
            if final.exists():
                def _force_remove(func, p, _exc):
                    Path(p).chmod(0o700)
                    func(p)
                shutil.rmtree(final, onerror=_force_remove)
            shutil.move(str(skill.path), final)
        return [s.name for s in parsed]


def _front_name(folder: Path) -> str:
    try:
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillError("SKILL.md must be saved as UTF-8") from exc
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        raise SkillError("SKILL.md must start with YAML front matter")
    try:
        front = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise SkillError("SKILL.md must start with YAML front matter") from exc
    if front is not None and not isinstance(front, dict):
        raise SkillError("SKILL.md front matter must be a mapping")
    raw_name = (front or {}).get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not NAME.match(name):
        raise SkillError("'name' must be lowercase letters, digits and hyphens")
    return name


def _validate_pack_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise ProjectError("not a SPIKE pack (format/version)")
    for field in ("specialists", "connectors"):
        value = manifest.get(field)
        if value is not None and (not isinstance(value, list) or not all(isinstance(x, dict) for x in value)):
            raise ProjectError(f"invalid '{field}' in pack.json")
    skills_field = manifest.get("skills")
    if skills_field is not None and (
        not isinstance(skills_field, list) or not all(isinstance(x, str) for x in skills_field)
    ):
        raise ProjectError("invalid 'skills' in pack.json")
    return manifest


def install_skills_zip(blob: bytes, skills_dir: Path) -> list[str]:
    with _open(blob) as archive:
        names = install_skills(archive, skills_dir)
    if not names:
        raise ProjectError("no skill found in the archive (expected <name>/SKILL.md)")
    return names


def export_pack(custom_specialists: list[dict[str, Any]], custom_connectors: list[dict[str, Any]],
                user_skills: list[Path]) -> bytes:
    connectors = [{k: strip_url_secrets(v) if k == "url" and isinstance(v, str) else v
                   for k, v in c.items() if k != "headers"} for c in custom_connectors]
    manifest = {"format": FORMAT, "version": VERSION, "specialists": custom_specialists, "connectors": connectors,
                "skills": sorted(p.name for p in user_skills)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        for folder in user_skills:
            for f in sorted(folder.rglob("*")):
                rel = f.relative_to(folder).as_posix()
                if f.is_file() and not _is_os_metadata(PurePosixPath(rel)):
                    z.write(f, f"skills/{folder.name}/{rel}")
    return buf.getvalue()


def read_pack(blob: bytes, skills_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Validate the pack, install its skills, and return (manifest, installed skill names)."""
    budget = [MAX_BYTES]
    with _open(blob) as archive:
        try:
            pack_info = archive.getinfo("pack.json")
            manifest = json.loads(_read_entry(archive, pack_info, budget).decode("utf-8-sig"))
        except (KeyError, ValueError) as exc:
            raise ProjectError("the archive has no valid pack.json") from exc
        _validate_pack_manifest(manifest)
        for info in archive.infolist():
            if info.is_dir() or info.filename == "pack.json":
                continue
            rel = clean_path(info.filename)
            if _is_os_metadata(rel):
                continue
            if not info.filename.startswith("skills/"):
                raise ProjectError(f"unexpected entry '{info.filename}'")
        skills = install_skills(archive, skills_dir, prefix="skills/", _budget=budget)
    return manifest, skills
