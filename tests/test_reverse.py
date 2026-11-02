"""Reverse Studio (A20), the parts with no server: which references are accepted, the description a model rebuilds
from, the clean-up of its answer, the score, and (when a Chromium exists) the real capture and render."""

import base64
import http.server
import os
import struct
import threading
import zlib
from pathlib import Path

import pytest

from spike.design import reverse, reverse_browser
from spike.design.reverse import ReverseError

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme Cloud | Home</title>
<meta property="og:site_name" content="Acme Cloud">
<style>
body{margin:0;font:16px/1.5 "Acme Sans", Georgia, serif;background:#f4f1ea;color:#222}
header{display:flex;align-items:center;justify-content:space-between;padding:12px 24px;background:#1f3a5f;color:#fff}
.acme-logo{width:120px;height:32px;background:url(/acme-logo.png) no-repeat}
nav a{color:#fff;margin-left:16px;text-decoration:none}
main{padding:24px;max-width:900px}
h1{font-size:32px;margin:0 0 12px}
.card{border:1px solid #d9d2c3;border-radius:8px;padding:16px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:24px}
button{background:#c2410c;color:#fff;border:0;border-radius:6px;padding:10px 18px;font-size:16px}
footer{padding:16px 24px;color:#666;font-size:13px}
</style></head><body>
<header><img class="acme-logo" src="/acme-logo.png" alt="Acme Cloud logo" width="120" height="32"><nav>
<a href="/pricing">Pricing</a><a href="/docs">Docs</a><a href="https://acme.example/login">Log in</a></nav></header>
<main><h1>Acme Cloud keeps your files safe</h1><p>Acme Cloud is trusted by teams everywhere to store documents.</p>
<svg class="acme-mark" width="40" height="40"><circle cx="20" cy="20" r="18" fill="#c2410c"/></svg>
<button>Start free with Acme</button>
<div class="cards"><div class="card"><h2>Secure</h2><p>Encrypted at rest.</p></div>
<div class="card"><h2>Fast</h2><p>Global edge.</p></div><div class="card"><h2>Simple</h2><p>No setup.</p></div></div></main>
<footer>© 2026 Acme Cloud Inc. All rights reserved.</footer></body></html>"""

# what a model that copied the reference would answer: every kind of thing that must not survive
COPIED = """Here is the page:
```html
<!doctype html><html><head><title>Acme Cloud</title>
<link rel="stylesheet" href="https://cdn.acme.example/site.css">
<style>@import url(https://cdn.acme.example/fonts.css);
@font-face{font-family:"Acme Sans";src:url(https://cdn.acme.example/acme.woff2)}
body{margin:0;background:#f4f1ea url(https://cdn.acme.example/bg.jpg)}.acme-hero{background:url('/hero.png') center/cover}</style>
<script>fetch('https://track.acme.example/hit')</script></head>
<body onload="track()"><!-- Acme Cloud header, do not edit -->
<header class="acme-hero"><img src="https://cdn.acme.example/logo.png" alt="Acme Cloud logo" width="120" height="32">
<svg width="40" height="40"><path d="M0 0L40 40"/></svg>
<a href="https://acme.example/pricing" onclick="go()">Acme Cloud pricing</a></header>
<h1 style="background-image:url(https://cdn.acme.example/h.png)">Acme Cloud keeps your files safe</h1>
<iframe src="https://acme.example/embed"></iframe></body></html>
```
Hope it helps."""


def png_bytes(width: int, height: int, rgb: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """A valid PNG of one colour, written with the standard library."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    row = b"\x00" + bytes(rgb) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def data_url(data: bytes, kind: str = "png") -> str:
    return f"data:image/{kind};base64," + base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------- what is accepted
@pytest.mark.parametrize("url", ["http://localhost:5173/", "https://localhost/x?y=1", "http://127.0.0.1:8000",
                                 "http://[::1]:3000/app", "http://127.0.0.2/", "http://app.localhost:8080/"])
def test_pages_on_this_computer_are_accepted(url):
    assert reverse.check_url(url) == url


@pytest.mark.parametrize("url", ["https://example.com/", "http://192.168.1.20:3000/", "http://localhost.evil.test/",
                                 "http://evil.test/localhost", "file:///etc/passwd", "ftp://localhost/", "javascript:alert(1)",
                                 "http://user:secret@localhost/", "http://0.0.0.0:80/", "http://localhost:99999/", "",
                                 "localhost:3000", "http://169.254.169.254/latest", "http://10.0.0.5/"])
def test_no_other_address_is_ever_opened(url):
    with pytest.raises(ReverseError, match="reverse_url"):
        reverse.check_url(url)


@pytest.mark.parametrize("path,ok", [("index.html", True), ("site/home.htm", True), ("../index.html", False),
                                     ("/etc/passwd.html", False), ("C:/x.html", False), ("a//b.html", False),
                                     ("notes.txt", False), ("", False), ("a\\..\\b.html", False)])
def test_page_paths_stay_inside_the_folder(path, ok):
    if ok:
        assert reverse.check_page_path(path) == path
    else:
        with pytest.raises(ReverseError, match="reverse_path"):
            reverse.check_page_path(path)


def test_image_size_is_read_from_the_header_of_each_format():
    assert reverse.image_size(png_bytes(120, 80)) == (120, 80)
    jpeg = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", 90, 140) + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01")
    assert reverse.image_size(jpeg) == (140, 90)
    lossless = b"RIFF\x00\x00\x00\x00WEBPVP8L\x00\x00\x00\x00\x2f" + ((300 - 1) | ((200 - 1) << 14)).to_bytes(4, "little")
    assert reverse.image_size(lossless) == (300, 200)
    extended = (b"RIFF\x00\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x00\x00\x00\x00" + (639).to_bytes(3, "little")
                + (359).to_bytes(3, "little"))
    assert reverse.image_size(extended) == (640, 360)
    for bad in (b"", b"GIF89a....", b"\x89PNG\r\n\x1a\n" + b"\0" * 8):
        with pytest.raises(ReverseError, match="image_invalid"):
            reverse.image_size(bad)
    for size in ((10, 10), (5000, 100), (4000, 4000)):
        with pytest.raises(ReverseError, match="reverse_image_size"):
            reverse.image_size(png_bytes(*size))


def test_the_confirmation_is_recorded_with_what_it_covers():
    image = data_url(png_bytes(80, 80))
    record = reverse.authorization("image", reverse.sha256_image(image), kind="image")
    assert record["confirmed"] is True and record["statement"] == reverse.STATEMENT
    assert record["reference"] == {"kind": "image", "sha256": reverse.sha256_image(image)} and record["at"].endswith("+00:00")
    assert reverse.authorization("url", "http://localhost:3000/", kind="url")["reference"] == \
        {"kind": "url", "value": "http://localhost:3000/"}


# ---------------------------------------------------------------- placeholder text and the description
def test_lorem_text_has_about_the_length_asked_and_no_real_words():
    assert reverse.lorem(30) == "Lorem ipsum dolor sit amet"[:30] or reverse.lorem(30).startswith("Lorem ipsum dolor")
    assert 20 <= len(reverse.lorem(30)) <= 30 and len(reverse.lorem(1)) == 1 and reverse.lorem(2) == "Lo"
    assert reverse.lorem(30, 7) != reverse.lorem(30, 0) and reverse.lorem(400).count(" ") > 40


def capture() -> dict:
    def node(tag, rect, style=None, **rest):
        return {"t": tag, "r": rect, "s": style or {}, **rest}

    card = lambda x: node("div", [x, 100, 100, 80], {"border": "1px solid #ddd", "padding": "8px"},  # noqa: E731
                          n=[node("p", [x + 8, 108, 80, 20], c=18), node("img", [x + 8, 130, 80, 40], k="img")])
    return {"viewport": {"width": 800, "height": 600}, "page": "#fafafa", "truncated": False, "names": ["Acme Cloud"],
            "root": node("body", [0, 0, 800, 400], {"margin": "0", "font-family": "'Acme Sans', Georgia, serif"}, n=[
                node("header", [0, 0, 800, 60], {"display": "flex", "background-color": "#1f3a5f"}, n=[
                    node("svg", [10, 10, 40, 40], k="svg"), node("h1", [60, 10, 300, 40], c=34)]),
                card(10), card(120), card(230),
                node("div", [0, 200, 800, 40], {"background-image": "image"}),
                node("input", [10, 260, 200, 30], k="input:text", c=12)])}


def test_the_description_has_layout_and_styles_but_never_the_original_text_or_names():
    text = reverse.describe(capture())
    assert text.startswith("Viewport 800x600 px. Page background #fafafa.")
    assert "header [0,0 800x60] {display:flex; background-color:#1f3a5f}" in text
    assert "[image placeholder" in text and "[graphic placeholder" in text and "<text>" in text
    assert "x3 (repeated every +110,+0)" in text  # three similar cards fold into one line
    assert "background-image:[image placeholder]" in text
    for leaked in ("Acme", "http", "src=", "href"):
        assert leaked not in text
    assert 'font-family:"Georgia", serif' in text  # a brand font is never named, a system one is
    h1 = next(line for line in text.splitlines() if line.strip().startswith("h1"))
    quoted = h1.split('"')[1]
    assert 25 <= len(quoted) <= 34 and quoted.split()[0].lower() in reverse.LOREM


def test_the_users_own_text_replaces_the_placeholders_in_reading_order():
    text = reverse.describe(capture(), "Mi tienda de macetas\nPlantas de interior para tu casa")
    lines = {line.split()[0]: line for line in text.splitlines() if line.strip()[:2] in ("h1", "p ", "in")}
    assert lines["h1"].endswith('"Mi tienda de macetas"') and lines["p"].endswith('"Plantas de interior para tu casa"')
    assert lines["input"].split('"')[1].split()[0].lower() in reverse.LOREM  # what is left over is lorem-style


def test_a_large_page_is_folded_to_fit_the_budget():
    deep = {"t": "div", "r": [0, 0, 100, 100], "s": {}}
    node = deep
    for level in range(12):
        child = {"t": "div", "r": [level, level, 90, 90], "s": {"padding": f"{level}px"}, "c": 40}
        node["n"] = [child]
        node = child
    cap = {"viewport": {"width": 800, "height": 600}, "root": deep}
    full, small = reverse.describe(cap, budget_tokens=3000), reverse.describe(cap, budget_tokens=150)
    assert len(small) < len(full) and "nested elements left out" in small
    assert reverse.estimate_tokens(small) <= 200


def test_names_to_remove_come_from_the_page_and_the_user_but_never_the_users_own_words():
    names = reverse.brand_names(["Acme Cloud", "Home", "Acme Cloud logo", "Acme Cloud Inc", "2026", "Menu", "ab"])
    assert names == ["Acme Cloud Inc", "Acme Cloud"]
    assert reverse.brand_names(["Acme Cloud"], own_text="Bienvenidos a Acme Cloud") == []
    assert reverse.brand_names([], avoid=["Globex", " x "]) == ["Globex"]


# ---------------------------------------------------------------- the clean-up of an answer
def test_html_is_found_in_a_fenced_block_in_a_whole_document_or_in_bare_markup():
    assert reverse.extract_html("hi\n```html\n<div>a</div>\n```\nbye") == "<div>a</div>"
    assert reverse.extract_html("Sure: <!doctype html><html><body>x</body></html> done").endswith("</html>")
    assert reverse.extract_html("<main><p>x</p></main>") == "<main><p>x</p></main>"
    with pytest.raises(ReverseError, match="reverse_invalid_output"):
        reverse.extract_html("I cannot do that.")


def test_a_copied_page_loses_every_logo_image_link_script_and_name():
    doc, removed = reverse.clean_document(COPIED, ["Acme Cloud", "Acme"])
    low = doc.replace(reverse.PLACEHOLDER_IMG, "").lower()  # the gray box is a data: URL; its SVG namespace is not a fetch
    assert doc.startswith("<!doctype html>") and doc.count("<style>") == 1 and "<title>Lorem</title>" in doc
    for gone in ("acme", "cdn.", "http", "<script", "onload", "onclick", "<iframe", "<link", "@import", "@font-face",
                 "<!--", "<path", "track.", "hero.png"):
        assert gone not in low, gone
    assert doc.count("spike-placeholder") == 2 and doc.count(reverse.PLACEHOLDER_IMG) == 1 and 'alt=""' in doc
    assert 'width="120"' in doc and 'height="32"' in doc and "data:image/svg+xml" in doc
    assert 'href="#"' in doc and "Lorem keeps your files safe" in doc and ">Lorem pricing</a>" in doc
    assert "linear-gradient(#d9dde3, #d9dde3)" in doc  # the url() backgrounds became neutral gray
    assert removed["scripts"] == 1 and removed["images_and_graphics"] == 2 and removed["event_handlers"] == 2
    assert removed["links"] >= 1


def test_only_known_tags_and_attributes_survive_and_the_markup_stays_editable():
    doc, _ = reverse.clean_document(
        '<div class="card" id="c1" data-x="1" onmouseover="x()" style="color:red;background:url(a.png)">'
        '<form action="https://evil.test" method="post"><input type="image" src="x.png"><button formaction="y">Go</button></form>'
        '<blink>old</blink><font color="red">kept text</font><video src="v.mp4"></video><a href="#top" target="_blank">up</a>'
        '<ul><li>one<li>two</ul></div>')
    assert '<div class="card" id="c1" style="color:red;background:linear-gradient(#d9dde3, #d9dde3)">' in doc
    for gone in ("data-x", "onmouseover", "action=", "formaction", "src=\"x.png\"", "<blink", "<font", "<video", "target"):
        assert gone not in doc
    assert 'type="text"' in doc and "old" in doc and "kept text" in doc and 'href="#top"' in doc
    assert "<li>one</li><li>two</li></ul>" in doc.replace("\n", "")


def test_an_answer_without_markup_is_refused_and_a_fragment_becomes_a_page():
    doc, _ = reverse.clean_document("<section><h1>Hola</h1></section>")
    assert doc.startswith("<!doctype html>") and '<meta charset="utf-8">' in doc and "viewport" in doc
    assert "<body>\n<section><h1>Hola</h1></section>\n</body>" in doc
    with pytest.raises(ReverseError, match="reverse_invalid_output"):
        reverse.clean_document("no code here")


# ---------------------------------------------------------------- the score
def test_the_score_is_one_minus_the_mean_absolute_difference():
    white, black = b"\xff" * 12, b"\x00" * 12
    assert reverse.similarity(white, white, 2, 2) == 1.0
    assert reverse.similarity(white, black, 2, 2) == 0.0
    half = b"\xff\xff\xff" * 2 + b"\x00\x00\x00" * 2
    assert reverse.similarity(white, half, 2, 2) == 0.5
    one_channel = (b"\xff\xff\xff" * 3) + b"\xff\xff\x00"  # 255 off in 1 of 12 values
    assert reverse.similarity(white, one_channel, 2, 2) == round(1 - 1 / 12, 4)
    with pytest.raises(ReverseError):
        reverse.similarity(white, black[:-3], 2, 2)


# ---------------------------------------------------------------- a real browser (skipped where there is none)
async def need_browser():
    playwright = pytest.importorskip("playwright.async_api")
    async with playwright.async_playwright() as pw:
        executable = os.environ.get("SPIKE_CHROMIUM") or pw.chromium.executable_path
        if not Path(executable).is_file():
            pytest.skip("needs installed Chromium or SPIKE_CHROMIUM; never downloaded by tests")


@pytest.fixture
def site():
    """The fixture page on a loopback port, plus a second page and a 404 for the logo."""
    pages = {"/": PAGE, "/index.html": PAGE, "/blank.html": "<!doctype html><title>x</title>"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path.split("?")[0])
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((body or "").encode("utf-8"))

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


async def test_a_real_page_is_captured_without_its_text_names_or_sources(site):
    await need_browser()
    cap = await reverse_browser.capture_page(url=site + "/", width=1000, height=700)
    assert cap["png"].startswith(b"\x89PNG") and reverse.image_size(cap["png"]) == (1000, 700)
    assert cap["viewport"] == {"width": 1000, "height": 700} and cap["page"] == "#f4f1ea"
    assert {"Acme Cloud", "Acme Cloud logo", "Acme Cloud Inc"} <= set(cap["names"])
    flat = str({k: v for k, v in cap.items() if k not in ("png", "names")}).replace('"Acme Sans"', "")  # a font stack
    for leaked in ("Acme", "keeps your files", "acme-logo", "http", "pricing", "Pricing", "Start free"):
        assert leaked not in flat, leaked
    text = reverse.describe(cap)
    assert "img [24,12 120x32] [image placeholder" in text and "svg [" in text and "display:grid" in text
    assert "button [" in text and "border-radius:6px" in text and "#c2410c" in text and 'font-family:"Georgia", serif' in text
    assert "Acme" not in text and "acme" not in text.lower()


async def test_only_the_pages_own_origin_is_reached(site):
    await need_browser()
    with pytest.raises(ReverseError, match="reverse_capture_failed"):
        await reverse_browser.capture_page(url=site + "/missing", width=800, height=600)
    with pytest.raises(ReverseError, match="reverse_capture_failed"):  # nothing listens there
        await reverse_browser.capture_page(url="http://127.0.0.1:9/", width=800, height=600, timeout_s=20)


async def test_a_page_of_the_project_is_served_from_its_folder_only(tmp_path):
    await need_browser()
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "app.css").write_text("h1{font-size:40px;color:#336699}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    (tmp_path / "site" / "index.html").write_text(
        '<!doctype html><link rel="stylesheet" href="app.css"><h1>Hola</h1><img src="../secret.txt" width="30" height="30">',
        encoding="utf-8")
    cap = await reverse_browser.capture_page(folder=tmp_path / "site", path="index.html", width=600, height=400)
    text = reverse.describe(cap)
    assert "font-size:40px" in text and "color:#336699" in text
    with pytest.raises(ReverseError, match="reverse_capture_failed"):
        await reverse_browser.capture_page(folder=tmp_path / "site", path="nothing.html", width=600, height=400)


async def test_the_score_is_measured_on_a_real_render_and_changes_with_the_page(site):
    await need_browser()
    cap = await reverse_browser.capture_page(url=site + "/", width=900, height=600)
    reference = data_url(cap["png"])
    same = await reverse_browser.measure(PAGE, reference, 900, 600)
    assert same["score"] >= 0.999 and same["width"] == 900 and same["height"] == 600
    assert same["metric"] == "1 - mean absolute RGB difference / 255"
    blank = await reverse_browser.measure("<!doctype html><body style='margin:0;background:#fff'>", reference, 900, 600)
    dark = await reverse_browser.measure("<!doctype html><body style='margin:0;background:#000'>", reference, 900, 600)
    assert 0 < dark["score"] < blank["score"] < same["score"]
    assert dark["score"] < 0.5  # a black page against a mostly light one is far


async def test_the_reference_may_be_a_jpeg_and_the_render_never_runs_scripts_or_reaches_out(site):
    await need_browser()
    playwright = pytest.importorskip("playwright.async_api")
    async with playwright.async_playwright() as pw:
        browser = await reverse_browser._launch(pw)
        try:
            page = await browser.new_page(viewport={"width": 400, "height": 300})
            await page.set_content("<body style='margin:0;background:#2a6;color:#fff'><h1>Hola</h1>")
            jpeg = await page.screenshot(type="jpeg", quality=92)
        finally:
            await browser.close()
    assert reverse.image_size(jpeg) == (400, 300)
    html = ("<!doctype html><body style='margin:0;background:#2a6;color:#fff'><h1>Hola</h1>"
            f"<script>document.body.style.background='#000'</script><img src='{site}/logo.png' width=1 height=1>")
    result = await reverse_browser.measure(html, data_url(jpeg, "jpeg"), 400, 300)
    assert result["score"] > 0.97  # the script did not run: the page is still green
    with pytest.raises(ReverseError, match="image_invalid"):
        await reverse_browser.measure(html, "data:image/png;base64,AAAA", 400, 300)
