"""A21 Device Lab: open a local web app in phone, tablet and desktop profiles and report what breaks in each.

The page runs in the headless Chromium SPIKE already drives (Spike Motion's launcher: SPIKE_CHROMIUM, else Playwright's
Chromium, else an installed Chrome or Edge). Each profile is a fresh browser context with its own viewport, device scale
factor, touch and mobile flags and a user agent of a generic class; this EMULATES a device in a desktop browser engine,
it is not a real-device test. Per profile: a screenshot, console errors and uncaught exceptions, failed requests (network
failures and HTTP errors), horizontal overflow (and which elements cause it), tap targets under 24x24 CSS px and text
under 12 px (`device_lab_checks.js`, deterministic geometry, no model). The target must be on this computer (localhost,
127.0.0.0/8, ::1) unless the user names the host for this run; the browser may reach only the target, loopback and the
hosts the user named (anything else is blocked and listed, redirects included), so a redirect cannot carry it away.

Optional Android: when `adb` is already on the PATH and lists a device or emulator, it is shown. Taking its screenshot
(`adb exec-out screencap -p`) and opening the URL on it happen only when the caller says the user approved. SPIKE never
downloads adb, an SDK or an emulator, and no check runs on the device: only the picture of its screen."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import json
import re
import shlex
import shutil
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from spike.tools.base import Review, Tool, ToolResult

CHECKS = Path(__file__).with_name("device_lab_checks.js").read_text(encoding="utf-8")
MIN_TAP = 24  # CSS px: a smaller control is reported (WCAG 2.2 target size, minimum)
MIN_FONT = 12  # CSS px: smaller text is reported
LIST_LIMIT = 20  # items kept per category and profile; the total is always counted
MAX_PROFILES = 12
MAX_CUSTOM = 6
MAX_ALLOW = 8
NAV_TIMEOUT_MS = 30_000
PROFILE_TIMEOUT_S = 60
TOTAL_TIMEOUT_S = 420
MAX_SHOT_BYTES = 3 * 1024 * 1024  # a bigger screenshot is left out of the report
MAX_SHOT_HEIGHT = 4000  # CSS px of a full-page screenshot
MAX_SHOT_WIDTH = 2400
ADB_TIMEOUT_S = 20
MAX_ADB_BYTES = 24 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
REASONS = ("overflow", "tap_targets", "small_text", "console_errors", "failed_requests")


class DeviceLabError(Exception):
    """A refusal or a problem that stops the run. `code` names it so the app can translate it; the text is English
    (and Spanish when the model reads it)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# ---------------------------------------------------------------------------------------------------- profiles
@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    kind: str  # phone | tablet | laptop | desktop | custom
    width: int
    height: int
    scale: float = 1.0
    touch: bool = False
    mobile: bool = False
    user_agent: str = ""
    builtin: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generic_agent(klass: str) -> str:
    """A user agent that names only a class of device (no browser, system or maker): pages that sniff for Mobile or
    Tablet see it, pages that look for a specific browser do not."""
    return f"SpikeDeviceLab/1.0 ({klass})"


PROFILES: tuple[Profile, ...] = (
    Profile("small-phone", "Small phone", "phone", 360, 640, 2, True, True, generic_agent("Mobile; phone; touch")),
    Profile("large-phone", "Large phone", "phone", 414, 896, 2, True, True, generic_agent("Mobile; phone; touch")),
    Profile("tablet-portrait", "Tablet, portrait", "tablet", 768, 1024, 2, True, True, generic_agent("Tablet; touch")),
    Profile("tablet-landscape", "Tablet, landscape", "tablet", 1024, 768, 2, True, True,
            generic_agent("Tablet; touch")),
    Profile("laptop", "Laptop", "laptop", 1366, 768, 1, False, False, generic_agent("Laptop; desktop")),
    Profile("desktop", "Desktop", "desktop", 1920, 1080, 1, False, False, generic_agent("Desktop")),
)
BUILTIN = {p.id: p for p in PROFILES}


