"""Filesystem locations. Everything SPIKE writes lives under SPIKE_HOME (default ~/.spike)."""

from __future__ import annotations

import os
from pathlib import Path


def spike_home() -> Path:
    env = os.environ.get("SPIKE_HOME")
    home = Path(env).expanduser() if env else (Path.home() / ".spike")
    home.mkdir(parents=True, exist_ok=True)
    return home


def models_dir() -> Path:
    d = spike_home() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def adapters_dir() -> Path:
    d = spike_home() / "adapters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def workspace_dir() -> Path:
    env = os.environ.get("SPIKE_WORKSPACE")
    d = Path(env).expanduser() if env else (spike_home() / "workspace")
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_git_name(part: str) -> bool:
    """Whether a path component is git's own folder, in the spellings a file system treats alike (case, trailing dots
    and spaces on Windows, the 8.3 short name GIT~1, an NTFS stream name: `.git::$INDEX_ALLOCATION` is the folder)."""
    name = part.split(":", 1)[0].rstrip(". ").lower()
    return name == ".git" or (name.startswith("git~") and name[4:].isdigit())
