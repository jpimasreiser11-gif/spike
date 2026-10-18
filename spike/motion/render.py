"""Render an animated HTML scene to a video. The scene runs in a headless Chromium with no network (every request
but the scene itself is refused, and a CSP allows only inline code and data: URLs) on a virtual clock: before each
frame SPIKE moves time forward by exactly 1/fps, runs the timers and animation-frame callbacks that fall due, and
seeks every CSS/Web animation and SVG animation to that time. So the same scene gives the same frames on every run,
however slow the computer is. The frames are piped to ffmpeg as PNG."""

from __future__ import annotations

import asyncio
import functools
import os
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MAX_SECONDS = 60
MAX_FPS = 60
MIN_FPS = 1
GIF_FPS = 15  # a GIF at more frames per second only grows
DEFAULT_SECONDS = 5
MAX_SIDE = 1920
MAX_SCENE = 5 * 1024 * 1024  # images and fonts go inline as data: URLs
TIMEOUT_S = 600
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080), "4:5": (1080, 1350), "1080p": (1920, 1080)}
FORMATS = (".mp4", ".webm", ".gif")
ORIGIN = "http://scene.invalid/"  # .invalid never resolves; the route below serves the scene at this address
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; "
       "font-src data:; media-src data: blob:; form-action 'none'; base-uri 'none'")

# The virtual clock, installed before the scene's own scripts. performance.now, Date, timers and
# requestAnimationFrame follow it; Math.random is seeded. __spikeSeek(ms) is called once per frame.
CLOCK = r"""
(() => {
  let now = 0, nextId = 1, seed = 0x5eed;
  const frames = new Map(), timers = new Map(), starts = new WeakMap(), authorPaused = new WeakSet();
  const EPOCH = 1767225600000; // 2026-01-01T00:00:00Z, so Date.now() is the same on every render
  const RealDate = Date;
  class SceneDate extends RealDate {
    constructor(...args) { if (args.length) super(...args); else super(EPOCH + now); }
    static now() { return EPOCH + now; }
  }
  window.Date = SceneDate;
  performance.now = () => now;
  Math.random = () => { // mulberry32
    seed = (seed + 0x6d2b79f5) | 0;
    let x = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
  window.requestAnimationFrame = (cb) => { const id = nextId++; frames.set(id, cb); return id; };
  window.cancelAnimationFrame = (id) => { frames.delete(id); };
  const later = (repeat) => (cb, ms, ...args) => {
    const id = nextId++, wait = Math.max(0, Number(ms) || 0);
    timers.set(id, { at: now + wait, cb, args, every: repeat ? Math.max(1, wait) : 0 });
    return id;
  };
  window.setTimeout = later(false);
  window.setInterval = later(true);
  window.clearTimeout = window.clearInterval = (id) => { timers.delete(id); };
  const call = (fn, ...args) => {
    try { if (typeof fn === "function") fn(...args); } catch (e) {
      const where = String((e && e.stack) || "").split("\n").find((line) => line.includes("scene.invalid"));
      console.error(String(e && e.name ? `${e.name}: ${e.message}` : e) + (where ? ` (${where.trim()})` : ""));
    }
  };
  const mark = () => { // animations started by a script start at the virtual time that script ran
    for (const a of document.getAnimations()) {
      if (starts.has(a)) continue;
      starts.set(a, now);
      if (a.playState === "paused") authorPaused.add(a);
    }
  };
  window.__spikeSeek = (t) => {
    for (let guard = 0; guard < 100000; guard++) {
      let due = null;
      for (const entry of timers) if (entry[1].at <= t && (!due || entry[1].at < due[1].at)) due = entry;
      if (!due) break;
      const [id, x] = due;
      now = x.at;
      if (x.every) x.at += x.every; else timers.delete(id);
      call(x.cb, ...x.args);
      mark();
    }
    now = t;
    mark();
    const queued = [...frames.values()];
    frames.clear();
    for (const cb of queued) { call(cb, t); mark(); }
    for (const a of document.getAnimations()) {
      if (authorPaused.has(a)) continue;
      a.pause();
      a.currentTime = Math.max(0, t - starts.get(a)) * (a.playbackRate || 1);
    }
    for (const svg of document.querySelectorAll("svg")) {
      if (svg.ownerSVGElement || typeof svg.setCurrentTime !== "function") continue;
      svg.pauseAnimations();
      svg.setCurrentTime(t / 1000);
    }
  };
  window.__spikeDuration = () => {
    const meta = document.querySelector('meta[name="spike-duration"]');
    if (meta && Number(meta.content) > 0) return { seconds: Number(meta.content), source: "meta" };
    let end = 0, forever = false;
    for (const a of document.getAnimations()) {
      const e = a.effect ? a.effect.getComputedTiming().endTime : 0;
      if (e === Infinity) forever = true; else if (e > end) end = e;
    }
    return end > 0 ? { seconds: end / 1000, source: "animations" } : { seconds: null, source: forever ? "forever" : "none" };
  };
})();
"""


