"""The desktop driver: screenshots of the user's own screen and mouse and keyboard actions on it, done with programs
the OS already has and nothing else (no library is installed): `xdotool` with `import` (ImageMagick) or `scrot` on
Linux/X11, `screencapture` + `sips` + `osascript` (and `cliclick` when installed) on macOS, PowerShell with
System.Windows.Forms and user32 on Windows. Detection says what exists and what is missing; a computer without the
programs (or a Wayland session, which these tools cannot drive) gets a clear reason, never a half-working driver.
Every command line and script is built by a pure function and run through an injectable runner, so the tests use
fake programs. The macOS and Windows drivers are written from the programs' documentation and checked against fake
runners only: they have not been run on real macOS or Windows machines."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_EDGE = 1568  # screenshots are shrunk to fit every model's limits: long edge and total pixels
MAX_PIXELS = 1_150_000
ACTION_TIMEOUT_S = 20.0
CAPTURE_TIMEOUT_S = 40.0
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class DriverError(RuntimeError):
    """An action could not be done (a missing program, a refused permission, a bad argument). The message is safe to
    show to the user and to hand back to the model."""


@dataclass(frozen=True)
class Ran:
    code: int
    out: bytes = b""
    err: str = ""


Runner = Callable[[Sequence[str], bytes | None, float], Ran]


def run_program(argv: Sequence[str], stdin: bytes | None = None, timeout: float = ACTION_TIMEOUT_S) -> Ran:
    """Run a program without a shell; a missing program or a timeout is a result, not an exception."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console window flashes up
    try:
        done = subprocess.run(list(argv), input=stdin, capture_output=True, timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired:
        return Ran(124, b"", f"{Path(argv[0]).name} timed out")
    except OSError as exc:
        return Ran(127, b"", f"{exc.__class__.__name__}: {exc}")
    return Ran(done.returncode, done.stdout, done.stderr.decode("utf-8", "replace").strip()[:500])


# --------------------------------------------------------------------------- screenshots and their coordinates
def fit_size(width: int, height: int) -> tuple[int, int]:
    """The size a screenshot is shrunk to before the model sees it: long edge and total pixels within the limits that
    hold for every model (the provider's own scaling rule; coordinates are mapped back with the same ratio)."""
    scale = min(1.0, MAX_EDGE / max(width, height), math.sqrt(MAX_PIXELS / (width * height)))
    return max(1, int(width * scale)), max(1, int(height * scale))


def png_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG's header, or None when the bytes are not a PNG."""
    if len(data) < 24 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


@dataclass(frozen=True)
class Shot:
    """A screenshot as the model sees it (`width` x `height`) and the screen it came from, in the units the mouse
    uses (`screen_width` x `screen_height`: points on a Retina Mac, so the two ratios differ from the pixel ratio)."""

    png: bytes
    width: int
    height: int
    screen_width: int
    screen_height: int

    def to_screen(self, x: int, y: int) -> tuple[int, int]:
        """A point of the model's image as a point of the screen, kept inside it."""
        sx = round(x * self.screen_width / self.width)
        sy = round(y * self.screen_height / self.height)
        return min(max(sx, 0), self.screen_width - 1), min(max(sy, 0), self.screen_height - 1)


# --------------------------------------------------------------------------- keys
MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt", "opt": "alt", "shift": "shift",
             "super": "super", "cmd": "super", "command": "super", "meta": "super", "win": "super", "windows": "super"}
KEYS = {"return": "Return", "enter": "Return", "kp_enter": "Return", "tab": "Tab", "escape": "Escape", "esc": "Escape",
        "backspace": "BackSpace", "delete": "Delete", "del": "Delete", "space": "space", "up": "Up", "arrowup": "Up",
        "down": "Down", "arrowdown": "Down", "left": "Left", "arrowleft": "Left", "right": "Right",
        "arrowright": "Right", "home": "Home", "end": "End", "pageup": "Page_Up", "page_up": "Page_Up",
        "prior": "Page_Up", "pagedown": "Page_Down", "page_down": "Page_Down", "next": "Page_Down",
        "insert": "Insert", "plus": "plus", "minus": "minus"}


def parse_key(combo: str) -> tuple[tuple[str, ...], str]:
    """("ctrl+Shift+s") -> (("ctrl", "shift"), "s"): modifiers by one name each, the key by its X11 keysym name."""
    combo = combo.strip()
    if not combo:
        raise DriverError("a key is needed")
    parts = [p for p in combo.split("+") if p != ""]
    if combo.endswith("+"):  # "ctrl++": the key is the plus sign
        parts.append("plus")
    mods: list[str] = []
    for part in parts[:-1]:
        mods.append(_modifier(part))
    last = parts[-1].strip()
    if last.lower() in MODIFIERS and not mods:
        return (), MODIFIERS[last.lower()]  # a lone modifier key: pressing it
    key = KEYS.get(last.lower())
    if key is None:
        key = last.upper() if len(last) > 1 and last[0] in "fF" and last[1:].isdigit() else last
    return tuple(dict.fromkeys(mods)), key


