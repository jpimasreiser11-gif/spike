"""Project folders and the project archive (a zip with project.json and the project's files, never any key)."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from spike.memory.store import KINDS, MAX_TEXT, MemoryStore
from spike.store.db import Store

FORMAT, VERSION = "spike-project", 1
MAX_FILE_BYTES = 50 * 1024**2
MAX_ARCHIVE_BYTES = 500 * 1024**2  # uncompressed, guards against zip bombs
MAX_MEMORIES = 1000
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
        if self._linked(self.root, path):
            raise ProjectError("file path leaves the project or uses a symbolic link")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def remove(self, pid: str) -> None:
        """Remove one managed project; retry read-only Git objects, but report locked files for a later retry.

        Never chmod links or paths outside this project. Missing files are already removed; other failures must
        reach the caller before its project record and conversations are deleted. This is not an atomic rollback.
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]+", pid):
            raise ProjectError("invalid project id / identificador de proyecto no válido")
        base = self.root / pid
        if self._linked(self.root, base) or not base.resolve().is_relative_to(self.root.resolve()):
            raise ProjectError("project folder uses a link or leaves its root / la carpeta del proyecto usa un enlace o sale de su raíz")

        def retry_readonly(function, path, info):
            error = info[1]
            if isinstance(error, FileNotFoundError):
                return
            target = Path(path)
            if (not isinstance(error, PermissionError) or function not in (os.unlink, os.remove, os.rmdir)
                    or target.is_symlink() or not target.resolve().is_relative_to(base.resolve())):
                raise error
            target.chmod(target.stat().st_mode | stat.S_IWUSR)
            function(path)

        try:
            shutil.rmtree(base, onerror=retry_readonly)
        except OSError as exc:
            raise ProjectError("Cannot remove project files; close applications using them and retry. / "
                               "No se pueden eliminar los archivos; cierra las aplicaciones que los usan y reintenta.") from exc

    def list(self, pid: str) -> list[dict[str, Any]]:
        base = self.folder(pid)  # a repository's own files (Parallel Prototypes makes one) are not the user's files
        return [{"path": p.relative_to(base).as_posix(), "size": p.stat().st_size}
                for p in sorted(base.rglob("*"))
                if p.is_file() and ".git" not in p.relative_to(base).parts and not self._linked(base, p)]

    @staticmethod
    def _linked(base: Path, path: Path) -> bool:
        return any(p.is_symlink() for p in (path, *path.parents) if p != base and base in p.parents)

    def path(self, pid: str, relative: str) -> Path:
        base = self.folder(pid)
        target = base.joinpath(*clean_path(relative).parts)
        if self._linked(base, target) or not target.resolve().is_relative_to(base.resolve()):
            raise ProjectError("file path leaves the project or uses a symbolic link")
        return target

    def write(self, pid: str, relative: str, data: bytes) -> dict[str, Any]:
        if len(data) > MAX_FILE_BYTES:
            raise ProjectError(f"files are limited to {MAX_FILE_BYTES // 1024**2} MB")
        target = self.path(pid, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": clean_path(relative).as_posix(), "size": len(data)}


def export_project(store: Store, files: ProjectFiles, pid: str, memory: MemoryStore | None = None) -> bytes:
    project = store.get_project(pid)
    conversations = []
    for conv in sorted(store.list_conversations(project_id=pid, limit=100_000), key=lambda c: (c["created"], c["id"])):
        messages = [{k: m[k] for k in ("role", "content", "meta", "created")} for m in store.messages(conv["id"])]
        conversations.append({**{k: conv[k] for k in ("title", "mode", "provider_id", "created", "updated")},
                              "messages": messages})
    manifest = {"format": FORMAT, "version": VERSION,
                "project": {k: project[k] for k in ("name", "instructions", "mode", "design")},
                "conversations": conversations}
    if memory is not None:
        # Indexed files and chat summaries are rebuilt locally; notes never carry local sources or metadata.
        notes = [m for m in memory.list(scope=f"project:{pid}", limit=-1)
                 if not m.source.startswith(("file:", "conversation:"))]
        if len(notes) > MAX_MEMORIES:
            raise ProjectError("too many project notes to export")
        manifest["memories"] = [{"kind": m.kind, "text": m.text} for m in sorted(notes, key=lambda m: (m.kind, m.text))]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_entry("project.json"), json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
        for item in files.list(pid):
            z.writestr(_entry(f"files/{item['path']}"), files.path(pid, item["path"]).read_bytes())
    return buf.getvalue()


def _entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))  # fixed time: same content, same archive
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def import_project(store: Store, files: ProjectFiles, blob: bytes, modes: set[str],
                   memory: MemoryStore | None = None) -> dict[str, Any]:
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
        notes = manifest.get("memories", [])
        if not isinstance(notes, list) or len(notes) > MAX_MEMORIES:
            raise ProjectError("invalid project notes or note budget exceeded")
        for note in notes:
            if (not isinstance(note, dict) or note.get("kind") not in KINDS
                    or not isinstance(note.get("text"), str) or not note["text"].strip()
                    or len(note["text"]) > MAX_TEXT):
                raise ProjectError("invalid project note (kind/text)")
        if notes and memory is None:
            raise ProjectError("project notes need a memory store")
        meta = manifest.get("project") or {}
        if not isinstance(meta.get("name"), str) or not meta["name"].strip():
            raise ProjectError("the project has no name")
        mode = meta.get("mode") or "auto"
        design = meta.get("design") if isinstance(meta.get("design"), str) else ""
        project = store.create_project(meta["name"], str(meta.get("instructions") or ""),
                                       mode if mode in modes else "auto",
                                       design if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", design) else "")
        try:
            if memory is not None:
                for note in notes:
                    memory.add(note["text"], note["kind"], scope=f"project:{project['id']}")
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
            if memory is not None:
                memory.delete_scope(f"project:{project['id']}")
            store.delete_project(project["id"])
            files.remove(project["id"])
            raise
    return project