def parse_custom(data: Any, taken: set[str]) -> Profile:
    """A user's own profile from {name, width, height, scale, touch, mobile, user_agent}; the id is made from the name."""
    def bad(why: str) -> DeviceLabError:
        return DeviceLabError("device_lab_custom", f"invalid custom profile: {why}")

    if not isinstance(data, dict):
        raise bad("expected an object")
    name = data.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or not name.isprintable():
        raise bad("name must be 1 to 40 printable characters")

    def number(key: str, low: float, high: float, default: float | None = None, whole: bool = False) -> float:
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high or (
                whole and value != int(value)):
            raise bad(f"{key} must be {'a whole number ' if whole else 'a number '}from {low:g} to {high:g}")
        return value

    touch, mobile = data.get("touch", False), data.get("mobile")
    if mobile is None:
        mobile = touch
    if not isinstance(touch, bool) or not isinstance(mobile, bool):
        raise bad("touch and mobile must be true or false")
    agent = data.get("user_agent") or generic_agent("Custom")
    if not isinstance(agent, str) or len(agent) > 300 or not all(32 <= ord(c) < 127 for c in agent):
        raise bad("user_agent must be up to 300 printable ASCII characters")
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "profile"
    ident, n = f"custom-{slug}"[:48], 2
    while ident in taken or ident in BUILTIN:
        ident, n = f"custom-{slug}"[:44] + f"-{n}", n + 1
    return Profile(ident, name.strip(), "custom", int(number("width", 200, 4000, whole=True)),
                   int(number("height", 200, 4000, whole=True)), float(number("scale", 1, 4, 1)), touch, mobile,
                   agent, builtin=False)


def pick_profiles(ids: Any, custom: Any) -> list[Profile]:
    """The built-in profiles named by `ids` (all of them when it is empty) plus the custom ones, in order."""
    if ids in (None, "", []):
        ids = [] if custom else [p.id for p in PROFILES]
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise DeviceLabError("device_lab_profile", "profiles must be a list of profile ids")
    unknown = [i for i in ids if i not in BUILTIN]
    if unknown:
        raise DeviceLabError("device_lab_profile", f"unknown profile {unknown[0][:40]!r}; use: " + ", ".join(BUILTIN))
    chosen = [BUILTIN[i] for i in dict.fromkeys(ids)]
    if custom in (None, ""):
        custom = []
    if not isinstance(custom, list) or len(custom) > MAX_CUSTOM:
        raise DeviceLabError("device_lab_custom", f"custom profiles must be a list of at most {MAX_CUSTOM}")
    for item in custom:
        chosen.append(parse_custom(item, {p.id for p in chosen}))
    if not chosen:
        raise DeviceLabError("device_lab_profile", "choose at least one profile")
    return chosen[:MAX_PROFILES]


# ---------------------------------------------------------------------------------------------------- the host rule
@dataclass(frozen=True)
class Target:
    url: str  # what the browser opens
    scheme: str
    host: str
    port: int | None
    path: str

    @property
    def shown(self) -> str:
        """The address for reports: no query or fragment (they may carry tokens)."""
        return f"{self.scheme}://{'[' + self.host + ']' if ':' in self.host else self.host}" \
               f"{':' + str(self.port) if self.port else ''}{self.path or '/'}"[:300]


def clean_host(value: str) -> str:
    return value.strip().strip("[]").lower().rstrip(".")


def is_loopback(host: str) -> bool:
    """localhost (and *.localhost, which browsers resolve to this computer) or a loopback address."""
    host = clean_host(host)
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


HOSTNAME = re.compile(r"(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*")


def parse_allow_hosts(values: Any) -> tuple[str, ...]:
    """The hosts the user names for this run: plain host names or addresses, no scheme, port, path or wildcard."""
    if values in (None, ""):
        return ()
    if not isinstance(values, list | tuple) or len(values) > MAX_ALLOW:
        raise DeviceLabError("device_lab_hosts", f"allow_hosts must be a list of at most {MAX_ALLOW} host names")
    out: list[str] = []
    for value in values:
        host = clean_host(value) if isinstance(value, str) else ""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not HOSTNAME.fullmatch(host):
                raise DeviceLabError("device_lab_hosts", "allow_hosts takes plain host names or IP addresses: no "
                                     "scheme, port, path or wildcard") from None
        if host not in out:
            out.append(host)
    return tuple(out)