class MotionError(Exception):
    pass


@dataclass
class Rendered:
    path: str
    format: str
    codec: str
    width: int
    height: int
    fps: int
    seconds: float
    frames: int
    bytes: int = 0
    duration_from: str = ""  # "argument", "meta", "animations" or "default"
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # the scene's JavaScript errors
    blocked: list[str] = field(default_factory=list)  # addresses the scene tried to load

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_size(size: str | None) -> tuple[int, int]:
    text = (size or "16:9").strip().lower()
    if text in SIZES:
        return SIZES[text]
    m = re.fullmatch(r"(\d{2,4})\s*[x×]\s*(\d{2,4})", text)
    if not m:
        raise MotionError(f"size must be one of {', '.join(SIZES)} or WIDTHxHEIGHT, not {size!r}")
    w, h = int(m[1]), int(m[2])
    if not (16 <= w <= MAX_SIDE and 16 <= h <= MAX_SIDE) or w % 2 or h % 2:
        raise MotionError(f"width and height must be even numbers from 16 to {MAX_SIDE}")
    return w, h


def ffmpeg() -> str:
    found = os.environ.get("SPIKE_FFMPEG") or shutil.which("ffmpeg")
    if not found or not Path(found).is_file():
        raise MotionError("ffmpeg is not installed. Install it (macOS: brew install ffmpeg; Debian/Ubuntu: "
                          "sudo apt install ffmpeg; Windows: winget install ffmpeg) or set SPIKE_FFMPEG to its path")
    return found


