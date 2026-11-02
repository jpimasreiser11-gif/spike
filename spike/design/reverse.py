"""Reverse Studio (A20): turn a reference the user owns into one editable HTML/CSS file. This module is the part with
no browser and no server: which references are accepted, the compact description a model rebuilds from, the prompts,
and the clean-up that makes sure the answer carries no logo, image, link or brand name of the reference. The headless
browser (capture and fidelity) is `reverse_browser`; the routes are `spike/server/reverse_api.py`.

The reference is either an image (sent as an image, only to a provider that supports vision and may receive files) or
a page on this computer, whose structure and computed styles are read in a headless browser. From a page the model
gets layout and styling only: text becomes lorem-style placeholders of the same length (or the user's own text),
images and graphics become neutral boxes, and no class name, id, link or font name of the page is passed on."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import ipaddress
import re
import struct
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from spike.core.context import CHARS_PER_TOKEN, estimate_tokens

CAPTURE_JS = Path(__file__).with_name("reverse_capture.js").read_text(encoding="utf-8")
STATEMENT = "I own this reference or have permission to use it"
MAX_HTML = 1_000_000
MAX_PIXELS = 12_000_000
MIN_SIDE, MAX_SIDE = 64, 4096
PLACEHOLDER = "#d9dde3"
FONTS = {"arial": "Arial", "helvetica": "Helvetica", "georgia": "Georgia", "times new roman": "Times New Roman",
         "courier new": "Courier New", "verdana": "Verdana", "tahoma": "Tahoma", "trebuchet ms": "Trebuchet MS"}
GENERIC = {"sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
           "ui-monospace"}
LOREM = ["lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit", "sed", "do", "eiusmod",
         "tempor", "incididunt", "ut", "labore", "et", "dolore", "magna", "aliqua", "enim", "ad", "minim", "veniam",
         "quis", "nostrud", "exercitation", "ullamco", "laboris", "nisi", "aliquip", "ex", "ea", "commodo",
         "consequat", "duis", "aute", "irure", "in", "reprehenderit", "voluptate", "velit", "esse", "cillum",
         "fugiat", "nulla", "pariatur", "excepteur", "sint", "occaecat", "cupidatat", "non", "proident", "sunt",
         "culpa", "qui", "officia", "deserunt", "mollit", "anim", "id", "est", "laborum"]
# words that are not a name: never removed from an answer
GENERIC_NAMES = {"home", "inicio", "welcome", "bienvenido", "bienvenida", "dashboard", "panel", "login", "index",
                 "untitled", "document", "page", "pagina", "página", "app", "contact", "contacto", "about", "pricing",
                 "menu", "menú", "search", "buscar", "close", "cerrar", "photo", "foto", "image", "imagen", "logo",
                 "icon", "icono", "avatar", "banner", "title", "título", "titulo", "main", "header", "footer",
                 "sign in", "sign up", "log in", "submit", "send", "enviar", "next", "back", "more", "read more"}
EDGE_WORDS = re.compile(r"^(?:(?:logo|logotipo|icon|icono|image|imagen|photo|foto|brand|marca|home|inicio|of|de|the|"
                        r"el|la)\s+)+|(?:\s+(?:logo|logotipo|icon|icono|image|imagen|photo|foto|brand|marca|home))+$",
                        re.IGNORECASE)
SUFFIXES = re.compile(r"[\s,]+(?:inc|llc|ltd|corp|co|gmbh|s\.?l\.?|s\.?a\.?|plc|ag|bv)\.?$", re.IGNORECASE)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
TAGS = {"header", "footer", "nav", "main", "section", "article", "aside", "div", "span", "p", "a", "h1", "h2", "h3",
        "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "caption", "colgroup", "col", "form", "label", "input", "button", "select", "option", "optgroup", "textarea",
        "fieldset", "legend", "img", "figure", "figcaption", "blockquote", "pre", "code", "em", "strong", "b", "i", "u",
        "s", "small", "sub", "sup", "mark", "br", "hr", "abbr", "cite", "q", "time", "address", "details", "summary",
        "kbd", "picture", "menu", "output", "progress", "meter"}
DROP_WITH_CONTENT = {"script", "noscript", "iframe", "object", "embed", "template", "applet", "frame", "frameset",
                     "audio", "video", "canvas", "math", "datalist", "map", "slot"}
AUTOCLOSE = {"li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "option": {"option"}, "optgroup": {"option"},
             "tr": {"td", "th", "tr"}, "td": {"td", "th"}, "th": {"td", "th"}, "p": {"p"}}
GLOBAL_ATTRS = {"class", "id", "lang", "dir", "role", "title", "hidden", "tabindex", "style"}
TAG_ATTRS = {"a": {"href"}, "img": {"width", "height", "alt"}, "input": {"type", "value", "placeholder", "name",
             "checked", "disabled", "readonly", "min", "max", "step", "for"}, "label": {"for"},
             "button": {"type", "disabled", "name"}, "td": {"colspan", "rowspan", "scope"},
             "th": {"colspan", "rowspan", "scope"}, "ol": {"start", "type"}, "li": {"value"},
             "select": {"name", "disabled", "multiple"}, "option": {"value", "selected", "disabled"},
             "textarea": {"name", "placeholder", "rows", "cols", "disabled", "readonly"}, "time": {"datetime"},
             "progress": {"value", "max"}, "meter": {"value", "min", "max"}, "details": {"open"},
             "col": {"span"}, "colgroup": {"span"}}
URL = re.compile(r"url\(\s*(?:'[^']*'|\"[^\"]*\"|[^)]*)\s*\)|image-set\([^)]*\)|-webkit-image-set\([^)]*\)", re.I)
PLACEHOLDER_CSS = f"linear-gradient({PLACEHOLDER}, {PLACEHOLDER})"
PLACEHOLDER_IMG = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 9' "
                   "preserveAspectRatio='none'%3E%3Crect width='16' height='9' fill='%23" + PLACEHOLDER[1:] + "'/%3E%3C/svg%3E")


class ReverseError(ValueError):
    """A safe error code (`reverse_*`); the browser supplies the translated explanation."""


# ---------------------------------------------------------------- what is accepted
def check_url(url: str) -> str:
    """A page on this computer: http(s) on localhost or a loopback address, with no credentials. Nothing else is
    opened, so a reference on someone else's server can never be fetched from here."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for a port out of range
    except ValueError as exc:
        raise ReverseError("reverse_url") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or parts.username or parts.password or not host:
        raise ReverseError("reverse_url")
    if host != "localhost" and not host.endswith(".localhost"):
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ReverseError("reverse_url")
        except ValueError as exc:
            raise ReverseError("reverse_url") from exc
    return url


