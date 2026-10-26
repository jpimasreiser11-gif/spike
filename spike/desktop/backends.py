"""The three desktop drivers (see `driver.py`): X11 with xdotool, macOS with screencapture/osascript, Windows with
PowerShell. Each action is one program run with an argument list (never a shell string); text typed by the model
reaches the programs as an argument, an AppleScript string literal or a base64 value, never as code."""

from __future__ import annotations

import base64
import re
import shutil
from collections.abc import Callable, Mapping, Sequence

from spike.desktop.driver import (
    ACTION_TIMEOUT_S,
    CAPTURE_TIMEOUT_S,
    Availability,
    Driver,
    DriverError,
    Runner,
    parse_key,
    scratch_dir,
    unavailable,
)

CLICKS = ("left_click", "right_click", "middle_click", "double_click", "triple_click", "mouse_move", "left_click_drag")
EVERYTHING = frozenset(("screenshot", *CLICKS, "scroll", "type", "key", "wait", "cursor_position"))


# --------------------------------------------------------------------------- Linux / X11: xdotool
X_BUTTON = {"left": 1, "middle": 2, "right": 3}
X_SCROLL = {"up": 4, "down": 5, "left": 6, "right": 7}  # X11 wheel buttons


def xdotool_click_argv(binary: str, x: int, y: int, button: str, count: int, mods: Sequence[str]) -> list[str]:
    argv = [binary]
    for mod in mods:
        argv += ["keydown", mod]
    argv += ["mousemove", str(x), str(y), "click"]
    if count > 1:
        argv += ["--repeat", str(count), "--delay", "80"]
    argv.append(str(X_BUTTON[button]))
    for mod in reversed(mods):
        argv += ["keyup", mod]
    return argv


def xdotool_scroll_argv(binary: str, x: int | None, y: int | None, direction: str, amount: int,
                        mods: Sequence[str]) -> list[str]:
    argv = [binary]
    for mod in mods:
        argv += ["keydown", mod]
    if x is not None and y is not None:
        argv += ["mousemove", str(x), str(y)]
    argv += ["click", "--repeat", str(amount), "--delay", "30", str(X_SCROLL[direction])]
    for mod in reversed(mods):
        argv += ["keyup", mod]
    return argv


def xdotool_drag_argv(binary: str, x1: int, y1: int, x2: int, y2: int, mods: Sequence[str]) -> list[str]:
    argv = [binary]
    for mod in mods:
        argv += ["keydown", mod]
    argv += ["mousemove", str(x1), str(y1), "mousedown", "1", "sleep", "0.15", "mousemove", str(x2), str(y2),
             "sleep", "0.15", "mouseup", "1"]
    for mod in reversed(mods):
        argv += ["keyup", mod]
    return argv


def xdotool_key_argv(binary: str, combo: str, repeat: int) -> list[str]:
    mods, key = parse_key(combo)
    return [binary, "key", "--clearmodifiers", "--", *(["+".join([*mods, key])] * repeat)]


