"""Local error log (G43): the app's latest unhandled failures, kept in SPIKE_HOME/logs/errors.log for the user to
read in Settings and, if they choose, paste into an issue. Nothing is sent anywhere.

An entry says where it failed (the route's template or the job's kind, never the URL or its values), the exception's
type and the frames (file:line in function). It never keeps the exception's message, request bodies, file contents
or source lines: messages are where paths, keys and document text end up. What it keeps is anonymised again on read:
the home folder becomes ~, the SPIKE home ~/.spike, other absolute paths keep only their last name, keys are cut and
URLs lose their credentials and query. The file rotates at 1 MB and keeps 2 old copies.
"""

from __future__ import annotations

import asyncio
import errno as errno_codes
import json
import logging
import platform
import re
import sysconfig
import traceback
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from spike import __version__
from spike.runtime.paths import spike_home
from spike.runtime.urls import strip_url_secrets
from spike.skills.validation import _SECRET

LOG_NAME = "errors.log"
MAX_BYTES = 1_000_000
BACKUPS = 2
MAX_FRAMES = 12  # the innermost ones: where it broke
MAX_TEXT = 200

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")
# an absolute path's folders (the name at the end stays): /srv/a/b/ or C:\Users\x\ -> …/ or …\
_POSIX_DIRS = re.compile(r"(?<![\w~.:/\\<>-])/(?:[^\s/\\'\"<>|:]+/)+")
_WINDOWS_DIRS = re.compile(r"\b[A-Za-z]:[\\/](?:[^\s\\/'\"<>|:]+[\\/])+")
_ROUTE = re.compile(r"[A-Z]{3,7} /(?:api|v1|mcp)(?:/[\w{}:.-]*)*")  # a route template from the code, not a file
_ROOT = Path(__file__).resolve().parent.parent  # the folder holding the spike package: a checkout or site-packages
_STDLIB = Path(sysconfig.get_paths()["stdlib"]).resolve()

_handler: ErrorLogHandler | None = None


def _replace_folder(text: str, folder: Path, label: str) -> str:
    for form in {str(folder), folder.as_posix()}:
        if len(form) > 1:
            text = re.sub(re.escape(form) + r"(?![\w.-])", lambda _m: label, text)
    return text


def anonymise(text: str) -> str:
    """`text` without what identifies the user or their files: SPIKE home -> ~/.spike, home -> ~, the folders of any
    other absolute path dropped, keys cut and URLs reduced to scheme, host and path."""
    text = strip_url_secrets(str(text))
    text = _BEARER.sub("<secret>", _SECRET.sub("<secret>", text))
    homes = {spike_home()} | ({_handler.folder.parent} if _handler else set())
    for folder in sorted(homes, key=lambda p: -len(str(p))):  # the SPIKE home first: it is usually inside the home
        text = _replace_folder(text, folder, "~/.spike")
    text = _replace_folder(text, Path.home(), "~")
    text = _WINDOWS_DIRS.sub(lambda m: "…" + m[0][-1], text)
    return _POSIX_DIRS.sub("…/", text)


def short_path(filename: str) -> str:
    """A frame's file as a maintainer reads it: relative to SPIKE's folder, the installed packages or the standard
    library; anything else anonymised."""
    try:
        path = Path(filename).resolve()
    except (OSError, ValueError):
        return anonymise(filename)
    parts = path.parts
    for marker in ("site-packages", "dist-packages"):
        if marker in parts:
            return "/".join(parts[len(parts) - parts[::-1].index(marker):])
    for base in (_ROOT, _STDLIB):
        if path.is_relative_to(base):
            return path.relative_to(base).as_posix()
    return anonymise(path.as_posix())  # forward slashes on every system, so frames read the same everywhere


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    text = anonymise(str(text)).replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _where(kind: Any, where: Any) -> str:
    where = str(where)
    return where if kind == "route" and _ROUTE.fullmatch(where) else _clip(where, 160)


def _entry(record: logging.LogRecord) -> dict[str, Any]:
    exc_type, exc, tb = record.exc_info or (None, None, None)
    where = getattr(record, "spike_where", None) or f"{record.name}: {record.msg}"  # the template, never its args
    entry: dict[str, Any] = {
        "time": round(record.created, 3), "kind": getattr(record, "spike_kind", "log"),
        "where": _where(getattr(record, "spike_kind", "log"), where),
        "type": _clip(getattr(exc_type, "__name__", "Exception"), 80),
        # the code object's file, line and name: no source line is read and no local value is kept
        "frames": [_clip(f"{short_path(f.f_code.co_filename)}:{line} in {f.f_code.co_name}")
                   for f, line in traceback.walk_tb(tb)][-MAX_FRAMES:],
        "version": __version__,
    }
    if isinstance(exc, OSError) and exc.errno in errno_codes.errorcode:
        entry["errno"] = errno_codes.errorcode[exc.errno]
    return entry