def _modifier(name: str) -> str:
    mod = MODIFIERS.get(name.strip().lower())
    if mod is None:
        raise DriverError(f"'{name}' is not a modifier key")
    return mod


def parse_modifiers(text: str | None) -> tuple[str, ...]:
    """The modifier keys held during a click or scroll (`text` of the call: "shift", "ctrl+shift")."""
    if not text:
        return ()
    return tuple(dict.fromkeys(_modifier(part) for part in text.split("+")))


# --------------------------------------------------------------------------- the driver
class Driver(ABC):
    """What the session needs from a computer. Coordinates are screen points; the session maps the model's."""

    backend = "none"
    supports: frozenset[str] = frozenset()  # the computer-use tool's names of the actions this driver can do

    def __init__(self, run: Runner = run_program):
        self.run = run

    @abstractmethod
    def screen_size(self) -> tuple[int, int]: ...

    @abstractmethod
    def capture(self, width: int, height: int) -> bytes:
        """A PNG of the whole screen shrunk to `width` x `height`."""

    def screenshot(self) -> Shot:
        screen_w, screen_h = self.screen_size()
        width, height = fit_size(screen_w, screen_h)
        png = self.capture(width, height)
        size = png_size(png)
        if size is None:
            raise DriverError("the screenshot program did not return a PNG image")
        if size[0] > MAX_EDGE or size[1] > MAX_EDGE or size[0] * size[1] > MAX_PIXELS * 1.02:
            raise DriverError(f"the screenshot is {size[0]}x{size[1]} and there is no program here to shrink it; "
                              "install ImageMagick (convert or magick) so SPIKE can send a smaller image")
        return Shot(png, size[0], size[1], screen_w, screen_h)

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left", count: int = 1, mods: Sequence[str] = ()) -> None: ...

    @abstractmethod
    def move(self, x: int, y: int) -> None: ...

    @abstractmethod
    def drag(self, x1: int, y1: int, x2: int, y2: int, mods: Sequence[str] = ()) -> None: ...

    @abstractmethod
    def scroll(self, x: int | None, y: int | None, direction: str, amount: int,
               mods: Sequence[str] = ()) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def key(self, combo: str, repeat: int = 1) -> None: ...

    def cursor_position(self) -> tuple[int, int]:
        raise DriverError("this computer's driver cannot read the mouse position")

    def secure_field_focused(self) -> bool | None:
        """True when the focused field is a password field, False when it is not, None when this driver cannot tell
        (then only the model's own words and the user's eyes protect a password)."""
        return None

    def check(self, argv: Sequence[str], what: str, stdin: bytes | None = None,
              timeout: float = ACTION_TIMEOUT_S) -> Ran:
        """Run a program for an action; a failure becomes a DriverError that names the action and the program."""
        done = self.run(argv, stdin, timeout)
        if done.code != 0:
            raise DriverError(f"{what} failed ({Path(argv[0]).name}): {done.err or 'exit code ' + str(done.code)}")
        return done


# --------------------------------------------------------------------------- what this computer offers
@dataclass(frozen=True)
class Availability:
    """Whether this computer can be driven, and how. `reason` is English; `code` names it so the app can translate:
    wayland | no_display | no_xdotool | no_capture | display_unreachable | no_powershell | no_macos_tools |
    unsupported_os. `needs`: what to install. `notes`: things that work only in part."""

    available: bool
    backend: str = "none"
    reason: str = ""
    code: str = ""
    needs: str = ""
    supports: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "backend": self.backend, "reason": self.reason, "code": self.code,
                "needs": self.needs, "supports": list(self.supports), "notes": list(self.notes)}


def unavailable(code: str, reason: str, needs: str = "") -> tuple[None, Availability]:
    return None, Availability(False, "none", reason, code, needs)


def detect(platform: str | None = None, which: Callable[[str], str | None] = shutil.which,
           env: Mapping[str, str] | None = None, run: Runner = run_program) -> tuple[Driver | None, Availability]:
    """The driver this computer supports, with what it can do, or None and why not. `platform`, `which`, `env` and
    `run` can be replaced (the tests use fake programs and other systems)."""
    from spike.desktop import backends  # the OS drivers import this module

    platform, env = platform or sys.platform, os.environ if env is None else env
    if platform.startswith("linux"):
        return backends.detect_x11(which, env, run)
    if platform == "darwin":
        return backends.detect_macos(which, run)
    if platform in ("win32", "cygwin"):
        return backends.detect_windows(which, run)
    return unavailable("unsupported_os", f"no desktop driver is known for {platform}")


def scratch_dir() -> Path:
    """A private folder for the one screenshot file a program writes (the caller removes it)."""
    return Path(tempfile.mkdtemp(prefix="spike-desktop-"))