def check_target(url: Any, allow_hosts: Any = ()) -> Target:
    """Accept an http(s) address on this computer, or on a host the user named for this run; refuse anything else."""
    allowed = parse_allow_hosts(allow_hosts)
    text = url.strip() if isinstance(url, str) else ""
    if not text or len(text) > 2000 or any(ord(c) <= 32 or ord(c) == 127 for c in text):
        raise DeviceLabError("device_lab_url", "give one http:// or https:// address without spaces")
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise DeviceLabError("device_lab_url", "that address is not valid") from None
    if parts.scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None:
        raise DeviceLabError("device_lab_url", "give an http:// or https:// address without a user name or password")
    host = clean_host(host)
    if not is_loopback(host) and host not in allowed:
        raise DeviceLabError(
            "device_lab_host", f"{host} is not on this computer, so Device Lab does not open it. Use localhost, "
            f"127.0.0.1 or [::1], or name the host for this run. / {host} no está en este ordenador, así que "
            "Device Lab no lo abre. Usa localhost, 127.0.0.1 o [::1], o indica el host para esta ejecución.")
    return Target(text, parts.scheme, host, port, parts.path)


def reachable(url: str, allowed: frozenset[str]) -> bool:
    """Whether the browser may request this address: this computer, or a host the user named for the run."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme in ("data", "blob", "about"):  # nothing leaves the page
        return True
    return bool(host) and (is_loopback(host) or clean_host(host) in allowed)


def bypass_rules(allowed: frozenset[str]) -> str:
    """Chromium's proxy-bypass list for a browser whose only proxy is a dead end: this computer and the named hosts
    connect directly. `<-loopback>` first, because Chromium would otherwise also send link-local addresses (such as
    169.254.169.254) around the proxy."""
    named = [f"[{h}]" if ":" in h else h for h in sorted(allowed) if not is_loopback(h)]
    return ";".join(["<-loopback>", "localhost", "*.localhost", "127.0.0.0/8", "[::1]", *named])


def public_url(url: str) -> str:
    """A request address for reports: scheme, host and path only (queries may carry tokens), cut short."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url[:80]
    if parts.scheme not in ("http", "https", "ws", "wss"):
        return f"{parts.scheme}:"
    return f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}{parts.path}"[:200]


# ---------------------------------------------------------------------------------------------------- one profile
def describe(profile: dict[str, Any]) -> str:
    """The reason for a profile's verdict in one English line."""
    if profile["status"] == "error":
        return profile["reason"]
    parts = []
    if "overflow" in profile["reasons"]:
        parts.append(f"the page is {profile['overflow']['px']:g} px wider than the screen")
    for key, text in (("tap_targets", "tap target{s} under 24 px"), ("small_text", "text{s} under 12 px"),
                      ("console_errors", "console error{s}"), ("failed_requests", "failed request{s}")):
        total = profile[key]["total"]
        if key in profile["reasons"]:
            parts.append(f"{total} " + text.replace("{s}", "" if total == 1 else "s"))
    return "; ".join(parts) or "no problems found"


def category(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"total": len(items) if total is None else total, "items": items[:LIST_LIMIT]}


def blank(profile: Profile) -> dict[str, Any]:
    """A profile's result before anything is known: an `error` with empty findings."""
    return {"id": profile.id, "name": profile.name, "kind": profile.kind, "builtin": profile.builtin,
            "viewport": {"width": profile.width, "height": profile.height}, "scale": profile.scale,
            "touch": profile.touch, "mobile": profile.mobile, "user_agent": profile.user_agent, "status": "error",
            "reasons": [], "reason": "", "http_status": None, "title": "", "notes": [], "layout": None,
            "overflow": {**category([]), "px": 0}, "tap_targets": category([]), "small_text": category([]),
            "console_errors": category([]), "failed_requests": category([]), "blocked_requests": category([]),
            "screenshot": "", "seconds": 0.0}


