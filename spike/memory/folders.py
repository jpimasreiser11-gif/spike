"""Opt-in folder indexing: folders the user chose put their files in Neural Memory, and only those.

Nothing is indexed until the user adds a folder (an absolute path, in Settings). A folder has include and exclude
globs, a size limit per file and a limit of files; by default it takes text, Markdown, code, HTML, PDF and Word and
skips hidden files and folders, `node_modules`, virtual environments, build output, secrets and binaries. The walk
never follows a link out of the folder, never enters SPIKE's own data folder and re-checks the path of every file
just before reading it. Each file becomes one `document` memory whose source is its path (`file:/the/path`), so
answers cite it. Re-indexing compares modification time and size with what was indexed and only reads the files that
changed (and forgets the ones that vanished); it runs in the background with progress in `Job`. Forgetting a folder
deletes the memories of its files, with their chunks, word index and vectors, and the folder's own rows.

Glob rules (names are compared case-insensitively): a pattern without `/` is matched against the file or folder name
(`node_modules`, `*.min.js`, `.*`); one with `/` against the path relative to the folder, where `*` also crosses
slashes (`drafts/*`).
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spike.memory.extract import extract_text
from spike.memory.store import GLOBAL, MemoryStore

log = logging.getLogger(__name__)

DEFAULT_INCLUDE = (
    "*.txt", "*.md", "*.markdown", "*.rst", "*.csv", "*.tsv", "*.json", "*.jsonl", "*.yaml", "*.yml", "*.toml",
    "*.xml", "*.ini", "*.cfg", "*.tex", "*.html", "*.htm", "*.pdf", "*.docx",
    "*.py", "*.js", "*.ts", "*.tsx", "*.jsx", "*.java", "*.go", "*.rs", "*.c", "*.h", "*.cpp", "*.sql", "*.sh")
DEFAULT_EXCLUDE = (
    ".*", "node_modules", "venv", "env", "virtualenv", "site-packages", "__pycache__", "dist", "build",
    "*.min.js", "*.min.css", "*.map", "*.lock", "package-lock.json",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "id_rsa*", "id_ed25519*", "secrets*", "credentials*")
DEFAULT_MAX_FILE_BYTES = 5 * 1024**2
DEFAULT_MAX_FILES = 2000
MAX_FILE_BYTES_LIMIT = 200 * 1024**2
MAX_FILES_LIMIT = 20_000
MAX_SCAN = 200_000  # directory entries looked at in one pass: a folder this large should be narrowed
MAX_PATTERNS = 100
SNIFF = 4096
CONTAINERS = {".pdf", ".docx", ".xlsx", ".pptx"}  # binary on purpose: their extractors read them
EMBED_BATCH = 512
STATUS_INDEXED, STATUS_UNREADABLE, STATUS_BINARY = "indexed", "unreadable", "binary"

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, include TEXT NOT NULL, exclude TEXT NOT NULL,
  max_file_bytes INTEGER NOT NULL, max_files INTEGER NOT NULL, added REAL NOT NULL, indexed REAL,
  summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS folder_files (
  folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE, rel TEXT NOT NULL,
  mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
  memory_id TEXT REFERENCES memories(id) ON DELETE CASCADE, PRIMARY KEY (folder_id, rel)
);
CREATE INDEX IF NOT EXISTS folder_files_memory ON folder_files(memory_id);
"""


class FolderError(ValueError):
    """A folder or rule that cannot be accepted; the message is safe to show."""


@dataclass
class Folder:
    id: str
    path: str
    scope: str
    include: list[str]
    exclude: list[str]
    max_file_bytes: int
    max_files: int
    added: float
    indexed: float | None = None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    """One indexing pass over a folder; the API shows it while it runs and after."""

    folder_id: str
    force: bool = False
    state: str = "queued"  # queued | scanning | indexing | embedding | done | error | cancelled
    total: int = 0  # files that passed the rules
    done: int = 0  # of those, looked at so far
    indexed: int = 0  # read again this pass
    unchanged: int = 0
    removed: int = 0
    embedded: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    current: str = ""
    started: float = field(default_factory=time.time)
    finished: float | None = None
    error: str = ""
    warning: str = ""
    cancel: bool = False
    scheduled: bool = False  # something is going to run it

    @property
    def active(self) -> bool:
        return self.state in ("queued", "scanning", "indexing", "embedding")

    def public(self) -> dict[str, Any]:
        return {"state": self.state, "total": self.total, "done": self.done, "indexed": self.indexed,
                "unchanged": self.unchanged, "removed": self.removed, "embedded": self.embedded,
                "skipped": dict(self.skipped), "current": self.current, "started": self.started,
                "finished": self.finished, "error": self.error, "warning": self.warning, "force": self.force}


