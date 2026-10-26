"""Desktop actions (A19), the parts that need no task: the drivers with fake programs, the actions and which of them
always ask, and the provider adapter against fixture JSON. The macOS and Windows drivers are checked against fake
programs only: they have not been run on real machines. The fixtures are written from the provider's documentation."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from spike.core.types import PaidCallBlocked, ProviderError
from spike.desktop import backends
from spike.desktop.actions import (
    NOT_OFFERED,
    ActionError,
    classify,
    describe,
    parse_action,
    region_for,
    summary,
)
from spike.desktop.adapters import (
    BETAS,
    MEMBERS,
    NOT_EXECUTED,
    V20250124,
    V20251124,
    AnthropicAdapter,
    Call,
    image_tokens,
    tool_variant,
)
from spike.desktop.driver import (
    Ran,
    Shot,
    detect,
    fit_size,
    parse_key,
    parse_modifiers,
    png_size,
)
from spike.providers.anthropic import AnthropicProvider
from spike.providers.openai_compat import OpenAICompatProvider
from tests.helpers_desktop import REQUESTS, RESPONSES, png, provider_config, reply


class Programs:
    """A runner that answers by program name and keeps every command line it was given. An answer is a Ran or a
    function of the command line."""

    def __init__(self, **answers):
        self.answers, self.calls = answers, []

    def __call__(self, argv, stdin=None, timeout=0.0):
        self.calls.append(list(argv))
        answer = self.answers.get(Path(argv[0]).name)
        if answer is None:
            return Ran(127, b"", "not found")
        return answer(list(argv)) if callable(answer) else answer


def which_of(*names: str) -> Callable[[str], str | None]:
    return lambda name: f"/usr/bin/{name}" if name in names else None


GEOMETRY = Ran(0, b"1024 768\n")
IMAGEMAGICK = Ran(0, b"Version: ImageMagick 6.9.12")
X_ENV = {"DISPLAY": ":0"}


# ---------------------------------------------------------------- screenshots and coordinates
def test_screenshots_are_shrunk_to_the_limits_every_model_has():
    assert fit_size(1024, 768) == (1024, 768)  # already inside
    for w, h in ((2560, 1440), (3840, 2160), (1920, 1080), (5120, 2880), (800, 3000)):
        sw, sh = fit_size(w, h)
        assert max(sw, sh) <= 1568 and sw * sh <= 1_150_000
        assert abs(sw / sh - w / h) < 0.01  # the shape is kept
    assert fit_size(1, 1) == (1, 1)


def test_the_models_points_are_mapped_back_to_the_screen_and_kept_inside_it():
    shot = Shot(b"", 1238, 928, 2048, 1536)
    assert shot.to_screen(0, 0) == (0, 0)
    assert shot.to_screen(619, 464) == (1024, 768)
    assert shot.to_screen(5000, 5000) == (2047, 1535)  # a point beyond the image is clamped, never off the screen
    retina = Shot(b"", 1280, 800, 1440, 900)  # the mouse uses points, the screenshot has other pixels
    assert retina.to_screen(640, 400) == (720, 450)


def test_png_size_reads_the_header_and_refuses_anything_else():
    assert png_size(png(40, 30)) == (40, 30)
    assert png_size(b"not an image at all, not an image at all") is None
    assert png_size(b"") is None


# ---------------------------------------------------------------- keys
@pytest.mark.parametrize("combo, parsed", [
    ("Return", ((), "Return")), ("enter", ((), "Return")), ("ctrl+c", (("ctrl",), "c")),
    ("Ctrl+Shift+Left", (("ctrl", "shift"), "Left")), ("alt+F4", (("alt",), "F4")), ("f5", ((), "F5")),
    ("ctrl++", (("ctrl",), "plus")), ("cmd+space", (("super",), "space")), ("shift", ((), "shift")),
    ("ctrl+ctrl+a", (("ctrl",), "a")), ("PageDown", ((), "Page_Down")),
])
def test_key_combinations_are_parsed(combo, parsed):
    assert parse_key(combo) == parsed


def test_bad_keys_and_modifiers_are_refused():
    for bad in ("", "  ", "banana+a"):
        with pytest.raises(backends.DriverError):
            parse_key(bad)
    assert parse_modifiers(None) == () and parse_modifiers("") == ()
    assert parse_modifiers("ctrl+shift") == ("ctrl", "shift")
    with pytest.raises(backends.DriverError, match="not a modifier"):
        parse_modifiers("banana")


# ---------------------------------------------------------------- Linux / X11
def test_xdotool_command_lines():
    assert backends.xdotool_click_argv("xdotool", 10, 20, "left", 1, ()) == ["xdotool", "mousemove", "10", "20",
                                                                              "click", "1"]
    assert backends.xdotool_click_argv("xdotool", 10, 20, "right", 3, ("shift",)) == [
        "xdotool", "keydown", "shift", "mousemove", "10", "20", "click", "--repeat", "3", "--delay", "80", "3",
        "keyup", "shift"]
    assert backends.xdotool_scroll_argv("xdotool", 5, 6, "down", 4, ())[-5:] == ["--repeat", "4", "--delay", "30", "5"]
    assert backends.xdotool_scroll_argv("xdotool", None, None, "up", 2, ("ctrl",)) == [
        "xdotool", "keydown", "ctrl", "click", "--repeat", "2", "--delay", "30", "4", "keyup", "ctrl"]
    assert backends.xdotool_drag_argv("xdotool", 1, 2, 3, 4, ())[1:5] == ["mousemove", "1", "2", "mousedown"]
    assert backends.xdotool_key_argv("xdotool", "ctrl+Shift+s", 2) == [
        "xdotool", "key", "--clearmodifiers", "--", "ctrl+shift+s", "ctrl+shift+s"]


@pytest.mark.parametrize("env, present, runs, code", [
    ({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}, ("xdotool", "import"), {}, "wayland"),
    ({"WAYLAND_DISPLAY": "wayland-0"}, ("xdotool", "import"), {}, "wayland"),
    ({}, ("xdotool", "import"), {}, "no_display"),
    (X_ENV, ("import",), {}, "no_xdotool"),
    (X_ENV, ("xdotool",), {}, "no_capture"),
    (X_ENV, ("xdotool", "import"), {"import": Ran(0, b"import (GNU) 1.0")}, "no_capture"),  # another `import`
    (X_ENV, ("xdotool", "import"), {"import": IMAGEMAGICK, "xdotool": Ran(1, b"", "Can't open display")},
     "display_unreachable"),
])
def test_x11_is_refused_with_a_reason_and_what_to_install(env, present, runs, code):
    driver, avail = detect("linux", which_of(*present), env, Programs(**{"xdotool": GEOMETRY, **runs}))
    assert driver is None and not avail.available and avail.code == code and avail.reason
    if code in ("no_xdotool", "no_capture"):
        assert avail.needs


def test_x11_driver_takes_a_screenshot_and_does_the_actions_with_imagemagick():
    def grab(argv):
        size = argv[argv.index("-resize") + 1].rstrip("!")
        return Ran(0, png(*map(int, size.split("x"))))

    run = Programs(xdotool=Ran(0, b"2560 1440\n"), **{"import": lambda argv: IMAGEMAGICK if "-version" in argv else grab(argv)})
    driver, avail = detect("linux", which_of("xdotool", "import"), X_ENV, run)
    assert avail.available and avail.backend == "xdotool" and "left_click" in avail.supports
    shot = driver.screenshot()
    width, height = fit_size(2560, 1440)
    assert (shot.width, shot.height, shot.screen_width, shot.screen_height) == (width, height, 2560, 1440)
    assert ["/usr/bin/import", "-window", "root", "-resize", f"{width}x{height}!", "png:-"] in run.calls
    driver.click(10, 20)
    driver.type_text("-rf hola")
    driver.key("ctrl+a")
    assert run.calls[-3:] == [["/usr/bin/xdotool", "mousemove", "10", "20", "click", "1"],
                              ["/usr/bin/xdotool", "type", "--delay", "12", "--", "-rf hola"],
                              ["/usr/bin/xdotool", "key", "--clearmodifiers", "--", "ctrl+a"]]


def test_x11_driver_uses_scrot_and_shrinks_with_convert_when_it_can():
    def scrot(argv):
        Path(argv[-1]).write_bytes(png(1024, 768))
        return Ran(0)

    run = Programs(xdotool=Ran(0, b"3840 2160\n"), scrot=scrot,
                   convert=lambda argv: Ran(0, png(*map(int, argv[argv.index("-resize") + 1].rstrip("!").split("x")))))
    driver, avail = detect("linux", which_of("xdotool", "scrot", "convert"), X_ENV, run)
    assert avail.available and not avail.notes
    shot = driver.screenshot()
    assert (shot.width, shot.height) == fit_size(3840, 2160)
    assert any(c[0].endswith("scrot") for c in run.calls) and any(c[0].endswith("convert") for c in run.calls)


def test_a_screenshot_too_big_to_send_is_refused_when_nothing_can_shrink_it():
    def scrot(argv):
        Path(argv[-1]).write_bytes(png(3000, 1700))
        return Ran(0)

    driver, avail = detect("linux", which_of("xdotool", "scrot"), X_ENV, Programs(xdotool=Ran(0, b"3000 1700\n"),
                                                                                   scrot=scrot))
    assert avail.available and any("install ImageMagick" in n for n in avail.notes)
    with pytest.raises(backends.DriverError, match="no program here to shrink"):
        driver.screenshot()


def test_a_program_that_fails_or_returns_junk_is_an_error_naming_the_action():
    run = Programs(xdotool=lambda argv: Ran(1, b"", "BadWindow") if argv[1] == "mousemove" else GEOMETRY,
                   **{"import": lambda argv: IMAGEMAGICK if "-version" in argv else Ran(0, b"junk")})
    driver, _ = detect("linux", which_of("xdotool", "import"), X_ENV, run)
    with pytest.raises(backends.DriverError, match=r"the click failed \(xdotool\): BadWindow"):
        driver.click(1, 2)
    with pytest.raises(backends.DriverError, match="did not return a PNG"):
        driver.screenshot()


def test_x11_reads_the_mouse_position():
    run = Programs(xdotool=lambda argv: Ran(0, b"X=33\nY=44\nSCREEN=0\nWINDOW=1\n") if argv[1] == "getmouselocation"
                   else GEOMETRY, **{"import": IMAGEMAGICK})
    driver, _ = detect("linux", which_of("xdotool", "import"), X_ENV, run)
    assert driver.cursor_position() == (33, 44)
    assert driver.secure_field_focused() is None  # X11 cannot say: only the model's words and the user's eyes


# ---------------------------------------------------------------- macOS (fake programs only)
def test_applescript_strings_cannot_end_early():
    assert backends.applescript_string('a"b\\c') == '"a\\"b\\\\c"'
    hostile = '" & (do shell script "touch /tmp/x") & "'
    assert backends.mac_type_lines(hostile) == [r'keystroke "\" & (do shell script \"touch /tmp/x\") & \""']
    assert backends.mac_type_lines('Hola "mundo"\nlinea2\tx') == [
        r'keystroke "Hola \"mundo\""', "key code 36", 'keystroke "linea2"', "key code 48", 'keystroke "x"']


def test_mac_keys_and_command_lines():
    assert backends.mac_key_line("Return") == "key code 36"
    assert backends.mac_key_line("cmd+s") == 'keystroke "s" using {command down}'
    assert backends.mac_key_line("ctrl+shift+Left") == "key code 123 using {control down, shift down}"
    with pytest.raises(backends.DriverError, match="not known on macOS"):
        backends.mac_key_line("banana")
    assert backends.osascript_argv("osascript", ["key code 36"]) == [
        "osascript", "-e", 'tell application "System Events"', "-e", "key code 36", "-e", "end tell"]
    assert backends.cliclick_click_argv("cliclick", 10, 20, "left", 2, ()) == ["cliclick", "dc:10,20"]
    assert backends.cliclick_click_argv("cliclick", 10, 20, "left", 1, ("shift", "super")) == [
        "cliclick", "kd:shift,cmd", "c:10,20", "ku:shift,cmd"]
    for button, count in (("middle", 1), ("right", 2)):
        with pytest.raises(backends.DriverError, match="cannot do"):
            backends.cliclick_click_argv("cliclick", 1, 2, button, count, ())
    assert backends.cliclick_drag_argv("cliclick", 1, 2, 3, 4, ()) == [
        "cliclick", "dd:1,2", "w:150", "m:3,4", "w:150", "du:3,4"]


def mac_programs(**extra):
    def screencapture(argv):
        Path(argv[-1]).write_bytes(png(2880, 1800))
        return Ran(0)

    def sips(argv):
        Path(argv[-1]).write_bytes(png(int(argv[3]), int(argv[2])))
        return Ran(0)

    def osascript(argv):
        script = " ".join(argv)
        if "bounds of window of desktop" in script:
            return Ran(0, b"0, 0, 1440, 900\n")
        if "AXSubrole" in script:
            return Ran(0, b"AXSecureTextField\n")
        return Ran(0)

    return Programs(screencapture=screencapture, sips=sips, osascript=osascript, cliclick=Ran(0, b"1,2\n"), **extra)


def test_macos_needs_its_own_programs():
    driver, avail = detect("darwin", which_of("osascript", "sips"), {}, mac_programs())
    assert driver is None and avail.code == "no_macos_tools" and "screencapture" in avail.reason


def test_macos_screenshot_is_shrunk_with_sips_and_the_mouse_uses_points():
    run = mac_programs()
    driver, avail = detect("darwin", which_of("screencapture", "osascript", "sips", "cliclick"), {}, run)
    assert avail.available and "right_click" in avail.supports and "scroll" not in avail.supports
    assert any("Screen Recording" in n for n in avail.notes)
    shot = driver.screenshot()
    assert (shot.screen_width, shot.screen_height) == (1440, 900) and (shot.width, shot.height) == fit_size(1440, 900)
    x, y = shot.to_screen(shot.width // 2, shot.height // 2)  # the middle of the image is the middle of the screen
    assert x == 720 and abs(y - 450) <= 1
    driver.click(10, 20, "right")
    assert run.calls[-1] == ["/usr/bin/cliclick", "rc:10,20"]
    with pytest.raises(backends.DriverError, match="scrolling is not available"):
        driver.scroll(1, 2, "down", 3)
    assert driver.secure_field_focused() is True


def test_macos_without_cliclick_only_clicks_plainly_and_says_so():
    run = mac_programs()
    driver, avail = detect("darwin", which_of("screencapture", "osascript", "sips"), {}, run)
    assert "right_click" not in avail.supports and "left_click" in avail.supports
    assert any("cliclick is not installed" in n for n in avail.notes)
    driver.click(10, 20)
    assert "click at {10, 20}" in run.calls[-1] and run.calls[-1][0].endswith("osascript")
    with pytest.raises(backends.DriverError, match="needs the cliclick program"):
        driver.click(10, 20, "right")
    with pytest.raises(backends.DriverError, match="needs the cliclick program"):
        driver.drag(1, 2, 3, 4)


# ---------------------------------------------------------------- Windows (fake PowerShell only)
def test_sendkeys_text_and_combinations():
    assert backends.sendkeys_text("a+b^c%d~(e){f}[g]\n\t") == "a{+}b{^}c{%}d{~}{(}e{)}{{}f{}}{[}g{]}{ENTER}{TAB}"
    assert backends.sendkeys_combo("ctrl+c") == "^c"
    assert backends.sendkeys_combo("ctrl+shift+s") == "^+(s)"
    assert backends.sendkeys_combo("alt+F4") == "%{F4}"
    assert backends.sendkeys_combo("ctrl+Left") == "^{LEFT}"
    assert backends.sendkeys_combo("Return") == "{ENTER}"
    with pytest.raises(backends.DriverError, match="Windows key"):
        backends.sendkeys_combo("cmd+r")


def test_powershell_scripts_press_and_release_keys_around_the_click():
    script = backends.ps_click(10, 20, "left", 2, ("shift",))
    assert script.count("mouse_event(2,") == 2 and script.count("mouse_event(4,") == 2  # two presses, two releases
    down, cursor, release = (script.index(s) for s in ("keybd_event([byte]16, 0, 0,", "SetCursorPos(10, 20)",
                                                      "keybd_event([byte]16, 0, 2,"))
    assert down < cursor < release
    assert "mouse_event(2048, 0, 0, -120" in backends.ps_scroll(None, None, "down", 1, ())
    assert "mouse_event(2048, 0, 0, 120" in backends.ps_scroll(5, 6, "up", 1, ())


def windows_programs(scripts: list[str]):
    """PowerShell that records each script it is asked to run and answers the way the real one would."""

    def powershell(argv):
        text = Path(argv[-1]).read_text(encoding="ascii")
        scripts.append(text)
        if "GetSystemMetrics(0)).ToString()" in text:
            return Ran(0, b"1920 1080")
        if "CopyFromScreen" in text:
            return Ran(0, base64.b64encode(png(*map(int, text.split("Bitmap ")[2].split("\n")[0].split(", ")))))
        if "IsPasswordProperty" in text:
            return Ran(0, b"True")
        return Ran(0)

    return Programs(powershell=powershell)


def test_windows_text_reaches_powershell_only_as_base64_and_scripts_are_plain_ascii():
    scripts: list[str] = []
    run = windows_programs(scripts)
    driver, avail = detect("win32", which_of("powershell"), {}, run)
    assert avail.available and avail.backend == "windows"
    hostile = '"; Remove-Item -Recurse C:\\ # ñ'
    driver.type_text(hostile)
    script = scripts[-1]
    assert "Remove-Item" not in script and script.isascii()
    data = script.split("FromBase64String('")[1].split("'")[0]
    assert base64.b64decode(data).decode("utf-8") == backends.sendkeys_text(hostile)
    assert run.calls[-1][:7] == ["/usr/bin/powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", run.calls[-1][6]]
    assert driver.secure_field_focused() is True


def test_windows_screenshot_comes_back_as_base64_and_the_scratch_folder_goes_away():
    scripts: list[str] = []
    driver, _ = detect("win32", which_of("powershell"), {}, windows_programs(scripts))
    shot = driver.screenshot()
    assert (shot.screen_width, shot.screen_height) == (1920, 1080) and (shot.width, shot.height) == fit_size(1920, 1080)
    folder = driver._folder
    assert folder is not None and folder.is_dir()
    driver.close()
    assert not folder.exists()


def test_windows_and_other_systems_without_what_they_need_say_so():
    assert detect("win32", which_of(), {}, Programs())[1].code == "no_powershell"
    assert detect("win32", which_of("pwsh"), {}, Programs(pwsh=Ran(1, b"", "no display")))[1].code == "display_unreachable"
    driver, avail = detect("freebsd14", which_of(), {}, Programs())
    assert driver is None and avail.code == "unsupported_os"


# ---------------------------------------------------------------- actions
def test_actions_are_checked_and_the_models_numbers_are_made_safe():
    a = parse_action("left_click", {"coordinate": [10.4, 20.6], "text": "shift"})
    assert (a.coordinate, a.text, a.passive) == ((10, 21), "shift", False)
    assert parse_action("left_click", {}).coordinate is None  # a click where the mouse is
    assert parse_action("scroll", {"coordinate": [1, 2], "scroll_direction": "down", "scroll_amount": 999}).amount == 30
    assert parse_action("scroll", {"scroll_direction": "up"}).amount == 3
    assert parse_action("wait", {"duration": 3600}).duration == 30.0 and parse_action("screenshot", {}).passive
    assert parse_action("key", {"text": "ctrl+a", "repeat": 3}).repeat == 3
    drag = parse_action("left_click_drag", {"start_coordinate": [1, 2], "coordinate": [3, 4]})
    assert (drag.start, drag.coordinate) == ((1, 2), (3, 4))


@pytest.mark.parametrize("name, args, message", [
    ("frobnicate", {}, "unknown action"),
    ("left_click", {"coordinate": [-1, 5]}, "outside the screen"),
    ("left_click", {"coordinate": [1]}, r"must be \[x, y\]"),
    ("left_click", {"coordinate": "10,20"}, r"must be \[x, y\]"),
    ("left_click", {"coordinate": [True, 2]}, r"must be \[x, y\]"),
    ("left_click", {"coordinate": [math.nan, 2]}, r"must be \[x, y\]"),
    ("mouse_move", {}, "'coordinate' is required"),
    ("left_click_drag", {"coordinate": [1, 2]}, "'start_coordinate' is required"),
    ("type", {}, "'text' is required"),
    ("type", {"text": 5}, "must be a string"),
    ("type", {"text": "x" * 4001}, "type it in parts"),
    ("key", {"text": ""}, "'text' is required"),
    ("key", {"text": "a", "repeat": 0}, "'repeat'"),
    ("key", {"text": "a", "repeat": 101}, "'repeat'"),
    ("scroll", {"scroll_direction": "sideways"}, "scroll_direction"),
    ("scroll", {"scroll_direction": "up", "scroll_amount": "lots"}, "scroll_amount"),
    ("wait", {"duration": -1}, "duration"),
])
def test_a_malformed_action_is_refused_with_a_message_for_the_model(name, args, message):
    with pytest.raises(ActionError, match=message):
        parse_action(name, args)


@pytest.mark.parametrize("name", sorted(NOT_OFFERED))
def test_actions_the_drivers_cannot_do_safely_are_refused_not_guessed(name):
    with pytest.raises(ActionError, match="not available on this computer"):
        parse_action(name, {"coordinate": [1, 2], "region": [1, 2, 3, 4], "text": "ctrl"})


# ---------------------------------------------------------------- which actions always ask
def kind(action, words="", secure=None):
    found = classify(parse_action(*action), words, secure)
    return found.kind if found else None


CLICK = ("left_click", {"coordinate": [5, 5]})


@pytest.mark.parametrize("action, words, secure, expected", [
    (CLICK, "I will click the search box.", None, None),
    (CLICK, "[SENSITIVE: send] Clicking Send.", None, "send"),
    (CLICK, "[sensitive: PURCHASE] pay now", None, "purchase"),
    (CLICK, "[SENSITIVE] something", None, "labelled"),
    (CLICK, "[SENSITIVE: lunar landing]", None, "labelled"),
    (CLICK, "Voy a pulsar Eliminar para borrar el archivo.", None, "delete"),
    (CLICK, "Now I click Buy to complete the purchase.", None, "purchase"),
    (CLICK, "Pulsaré Enviar para mandar el correo.", None, "send"),
    (CLICK, "Haré clic en Pagar.", None, "purchase"),
    (("type", {"text": "hola"}), "Escribo la contraseña.", None, "password"),
    (("type", {"text": "1234"}), "I enter the card number and CVV.", None, "password"),
    (("type", {"text": "hola"}), "Escribo un saludo.", None, None),
    (("type", {"text": "hola"}), "Escribo un saludo.", True, "password"),  # the driver saw a password field
    (("type", {"text": "hola"}), "Escribo un saludo.", False, None),
    (("type", {"text": "linea 1\nlinea 2"}), "", None, "submit"),
    (("key", {"text": "Return"}), "", None, "submit"),
    (("key", {"text": "enter"}), "", None, "submit"),
    (("key", {"text": "Delete"}), "", None, "delete"),
    (("key", {"text": "super+BackSpace"}), "", None, "delete"),
    (("key", {"text": "alt+F4"}), "", None, "close"),
    (("key", {"text": "ctrl+q"}), "", None, "close"),
    (("key", {"text": "ctrl+c"}), "", None, None),
    (("key", {"text": "Tab"}), "", None, None),
    (("screenshot", {}), "[SENSITIVE: send]", None, None),  # looking changes nothing
    (("wait", {"duration": 1}), "delete everything", None, None),
])
def test_sensitive_actions_are_recognised(action, words, secure, expected):
    assert kind(action, words, secure) == expected


def test_a_password_is_never_shown_or_kept():
    action = parse_action("type", {"text": "hunter2-secret"})
    for shown in (describe(action, masked=True), {"s": summary(action, masked=True)}):
        assert "hunter2" not in json.dumps(shown)
    assert describe(action, masked=True)["chars"] == 14 and "text" not in describe(action, masked=True)
    assert describe(action)["text"] == "hunter2-secret"  # not masked: an ordinary text is shown in full


def test_the_card_describes_the_action_and_crops_the_screenshot_around_it():
    assert summary(parse_action("left_click", {"coordinate": [5, 6]})) == "left click at (5, 6)"
    assert summary(parse_action("double_click", {"coordinate": [5, 6]})) == "double click at (5, 6)"
    assert summary(parse_action("left_click_drag", {"start_coordinate": [1, 2], "coordinate": [3, 4]})
                   ) == "drag from (1, 2) to (3, 4)"
    assert summary(parse_action("key", {"text": "ctrl+a", "repeat": 2})) == "press ctrl+a x2"
    assert summary(parse_action("type", {"text": "a\nb"})) == "type “a⏎b”"
    assert region_for(parse_action("type", {"text": "x"}), 1024, 768) is None
    for point in ((5, 5), (512, 742), (1023, 767), (0, 400)):
        region = region_for(parse_action("left_click", {"coordinate": list(point)}), 1024, 768)
        assert region["x"] >= 0 and region["x"] + region["w"] <= 1024 and region["y"] >= 0
        assert region["y"] + region["h"] <= 768
        assert region["x"] <= point[0] <= region["x"] + region["w"] and region["y"] <= point[1] <= region["y"] + region["h"]
        assert region["points"] == [{"x": point[0], "y": point[1]}] and (region["image_w"], region["image_h"]) == (1024, 768)
    drag = region_for(parse_action("left_click_drag", {"start_coordinate": [100, 100], "coordinate": [700, 500]}), 1024, 768)
    assert len(drag["points"]) == 2 and drag["w"] >= 600


# ---------------------------------------------------------------- the provider adapter (fixtures from the docs)
@pytest.mark.parametrize("model, expected", [
    ("claude-opus-5-5", "computer_toolset_20260801"), ("claude-sonnet-5-5", "computer_toolset_20260801"),
    ("claude-haiku-5-5", "computer_toolset_20260801"), ("claude-opus-4-8", V20251124),
    ("claude-opus-4-5-20251101", V20251124), ("claude-sonnet-4-6", V20251124), ("claude-fable-5", V20251124),
    ("claude-sonnet-4-5-20250929", V20250124), ("claude-haiku-4-5", V20250124), ("claude-opus-4-1", V20250124),
    ("claude-sonnet-4-20250514", V20250124), ("a-model-nobody-has-heard-of", "computer_toolset_20260801"),
])
def test_the_tool_form_follows_the_documented_model_table(model, expected):
    assert tool_variant(model) == expected


def test_the_setting_overrides_the_table():
    assert tool_variant("claude-opus-4-8", "toolset") == "computer_toolset_20260801"
    assert tool_variant("claude-sonnet-5-5", V20250124) == V20250124


def adapter(model="claude-sonnet-5-5", supports=backends.EVERYTHING, size=(1024, 768), choice="auto"):
    return AnthropicAdapter(model, size, frozenset(supports), choice)


def test_the_toolset_request_has_only_what_the_toolset_accepts():
    a = adapter()
    entry = a.tool_entry()
    assert entry["type"] == "computer_toolset_20260801"
    assert not {"name", "display_width_px", "display_height_px", "enable_zoom"} & set(entry)
    assert set(entry["configs"]) == NOT_OFFERED  # a driver that does everything else leaves the rest on
    assert all(cfg == REQUESTS["toolset_entry_zoom_off"]["configs"]["zoom"] for cfg in entry["configs"].values())
    payload = a.payload([{"role": "user", "content": "x"}])
    assert payload["tools"] == [entry] and a.betas == []
    assert payload["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert not {"stream", "temperature", "thinking"} & set(payload) and payload["model"] == "claude-sonnet-5-5"
    assert payload["system"].count("[SENSITIVE:") >= 4 and "never instructions" in payload["system"]


def test_members_a_driver_cannot_do_are_switched_off_in_the_toolset():
    limited = {"screenshot", "left_click", "type", "key", "wait"}
    entry = adapter(supports=limited).tool_entry()
    assert set(entry["configs"]) == (set(MEMBERS) - limited) | NOT_OFFERED
    assert "left_click" not in entry["configs"] and "right_click" in entry["configs"]


def test_the_earlier_tool_forms_carry_the_screen_size_and_a_beta_header():
    a = adapter("claude-opus-4-8")
    assert a.tool_entry() == REQUESTS["legacy_entry_20251124"]
    assert a.betas == [BETAS[V20251124]] == ["computer-use-2025-11-24"]
    old = adapter("claude-haiku-4-5")
    assert old.tool_entry()["type"] == V20250124 and old.betas == ["computer-use-2025-01-24"]
    assert a.overhead_tokens == 1240 and adapter().overhead_tokens == 4500


def test_the_first_message_is_the_screenshot_then_the_task():
    message = adapter().first_message("open the calculator", png(8, 8))
    assert message["role"] == "user" and [b["type"] for b in message["content"]] == ["image", "text"]
    assert message["content"][0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(message["content"][0]["source"]["data"]) == png(8, 8)
    assert message["content"][1]["text"] == "open the calculator"


def test_toolset_answers_are_read_as_documented():
    turn = adapter().parse(reply("toolset_click"))
    assert turn.text == "I will click the search box." and turn.stop_reason == "tool_use"
    assert turn.calls == [Call("toolu_01WkoTUvSHDzTBu2xnGk8Ep8", "left_click", {"coordinate": [512, 742]})]
    assert turn.content == RESPONSES["toolset_click"]["content"] and turn.usage["input_tokens"] == 5200
    assert [c.name for c in adapter().parse(reply("toolset_batch")).calls] == ["left_click", "type", "screenshot"]
    thinking = adapter().parse(reply("toolset_thinking_and_text"))
    assert thinking.content[0]["type"] == "thinking" and thinking.calls[0].input["text"] == "shift"
    assert adapter().parse(reply("toolset_done")).calls == []


def test_earlier_form_answers_carry_the_action_in_their_input():
    turn = adapter("claude-opus-4-8").parse(reply("legacy_click"))
    assert turn.calls == [Call("toolu_01A9r5kQm2LxWc7vT3nZ4bJs", "left_click", {"coordinate": [500, 300]})]
    assert adapter("claude-opus-4-8").parse(reply("legacy_type")).calls[0].input == {"text": "hello"}


def test_errors_and_nonsense_from_the_provider_are_provider_errors():
    with pytest.raises(ProviderError, match="does not support tool types"):
        adapter().parse(reply("error"))
    with pytest.raises(ProviderError):
        adapter().parse("not an object")  # type: ignore[arg-type]


def test_results_have_the_shape_the_documentation_shows():
    batch = reply("toolset_batch")["content"]
    a = adapter()
    assert a.result(Call(batch[0]["id"], "left_click", {}), "OK") == REQUESTS["toolset_result_text"]
    failed = a.result(Call(batch[2]["id"], "screenshot", {}), NOT_EXECUTED, error=True)
    assert failed == REQUESTS["toolset_result_failed"]
    with_image = a.result(Call("toolu_x", "left_click", {}), "OK", png(4, 4))
    assert [b["type"] for b in with_image["content"]] == ["text", "image"] and with_image["toolset_name"] == "computer"
    assert [b["type"] for b in a.result(Call("toolu_x", "screenshot", {}), png=png(4, 4))["content"]] == ["image"]
    old = adapter("claude-opus-4-8").result(Call("toolu_x", "left_click", {}), "OK")
    assert "toolset_name" not in old and old["tool_use_id"] == "toolu_x"
    assert a.results_message([failed]) == {"role": "user", "content": [failed]}


def test_a_screenshots_tokens_never_come_out_low():
    assert image_tokens(1024, 768) == math.ceil(1024 * 768 / 750) == 1049
    assert image_tokens(1568, 735) == max(math.ceil(1568 * 735 / 750), 56 * 27)


# ---------------------------------------------------------------- the Anthropic request itself
def anthropic(handler, **config) -> AnthropicProvider:
    return AnthropicProvider(provider_config(**config), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_send_raw_posts_the_payload_with_the_beta_header_and_returns_the_answer():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=RESPONSES["toolset_done"])

    payload = adapter("claude-opus-4-8").payload([{"role": "user", "content": "x"}])
    answer = await anthropic(handler).send_raw(payload, beta=["computer-use-2025-11-24"])
    assert answer == RESPONSES["toolset_done"]
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://api.anthropic.com/v1/messages"
    assert json.loads(request.content) == payload
    assert request.headers["x-api-key"] == "sk-ant-test" and request.headers["anthropic-beta"] == "computer-use-2025-11-24"
    await anthropic(handler).send_raw(payload)
    assert "anthropic-beta" not in seen[1].headers  # the toolset needs no beta header
    await anthropic(handler, headers={"anthropic-beta": "other-beta"}).send_raw(payload, beta=["computer-use-2025-11-24"])
    assert seen[2].headers["anthropic-beta"] == "other-beta,computer-use-2025-11-24"


async def test_send_raw_failures_are_provider_errors_and_a_paid_block_sends_nothing():
    hits = []

    def handler(request):
        hits.append(request)
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(ProviderError, match="authentication failed"):
        await anthropic(handler).send_raw({"model": "m"})

    def down(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(ProviderError, match="connection failed"):
        await anthropic(down).send_raw({"model": "m"})
    before = len(hits)
    with pytest.raises(PaidCallBlocked):
        await anthropic(handler, allow_paid=False).send_raw({"model": "m"})
    assert len(hits) == before


async def test_a_provider_without_a_computer_use_request_refuses_it():
    openai = OpenAICompatProvider(provider_config(id="o", kind="openai", name="OpenAI-compatible",
                                                  base_url="https://example.invalid/v1"),
                                  client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert openai.computer_use_adapter is None
    with pytest.raises(ProviderError, match="no computer-use request"):
        await openai.send_raw({})