class X11Driver(Driver):
    """xdotool for the mouse and keyboard; `import` (ImageMagick) or `scrot` for screenshots, `convert`/`magick` to
    shrink a scrot image."""

    backend = "xdotool"
    supports = EVERYTHING

    def __init__(self, xdotool: str, grab: str, grab_kind: str, shrink: str | None, run: Runner):
        super().__init__(run)
        self.xdotool, self.grab, self.grab_kind, self.shrink = xdotool, grab, grab_kind, shrink

    def screen_size(self) -> tuple[int, int]:
        out = self.check([self.xdotool, "getdisplaygeometry"], "reading the screen size").out.split()
        try:
            return int(out[0]), int(out[1])
        except (IndexError, ValueError) as exc:
            raise DriverError("xdotool did not report the screen size") from exc

    def capture(self, width: int, height: int) -> bytes:
        size = f"{width}x{height}!"
        if self.grab_kind == "import":
            return self.check([self.grab, "-window", "root", "-resize", size, "png:-"], "the screenshot",
                              timeout=CAPTURE_TIMEOUT_S).out
        folder = scratch_dir()
        try:
            shot = folder / "screen.png"
            self.check([self.grab, "-o", str(shot)], "the screenshot", timeout=CAPTURE_TIMEOUT_S)
            if self.shrink:
                return self.check([self.shrink, str(shot), "-resize", size, "png:-"], "shrinking the screenshot",
                                  timeout=CAPTURE_TIMEOUT_S).out
            return shot.read_bytes() if shot.is_file() else b""
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def click(self, x: int, y: int, button: str = "left", count: int = 1, mods: Sequence[str] = ()) -> None:
        self.check(xdotool_click_argv(self.xdotool, x, y, button, count, mods), "the click")

    def move(self, x: int, y: int) -> None:
        self.check([self.xdotool, "mousemove", str(x), str(y)], "moving the mouse")

    def drag(self, x1: int, y1: int, x2: int, y2: int, mods: Sequence[str] = ()) -> None:
        self.check(xdotool_drag_argv(self.xdotool, x1, y1, x2, y2, mods), "the drag")

    def scroll(self, x: int | None, y: int | None, direction: str, amount: int, mods: Sequence[str] = ()) -> None:
        self.check(xdotool_scroll_argv(self.xdotool, x, y, direction, amount, mods), "the scroll")

    def type_text(self, text: str) -> None:
        self.check([self.xdotool, "type", "--delay", "12", "--", text], "typing", timeout=60.0)

    def key(self, combo: str, repeat: int = 1) -> None:
        self.check(xdotool_key_argv(self.xdotool, combo, repeat), "the key press")

    def cursor_position(self) -> tuple[int, int]:
        out = self.check([self.xdotool, "getmouselocation", "--shell"], "reading the mouse position").out.decode()
        found = dict(re.findall(r"^([XY])=(\d+)$", out, re.M))
        if "X" not in found or "Y" not in found:
            raise DriverError("xdotool did not report the mouse position")
        return int(found["X"]), int(found["Y"])


