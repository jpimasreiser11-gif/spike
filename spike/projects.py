"""Project folders and the project archive (a zip with project.json and the project's files, never any key)."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from spike.store.db import Store

FORMAT, VERSION = "spike-project", 1
MAX_FILE_BYTES = 50 * 1024**2
MAX_ARCHIVE_BYTES = 500 * 1024**2  # uncompressed, guards against zip bombs
MAX_ENTRIES = 5000


class ProjectError(ValueError):
    """A request about a project that cannot be honoured; the message is safe to show."""


def clean_path(relative: str) -> PurePosixPath:
    """A relative path that stays inside its folder, or ProjectError."""
    path = PurePosixPath(relative.replace("\\", "/"))
    if not relative or path.is_absolute() or any(part in ("", "..") for part in path.parts) or ":" in path.parts[0]:
        raise ProjectError(f"invalid file path '{relative}'")
    return path


class ProjectFiles:
    def __init__(self, root: Path):
        self.root = root

    def folder(self, pid: str) -> Path:
        path = self.root / pid / "files"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def remove(self, pid: str) -> None:
        shutil.rmtree(self.root / pid, ignore_errors=True)

    def list(self, pid: str) -> list[dict[str, Any]]:
        base = self.folder(pid)
        return [{"path": p.relative_to(base).as_posix(), "size": p.stat().st_size}
                for p in sorted(base.rglob("*")) if p.is_file()]

    def path(self, pid: str, relative: str) -> Path:
        return self.folder(pid).joinpath(*clean_path(relative).parts)

    def write(self, pid: str, relative: str, data: bytes) -> dict[str, Any]:
        if len(data) > MAX_FILE_BYTES:
            raise ProjectError(f"files are limited to {MAX_FILE_BYTES // 1024**2} MB")
        target = self.path(pid, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": clean_path(relative).as_posix(), "size": len(data)}


def export_project(store: Store, files: ProjectFiles, pid: str) -> bytes:
    project = store.get_project(pid)
    conversations = []
    for conv in sorted(store.list_conversations(project_id=pid, limit=100_000), key=lambda c: (c["created"], c["id"])):
        messages = [{k: m[k] for k in ("role", "content", "meta", "created")} for m in store.messages(conv["id"])]
        conversations.append({**{k: conv[k] for k in ("title", "mode", "provider_id", "created", "updated")},
                              "messages": messages})
    manifest = {"format": FORMAT, "version": VERSION,
                "project": {k: project[k] for k in ("name", "instructions", "mode")}, "conversations": conversations}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_entry("project.json"), json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
        base = files.folder(pid)
        for item in files.list(pid):
            z.writestr(_entry(f"files/{item['path']}"), (base / item["path"]).read_bytes())
    return buf.getvalue()


def _entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))  # fixed time: same content, same archive
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def import_project(store: Store, files: ProjectFiles, blob: bytes, modes: set[str]) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ProjectError("not a SPIKE project archive (zip)") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
            raise ProjectError("the archive is too large")
        payload: list[tuple[PurePosixPath, zipfile.ZipInfo]] = []
        for info in infos:
            if info.is_dir():
                continue
            if info.filename == "project.json":
                continue
            if not info.filename.startswith("files/"):
                raise ProjectError(f"unexpected entry '{info.filename}'")
            payload.append((clean_path(info.filename[len("files/"):]), info))
        try:
            manifest = json.loads(archive.read("project.json"))
        except (KeyError, ValueError) as exc:
            raise ProjectError("the archive has no valid project.json") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ProjectError("the archive is not a SPIKE project (format/version)")
        meta = manifest.get("project") or {}
        if not isinstance(meta.get("name"), str) or not meta["name"].strip():
            raise ProjectError("the project has no name")
        mode = meta.get("mode") or "auto"
        project = store.create_project(meta["name"], str(meta.get("instructions") or ""),
                                       mode if mode in modes else "auto")
        try:
            for conv in manifest.get("conversations") or []:
                c = store.create_conversation(title=str(conv.get("title") or "Imported chat"),
                                              mode=conv.get("mode") if conv.get("mode") in modes else "auto",
                                              provider_id=conv.get("provider_id"), project_id=project["id"],
                                              created=conv.get("created"), updated=conv.get("updated"))
                for m in conv.get("messages") or []:
                    if m.get("role") in ("user", "assistant"):
                        store.add_message(c["id"], m["role"], str(m.get("content") or ""), m.get("meta") or {},
                                          created=m.get("created"))
            for path, info in payload:
                files.write(project["id"], path.as_posix(), archive.read(info))
        except Exception:
            store.delete_project(project["id"])
            files.remove(project["id"])
            raise
    return project
