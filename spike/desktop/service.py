"""What the app needs around a desktop task: whether one may start (and if not, why, in a code the app can translate),
the cost estimate shown before it starts, the one task that runs at a time, and the screenshots kept for a chat's
proof package. The checks are in the order the user would fix them."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from spike.desktop.adapters import ADAPTERS
from spike.desktop.driver import Availability, Driver, detect, fit_size
from spike.desktop.session import DesktopBroker, DesktopTask, Refused, estimate
from spike.desktop.settings import DEFAULTS, HARD_MAX_STEPS

LOOPBACK = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def points_at_this_computer(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    return host in LOOPBACK or host.startswith("127.")


class DesktopService:
    """`settings()` is the app's `desktop` setting; `provider(pid)` the guarded provider; `configs()` the stored provider
    list. `detect` finds the driver (tests replace it, or set `driver` directly)."""

    def __init__(self, settings: Callable[[], dict[str, Any]], provider: Callable[[str], Any],
                 configs: Callable[[], list[dict[str, Any]]], home: Path,
                 detect: Callable[[], tuple[Driver | None, Availability]] = detect):
        self.settings, self.provider, self.configs, self.home = settings, provider, configs, home
        self._detect = detect
        self.broker = DesktopBroker()
        self.task: DesktopTask | None = None
        self.driver: Driver | None = None
        self.availability: Availability | None = None
        self.task_options: dict[str, Any] = {}  # extra DesktopTask arguments (the tests: no waiting for the screen)

    # ------------------------------------------------------------------ what this computer offers
    def look(self, refresh: bool = False) -> Availability:
        if refresh or self.availability is None:
            self.driver, self.availability = self._detect()
        return self.availability

    # ------------------------------------------------------------------ providers
    def refusal(self, provider_id: str) -> Refused | None:
        """Why a task could not start with this provider now, or None. Local models are refused first: whatever else is
        true, a local model never does desktop actions."""
        raw = next((c for c in self.configs() if c["id"] == provider_id), None)
        if raw is None:
            return Refused("no_provider", "Choose the API provider that will do desktop actions (Settings → Desktop).")
        if raw.get("local") or points_at_this_computer(raw.get("base_url", "")):
            return Refused("local", f"{raw['name']} runs on this computer. Desktop actions are never done by a local "
                                    "model: choose an API provider with a computer-use tool.")
        provider = self.provider(provider_id)
        if getattr(provider, "computer_use_adapter", None) not in ADAPTERS:
            return Refused("unsupported", f"{raw['name']} has no computer-use tool that SPIKE can use. Only Anthropic's "
                                          "Messages API is supported for desktop actions so far.")
        if not provider.config.api_key:
            return Refused("no_key", f"{raw['name']} has no API key. Add it in Settings → Providers.")
        if (reason := provider.screens_blocked()) is not None:
            cfg = provider.config
            code = ("paid" if cfg.paid and not cfg.allow_paid else
                    "privacy" if provider.blocked() is None else "limit")
            return Refused(code, reason)
        return None

    def provider_states(self) -> list[dict[str, Any]]:
        """Every provider with whether it can do desktop actions now, for the settings page."""
        out = []
        for raw in self.configs():
            refused = self.refusal(raw["id"])
            out.append({"id": raw["id"], "name": raw["name"], "model": raw.get("model", ""),
                        "ok": refused is None, "code": refused.code if refused else "",
                        "reason": str(refused) if refused else ""})
        return out

    def status(self, refresh: bool = False) -> dict[str, Any]:
        cfg = {**DEFAULTS, **(self.settings() or {})}
        return {"settings": cfg, "driver": self.look(refresh).to_dict(), "providers": self.provider_states(),
                "hard_max_steps": HARD_MAX_STEPS, "running": self.busy(),
                "task": self.task.id if self.task and self.busy() else None}

    # ------------------------------------------------------------------ a task
    def busy(self) -> bool:
        return self.task is not None and self.task.busy()

    def preflight(self, provider_id: str | None = None) -> tuple[str, dict[str, Any]]:
        """(provider id, settings) for a task that may start, or raise Refused."""
        cfg = {**DEFAULTS, **(self.settings() or {})}
        if not cfg["enabled"]:
            raise Refused("off", "Desktop actions are off. Turn them on in Settings → Desktop.")
        pid = provider_id or cfg["provider_id"]
        if refused := self.refusal(pid):
            raise refused
        avail = self.look()
        if not avail.available or self.driver is None:
            raise Refused("no_driver", f"This computer cannot be controlled: {avail.reason}"
                                       + (f" (install {avail.needs})" if avail.needs else ""))
        if self.busy():
            raise Refused("busy", "A desktop task is already running. Stop it first.")
        return pid, cfg

    def estimate(self, provider_id: str | None = None, max_steps: int | None = None) -> dict[str, Any]:
        pid, cfg = self.preflight(provider_id)
        provider = self.provider(pid)
        driver = self.driver
        assert driver is not None
        shot_size = fit_size(*driver.screen_size())
        adapter = ADAPTERS[provider.computer_use_adapter](provider.config.model, shot_size, driver.supports, cfg["tool"])
        steps = min(max_steps or cfg["max_steps"], cfg["max_steps"], HARD_MAX_STEPS)
        limits = provider.limits()
        return {**estimate(steps, shot_size, adapter.overhead_tokens, limits), "provider": provider.config.name,
                "model": provider.config.model, "tool": adapter.variant,
                "priced": any(limits.get(k) is not None for k in ("price_in", "price_out"))}

    def start(self, goal: str, provider_id: str | None = None, keep_shots: bool = False,
              conversation_id: str | None = None) -> DesktopTask:
        pid, cfg = self.preflight(provider_id)
        provider = self.provider(pid)
        driver = self.driver
        assert driver is not None
        task = DesktopTask(goal, provider, driver, ADAPTERS[provider.computer_use_adapter], cfg, self.broker,
                           enabled=lambda: bool((self.settings() or {}).get("enabled")), **self.task_options)
        if keep_shots and conversation_id:
            task.shot_dir = self.home / "desktop" / conversation_id / task.id
        task.running = True  # the place is taken from now on, not from the first event
        self.task = task
        return task

    def forget(self, conversation_id: str) -> None:
        """A deleted chat takes the screenshots kept for its proof package with it."""
        shutil.rmtree(self.home / "desktop" / conversation_id, ignore_errors=True)

    def kept_files(self, conversation_id: str) -> dict[str, bytes]:
        """The screenshots the user asked to keep for this chat, as proof-package paths."""
        root = self.home / "desktop" / conversation_id
        if not root.is_dir():
            return {}
        return {f"desktop/{p.relative_to(root).as_posix()}": p.read_bytes() for p in sorted(root.rglob("*.png"))}
