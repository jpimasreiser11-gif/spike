"""Deleting all of the user's data in SPIKE_HOME (G36).

Everything under SPIKE_HOME goes (conversations and history, memory with its vectors and folder indexes, evolution
data, checkpoints, projects and their files, the default workspace, skills, design systems, view scripts, finance
records, logs, screenshots, prototypes and other caches) except what is not the user's data: the llama-server binary
(`bin/`), the launcher lock, and, unless asked, downloaded models and adapters (with `setup.json`, which records that
they are installed) and the key store. Folders the user asked SPIKE to index are never touched: only their index is
deleted. A workspace set with SPIKE_WORKSPACE outside SPIKE_HOME is the user's own folder and is not deleted.

Call it with SPIKE's databases closed; the server closes its state, deletes, and opens a new, empty state.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import sys
from pathlib import Path

ALWAYS_KEPT = {"bin", "launcher.lock"}
MODELS = {"models", "adapters", "setup.json"}
NAMES_FILE = "secret-names.json"  # names of keys kept in the OS keychain (no values), to delete them later
SECRETS = {"secrets.json", "secrets.tmp", NAMES_FILE}


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()  # a link is removed, never what it points to
        return

    def retry(func, p, _exc):  # read-only files (Windows, git objects in a project)
        if not Path(p).is_symlink():
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def kept(delete_models: bool = False, delete_secrets: bool = False) -> set[str]:
    return ALWAYS_KEPT | (set() if delete_models else MODELS) | (set() if delete_secrets else SECRETS)


# Folders of a user's home that SPIKE never creates in its own ("desktop" is not here: SPIKE keeps the desktop task's
# screenshots in a folder of that name).
USER_FOLDERS = {"documents", "downloads", "library", "pictures", "music", "movies", "videos", ".ssh", ".config",
                "appdata", "applications", "onedrive"}


def check_home(home: Path) -> Path:
    """Refuse to delete anything unless `home` is plainly SPIKE's own data folder. A SPIKE_HOME pointed by mistake at
    the user's home (or a parent of it, or a drive root) would otherwise lose every file the user has."""
    real = Path(home).resolve()
    user = Path.home().resolve()
    if real == Path(real.anchor) or real == user or real in user.parents:
        raise ValueError("refused: SPIKE's data folder is the home folder or a parent of it, not a folder of its own")
    if not (real / "spike.db").is_file():
        raise ValueError("refused: the folder has no spike.db, so it is not SPIKE's data folder")
    found = {p.name.lower() for p in real.iterdir()} & USER_FOLDERS
    if found:
        raise ValueError(f"refused: the folder holds {sorted(found)[0]!r}, which belongs to a user's home, not SPIKE")
    return real


def delete_everything(home: Path, delete_models: bool = False, delete_secrets: bool = False) -> dict:
    """Removes every top-level entry of `home` except the kept ones; returns what was removed and what failed.
    Raises ValueError, deleting nothing, when `home` is not SPIKE's own data folder (check_home)."""
    home = check_home(home)
    keep = kept(delete_models, delete_secrets)
    removed, failed = [], []
    for entry in sorted(home.iterdir(), key=lambda p: p.name):
        if entry.name in keep:
            continue
        try:
            _remove(entry)
            removed.append(entry.name)
        except OSError:
            failed.append(entry.name)
    with contextlib.suppress(OSError):
        home.mkdir(parents=True, exist_ok=True)
    return {"deleted": len(removed), "removed": removed, "failed": failed}