def check_page_path(path: str) -> str:
    """A relative `.html` path of the project or workspace; it stays inside its folder (the caller resolves it)."""
    clean = (path or "").strip().replace("\\", "/")
    parts = clean.split("/")
    if (not clean or clean.startswith("/") or any(p in ("", "..") for p in parts) or ":" in parts[0]
            or not clean.lower().endswith((".html", ".htm"))):
        raise ReverseError("reverse_path")
    return clean


def image_size(data: bytes) -> tuple[int, int]:
    """Width and height of a PNG, JPEG or WebP from its header, with no decoder."""
    w = h = 0
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
    elif data.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
            elif marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
            elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                break
            else:
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X" and len(data) >= 30:
            w, h = 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        elif kind == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        elif kind == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            w, h = w & 0x3FFF, h & 0x3FFF
    if not w or not h:
        raise ReverseError("image_invalid")
    if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE or w * h > MAX_PIXELS:
        raise ReverseError("reverse_image_size")
    return w, h


def authorization(source: str, reference: str, *, kind: str, now: dt.datetime | None = None) -> dict[str, Any]:
    """What is saved with the result: that the user confirmed the right to use the reference, when, and which
    reference (the hash of an image, or the address or path of a page)."""
    when = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    ref = {"kind": kind, **({"sha256": reference} if kind == "image" else {"value": reference})}
    return {"confirmed": True, "statement": STATEMENT, "at": when.isoformat(), "source": source, "reference": ref}


