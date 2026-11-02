"""Reverse Studio's headless browser: it reads the structure of a page on this computer and renders the generated page
to measure how close it is to the reference. It is the same Chromium the other features use (`SPIKE_CHROMIUM`, else
Playwright's own, else an installed Chrome or Edge; see `spike.motion.render.launch`), started only for one request
and closed after it. Pages are loaded with every address but their own refused; the page SPIKE generated is
rendered with JavaScript off and no network at all."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from spike.design.reverse import CAPTURE_JS, ReverseError, similarity

ORIGIN = "http://project.invalid/"  # .invalid never resolves; a page of the project is served here, from its folder
TIMEOUT_MS = 30_000
MAX_FILE = 20 * 1024 * 1024
QUIET = ("--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run")  # no chatter

# Both images, decoded by the browser (so PNG, JPEG and WebP all work), drawn at the reference's size on white, kept
# in the page as base64 RGB (by the browser's own encoder) and fetched in blocks: one huge string is slow to return.
DECODE_JS = """
async ([reference, render, w, h]) => {
  const load = url => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => no(new Error('decode')); i.src = url; });
  const rgb = img => {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const x = c.getContext('2d', {willReadFrequently: true});
    x.fillStyle = '#fff'; x.fillRect(0, 0, w, h); x.drawImage(img, 0, 0, w, h);
    const d = x.getImageData(0, 0, w, h).data, out = new Uint8Array(w * h * 3);
    for (let i = 0, j = 0; i < d.length; i += 4, j += 3) { out[j] = d[i]; out[j + 1] = d[i + 1]; out[j + 2] = d[i + 2]; }
    return new Promise(ok => { const f = new FileReader(); f.onload = () => ok(f.result.split(',')[1]); f.readAsDataURL(new Blob([out])); });
  };
  window.__spikePixels = [await rgb(await load(reference)), await rgb(await load(render))];
  return window.__spikePixels.map(s => s.length);
}
"""
BLOCK = 2 * 1024 * 1024  # characters per fetch; a multiple of 4, so every block is valid base64 on its own


async def _pixels(page, which: int, length: int) -> bytes:
    parts = [await page.evaluate("([k, i, n]) => window.__spikePixels[k].slice(i, i + n)", [which, i, BLOCK])
             for i in range(0, length, BLOCK)]
    return base64.b64decode("".join(parts))


async def _launch(pw):
    from spike.motion.render import MotionError, launch

    try:
        return await launch(pw, QUIET)
    except MotionError as exc:
        raise ReverseError("reverse_browser_missing") from exc


def _playwright():
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ReverseError("reverse_browser_missing") from exc
    return async_playwright()


def available() -> bool:
    """Whether Playwright for Python is installed. Whether a browser can start is only known when one is started."""
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc.lower()


async def capture_page(*, url: str | None = None, folder: Path | None = None, path: str | None = None,
                       width: int = 1280, height: int = 800, timeout_s: float = 60) -> dict[str, Any]:
    """The capture (`CAPTURE_JS`) and a PNG screenshot of the page at `width`x`height`. The page is `url` (only its
    own origin may be reached) or `path` inside `folder` (served from there; nothing outside it can be read)."""
    base = ORIGIN + quote(path or "") if folder is not None else url
    assert base is not None
    allowed = _origin(base)
    root = folder.resolve() if folder is not None else None

    async def serve(route) -> None:
        request_url = route.request.url
        if request_url.startswith("data:") or request_url.startswith("blob:"):
            await route.continue_()
        elif root is not None and request_url.startswith(ORIGIN):
            target = (root / unquote(urlsplit(request_url).path.lstrip("/"))).resolve()
            if root not in target.parents or not target.is_file() or target.stat().st_size > MAX_FILE:
                await route.fulfill(status=404, body="")
                return
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            await route.fulfill(status=200, body=target.read_bytes(), content_type=kind,
                                headers={"Cache-Control": "no-store"})
        elif root is None and _origin(request_url) == allowed:
            await route.continue_()
        else:
            await route.abort()

    async def run() -> dict[str, Any]:
        async with _playwright() as pw:
            browser = await _launch(pw)
            try:
                context = await browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                                    service_workers="block", accept_downloads=False)
                await context.route("**/*", serve)
                page = await context.new_page()
                context.on("page", lambda popup: asyncio.ensure_future(popup.close()))
                page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.dismiss()))
                try:
                    response = await page.goto(base, wait_until="load", timeout=TIMEOUT_MS)
                except Exception as exc:  # noqa: BLE001 - a refused connection, a timeout, a bad certificate
                    raise ReverseError("reverse_capture_failed") from exc
                if response is None or response.status >= 400:
                    raise ReverseError("reverse_capture_failed")
                with contextlib.suppress(Exception):  # a page that never goes idle (polling) is captured as it is
                    await page.wait_for_load_state("networkidle", timeout=3000)
                await page.evaluate("document.fonts.ready.then(() => true)")
                captured = await page.evaluate(CAPTURE_JS, {"maxNodes": 500})
                captured["png"] = await page.screenshot(type="png", animations="disabled")
                return captured
            finally:
                await browser.close()

    try:
        return await asyncio.wait_for(run(), timeout_s)
    except TimeoutError as exc:
        raise ReverseError("reverse_capture_failed") from exc


async def measure(html: str, reference: str, width: int, height: int, timeout_s: float = 60) -> dict[str, Any]:
    """Render `html` at `width`x`height` (JavaScript off, no network) and compare the screenshot with `reference`, a
    data URL of the image it was made from. The score is `similarity`: measured on this render, nothing more."""

    async def run() -> dict[str, Any]:
        async with _playwright() as pw:
            browser = await _launch(pw)
            try:
                shot_context = await browser.new_context(viewport={"width": width, "height": height},
                                                         device_scale_factor=1, java_script_enabled=False,
                                                         service_workers="block", accept_downloads=False)
                await shot_context.route("**/*", lambda route: route.abort())
                page = await shot_context.new_page()
                await page.set_content(html, wait_until="load", timeout=TIMEOUT_MS)
                png = await page.screenshot(type="png", animations="disabled")
                decoder = await (await browser.new_context(service_workers="block")).new_page()
                try:
                    sizes = await decoder.evaluate(DECODE_JS, [reference, "data:image/png;base64," +
                                                               base64.b64encode(png).decode("ascii"), width, height])
                except Exception as exc:  # noqa: BLE001 - an image the browser cannot decode
                    raise ReverseError("image_invalid") from exc
                a, b = await _pixels(decoder, 0, sizes[0]), await _pixels(decoder, 1, sizes[1])
                return {"score": similarity(a, b, width, height),
                        "metric": "1 - mean absolute RGB difference / 255", "width": width, "height": height}
            finally:
                await browser.close()

    try:
        return await asyncio.wait_for(run(), timeout_s)
    except TimeoutError as exc:
        raise ReverseError("reverse_failed") from exc
