"""API key storage.

Preferred backend: the OS keychain via `keyring` (macOS Keychain, Windows Credential Manager, Secret
Service on Linux). Fallback: a JSON file readable only by the current user (mode 0600). The fallback is
not encrypted; the UI says which backend is active so users can make an informed choice.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SERVICE = "spike-ai"


class SecretStore:
    def __init__(self, fallback_path: Path, use_keyring: bool = True):
        self.fallback_path = fallback_path
        self._keyring = None
        if use_keyring and not os.environ.get("SPIKE_NO_KEYRING"):
            try:
                import keyring
                from keyring.backends.fail import Keyring as FailKeyring

                if not isinstance(keyring.get_keyring(), FailKeyring):
                    self._keyring = keyring
            except Exception:
                self._keyring = None

    @property
    def backend(self) -> str:
        return "os-keychain" if self._keyring else "file-0600"

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self.fallback_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fallback_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.fallback_path)
        os.chmod(self.fallback_path, 0o600)

    def get(self, name: str) -> str | None:
        if self._keyring:
            return self._keyring.get_password(SERVICE, name)
        return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        if self._keyring:
            self._keyring.set_password(SERVICE, name, value)
            return
        data = self._load()
        data[name] = value
        self._save(data)

    def delete(self, name: str) -> None:
        if self._keyring:
            try:
                self._keyring.delete_password(SERVICE, name)
            except Exception:
                pass
            return
        data = self._load()
        if data.pop(name, None) is not None:
            self._save(data)

    def has(self, name: str) -> bool:
        return bool(self.get(name))
