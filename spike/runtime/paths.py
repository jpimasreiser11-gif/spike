"""Filesystem locations. Everything SPIKE writes lives under SPIKE_HOME (default ~/.spike)."""

from __future__ import annotations

import os
from pathlib import Path


def spike_home() -> Path:
    home = Path(os.environ.get("SPIKE_HOME", Path.home() / ".spike")).expanduser()
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
    d = Path(os.environ.get("SPIKE_WORKSPACE", spike_home() / "workspace")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d