async def check_profile(browser, profile: Profile, target: Target, allowed: frozenset[str]) -> dict[str, Any]:
    """One profile in its own browser context. Problems of the page are findings; only a page that cannot be opened
    or measured makes the profile an `error`."""
    started = time.monotonic()
    out = blank(profile)
    console: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    seen_blocked: set[str] = set()
    context = await browser.new_context(
        viewport={"width": profile.width, "height": profile.height}, device_scale_factor=profile.scale,
        is_mobile=profile.mobile, has_touch=profile.touch, user_agent=profile.user_agent or None,
        service_workers="block", accept_downloads=False)
    try:
        def block(url: str) -> None:
            shown = public_url(url)
            if shown not in seen_blocked:
                seen_blocked.add(shown)
                blocked.append({"url": shown})

        async def gate(route) -> None:
            if reachable(route.request.url, allowed):
                await route.continue_()
            else:
                block(route.request.url)
                await route.abort("blockedbyclient")

        await context.route("**/*", gate)
        page = await context.new_page()
        context.on("page", lambda popup: asyncio.ensure_future(popup.close()))
        page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.dismiss()))

        def on_console(message) -> None:
            # "Failed to load resource" is the browser repeating a failed request, which is listed on its own
            if message.type == "error" and not message.text.startswith("Failed to load resource"):
                where = message.location or {}
                line = f":{where['lineNumber']}" if where.get("lineNumber") else ""
                console.append({"text": message.text[:300], "kind": "console", "source": public_url(where.get("url", "")) + line})

        def on_exception(exc) -> None:
            console.append({"text": str(exc)[:300], "kind": "exception", "source": ""})

        def on_request_failed(request) -> None:
            if not reachable(request.url, allowed):  # a redirect that the route never saw: the browser's dead-end proxy
                block(request.url)  # stopped it
            else:
                failed.append({"url": public_url(request.url), "method": request.method, "type": request.resource_type,
                               "failure": (request.failure or "failed")[:120]})

        def on_response(response) -> None:
            if response.status >= 400:
                failed.append({"url": public_url(response.url), "method": response.request.method,
                               "type": response.request.resource_type, "status": response.status})

        page.on("console", on_console)
        page.on("pageerror", on_exception)
        page.on("requestfailed", on_request_failed)
        page.on("response", on_response)
        try:
            response = await page.goto(target.url, wait_until="load", timeout=NAV_TIMEOUT_MS)
            out["http_status"] = response.status if response else None
            with contextlib.suppress(Exception):  # a page that never goes quiet is measured as it is
                await page.wait_for_load_state("networkidle", timeout=2000)  # late requests and errors, best effort
            data = await page.evaluate(CHECKS, {"minTap": MIN_TAP, "minFont": MIN_FONT, "limit": LIST_LIMIT})
        except Exception as exc:  # noqa: BLE001 - refused connection, timeout, blocked redirect, closed page
            with contextlib.suppress(Exception):
                await page.wait_for_timeout(150)  # a refused redirect is reported just after the navigation fails
            out["reasons"] = ["navigation"]
            out["reason"] = (f"the page leads to {urlsplit(blocked[0]['url']).netloc}, which is not allowed for this run"
                             if blocked else (str(exc).splitlines() or ["the page could not be opened"])[0][:200])
            out["blocked_requests"] = category(blocked)
            return out
        out["title"] = data["title"]
        out["layout"] = {"viewport_width": data["viewport"]["width"], "viewport_height": data["viewport"]["height"],
                         "document_width": data["document"]["width"], "document_height": data["document"]["height"],
                         "viewport_meta": data["viewport_meta"], "touch_points": data["touch_points"],
                         "scale": data["viewport"]["scale"]}
        out["overflow"] = {**data["overflow"], "px": data["overflow"]["px"] if data["overflow"]["px"] > 1 else 0}
        for key in ("tap_targets", "small_text"):
            out[key] = data[key]
        out["console_errors"], out["failed_requests"] = category(console, len(console)), category(failed, len(failed))
        out["blocked_requests"] = category(blocked)
        if profile.mobile and not data["viewport_meta"]:
            out["notes"].append("no_viewport_meta")
        out["screenshot"] = await screenshot(page, data, out["notes"])
        out["reasons"] = [r for r in REASONS if (out[r]["px"] if r == "overflow" else out[r]["total"])]
        out["status"] = "fail" if out["reasons"] else "pass"
        out["reason"] = describe(out)
        return out
    finally:
        out["seconds"] = round(time.monotonic() - started, 2)
        await context.close()


async def screenshot(page, data: dict[str, Any], notes: list[str]) -> str:
    """The whole page as a PNG data URL at CSS-pixel size, cut at a sane size; "" (with a note) when it fails."""
    try:
        width = max(data["viewport"]["width"], min(data["document"]["width"], MAX_SHOT_WIDTH))
        height = max(1, min(data["document"]["height"], MAX_SHOT_HEIGHT))
        png = await page.screenshot(type="png", full_page=True, scale="css", animations="disabled",
                                    clip={"x": 0, "y": 0, "width": width, "height": height})
    except Exception:  # noqa: BLE001 - the findings stand without the picture
        notes.append("screenshot_failed")
        return ""
    if len(png) > MAX_SHOT_BYTES:
        notes.append("screenshot_too_large")
        return ""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