def detect_x11(which: Callable[[str], str | None], env: Mapping[str, str], run: Runner
               ) -> tuple[Driver | None, Availability]:
    if env.get("XDG_SESSION_TYPE", "").lower() == "wayland" or (env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY")):
        return unavailable("wayland", "this is a Wayland session, and the programs SPIKE can use (xdotool, import) "
                                      "only drive X11: log in to an X11 session to use desktop actions")
    if not env.get("DISPLAY"):
        return unavailable("no_display", "there is no graphical display here ($DISPLAY is not set)")
    xdotool = which("xdotool")
    if not xdotool:
        return unavailable("no_xdotool", "xdotool is not installed", "xdotool")
    grab, kind = which("import"), "import"
    if grab and b"ImageMagick" not in run([grab, "-version"], None, ACTION_TIMEOUT_S).out:
        grab = None  # some other program called import
    if not grab:
        grab, kind = which("scrot"), "scrot"
    if not grab:
        return unavailable("no_capture", "no screenshot program was found", "ImageMagick (import) or scrot")
    shrink = which("magick") or which("convert")
    driver = X11Driver(xdotool, grab, kind, shrink, run)
    try:
        size = driver.screen_size()
    except DriverError as exc:
        return unavailable("display_unreachable", f"xdotool cannot reach the display: {exc}")
    notes: list[str] = []
    if kind == "scrot" and not shrink and max(size) > 1568:
        notes.append("scrot cannot shrink screenshots and this screen is larger than the limit: install ImageMagick")
    return driver, Availability(True, driver.backend, supports=tuple(sorted(driver.supports)), notes=tuple(notes))


# --------------------------------------------------------------------------- macOS: screencapture, sips, osascript
MAC_KEY_CODES = {"Return": 36, "Tab": 48, "space": 49, "BackSpace": 51, "Escape": 53, "Delete": 117, "Home": 115,
                 "End": 119, "Page_Up": 116, "Page_Down": 121, "Left": 123, "Right": 124, "Down": 125, "Up": 126,
                 "F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97, "F7": 98, "F8": 100, "F9": 101,
                 "F10": 109, "F11": 103, "F12": 111}
MAC_MODS = {"ctrl": "control down", "alt": "option down", "shift": "shift down", "super": "command down"}
CLICLICK_MODS = {"ctrl": "ctrl", "alt": "alt", "shift": "shift", "super": "cmd"}


def applescript_string(text: str) -> str:
    """`text` as an AppleScript string literal (only backslash and double quote need escaping)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mac_type_lines(text: str) -> list[str]:
    """The System Events lines that type `text`: a line break is the Return key, a tab the Tab key."""
    lines: list[str] = []
    for i, row in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        if i:
            lines.append("key code 36")
        for j, chunk in enumerate(row.split("\t")):
            if j:
                lines.append("key code 48")
            if chunk:
                lines.append(f"keystroke {applescript_string(chunk)}")
    return lines


def mac_key_line(combo: str) -> str:
    mods, key = parse_key(combo)
    using = f" using {{{', '.join(MAC_MODS[m] for m in mods)}}}" if mods else ""
    if key in MAC_KEY_CODES:
        return f"key code {MAC_KEY_CODES[key]}{using}"
    if len(key) == 1:
        return f"keystroke {applescript_string(key)}{using}"
    raise DriverError(f"the key '{key}' is not known on macOS")


def osascript_argv(binary: str, lines: Sequence[str]) -> list[str]:
    """Run `lines` inside `tell application "System Events"`."""
    argv = [binary, "-e", 'tell application "System Events"']
    for line in lines:
        argv += ["-e", line]
    return [*argv, "-e", "end tell"]


def cliclick_click_argv(binary: str, x: int, y: int, button: str, count: int, mods: Sequence[str]) -> list[str]:
    if button == "middle":
        raise DriverError("cliclick cannot do a middle click")
    command = {("left", 1): "c", ("left", 2): "dc", ("left", 3): "tc", ("right", 1): "rc"}.get((button, count))
    if command is None:
        raise DriverError(f"cliclick cannot do a {button} click repeated {count} times")
    held = ",".join(CLICLICK_MODS[m] for m in mods)
    return [binary, *([f"kd:{held}"] if held else []), f"{command}:{x},{y}", *([f"ku:{held}"] if held else [])]


def cliclick_drag_argv(binary: str, x1: int, y1: int, x2: int, y2: int, mods: Sequence[str]) -> list[str]:
    held = ",".join(CLICLICK_MODS[m] for m in mods)
    return [binary, *([f"kd:{held}"] if held else []), f"dd:{x1},{y1}", "w:150", f"m:{x2},{y2}", "w:150",
            f"du:{x2},{y2}", *([f"ku:{held}"] if held else [])]


class MacDriver(Driver):
    """screencapture (+ sips to shrink) for screenshots, System Events for typing and keys, cliclick for the mouse
    when it is installed (without it only a plain left click works, through System Events). Scrolling is not offered:
    macOS has no program for it that SPIKE can rely on."""

    backend = "macos"

    def __init__(self, tools: Mapping[str, str], run: Runner):
        super().__init__(run)
        self.tools = dict(tools)
        self.cliclick = tools.get("cliclick")
        self.supports = frozenset(["screenshot", "left_click", "type", "key", "wait"] + (
            ["right_click", "double_click", "triple_click", "mouse_move", "left_click_drag", "cursor_position"]
            if self.cliclick else []))

    def _osascript(self, lines: Sequence[str], what: str) -> bytes:
        return self.check(osascript_argv(self.tools["osascript"], lines), what).out

    def screen_size(self) -> tuple[int, int]:
        out = self.check([self.tools["osascript"], "-e", 'tell application "Finder" to get bounds of window of desktop'],
                         "reading the screen size").out.decode("utf-8", "replace")
        numbers = [int(n) for n in re.findall(r"-?\d+", out)]
        if len(numbers) < 4 or numbers[2] <= 0 or numbers[3] <= 0:
            raise DriverError("macOS did not report the screen size")
        return numbers[2], numbers[3]

    def capture(self, width: int, height: int) -> bytes:
        folder = scratch_dir()
        try:
            shot = folder / "screen.png"
            self.check([self.tools["screencapture"], "-x", "-t", "png", str(shot)], "the screenshot",
                       timeout=CAPTURE_TIMEOUT_S)
            self.check([self.tools["sips"], "--resampleHeightWidth", str(height), str(width), str(shot)],
                       "shrinking the screenshot", timeout=CAPTURE_TIMEOUT_S)
            return shot.read_bytes()
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def click(self, x: int, y: int, button: str = "left", count: int = 1, mods: Sequence[str] = ()) -> None:
        if self.cliclick:
            self.check(cliclick_click_argv(self.cliclick, x, y, button, count, mods), "the click")
        elif button == "left" and count == 1 and not mods:
            self._osascript([f"click at {{{x}, {y}}}"], "the click")
        else:
            raise DriverError("this click needs the cliclick program (brew install cliclick); without it SPIKE can "
                              "only do a plain left click")

    def move(self, x: int, y: int) -> None:
        if not self.cliclick:
            raise DriverError("moving the mouse needs the cliclick program (brew install cliclick)")
        self.check([self.cliclick, f"m:{x},{y}"], "moving the mouse")

    def drag(self, x1: int, y1: int, x2: int, y2: int, mods: Sequence[str] = ()) -> None:
        if not self.cliclick:
            raise DriverError("dragging needs the cliclick program (brew install cliclick)")
        self.check(cliclick_drag_argv(self.cliclick, x1, y1, x2, y2, mods), "the drag")

    def scroll(self, x: int | None, y: int | None, direction: str, amount: int, mods: Sequence[str] = ()) -> None:
        raise DriverError("scrolling is not available on this computer: use the keyboard (Page Down, arrows)")

    def type_text(self, text: str) -> None:
        self.check(osascript_argv(self.tools["osascript"], mac_type_lines(text)), "typing", timeout=60.0)

    def key(self, combo: str, repeat: int = 1) -> None:
        self._osascript([mac_key_line(combo)] * repeat, "the key press")

    def cursor_position(self) -> tuple[int, int]:
        if not self.cliclick:
            return super().cursor_position()
        out = self.check([self.cliclick, "p:."], "reading the mouse position").out.decode()
        found = re.search(r"(-?\d+),(-?\d+)", out)
        if not found:
            raise DriverError("cliclick did not report the mouse position")
        return int(found.group(1)), int(found.group(2))

    def secure_field_focused(self) -> bool | None:
        script = ["set p to first application process whose frontmost is true",
                  'return value of attribute "AXSubrole" of (value of attribute "AXFocusedUIElement" of p)']
        done = self.run(osascript_argv(self.tools["osascript"], script), None, ACTION_TIMEOUT_S)
        return None if done.code != 0 else b"AXSecureTextField" in done.out


def detect_macos(which: Callable[[str], str | None], run: Runner) -> tuple[Driver | None, Availability]:
    tools = {name: which(name) for name in ("screencapture", "osascript", "sips", "cliclick")}
    missing = [n for n in ("screencapture", "osascript", "sips") if not tools[n]]
    if missing:
        return unavailable("no_macos_tools", f"these macOS programs were not found: {', '.join(missing)}")
    driver = MacDriver({n: p for n, p in tools.items() if p}, run)
    try:
        driver.screen_size()
    except DriverError as exc:
        return unavailable("display_unreachable", f"macOS did not answer: {exc}")
    notes = ["the app that runs SPIKE needs the Screen Recording and Accessibility permissions (System Settings > "
             "Privacy & Security)"]
    if not driver.cliclick:
        notes.append("cliclick is not installed (brew install cliclick): only plain left clicks, no dragging; "
                     "scrolling is never available")
    else:
        notes.append("scrolling is not available; use the keyboard")
    return driver, Availability(True, driver.backend, supports=tuple(sorted(driver.supports)), notes=tuple(notes))


# --------------------------------------------------------------------------- Windows: PowerShell
PS_PREAMBLE = """$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class SpikeU {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, int data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int index);
}
"@
[void][SpikeU]::SetProcessDPIAware()
"""
WIN_MOUSE = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}  # down, up
WIN_MODS = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "super": 0x5B}  # virtual-key codes
SENDKEYS_KEYS = {"Return": "{ENTER}", "Tab": "{TAB}", "Escape": "{ESC}", "BackSpace": "{BACKSPACE}",
                 "Delete": "{DELETE}", "Up": "{UP}", "Down": "{DOWN}", "Left": "{LEFT}", "Right": "{RIGHT}",
                 "Home": "{HOME}", "End": "{END}", "Page_Up": "{PGUP}", "Page_Down": "{PGDN}", "Insert": "{INSERT}",
                 "space": " ", "plus": "{+}", "minus": "-"}
SENDKEYS_MODS = {"ctrl": "^", "alt": "%", "shift": "+"}


def sendkeys_text(text: str) -> str:
    """`text` for [System.Windows.Forms.SendKeys]::SendWait: its special characters in braces, line breaks as Enter."""
    out = []
    for ch in text.replace("\r\n", "\n").replace("\r", "\n"):
        out.append("{ENTER}" if ch == "\n" else "{TAB}" if ch == "\t" else "{" + ch + "}" if ch in "+^%~(){}[]" else ch)
    return "".join(out)


def sendkeys_combo(combo: str) -> str:
    mods, key = parse_key(combo)
    if "super" in mods or key == "super":
        raise DriverError("the Windows key cannot be pressed from here")
    code = SENDKEYS_KEYS.get(key) or (f"{{{key}}}" if re.fullmatch(r"F([1-9]|1[0-6])", key) else None)
    if code is None:
        if len(key) != 1:
            raise DriverError(f"the key '{key}' is not known on Windows")
        code = sendkeys_text(key.lower() if mods else key)
    prefix = "".join(SENDKEYS_MODS[m] for m in mods)
    return f"{prefix}({code})" if len(mods) > 1 else f"{prefix}{code}"


def _ps_text(text: str) -> str:
    """A PowerShell expression that rebuilds `text` exactly (base64, so no character can end the string early)."""
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{data}'))"


def ps_mods(mods: Sequence[str], up: bool = False) -> str:
    flag = 2 if up else 0
    return "".join(f"[SpikeU]::keybd_event([byte]{WIN_MODS[m]}, 0, {flag}, [UIntPtr]::Zero)\n"
                   for m in (reversed(mods) if up else mods))


def ps_click(x: int, y: int, button: str, count: int, mods: Sequence[str]) -> str:
    down, up = WIN_MOUSE[button]
    click = f"[SpikeU]::mouse_event({down}, 0, 0, 0, [UIntPtr]::Zero)\n[SpikeU]::mouse_event({up}, 0, 0, 0, [UIntPtr]::Zero)\n"
    return (f"{ps_mods(mods)}[void][SpikeU]::SetCursorPos({int(x)}, {int(y)})\nStart-Sleep -Milliseconds 40\n"
            + (click + "Start-Sleep -Milliseconds 60\n") * count + ps_mods(mods, up=True))


def ps_drag(x1: int, y1: int, x2: int, y2: int, mods: Sequence[str]) -> str:
    down, up = WIN_MOUSE["left"]
    return (f"{ps_mods(mods)}[void][SpikeU]::SetCursorPos({int(x1)}, {int(y1)})\nStart-Sleep -Milliseconds 80\n"
            f"[SpikeU]::mouse_event({down}, 0, 0, 0, [UIntPtr]::Zero)\nStart-Sleep -Milliseconds 150\n"
            f"[void][SpikeU]::SetCursorPos({int(x2)}, {int(y2)})\nStart-Sleep -Milliseconds 150\n"
            f"[SpikeU]::mouse_event({up}, 0, 0, 0, [UIntPtr]::Zero)\n{ps_mods(mods, up=True)}")


def ps_scroll(x: int | None, y: int | None, direction: str, amount: int, mods: Sequence[str]) -> str:
    wheel = 0x0800 if direction in ("up", "down") else 0x1000  # vertical, horizontal; one notch is 120
    signed = 120 if direction in ("up", "right") else -120
    move = f"[void][SpikeU]::SetCursorPos({int(x)}, {int(y)})\n" if x is not None and y is not None else ""
    return (f"{ps_mods(mods)}{move}" + f"[SpikeU]::mouse_event({wheel}, 0, 0, {signed}, [UIntPtr]::Zero)\n" * amount
            + ps_mods(mods, up=True))


def ps_screenshot(width: int, height: int) -> str:
    return ("$w = [SpikeU]::GetSystemMetrics(0); $h = [SpikeU]::GetSystemMetrics(1)\n"
            "$full = New-Object System.Drawing.Bitmap $w, $h\n"
            "$g = [System.Drawing.Graphics]::FromImage($full)\n$g.CopyFromScreen(0, 0, 0, 0, $full.Size)\n$g.Dispose()\n"
            f"$small = New-Object System.Drawing.Bitmap {int(width)}, {int(height)}\n"
            "$g2 = [System.Drawing.Graphics]::FromImage($small)\n"
            "$g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic\n"
            f"$g2.DrawImage($full, 0, 0, {int(width)}, {int(height)})\n$g2.Dispose()\n"
            "$ms = New-Object System.IO.MemoryStream\n$small.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)\n"
            "[Console]::Out.Write([Convert]::ToBase64String($ms.ToArray()))\n")


class WindowsDriver(Driver):
    """PowerShell with System.Windows.Forms, System.Drawing and user32 (mouse_event, keybd_event, SetCursorPos). Each
    action writes a short ASCII script to a private folder and runs it with -File; typed text travels as base64.
    Typing uses SendKeys, which only types characters the current keyboard layout has."""

    backend = "windows"
    supports = EVERYTHING

    def __init__(self, powershell: str, run: Runner):
        super().__init__(run)
        self.powershell, self._folder = powershell, None

    def _script(self, body: str, what: str, timeout: float = ACTION_TIMEOUT_S) -> bytes:
        if self._folder is None:
            self._folder = scratch_dir()
        path = self._folder / "action.ps1"
        path.write_text(PS_PREAMBLE + body, encoding="ascii", errors="replace", newline="\n")
        return self.check([self.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                           str(path)], what, timeout=timeout).out

    def close(self) -> None:
        if self._folder is not None:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None

    def screen_size(self) -> tuple[int, int]:
        out = self._script("[Console]::Out.Write(([SpikeU]::GetSystemMetrics(0)).ToString() + ' ' + "
                           "([SpikeU]::GetSystemMetrics(1)).ToString())\n", "reading the screen size").split()
        try:
            return int(out[0]), int(out[1])
        except (IndexError, ValueError) as exc:
            raise DriverError("Windows did not report the screen size") from exc

    def capture(self, width: int, height: int) -> bytes:
        text = self._script(ps_screenshot(width, height), "the screenshot", CAPTURE_TIMEOUT_S).decode("ascii", "ignore")
        try:
            return base64.b64decode(text.strip())
        except ValueError as exc:
            raise DriverError("PowerShell did not return an image") from exc

    def click(self, x: int, y: int, button: str = "left", count: int = 1, mods: Sequence[str] = ()) -> None:
        self._script(ps_click(x, y, button, count, mods), "the click")

    def move(self, x: int, y: int) -> None:
        self._script(f"[void][SpikeU]::SetCursorPos({int(x)}, {int(y)})\n", "moving the mouse")

    def drag(self, x1: int, y1: int, x2: int, y2: int, mods: Sequence[str] = ()) -> None:
        self._script(ps_drag(x1, y1, x2, y2, mods), "the drag")

    def scroll(self, x: int | None, y: int | None, direction: str, amount: int, mods: Sequence[str] = ()) -> None:
        self._script(ps_scroll(x, y, direction, amount, mods), "the scroll")

    def type_text(self, text: str) -> None:
        self._script(f"[System.Windows.Forms.SendKeys]::SendWait({_ps_text(sendkeys_text(text))})\n", "typing", 60.0)

    def key(self, combo: str, repeat: int = 1) -> None:
        keys = sendkeys_combo(combo) * repeat
        self._script(f"[System.Windows.Forms.SendKeys]::SendWait({_ps_text(keys)})\n", "the key press")

    def cursor_position(self) -> tuple[int, int]:
        out = self._script("$p = [System.Windows.Forms.Cursor]::Position\n"
                           "[Console]::Out.Write($p.X.ToString() + ' ' + $p.Y.ToString())\n",
                           "reading the mouse position").split()
        try:
            return int(out[0]), int(out[1])
        except (IndexError, ValueError) as exc:
            raise DriverError("Windows did not report the mouse position") from exc

    def secure_field_focused(self) -> bool | None:
        script = ("Add-Type -AssemblyName UIAutomationClient\n"
                  "$e = [System.Windows.Automation.AutomationElement]::FocusedElement\n"
                  "[Console]::Out.Write($e.GetCurrentPropertyValue("
                  "[System.Windows.Automation.AutomationElement]::IsPasswordProperty).ToString())\n")
        try:
            return self._script(script, "reading the focused field").strip().lower() == b"true"
        except DriverError:
            return None


def detect_windows(which: Callable[[str], str | None], run: Runner) -> tuple[Driver | None, Availability]:
    powershell = which("powershell") or which("pwsh")
    if not powershell:
        return unavailable("no_powershell", "PowerShell was not found", "PowerShell")
    driver = WindowsDriver(powershell, run)
    try:
        driver.screen_size()
    except DriverError as exc:
        return unavailable("display_unreachable", f"PowerShell could not read the screen: {exc}")
    notes = ["typing uses SendKeys: it types only characters the current keyboard layout has"]
    return driver, Availability(True, driver.backend, supports=tuple(sorted(driver.supports)), notes=tuple(notes))