@dataclass
class Candidate:
    rel: str
    path: Path
    size: int
    mtime_ns: int


@dataclass
class Scan:
    files: list[Candidate] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    truncated: bool = False

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _key(path: Path | str) -> str:
    return os.path.normcase(str(path))


def within(path: Path, root: Path) -> bool:
    """Whether `path` is `root` or inside it (both resolved, compared the way the OS compares names)."""
    p, r = _key(path), _key(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def matches(patterns: list[str] | tuple[str, ...], name: str, rel: str, directory: bool = False) -> bool:
    name, rel = name.casefold(), rel.casefold()
    for pattern in patterns:
        pattern = pattern.strip().casefold()
        if not pattern:
            continue
        if "/" in pattern:
            pattern = pattern.strip("/")
            if fnmatch.fnmatchcase(rel, pattern) or (directory and fnmatch.fnmatchcase(rel + "/", pattern)):
                return True
        elif fnmatch.fnmatchcase(name, pattern):
            return True
    return False


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def scan_folder(folder: Folder, protected: list[Path] | None = None) -> Scan:
    """The files of a folder that pass its rules, in path order. Reads names and sizes only, never contents."""
    scan = Scan()
    root = Path(folder.path)
    try:
        real_root = root.resolve(strict=True)
    except OSError as exc:
        raise FolderError(f"the folder cannot be read: {exc.strerror or exc}") from exc
    blocked = [p.resolve() for p in protected or []]
    seen = 0

    def denied(error: OSError) -> None:
        scan.skip("denied")

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=denied):
        here = Path(dirpath)
        if "pyvenv.cfg" in filenames:  # a Python virtual environment, whatever it is called
            dirnames.clear()
            scan.skip("venv")
            continue
        keep = []
        for name in sorted(dirnames):
            full = here / name
            rel = full.relative_to(root).as_posix()
            if matches(folder.exclude, name, rel, directory=True):
                continue
            if _is_link(full):
                scan.skip("link")
                continue
            try:
                real = full.resolve()
            except (OSError, RuntimeError):
                scan.skip("denied")
                continue
            if not within(real, real_root) or any(within(real, b) for b in blocked):
                scan.skip("outside")
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            seen += 1
            if seen > MAX_SCAN:
                scan.truncated = True
                dirnames.clear()
                return scan
            full = here / name
            rel = full.relative_to(root).as_posix()
            if matches(folder.exclude, name, rel) or not matches(folder.include, name, rel):
                continue
            try:
                if _is_link(full):  # a link is fine while its target stays inside the folder
                    target = full.resolve()
                    if not within(target, real_root) or any(within(target, b) for b in blocked):
                        scan.skip("outside")
                        continue
                    if not target.is_file():
                        continue
                st = full.stat()
            except (OSError, RuntimeError):
                scan.skip("denied")
                continue
            if not full.is_file():
                continue
            if st.st_size == 0:
                scan.skip("empty")
            elif st.st_size > folder.max_file_bytes:
                scan.skip("too_big")
            elif len(scan.files) >= folder.max_files:
                scan.skip("limit")
            else:
                scan.files.append(Candidate(rel, full, st.st_size, st.st_mtime_ns))
    return scan