def sha256_image(data_url: str) -> str:
    return hashlib.sha256(data_url.partition(",")[2].encode("ascii", "ignore")).hexdigest()


# ---------------------------------------------------------------- placeholder text
def lorem(chars: int, offset: int = 0) -> str:
    """Placeholder text of about `chars` characters: whole words from a fixed list, at least one (cut to fit)."""
    chars = max(1, chars)
    words: list[str] = []
    size = 0
    for i in range(len(LOREM)):
        word = LOREM[(offset + i) % len(LOREM)]
        if words and size + 1 + len(word) > chars:
            break
        words.append(word)
        size += len(word) + (1 if len(words) > 1 else 0)
    text = " ".join(words)[:chars]
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------- the description a model rebuilds from
def _font(value: str) -> str:
    """Only a generic or a very common system family: a page's own font name could be a brand."""
    names = [n.strip().strip("'\"").lower() for n in value.split(",")]
    named = next((n for n in names if n in FONTS), None)
    generic = next((n for n in reversed(names) if n in GENERIC), "serif" if named in ("georgia", "times new roman")
                   else "monospace" if named == "courier new" else "sans-serif")
    return f'"{FONTS[named]}", {generic}' if named else generic


def _style_text(style: dict[str, str]) -> str:
    items = []
    for key, value in style.items():
        if key == "font-family":
            value = _font(value)
        elif key == "background-image" and value == "image":
            value = "[image placeholder]"
        items.append(f"{key}:{value}")
    return "; ".join(items)


def _signature(node: dict[str, Any]) -> str:
    kids = ",".join(_signature(k) for k in node.get("n", []))
    return f"{node['t']}|{node.get('k', '')}|{sorted(node['s'].items())}|{kids}"


class _Describer:
    def __init__(self, own_text: list[str], max_depth: int):
        self.own, self.max_depth, self.lines, self.offset = own_text, max_depth, [], 0

    def text(self, chars: int) -> str:
        if self.own:
            return self.own.pop(0)
        self.offset = (self.offset + 7) % len(LOREM)
        return lorem(chars, self.offset)

    def nodes(self, nodes: list[dict[str, Any]], depth: int) -> None:
        i = 0
        while i < len(nodes):
            node, j = nodes[i], i + 1
            sig = _signature(node)
            while j < len(nodes) and _signature(nodes[j]) == sig:
                j += 1
            self.node(node, depth, j - i, nodes[i + 1] if j - i > 1 else None)
            i = j

    def node(self, node: dict[str, Any], depth: int, repeat: int, second: dict[str, Any] | None) -> None:
        x, y, w, h = node["r"]
        kind = node.get("k", "")
        head = f"{'  ' * depth}{node['t']} [{x},{y} {w}x{h}]"
        if repeat > 1 and second:
            head += f" x{repeat} (repeated every {second['r'][0] - x:+d},{second['r'][1] - y:+d})"
        if kind == "img":
            head += " [image placeholder: a neutral gray box]"
        elif kind == "svg":
            head += " [graphic placeholder: a neutral gray box]"
        elif kind == "media":
            head += " [media placeholder: a neutral gray box]"
        elif kind.startswith("input:"):
            head += f" <{kind[6:]}>"
        style = _style_text(node["s"])
        if style:
            head += f" {{{style}}}"
        if node.get("c"):
            head += f' "{self.text(node["c"])}"'
        self.lines.append(head)
        kids = node.get("n", [])
        if kids and depth + 1 >= self.max_depth:
            self.lines.append(f"{'  ' * (depth + 1)}(+{sum(1 for _ in _walk(kids))} nested elements left out)")
        elif kids:
            self.nodes(kids, depth + 1)


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        yield from _walk(node.get("n", []))