# ---------------------------------------------------------------------------------------------------- Android (adb)
@dataclass
class AndroidRequest:
    """The user approved using adb: screenshot this device (the first usable one when `serial` is empty), and open
    the URL on it first unless `open_url` is false."""

    serial: str = ""
    open_url: bool = True
    wait_s: float = 3.0


def adb_path() -> str | None:
    return shutil.which("adb")


async def run_adb(adb: str, args: list[str], timeout_s: float = ADB_TIMEOUT_S) -> tuple[int, bytes]:
    """Run adb with a list of arguments (never a shell); returns its exit code and standard output."""
    proc = await asyncio.create_subprocess_exec(adb, *args, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except BaseException:  # a timeout or a stopped request: the program stops with it
        if proc.returncode is None:
            with contextlib.suppress(OSError):
                proc.kill()
        await proc.wait()
        raise
    if len(out) > MAX_ADB_BYTES:
        raise DeviceLabError("device_lab_android", "adb returned too much data")
    return proc.returncode or 0, out


SERIAL = re.compile(r"[A-Za-z0-9._:][A-Za-z0-9._:\-]{0,79}")  # never starts with "-": it cannot pass for an option


def parse_devices(text: str) -> list[dict[str, Any]]:
    """The rows of `adb devices -l`: serial, state (device, offline, unauthorized…), model and kind. Only a device
    in state `device` can be used."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or line.startswith(("*", "List of")) or not SERIAL.fullmatch(parts[0]):
            continue
        extra = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        rows.append({"serial": parts[0], "state": parts[1], "model": extra.get("model", "")[:60],
                     "kind": "emulator" if parts[0].startswith("emulator-") else "device", "usable": parts[1] == "device"})
    return rows


async def list_android() -> dict[str, Any]:
    """{found, devices, error}: whether adb is on the PATH and what `adb devices -l` lists. Starts no emulator."""
    adb = adb_path()
    if not adb:
        return {"found": False, "devices": [], "error": ""}
    try:
        code, out = await run_adb(adb, ["devices", "-l"], 10)
    except (OSError, TimeoutError, DeviceLabError):
        return {"found": True, "devices": [], "error": "adb_failed"}
    return {"found": True, "devices": parse_devices(out.decode("utf-8", errors="replace")) if code == 0 else [],
            "error": "" if code == 0 else "adb_failed"}


async def android_shot(request: AndroidRequest, target: Target) -> dict[str, Any]:
    """Open the URL on the device (reversing its port to this computer for a local address) and screenshot it. Each
    step is listed with whether it worked, so a partial result says what it is."""
    out: dict[str, Any] = {"status": "error", "serial": "", "model": "", "kind": "", "opened": False, "steps": [],
                           "screenshot": "", "error": ""}
    adb = adb_path()
    if not adb:
        out.update(status="no_adb")
        return out
    listing = await list_android()
    usable = [d for d in listing["devices"] if d["usable"]]
    device = next((d for d in usable if not request.serial or d["serial"] == request.serial), None)
    if device is None:
        out.update(status="no_device", error="" if listing["found"] and not listing["error"] else listing["error"])
        return out
    serial = device["serial"]
    out.update(serial=serial, model=device["model"], kind=device["kind"])
    port = target.port or (443 if target.scheme == "https" else 80)
    reverse = request.open_url and is_loopback(target.host)

    async def step(name: str, args: list[str]) -> bytes | None:
        try:
            code, data = await run_adb(adb, ["-s", serial, *args])
        except (OSError, TimeoutError, DeviceLabError):
            code, data = 1, b""
        out["steps"].append({"step": name, "ok": code == 0})
        return data if code == 0 else None

    try:
        if request.open_url:
            if reverse:
                await step("reverse", ["reverse", f"tcp:{port}", f"tcp:{port}"])
            # adb joins these words into one line for the device's shell, so the address is quoted for it
            out["opened"] = await step("open", ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
                                                shlex.quote(target.url)]) is not None
            await asyncio.sleep(max(0.0, min(request.wait_s, 30.0)))
        png = await step("screenshot", ["exec-out", "screencap", "-p"])
        if png is None or not png.startswith(PNG_SIGNATURE):
            out["error"] = "no_screenshot"
        else:
            out.update(status="ok", screenshot="data:image/png;base64," + base64.b64encode(png).decode("ascii"))
    finally:
        if reverse:
            await step("unreverse", ["reverse", "--remove", f"tcp:{port}"])
    return out


# ---------------------------------------------------------------------------------------------------- the run
def playwright_missing() -> bool:
    return find_spec("playwright") is None


async def run_device_lab(url: Any, *, profiles: Any = None, custom: Any = None, allow_hosts: Any = (),
                         android: AndroidRequest | None = None) -> dict[str, Any]:
    """Check `url` in every chosen profile and return the report (a dict ready for JSON). Raises DeviceLabError for a
    refused address or invalid profiles, or when no browser can be started."""
    allow = parse_allow_hosts(allow_hosts)
    target = check_target(url, allow)
    chosen = pick_profiles(profiles, custom)
    if playwright_missing():
        raise DeviceLabError("device_lab_browser", "Device Lab needs Playwright: pip install 'spike-ai[motion]', then "
                             "python -m playwright install chromium (or set SPIKE_CHROMIUM to a Chrome/Chromium)")
    from playwright.async_api import async_playwright

    from spike.motion.render import launch

    allowed = frozenset({target.host, *allow})
    started, clock = datetime.now(UTC), time.monotonic()
    results: list[dict[str, Any]] = []
    # The browser's only proxy is a port nobody listens on (held by this socket), with this computer and the named
    # hosts bypassing it: whatever else a page, a script or a redirect asks for fails in the network layer. Playwright's
    # routes do not see redirect hops, so this is what keeps a redirect from taking the browser to another machine.
    dead_end = socket.socket()
    try:
        dead_end.bind(("127.0.0.1", 0))
        flags = (f"--proxy-server=http://127.0.0.1:{dead_end.getsockname()[1]}",
                 f"--proxy-bypass-list={bypass_rules(allowed)}")
        async with async_playwright() as pw:
            try:
                browser = await launch(pw, flags)
            except Exception as exc:  # noqa: BLE001 - no Chromium found (MotionError), or SPIKE_CHROMIUM points nowhere
                raise DeviceLabError("device_lab_browser", str(exc).splitlines()[0][:300] if str(exc) else
                                     "the browser could not be started") from exc
            try:
                version = browser.version
                for profile in chosen:
                    left = max(1.0, TOTAL_TIMEOUT_S - (time.monotonic() - clock))
                    try:
                        results.append(await asyncio.wait_for(check_profile(browser, profile, target, allowed),
                                                              min(PROFILE_TIMEOUT_S, left)))
                    except TimeoutError:
                        results.append({**blank(profile), "reasons": ["timeout"], "reason": "the profile took too long"})
            finally:
                await browser.close()
    finally:
        dead_end.close()
    report: dict[str, Any] = {
        "kind": "device_lab", "version": 1, "url": target.shown, "started": started.isoformat(timespec="seconds"),
        "seconds": round(time.monotonic() - clock, 2), "browser": f"Chromium {version}", "emulated": True,
        "allow_hosts": list(allow), "limits": {"min_tap": MIN_TAP, "min_font": MIN_FONT},
        "summary": {"profiles": len(results), **{k: sum(r["status"] == k for r in results)
                                                 for k in ("pass", "fail", "error")}},
        "profiles": results, "android": None}
    if android is not None:
        report["android"] = await android_shot(android, target)
    return report


def for_model(report: dict[str, Any], keep: int = 5) -> str:
    """The report as compact JSON for the model: no pictures, and at most `keep` items per category."""
    def trim(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: [trim(i) for i in v[:keep]] if k == "items" else trim(v) for k, v in value.items() if k != "screenshot"}
        if isinstance(value, list):
            return [trim(v) for v in value]
        return value

    return json.dumps(trim(report), ensure_ascii=True, separators=(",", ":"))


# ---------------------------------------------------------------------------------------------------- the tool
@dataclass
class DeviceLabArgs:
    url: str
    profiles: Any = None
    custom: Any = None
    allow_hosts: Any = ()
    android: AndroidRequest | None = None
    problem: DeviceLabError | None = field(default=None, repr=False)


def read_args(args: dict[str, Any]) -> DeviceLabArgs:
    """The arguments of a call, checked: the first problem is kept in `.problem` instead of raised."""
    parsed = DeviceLabArgs(url=str(args.get("url") or ""), profiles=args.get("profiles"), custom=args.get("custom_profiles"),
                           allow_hosts=args.get("allow_hosts") or ())
    try:
        check_target(parsed.url, parsed.allow_hosts)
        pick_profiles(parsed.profiles, parsed.custom)
        if args.get("android"):
            serial = args.get("android_serial") or ""
            if not isinstance(serial, str) or (serial and not SERIAL.fullmatch(serial)):
                raise DeviceLabError("device_lab_android", "android_serial is not a valid device serial")
            parsed.android = AndroidRequest(serial=serial, open_url=args.get("android_open") is not False)
    except DeviceLabError as exc:
        parsed.problem = exc
    return parsed


class DeviceLab(Tool):
    name = "device_lab"
    description = ("On the user's request, open a web app that runs on this computer (a localhost, 127.0.0.1 or [::1] "
                   "address, or the project's own preview server) in several device profiles in a headless browser and "
                   "report, per profile: a screenshot, console errors, failed requests, horizontal overflow and the "
                   "elements that cause it, tap targets under 24x24 CSS px and text under 12 px, with a pass or fail "
                   "and the reason. Profiles: small-phone, large-phone, tablet-portrait, tablet-landscape, laptop, "
                   "desktop (all by default); `custom_profiles` adds the user's own {name, width, height, scale, touch}. "
                   "It EMULATES screens in a desktop browser engine: it is not a test on a real device. Another host "
                   "is refused unless the user named it in `allow_hosts` for this run. With `android` true and adb "
                   "already installed and a device or emulator connected, it also opens the page on that device and "
                   "takes its screenshot. Never installs a browser, adb, an SDK or an emulator.")
    parameters = {"type": "object", "properties": {
        "url": {"type": "string", "description": "the app's address, e.g. http://localhost:5173/"},
        "profiles": {"type": "array", "items": {"type": "string", "enum": list(BUILTIN)},
                     "description": "built-in profiles to check; default all"},
        "custom_profiles": {"type": "array", "maxItems": MAX_CUSTOM, "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"},
            "scale": {"type": "number"}, "touch": {"type": "boolean"}, "mobile": {"type": "boolean"},
            "user_agent": {"type": "string"}}, "required": ["name", "width", "height"]}},
        "allow_hosts": {"type": "array", "items": {"type": "string"},
                        "description": "host names the user explicitly allowed for this run (not on this computer)"},
        "android": {"type": "boolean", "description": "also use adb for a connected Android device or emulator"},
        "android_serial": {"type": "string", "description": "which device, when several are connected"},
        "android_open": {"type": "boolean", "description": "open the url on the device first (default true)"}},
        "required": ["url"]}
    risk = "execute"
    default_policy = "ask"
    job_queue = None  # set to the app's JobQueue: a run then waits its turn like a render

    def __init__(self, queue=None):
        self.job_queue = queue

    def review(self, args: dict[str, Any]) -> Review:
        parsed = read_args(args)
        if parsed.problem:
            return Review("deny", parsed.problem.message, code=parsed.problem.code)
        if playwright_missing():
            return Review("deny", "Device Lab needs Playwright (pip install 'spike-ai[motion]') and a Chromium. / "
                          "Device Lab necesita Playwright y un Chromium.", code="device_lab_browser")
        if parsed.android:
            return Review("ask", "It will open this page in a headless browser on your computer and use adb to open "
                          "it on your Android device and take its screenshot.", once=True, code="device_lab_android")
        if not is_loopback(check_target(parsed.url, parsed.allow_hosts).host):
            return Review("ask", "It will open a page that is not on this computer, on a host you allowed, in a "
                          "headless browser.", once=True, code="device_lab_host")
        return Review("ask", "It will open this local page in a headless browser on your computer and take "
                      "screenshots in several device sizes.", once=True, code="device_lab")

    async def run(self, args: dict[str, Any]) -> ToolResult:
        parsed = read_args(args)
        if parsed.problem:
            return ToolResult(ok=False, content=f"error: {parsed.problem.message}")

        async def work() -> dict[str, Any]:
            return await run_device_lab(parsed.url, profiles=parsed.profiles, custom=parsed.custom,
                                        allow_hosts=parsed.allow_hosts, android=parsed.android)

        try:
            report = await self.job_queue.execute("render", work) if self.job_queue is not None else await work()
        except DeviceLabError as exc:
            return ToolResult(ok=False, content=f"error: {exc.message}")
        content = for_model(report)
        return ToolResult(ok=True, content=content, private=[content], data={"ui": report})