def clean_patterns(value: Any, what: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_PATTERNS:
        raise FolderError(f"{what} must be a list of at most {MAX_PATTERNS} patterns")
    out = []
    for item in value:
        if not isinstance(item, str) or len(item) > 200 or "\0" in item:
            raise FolderError(f"{what}: each pattern must be text of at most 200 characters")
        if item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


def _row(r: sqlite3.Row) -> Folder:
    return Folder(id=r["id"], path=r["path"], scope=r["scope"], include=json.loads(r["include"]),
                  exclude=json.loads(r["exclude"]), max_file_bytes=r["max_file_bytes"], max_files=r["max_files"],
                  added=r["added"], indexed=r["indexed"], summary=json.loads(r["summary"] or "{}"))


class FolderIndex:
    """The folders the user chose, the files indexed from them and the indexing passes (see the module doc).

    `protected` gives paths that are never indexed (SPIKE's own data folder); `embed` gives the new chunks their
    vectors and returns how many it embedded (0 when there is no embedding model)."""

    def __init__(self, store: MemoryStore, protected: Callable[[], list[Path]] | None = None,
                 embed: Callable[[int], Awaitable[int]] | None = None):
        self.store = store
        self.protected = protected or (lambda: [])
        self.embed = embed
        self.jobs: dict[str, Job] = {}
        self._turn: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None
        with store.write() as db:
            db.executescript(SCHEMA)

    # ---------------------------------------------------------------- the list
    def list(self) -> list[Folder]:
        with self.store.read() as db:
            return [_row(r) for r in db.execute("SELECT * FROM folders ORDER BY added, id").fetchall()]

    def get(self, folder_id: str) -> Folder | None:
        with self.store.read() as db:
            r = db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        return _row(r) if r else None

    def add(self, path: str, scope: str = GLOBAL, include: Any = None, exclude: Any = None,
            max_file_bytes: int | None = None, max_files: int | None = None) -> Folder:
        if not isinstance(path, str) or not path.strip() or "\0" in path:
            raise FolderError("choose a folder")
        given = Path(path.strip())
        if not given.is_absolute():
            raise FolderError("the path must be absolute, for example /home/you/notes or C:\\Users\\you\\notes")
        try:
            real = given.resolve(strict=True)
        except OSError as exc:
            raise FolderError("that folder does not exist or cannot be read") from exc
        if not real.is_dir():
            raise FolderError("that path is not a folder")
        if real.parent == real:
            raise FolderError("choose a folder, not a whole disk")
        if any(within(real, p.resolve()) for p in self.protected()):
            raise FolderError("SPIKE's own data folder cannot be indexed")
        for other in self.list():
            if within(real, Path(other.path)) or within(Path(other.path), real):
                raise FolderError(f"it overlaps a folder already indexed: {other.path}")
        folder = Folder(
            id=uuid.uuid4().hex[:12], path=str(real), scope=scope,
            include=list(DEFAULT_INCLUDE) if include is None else clean_patterns(include, "include"),
            exclude=list(DEFAULT_EXCLUDE) if exclude is None else clean_patterns(exclude, "exclude"),
            max_file_bytes=self._limit(max_file_bytes, DEFAULT_MAX_FILE_BYTES, 1024, MAX_FILE_BYTES_LIMIT, "size"),
            max_files=self._limit(max_files, DEFAULT_MAX_FILES, 1, MAX_FILES_LIMIT, "files"), added=time.time())
        if not folder.include:
            raise FolderError("include at least one pattern, for example *.md")
        with self.store.write() as db:
            db.execute("INSERT INTO folders (id, path, scope, include, exclude, max_file_bytes, max_files, added) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (folder.id, folder.path, scope, json.dumps(folder.include), json.dumps(folder.exclude),
                        folder.max_file_bytes, folder.max_files, folder.added))
        return folder

    @staticmethod
    def _limit(value: Any, default: int, low: int, high: int, what: str) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise FolderError(f"the {what} limit must be a whole number between {low} and {high}")
        return value

    def update(self, folder_id: str, include: Any = None, exclude: Any = None, max_file_bytes: int | None = None,
               max_files: int | None = None) -> Folder | None:
        folder = self.get(folder_id)
        if folder is None:
            return None
        folder.include = folder.include if include is None else clean_patterns(include, "include")
        folder.exclude = folder.exclude if exclude is None else clean_patterns(exclude, "exclude")
        folder.max_file_bytes = self._limit(max_file_bytes, folder.max_file_bytes, 1024, MAX_FILE_BYTES_LIMIT, "size")
        folder.max_files = self._limit(max_files, folder.max_files, 1, MAX_FILES_LIMIT, "files")
        if not folder.include:
            raise FolderError("include at least one pattern, for example *.md")
        with self.store.write() as db:
            db.execute("UPDATE folders SET include = ?, exclude = ?, max_file_bytes = ?, max_files = ? WHERE id = ?",
                       (json.dumps(folder.include), json.dumps(folder.exclude), folder.max_file_bytes,
                        folder.max_files, folder_id))
        return folder

    def forget(self, folder_id: str) -> dict[str, int] | None:
        """Remove the folder and everything indexed from it: memories, chunks, word index rows and vectors."""
        job = self.jobs.get(folder_id)
        if job is not None:
            job.cancel = True
        with self.store.read() as db:
            if db.execute("SELECT 1 FROM folders WHERE id = ?", (folder_id,)).fetchone() is None:
                return None
            files = db.execute("SELECT COUNT(memory_id) FROM folder_files WHERE folder_id = ?",
                               (folder_id,)).fetchone()[0]
            chunks = db.execute("SELECT COUNT(*) FROM chunks WHERE memory_id IN "
                                "(SELECT memory_id FROM folder_files WHERE folder_id = ?)", (folder_id,)).fetchone()[0]
        self.store.delete_where("id IN (SELECT memory_id FROM folder_files WHERE folder_id = ? "
                                "AND memory_id IS NOT NULL)", (folder_id,))
        with self.store.write() as db:
            db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))  # its file rows go with it
        self.jobs.pop(folder_id, None)
        return {"files": files, "chunks": chunks}

    def forget_scope(self, scope: str | None) -> int:
        """Forget the folders of one scope (all of them for None); returns how many."""
        gone = 0
        for folder in self.list():
            if scope is None or folder.scope == scope:
                gone += self.forget(folder.id) is not None
        return gone

    def files(self, folder_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.store.read() as db:
            rows = db.execute("SELECT rel, size, status, mtime_ns FROM folder_files WHERE folder_id = ? "
                              "ORDER BY rel LIMIT ?", (folder_id, limit)).fetchall()
        return [{"path": r["rel"], "size": r["size"], "status": r["status"], "mtime_ns": r["mtime_ns"]} for r in rows]

    def public(self, folder: Folder) -> dict[str, Any]:
        with self.store.read() as db:
            files = db.execute("SELECT COUNT(memory_id) FROM folder_files WHERE folder_id = ?",
                               (folder.id,)).fetchone()[0]
            chunks = db.execute("SELECT COUNT(*) FROM chunks WHERE memory_id IN "
                                "(SELECT memory_id FROM folder_files WHERE folder_id = ?)", (folder.id,)).fetchone()[0]
        job = self.jobs.get(folder.id)
        return {"id": folder.id, "path": folder.path, "scope": folder.scope, "include": folder.include,
                "exclude": folder.exclude, "max_file_bytes": folder.max_file_bytes, "max_files": folder.max_files,
                "added": folder.added, "indexed": folder.indexed, "files": files, "chunks": chunks,
                "skipped": folder.summary.get("skipped", {}), "job": job.public() if job else None}

    # ---------------------------------------------------------------- indexing passes
    def queue(self, folder_id: str, force: bool = False) -> Job | None:
        """A job for the folder (the one already waiting or running, if any); `run` does it."""
        if self.get(folder_id) is None:
            return None
        job = self.jobs.get(folder_id)
        if job is not None and job.active:
            return job
        self.jobs[folder_id] = job = Job(folder_id, force=force)
        return job

    def start(self, folder_id: str, force: bool = False,
              spawn: Callable[[Awaitable[None]], Any] = asyncio.ensure_future) -> Job | None:
        """Queue a pass and hand it to `spawn` to run in the background, unless one is already on its way."""
        job = self.queue(folder_id, force)
        if job is not None and not job.scheduled:
            job.scheduled = True
            spawn(self.run(job))
        return job

    async def run(self, job: Job) -> None:
        loop = asyncio.get_running_loop()
        if self._turn is None or self._turn[0] is not loop:
            self._turn = (loop, asyncio.Lock())
        async with self._turn[1]:  # one folder at a time: the disk and the embedding model are shared
            try:
                await self._pass(job)
            except asyncio.CancelledError:
                job.state = "cancelled"
                raise
            except Exception as exc:  # a failed pass is reported on the job, never raised into the server
                log.warning("memory: indexing %s failed: %s", job.folder_id, exc)
                job.state, job.error = "error", str(exc)[:300]
            finally:
                job.finished = time.time()
                job.current = ""

    async def run_all(self, force: bool = False) -> None:
        """A pass over every folder, one after the other (SPIKE does this when it starts)."""
        jobs = []
        for folder in self.list():
            job = self.queue(folder.id, force)
            if job is not None and not job.scheduled:
                job.scheduled = True
                jobs.append(job)
        for job in jobs:
            await self.run(job)

    async def _pass(self, job: Job) -> None:
        folder = self.get(job.folder_id)
        if folder is None or job.cancel:
            job.state = "cancelled"
            return
        job.state = "scanning"
        scan = await asyncio.to_thread(scan_folder, folder, self.protected())
        job.total, job.skipped = len(scan.files), dict(scan.skipped)
        if scan.truncated:
            job.warning = f"the folder has more than {MAX_SCAN} entries: only the first ones were looked at"
        known = self._known(folder.id)
        current = {c.rel for c in scan.files}
        job.removed = await asyncio.to_thread(self._drop, folder.id, [r for r in known if r not in current])
        job.state = "indexing"
        for cand in scan.files:
            if job.cancel or self.get(folder.id) is None:
                job.state = "cancelled"
                return
            job.current = cand.rel
            before = known.get(cand.rel)
            if not job.force and before and before[:2] == (cand.mtime_ns, cand.size):
                job.unchanged += 1
                if before[2] != STATUS_INDEXED:
                    job.skipped[before[2]] = job.skipped.get(before[2], 0) + 1
            else:
                status = await asyncio.to_thread(self._index_file, folder, cand)
                if status is None:  # the folder was forgotten while this file was being read
                    job.state = "cancelled"
                    return
                if status == STATUS_INDEXED:
                    job.indexed += 1
                else:
                    job.skipped[status] = job.skipped.get(status, 0) + 1
            job.done += 1
        job.state = "embedding"
        await self._embed(job)
        summary = {"skipped": job.skipped, "truncated": scan.truncated}
        with self.store.write() as db:
            db.execute("UPDATE folders SET indexed = ?, summary = ? WHERE id = ?",
                       (time.time(), json.dumps(summary), folder.id))
        job.state = "done"

    async def _embed(self, job: Job) -> None:
        if self.embed is None:
            return
        try:
            while not job.cancel:
                n = await self.embed(EMBED_BATCH)
                job.embedded += n
                if n < EMBED_BATCH:
                    break
        except Exception as exc:  # the files are searchable by words; vectors follow when the model answers again
            job.warning = f"vectors pending: {str(exc)[:200]}"

    def _known(self, folder_id: str) -> dict[str, tuple[int, int, str]]:
        with self.store.read() as db:
            rows = db.execute("SELECT rel, mtime_ns, size, status FROM folder_files WHERE folder_id = ?",
                              (folder_id,)).fetchall()
        return {r["rel"]: (r["mtime_ns"], r["size"], r["status"]) for r in rows}

    def _drop(self, folder_id: str, rels: list[str]) -> int:
        """Forget files that are gone or no longer pass the rules."""
        for i in range(0, len(rels), 500):
            part = rels[i:i + 500]
            marks = ",".join("?" * len(part))
            self.store.delete_where(f"id IN (SELECT memory_id FROM folder_files WHERE folder_id = ? AND rel IN ({marks})"
                                    " AND memory_id IS NOT NULL)", (folder_id, *part))
            with self.store.write() as db:
                db.execute(f"DELETE FROM folder_files WHERE folder_id = ? AND rel IN ({marks})", (folder_id, *part))
        return len(rels)

    def _index_file(self, folder: Folder, cand: Candidate) -> str | None:
        """Read one file and (re)place its memory. Returns its status, or None if the folder is gone."""
        status, text = STATUS_UNREADABLE, None
        try:
            real = cand.path.resolve(strict=True)  # checked again now: a link may have been swapped since the scan
            if not within(real, Path(folder.path).resolve()):
                status = "outside"
            elif cand.path.suffix.lower() not in CONTAINERS and b"\0" in _head(real):
                status = STATUS_BINARY
            else:
                text = extract_text(cand.path)
                status = STATUS_INDEXED if text is not None else STATUS_UNREADABLE
        except OSError:
            status = STATUS_UNREADABLE
        source = f"file:{Path(folder.path, cand.rel).as_posix()}"
        with self.store.read() as db:  # holds the lock: a folder forgotten meanwhile cannot leave a memory behind
            if db.execute("SELECT 1 FROM folders WHERE id = ?", (folder.id,)).fetchone() is None:
                return None
            memory_id = None
            if status == STATUS_INDEXED and text is not None:
                memory = self.store.replace_source(folder.scope, source, text, "document", {
                    "by": "folder", "folder": folder.id, "rel": cand.rel, "size": cand.size})
                memory_id = memory.id
            elif status != "outside":
                self.store.delete_source(folder.scope, source)
            if status == "outside":
                return status  # not recorded: it is looked at again next time
            with self.store.write() as write:
                write.execute("INSERT OR REPLACE INTO folder_files (folder_id, rel, mtime_ns, size, status, memory_id) "
                              "VALUES (?,?,?,?,?,?)", (folder.id, cand.rel, cand.mtime_ns, cand.size, status,
                                                       memory_id))
        return status


def _head(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(SNIFF)