def describe(capture: dict[str, Any], own_text: str = "", budget_tokens: int = 3000) -> str:
    """The compact structure of a captured page: one line per element with its box, its non-default styles and a
    lorem-style text of the same length. Deeper levels are folded until it fits `budget_tokens`; similar siblings are
    folded into one line. The original text, sources, links, class names and ids are never in it."""
    own = [line.strip() for line in own_text.splitlines() if line.strip()]
    view = capture["viewport"]
    head = (f"Viewport {view['width']}x{view['height']} px. Page background {capture.get('page', '#ffffff')}."
            + (" The capture was cut at its element limit." if capture.get("truncated") else "")
            + "\nEach line is: tag [x,y widthxheight] {styles that differ from the browser's default} \"placeholder text\"."
            "\nIndented lines are children. `xN` means N similar siblings in a row (sizes and text lengths differ a "
            "little); the line shows the first one.\n")
    root = capture.get("root")
    if not root:
        return head + "(the page has no visible element)"
    depth = 14
    while True:
        d = _Describer(list(own), depth)
        d.nodes([root], 0)
        text = head + "\n".join(d.lines)
        if estimate_tokens(text) <= budget_tokens or depth <= 2:
            break
        depth -= 1
    room = int(budget_tokens * CHARS_PER_TOKEN)
    if len(text) > room:
        text = text[:room].rsplit("\n", 1)[0] + "\n[… structure cut to fit the model's context window]"
    return text


def brand_names(found: list[str], own_text: str = "", avoid: list[str] | None = None) -> list[str]:
    """Names to remove from an answer: what the page calls itself (title, logo labels, copyright line) and what the
    user listed, minus words that are only words and anything the user wrote in their own text."""
    own = own_text.lower()
    out: dict[str, str] = {}
    for raw in found:
        name = EDGE_WORDS.sub("", re.sub(r"\s+", " ", raw).strip()).strip(" .,:;|-–—")
        for variant in (name, SUFFIXES.sub("", name).strip()):
            low = variant.lower()
            if len(variant) >= 3 and low not in GENERIC_NAMES and not low.isdigit() and not (own and low in own):
                out.setdefault(low, variant)
    for raw in avoid or []:
        name = re.sub(r"\s+", " ", raw).strip()
        if len(name) >= 2:
            out.setdefault(name.lower(), name)
    return sorted(out.values(), key=len, reverse=True)[:60]


# ---------------------------------------------------------------- prompts
RULES = """You rebuild a layout as ONE self-contained HTML file with inline CSS. Rules, all of them mandatory:
1. One file: a single <style> block and the markup. No JavaScript, no <link>, no @import, no web fonts, no url() to
   anything: nothing is loaded from anywhere. Use font stacks that end in a generic family.
2. Never copy a logo, photo, icon or brand. Every image or graphic is an empty <div> (or <img> without a real source)
   in a neutral gray box of the same size. Do not draw logos with SVG.
3. All text is placeholder text: the lorem-style text you are given, or the user's own text. Never write a brand,
   product, company or person name, a slogan, a price or a real link: links are href="#".
4. Match the layout, sizes, spacing, colors and typography as closely as you can.
5. Make it easy to edit: semantic tags, readable class names, the main colors and spacings as CSS custom properties
   on :root, no inline styles unless needed.
Answer with the HTML only, in one ```html block, starting with <!doctype html>."""


def system_prompt() -> str:
    return "You are the Reverse Studio of SPIKE, an app that rebuilds a user's own design as clean, editable code.\n" + RULES


def _extras(own_text: str, avoid: list[str]) -> str:
    out = ""
    if own_text.strip():
        out += ("\nThe user's own text, in reading order; use it for the headings and paragraphs, one line per text "
                f"element, and lorem-style text for what is left over:\n{own_text.strip()[:2000]}\n")
    if avoid:
        out += f"\nNever write these names: {', '.join(avoid)}.\n"
    return out


def image_prompt(width: int, height: int, own_text: str = "", avoid: list[str] | None = None) -> str:
    return (f"The attached image is a reference the user owns, {width}x{height} px. Rebuild its layout, colors and "
            "typography as one HTML file that looks right in a viewport of exactly that size. Do not transcribe the "
            "text you can read in the image and do not name anything it names: write lorem-style placeholder text of "
            "about the same length, and neutral gray boxes for every image, logo and icon." + _extras(own_text, avoid or []))