@functools.lru_cache(maxsize=4)
def encoders(binary: str) -> frozenset[str]:
    out = subprocess.run([binary, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
    return frozenset(m[1] for m in re.finditer(r"^\s*V\S*\s+(\S+)", out, re.M))


def encoder_args(fmt: str, fps: int, have: frozenset[str]) -> tuple[str, list[str]]:
    if fmt == ".mp4":
        if "libx264" in have:
            return "h264", ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart"]
        if "libopenh264" in have:
            return "h264", ["-c:v", "libopenh264", "-b:v", "4M", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        return "mpeg4", ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if fmt == ".webm":
        if "libvpx-vp9" in have:
            return "vp9", ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-deadline", "good", "-cpu-used", "4",
                           "-row-mt", "1", "-pix_fmt", "yuv420p"]
        if "libvpx" in have:
            return "vp8", ["-c:v", "libvpx", "-crf", "10", "-b:v", "2M", "-pix_fmt", "yuv420p"]
        raise MotionError("this ffmpeg cannot write WebM (no libvpx): use .mp4")
    return "gif", ["-vf", "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                   "-loop", "0"]


def scene_html(text: str, suffix: str) -> str:
    """An .svg scene is shown on a blank page; an .html scene as it is."""
    if len(text.encode()) > MAX_SCENE:
        raise MotionError(f"the scene is larger than {MAX_SCENE // (1024 * 1024)} MB")
    if suffix == ".svg":
        return f'<!doctype html><html><body style="margin:0;overflow:hidden">{text}</body></html>'
    return text


async def launch(pw):
    """SPIKE_CHROMIUM, else Playwright's Chromium, else an installed Chrome or Edge."""
    root = hasattr(os, "geteuid") and os.geteuid() == 0  # Chromium's sandbox refuses to start as root
    options = {"chromium_sandbox": not root, "args": ["--disable-gpu", "--mute-audio"]}
    if os.environ.get("SPIKE_CHROMIUM"):
        return await pw.chromium.launch(executable_path=os.environ["SPIKE_CHROMIUM"], **options)
    first: Exception | None = None
    for channel in (None, "chrome", "msedge"):
        try:
            return await pw.chromium.launch(channel=channel, **options)
        except Exception as exc:  # noqa: BLE001 - the next browser may be there
            first = first or exc
    raise MotionError("no Chromium to play the scene: run `spike render --install-browser`, install Google Chrome, "
                      f"or set SPIKE_CHROMIUM ({str(first).splitlines()[0][:200] if first else ''})")


async def capture(html: str, width: int, height: int, fps: int, seconds: float | None,
                  on_frame: Callable[[bytes], Awaitable[None]], result: Rendered) -> None:
    """Play the scene frame by frame and hand each PNG to `on_frame`; fills in the result's timing and problems."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise MotionError("rendering needs Playwright: pip install 'spike-ai[motion]', then "
                          "python -m playwright install chromium (or set SPIKE_CHROMIUM to a Chrome/Chromium)") from exc

    async def serve(route) -> None:
        if route.request.url == ORIGIN:
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html,
                                headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store"})
        else:
            if len(result.blocked) < 10 and route.request.url not in result.blocked:
                result.blocked.append(route.request.url[:200])
            await route.abort()

    def console(message) -> None:
        if message.type != "error" or message.text.startswith("Failed to load resource"):
            return
        refused = re.match(r"Refused to [^']*'([^']+)'", message.text)  # the CSP stopped a load
        if refused:
            if len(result.blocked) < 10 and refused[1] not in result.blocked:
                result.blocked.append(refused[1][:200])
        elif "Content Security Policy" not in message.text and len(result.errors) < 10:
            result.errors.append(message.text[:500])

    async with async_playwright() as pw:
        browser = await launch(pw)
        try:
            context = await browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                                service_workers="block", accept_downloads=False, locale="es-ES",
                                                timezone_id="UTC")
            await context.route("**/*", serve)
            await context.add_init_script(CLOCK)
            page = await context.new_page()
            context.on("page", lambda popup: asyncio.ensure_future(popup.close()))
            page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.dismiss()))
            page.on("pageerror", lambda exc: len(result.errors) < 10 and result.errors.append(str(exc)[:500]))
            page.on("console", console)
            await page.goto(ORIGIN, wait_until="load", timeout=30_000)
            await page.evaluate("document.fonts.ready.then(() => true)")
            if seconds is None:
                found = await page.evaluate("__spikeDuration()")
                if found["seconds"]:
                    seconds, result.duration_from = float(found["seconds"]), found["source"]
                    if found["source"] == "meta" and seconds > MAX_SECONDS:
                        raise MotionError(f"the scene asks for {seconds:g} s; videos are at most {MAX_SECONDS} s")
                    if seconds > MAX_SECONDS:
                        result.notes.append(f"the animations last {seconds:g} s: cut at {MAX_SECONDS} s")
                        seconds = MAX_SECONDS
                else:
                    seconds, result.duration_from = DEFAULT_SECONDS, "default"
                    result.notes.append(("the scene loops forever" if found["source"] == "forever" else
                                         "the scene has no timed animations")
                                        + f": rendered {DEFAULT_SECONDS} s; give `seconds` or "
                                          '<meta name="spike-duration" content="…"> to choose')
            else:
                result.duration_from = "argument"
            frames = max(1, round(seconds * fps))
            result.seconds, result.frames = round(frames / fps, 3), frames
            for i in range(frames):
                await page.evaluate("t => __spikeSeek(t)", i * 1000 / fps)
                await on_frame(await page.screenshot(type="png"))
        finally:
            await browser.close()


async def render(html: str, out: Path, *, size: str | None = None, fps: int = 30, seconds: float | None = None,
                 timeout_s: float | None = None) -> Rendered:
    fmt = out.suffix.lower()
    if fmt not in FORMATS:
        raise MotionError(f"the video must be {', '.join(FORMATS)}, not {out.name}")
    width, height = parse_size(size)
    if not isinstance(fps, int) or not MIN_FPS <= fps <= MAX_FPS:
        raise MotionError(f"fps must be a whole number from {MIN_FPS} to {MAX_FPS}")
    if seconds is not None and not 0 < seconds <= MAX_SECONDS:
        raise MotionError(f"seconds must be more than 0 and at most {MAX_SECONDS}")
    binary = ffmpeg()
    result = Rendered(path=str(out), format=fmt[1:], codec="", width=width, height=height, fps=fps, seconds=0, frames=0)
    if fmt == ".gif" and fps > GIF_FPS:
        result.fps = fps = GIF_FPS
        result.notes.append(f"GIF at {GIF_FPS} fps")
    result.codec, args = encoder_args(fmt, fps, encoders(binary))
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f".{out.stem}.rendering{fmt}")
    proc = await asyncio.create_subprocess_exec(
        binary, "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png",
        "-i", "-", *args, "-r", str(fps), str(partial),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    assert proc.stdin is not None and proc.stderr is not None

    async def write(png: bytes) -> None:
        proc.stdin.write(png)
        await proc.stdin.drain()

    try:
        await asyncio.wait_for(capture(html, width, height, fps, seconds, write, result), timeout_s or TIMEOUT_S)
        proc.stdin.close()
        error = (await proc.stderr.read()).decode(errors="replace").strip()
        if await proc.wait() != 0:
            raise MotionError(f"ffmpeg failed: {error[-500:]}")
        os.replace(partial, out)
    except TimeoutError as exc:
        raise MotionError(f"rendering took longer than {timeout_s or TIMEOUT_S:g} s") from exc
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise MotionError("ffmpeg stopped while receiving frames") from exc
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        partial.unlink(missing_ok=True)
    result.bytes = out.stat().st_size
    return result
