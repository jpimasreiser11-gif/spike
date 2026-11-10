"""Backup and restore of the user's data in SPIKE_HOME (G34): one ZIP with a manifest and a SHA-256 per file.

What goes in: settings, conversations and history (spike.db), memory and its vectors (memory.db), evolution data,
projects and their files, the user's own skills, design systems, recorded view scripts and custom connector
definitions. What never goes in: API keys and connector secrets (secrets.json and the OS keychain are not read), files
that look like secrets (`.env`, keys, certificates), symlinks, checkpoints, logs and caches. Downloaded models and
adapters only when asked (`include_models`). SQLite files are copied with the backup API, so rows still in the -wal
file are in the copy and the copy is consistent while SPIKE keeps running.

A restore verifies the whole archive first (paths, symlinks, SHA-256 of every entry, decompressed size), shows what
would be added or replaced, and replaces nothing unless `overwrite` is set. Entries are only ever written to the fixed
set of places above, never to a path taken from the archive.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from spike import __version__

FORMAT, VERSION = "spike-backup", 1
MAX_BYTES = 4 * 1024**3  # decompressed bytes of the whole archive (models are the only way to get near it)
MAX_ENTRIES = 100_000
MAX_MANIFEST = 32 * 1024**2
CHUNK = 1024 * 1024

DB_FILES = ("spike.db", "memory.db", "evolution.db", "dev/sessions.db")
OTHER_FILES = ("tune.json",)
DATA_DIRS = ("projects", "skills", "design-systems", "view-scripts", "connectors")
MODEL_DIRS = ("models", "adapters")
SECRET_NAMES = {"secrets.json", "secrets.json.tmp", "id_rsa", "id_ed25519"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")
SKIP_SUFFIXES = ("-wal", "-shm", "-journal", ".tmp", ".part", ".lock")


class BackupError(ValueError):
    """The archive is not a valid, safe SPIKE backup (the message is shown to the user)."""


def is_secret_name(name: str) -> bool:
    low = name.lower()
    return (low in SECRET_NAMES or low.startswith(".env") or low.endswith(SECRET_SUFFIXES)
            or "secret" in low and low.endswith(".json"))


def _declared_total(infos: list[zipfile.ZipInfo]) -> int:
    return sum(max(0, i.file_size) for i in infos)


def safe_rel(rel: object, include_models: bool = True) -> str:
    """The relative POSIX path if it is one of the places a backup may hold, else BackupError."""
    if not isinstance(rel, str) or not rel or len(rel) > 400 or "\\" in rel or "\0" in rel or rel.startswith("/"):
        raise BackupError(f"unsafe path in the backup: {str(rel)[:80]!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") or ":" in p or p != p.strip() or p.endswith(".") for p in parts):
        raise BackupError(f"unsafe path in the backup: {rel[:80]!r}")
    if is_secret_name(parts[-1]) or any(is_secret_name(p) for p in parts):
        raise BackupError(f"a secret file cannot be in a backup: {rel[:80]!r}")
    allowed = rel in DB_FILES or rel in OTHER_FILES or (
        len(parts) > 1 and parts[0] in (DATA_DIRS + (MODEL_DIRS if include_models else ())))
    if not allowed:
        raise BackupError(f"path not allowed in a backup: {rel[:80]!r}")
    return rel


# ------------------------------------------------------------------------------------------------------- creating
def _sqlite_copy(src: Path, dest: Path) -> None:
    try:
        source = sqlite3.connect(str(src), timeout=30)
        try:
            target = sqlite3.connect(str(dest))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    except sqlite3.Error as exc:
        raise BackupError(f"could not copy the database {src.name}: {exc}") from exc


def _tree(home: Path, top: str) -> list[str]:
    out: list[str] = []
    root = home / top
    if not root.is_dir() or root.is_symlink():
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not (Path(dirpath, d).is_symlink() or is_secret_name(d)
                                                         or d.startswith(".restore-")))
        for name in sorted(filenames):
            p = Path(dirpath, name)
            if p.is_symlink() or not p.is_file() or is_secret_name(name) or name.endswith(SKIP_SUFFIXES):
                continue
            out.append(p.relative_to(home).as_posix())
    return out


def plan(home: Path, include_models: bool = False) -> list[str]:
    files = [f for f in (*DB_FILES, *OTHER_FILES) if (home / f).is_file() and not (home / f).is_symlink()]
    for top in DATA_DIRS + (MODEL_DIRS if include_models else ()):
        files += _tree(home, top)
    return [f for f in files if _restorable(f)]  # a name a restore would refuse (`a:b`, `x.`) is left out


def _restorable(rel: str) -> bool:
    try:
        safe_rel(rel)
    except BackupError:
        return False
    return True


def create_backup(home: Path, out: BinaryIO, include_models: bool = False) -> dict:
    """Writes the ZIP to `out`; returns the manifest."""
    home = Path(home)
    entries: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in plan(home, include_models):
            source = home / rel
            if rel in DB_FILES:
                source = Path(tmp) / rel.replace("/", "_")
                _sqlite_copy(home / rel, source)
            digest, size = hashlib.sha256(), 0
            try:
                with open(source, "rb") as f, z.open(zipfile.ZipInfo(f"files/{rel}", time.localtime()[:6]), "w",
                                                      force_zip64=True) as w:
                    while chunk := f.read(CHUNK):
                        digest.update(chunk)
                        size += len(chunk)
                        w.write(chunk)
            except OSError:
                continue  # a file removed or locked while the backup runs is left out, not a failed backup
            entries.append({"path": rel, "size": size, "sha256": digest.hexdigest()})
        manifest = {"format": FORMAT, "version": VERSION, "spike_version": __version__, "created": int(time.time()),
                    "include_models": include_models, "files": entries}
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    return manifest


# ------------------------------------------------------------------------------------------------------- reading
def _open(src: bytes | BinaryIO) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(src) if isinstance(src, bytes | bytearray) else src)
    except (zipfile.BadZipFile, OSError, EOFError, zlib.error, ValueError) as exc:
        raise BackupError("not a SPIKE backup (the file is not a valid or complete ZIP)") from exc
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES or _declared_total(infos) > MAX_BYTES:
        raise BackupError("the backup is too large")
    return z


def _read_manifest(z: zipfile.ZipFile) -> dict:
    try:
        info = z.getinfo("manifest.json")
    except KeyError as exc:
        raise BackupError("not a SPIKE backup (no manifest.json)") from exc
    if info.file_size > MAX_MANIFEST:
        raise BackupError("the manifest is too large")
    try:
        with z.open(info) as f:
            raw = f.read(MAX_MANIFEST + 1)
        if len(raw) > MAX_MANIFEST:
            raise BackupError("the manifest is too large")
        manifest = json.loads(raw.decode("utf-8"))
    except (zipfile.BadZipFile, zlib.error, OSError, EOFError, ValueError) as exc:
        raise BackupError("the manifest is damaged") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupError("not a SPIKE backup")
    if manifest.get("version") != VERSION:
        raise BackupError(f"unsupported backup format version {str(manifest.get('version'))[:20]}")
    if not isinstance(manifest.get("files"), list):
        raise BackupError("the manifest has no file list")
    return manifest


def _validate(z: zipfile.ZipFile) -> tuple[dict, dict[str, dict]]:
    names: set[str] = set()
    for info in z.infolist():
        if info.filename in names:
            raise BackupError("duplicate entry in the backup")
        names.add(info.filename)
        mode = info.external_attr >> 16
        if info.create_system == 3 and stat.S_ISLNK(mode):
            raise BackupError(f"a symlink cannot be in a backup: {info.filename[:80]!r}")
        if info.flag_bits & 0x1:
            raise BackupError("encrypted entries are not supported")
    manifest = _read_manifest(z)
    models = bool(manifest.get("include_models"))
    listed: dict[str, dict] = {}
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise BackupError("the manifest is damaged")
        rel = safe_rel(item.get("path"), models)
        sha = item.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64 or not isinstance(item.get("size"), int) or item["size"] < 0:
            raise BackupError(f"the manifest entry for {rel} is damaged")
        if rel in listed:
            raise BackupError(f"duplicate manifest entry {rel}")
        listed[rel] = item
    present = {n[6:] for n in names if n.startswith("files/") and not n.endswith("/")}
    stray = {n for n in names if n != "manifest.json" and not n.startswith("files/")}
    extra = (present - set(listed)) | stray
    if extra:
        raise BackupError(f"entry not in the manifest: {sorted(extra)[0][:80]!r}")
    missing = set(listed) - present
    if missing:
        raise BackupError(f"file listed in the manifest is missing from the archive: {sorted(missing)[0]}")
    return manifest, listed


def _stream(z: zipfile.ZipFile, rel: str, item: dict, budget: list[int], sink: BinaryIO | None) -> None:
    """Reads one entry counting the real decompressed bytes (headers may lie), checks size and SHA-256."""
    digest, size = hashlib.sha256(), 0
    try:
        with z.open(f"files/{rel}") as stream:
            while chunk := stream.read(CHUNK):
                budget[0] -= len(chunk)
                if budget[0] < 0:
                    raise BackupError("the backup is too large")
                size += len(chunk)
                digest.update(chunk)
                if sink is not None:
                    sink.write(chunk)
    except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError, OSError) as exc:
        raise BackupError(f"damaged entry in the backup: {rel}") from exc
    if size != item["size"] or digest.hexdigest() != item["sha256"].lower():
        raise BackupError(f"SHA-256 mismatch for {rel}: the backup is damaged or was modified")


def _target(home: Path, rel: str) -> Path:
    """home/rel without following symlinks that sit on the way."""
    path = home
    for part in rel.split("/"):
        path = path / part
        if path.is_symlink():
            raise BackupError(f"{rel} would be written through a link")
    return path


def _action(home: Path, rel: str, item: dict) -> str:
    target = _target(home, rel)
    if not target.exists():
        return "add"
    if not target.is_file():
        raise BackupError(f"{rel} would replace a folder")
    if rel in DB_FILES:
        return "replace"
    digest = hashlib.sha256()
    with open(target, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return "same" if digest.hexdigest() == item["sha256"].lower() else "replace"


def inspect_backup(src: bytes | BinaryIO, home: Path) -> dict:
    """Verifies the archive completely and says what a restore would do. Changes nothing."""
    home = Path(home)
    with _open(src) as z:
        manifest, listed = _validate(z)
        budget = [MAX_BYTES]
        for rel, item in listed.items():
            _stream(z, rel, item, budget, None)
        files = [{"path": rel, "size": item["size"], "action": _action(home, rel, item)} for rel, item in listed.items()]
    count = {a: sum(1 for f in files if f["action"] == a) for a in ("add", "replace", "same")}
    return {"format": FORMAT, "version": manifest["version"], "spike_version": manifest.get("spike_version", ""),
            "created": manifest.get("created", 0), "include_models": bool(manifest.get("include_models")),
            "total_bytes": sum(f["size"] for f in files), "files": files, **count}


# ------------------------------------------------------------------------------------------------------- restoring
def _check_db(path: Path) -> None:
    try:
        db = sqlite3.connect(str(path))
        try:
            ok = db.execute("PRAGMA quick_check").fetchone()
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise BackupError(f"{path.name} in the backup is not a valid database") from exc
    if not ok or ok[0] != "ok":
        raise BackupError(f"{path.name} in the backup is damaged")


def restore_backup(src: bytes | BinaryIO, home: Path, overwrite: bool = False,
                   progress: Callable[[str], None] | None = None) -> dict:
    """Restores the archive into `home`. Files that already exist are replaced only with `overwrite=True`; otherwise
    they are skipped. Call it while SPIKE's databases are closed (the server closes and reopens its state around it)."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    staging = home / f".restore-{uuid.uuid4().hex}"
    result = {"added": 0, "replaced": 0, "skipped": 0, "same": 0}
    try:
        with _open(src) as z:
            manifest, listed = _validate(z)
            budget = [MAX_BYTES]
            staged: dict[str, Path] = {}
            for rel, item in listed.items():
                action = _action(home, rel, item)
                if action == "same":
                    result["same"] += 1
                    continue
                if action == "replace" and not overwrite:
                    result["skipped"] += 1
                    _stream(z, rel, item, budget, None)  # still verified: a damaged archive fails as a whole
                    continue
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as sink:
                    _stream(z, rel, item, budget, sink)
                if rel in DB_FILES:
                    _check_db(dest)
                staged[rel] = dest
                result["added" if action == "add" else "replaced"] += 1
        for rel, dest in staged.items():  # only now, with everything verified, does anything in `home` change
            target = _target(home, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            if rel in DB_FILES:
                for side in ("-wal", "-shm"):
                    with contextlib.suppress(OSError):
                        Path(str(target) + side).unlink()
            os.replace(dest, target)
            if progress:
                progress(rel)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return result