def structure_prompt(structure: str, own_text: str = "", avoid: list[str] | None = None) -> str:
    return ("Below is the structure and the computed styles of a page the user owns, from a headless browser. Rebuild "
            "it as one HTML file that looks right in that viewport. The text shown is already placeholder text: use "
            "it as it is." + _extras(own_text, avoid or []) + "\n\n" + structure)


# ---------------------------------------------------------------- the answer
def extract_html(answer: str) -> str:
    """The HTML of a model's answer: the first fenced block, else from <!doctype>/<html> to the last </html>, else
    everything when it is markup."""
    block = re.search(r"```(?:html|HTML)?[ \t]*\n(.*?)```", answer, re.DOTALL)
    if block and "<" in block.group(1):
        return block.group(1).strip()
    start = re.search(r"<!doctype\s+html|<html[\s>]", answer, re.IGNORECASE)
    if start:
        end = answer.lower().rfind("</html>")
        return answer[start.start(): end + 7 if end > start.start() else len(answer)].strip()
    if re.search(r"<(div|section|main|header|body|p|h1|nav|article)[\s>]", answer, re.IGNORECASE):
        return answer.strip()
    raise ReverseError("reverse_invalid_output")


def scrub_css(css: str) -> str:
    """CSS that loads nothing: no @import or @font-face, every url() a neutral gray."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"@(?:import|charset|namespace)[^;]*;?", "", css, flags=re.IGNORECASE)
    css = re.sub(r"@font-face\s*\{[^}]*\}", "", css, flags=re.IGNORECASE)
    css = URL.sub(PLACEHOLDER_CSS, css)
    return re.sub(r"expression\s*\(|javascript:|behavior\s*:|-moz-binding[^;}]*", "", css, flags=re.IGNORECASE).strip()


class _Clean(HTMLParser):
    """Re-writes an answer so it is safe to keep and share: only a fixed set of tags and attributes, one <style>,
    images and graphics as neutral boxes, links as '#', no scripts, handlers, comments or external addresses; the
    names it is given are replaced by lorem-style words everywhere (text, attributes and styles alike)."""

    def __init__(self, names: list[str]):
        super().__init__(convert_charrefs=True)
        self.body: list[str] = []
        self.styles: list[str] = []
        self.title = ""
        self.lang = "en"
        self.body_attrs = ""
        ordered = sorted(names, key=len, reverse=True)
        self.pattern = re.compile("|".join(re.escape(n) for n in ordered), re.IGNORECASE) if ordered else None
        self.mode = ""      # "style" | "title" while inside those elements
        self.skip = ""      # a tag whose content is dropped, and how deep
        self.skip_depth = 0
        self.stack: list[str] = []
        self.placeholders = 0

    def scrub(self, text: str) -> str:
        if self.pattern is None:
            return text
        return self.pattern.sub(lambda m: "Lorem" if m.group(0)[:1].isupper() else "lorem", text)

    def attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        allowed = GLOBAL_ATTRS | TAG_ATTRS.get(tag, set())
        out = []
        for name, value in attrs:
            value = value or ""
            if name not in allowed and not name.startswith("aria-"):
                continue
            if name == "href":
                value = value if value.startswith("#") else "#"
            elif name == "style":
                value = scrub_css(value)
            elif name == "alt" and tag == "img":
                continue
            elif name == "type" and tag == "input" and value.lower() in ("image", "file"):
                value = "text"
            out.append(f' {name}="{html.escape(self.scrub(value), quote=True)}"')
        return "".join(out)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip:
            if tag == self.skip and tag not in VOID:
                self.skip_depth += 1
            return
        if tag in DROP_WITH_CONTENT or tag == "svg":
            if tag == "svg":
                self.body.append(self.graphic(dict(attrs)))
            if tag not in VOID:
                self.skip, self.skip_depth = tag, 1
            return
        if tag == "html":
            self.lang = re.sub(r"[^A-Za-z-]", "", dict(attrs).get("lang") or "en")[:12] or "en"
        elif tag == "body":
            self.body_attrs = self.attrs("body", [a for a in attrs if a[0] in ("class", "id", "style")])
        elif tag == "style":
            self.mode = "style"
        elif tag == "title":
            self.mode = "title"
        elif tag == "img":
            given = dict(attrs)
            size = "".join(f' {k}="{v}"' for k in ("width", "height") if (v := (given.get(k) or "")).isdigit())
            kept = [a for a in attrs if a[0] in ("id", "style", "title", "role")]
            kept.append(("class", f"{given.get('class') or ''} spike-placeholder".strip()))
            self.body.append(f'<img{self.attrs("img", kept)}{size} alt="" src="{PLACEHOLDER_IMG}">')
            self.placeholders += 1
        elif tag in TAGS:
            while self.stack and self.stack[-1] in AUTOCLOSE.get(tag, ()):  # <li>a<li>b: the first ends where the next starts
                self.body.append(f"</{self.stack.pop()}>")
            self.body.append(f"<{tag}{self.attrs(tag, attrs)}>")
            if tag not in VOID:
                self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            if tag == self.skip:
                self.skip_depth -= 1
                if self.skip_depth <= 0:
                    self.skip, self.skip_depth = "", 0
            return
        if tag in ("style", "title"):
            self.mode = ""
        elif tag in self.stack:
            while self.stack:
                top = self.stack.pop()
                self.body.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.mode == "style":
            self.styles.append(self.scrub(scrub_css(data)))
        elif self.mode == "title":
            self.title += self.scrub(data)
        else:
            self.body.append(html.escape(self.scrub(data), quote=False))

    def graphic(self, attrs: dict[str, str | None]) -> str:
        self.placeholders += 1
        size = ""
        for key in ("width", "height"):
            value = (attrs.get(key) or "").strip()
            if value.isdigit():
                size += f"{key}:{value}px;"
        return (f'<span class="spike-placeholder" role="img" aria-label="graphic placeholder" '
                f'style="display:inline-block;{size or "width:24px;height:24px;"}background:{PLACEHOLDER}"></span>')

    def close(self) -> None:
        super().close()
        while self.stack:
            self.body.append(f"</{self.stack.pop()}>")


def clean_document(answer: str, names: list[str] | None = None, *, title: str = "Reverse Studio") -> tuple[str, dict[str, Any]]:
    """The answer as one clean document, and what was done to it (counts of what was replaced or removed)."""
    source = extract_html(answer)
    if len(source) > MAX_HTML:
        raise ReverseError("reverse_invalid_output")
    parser = _Clean(names or [])
    parser.feed(source)
    parser.close()
    body = "".join(parser.body).strip()
    if "<" not in body:
        raise ReverseError("reverse_invalid_output")
    css = "\n".join(s for s in parser.styles if s)
    page_title = html.escape(parser.title.strip() or title, quote=False)
    doc = (f'<!doctype html>\n<html lang="{parser.lang}">\n<head>\n<meta charset="utf-8">\n'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{page_title}</title>\n'
           f"<style>\n{css}\n</style>\n</head>\n<body{parser.body_attrs}>\n{body}\n</body>\n</html>\n")
    removed = {"scripts": len(re.findall(r"<script\b", source, re.IGNORECASE)),
               "images_and_graphics": parser.placeholders,
               "links": len(re.findall(r"""\bhref\s*=\s*["']?(?!#)""", source, re.IGNORECASE)),
               "event_handlers": len(re.findall(r"\son[a-z]+\s*=", source, re.IGNORECASE))}
    return doc, removed


# ---------------------------------------------------------------- the score
def similarity(reference: bytes, render: bytes, width: int, height: int) -> float:
    """1 minus the mean absolute difference of the red, green and blue values of two images of the same size, over
    255: 1.0 when every pixel is identical, 0.0 for black against white. Both are raw RGB, 3 bytes per pixel."""
    import numpy as np

    expected = width * height * 3
    if len(reference) != expected or len(render) != expected:
        raise ReverseError("reverse_failed")
    a = np.frombuffer(reference, dtype=np.uint8)
    b = np.frombuffer(render, dtype=np.uint8)
    total, step = 0, 3_000_000
    for start in range(0, expected, step):  # in blocks, so a large image does not need a large temporary
        total += int(np.abs(a[start:start + step].astype(np.int16) - b[start:start + step].astype(np.int16)).sum())
    return round(1.0 - total / (expected * 255), 4)