class ErrorLogHandler(RotatingFileHandler):
    """Writes the ERROR records that carry an exception as one anonymised JSON line each (ASCII, so the size cap
    counts bytes)."""

    def __init__(self, folder: Path, max_bytes: int = MAX_BYTES, backups: int = BACKUPS):
        self.folder = folder
        super().__init__(folder / LOG_NAME, maxBytes=max_bytes, backupCount=backups, encoding="utf-8", delay=True)
        self.setLevel(logging.ERROR)
        self.addFilter(lambda r: bool(r.exc_info) and r.exc_info[1] is not None)

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_entry(record))

    def _open(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        return super()._open()

    def handleError(self, record: logging.LogRecord) -> None:
        pass  # failing to note a failure must never add one, nor print the record somewhere else

    def forget(self) -> None:
        """Close the file so it can be deleted; the next record opens a new one."""
        self.acquire()
        try:
            if self.stream:
                self.stream.close()
                self.stream = None
        finally:
            self.release()


def install(folder: Path, max_bytes: int = MAX_BYTES, backups: int = BACKUPS) -> ErrorLogHandler:
    """Record into `folder` from now on: explicit `record` calls and every `log.exception` of SPIKE's loggers. One
    log per process; installing again moves it."""
    global _handler
    uninstall()
    _handler = ErrorLogHandler(folder, max_bytes, backups)
    logging.getLogger("spike").addHandler(_handler)
    return _handler


def uninstall() -> None:
    global _handler
    if _handler is not None:
        logging.getLogger("spike").removeHandler(_handler)
        _handler.close()
        _handler = None


def record(kind: str, where: str, exc: BaseException) -> None:
    """Note an unhandled failure: `kind` is route, job or background; `where` a route template or a job's name."""
    if _handler is None:
        return
    rec = logging.LogRecord("spike.errors", logging.ERROR, "", 0, "failure", None, (type(exc), exc, exc.__traceback__))
    rec.spike_kind, rec.spike_where = kind, where
    _handler.handle(rec)


def record_task(kind: str, where: str):
    """A done-callback for an asyncio task that nobody awaits: its failure goes to the log."""
    def done(task: asyncio.Future) -> None:
        if _handler is not None and not task.cancelled() and (exc := task.exception()) is not None:
            record(kind, where, exc)
    return done


def log_files(folder: Path) -> list[Path]:
    """The log and its rotated copies that exist, oldest first."""
    old = sorted((p for p in folder.glob(LOG_NAME + ".*") if p.suffix[1:].isdigit()), key=lambda p: -int(p.suffix[1:]))
    return [p for p in [*old, folder / LOG_NAME] if p.is_file()]


def _clean(raw: Any) -> dict[str, Any] | None:
    """An entry as read back, keeping only the known fields, anonymised again (the file is plain text anyone could
    have edited, or an older SPIKE wrote)."""
    if not isinstance(raw, dict):
        return None
    try:
        out = {"time": float(raw.get("time") or 0), "kind": _clip(raw.get("kind") or "log", 20),
               "where": _where(raw.get("kind"), raw.get("where") or ""), "type": _clip(raw.get("type") or "", 80),
               "frames": [_clip(f) for f in list(raw.get("frames") or [])[-MAX_FRAMES:]],
               "version": _clip(raw.get("version") or "", 40)}
    except (TypeError, ValueError):
        return None
    if raw.get("errno"):
        out["errno"] = _clip(raw["errno"], 20)
    return out


def read(folder: Path, limit: int = 200) -> list[dict[str, Any]]:
    """The latest entries, newest first. Reads only the local log files."""
    entries = []
    for path in log_files(folder):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = _clean(json.loads(line))
            except ValueError:
                continue
            if entry:
                entries.append(entry)
    return entries[::-1][:limit]


def clear(folder: Path) -> None:
    if _handler is not None and _handler.folder == folder:
        _handler.forget()
    for path in log_files(folder):
        path.unlink(missing_ok=True)


def issue_text(entries: list[dict[str, Any]]) -> str:
    """The text the user can paste into an issue: versions and the anonymised entries, nothing else."""
    lines = ["SPIKE error log (anonymised on this computer; nothing was sent)", "",
             f"SPIKE: {__version__}", f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
             f"Python: {platform.python_version()}", ""]
    for e in entries:
        when = datetime.fromtimestamp(e["time"], UTC).strftime("%Y-%m-%d %H:%M:%S UTC") if e["time"] else "?"
        code = f" [{e['errno']}]" if e.get("errno") else ""
        lines += [f"## {when} · {e['kind']} · {e['where']}", f"{e['type']}{code} (SPIKE {e['version']})",
                  *(f"    {f}" for f in e["frames"]), ""]
    if not entries:
        lines.append("(no errors recorded)")
    return "\n".join(lines).rstrip() + "\n"
