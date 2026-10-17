"""Design systems (Spike Design, C4): a `DESIGN.md` (the open format open-design and awesome-design-md use: visual
intent, colours, type, spacing, components, anti-patterns) and, when it has one, a `tokens.css` with the `:root`
custom properties to paste into a page. A chat, a project or a Forge task can use one: its text goes into the
system prompt, so pages, slides and documents the model makes follow it.

SPIKE ships 20 generic systems from open-design (Apache-2.0; no system that imitates a company's brand) and its own;
the user can import a `DESIGN.md`, or a zip with one (and its `tokens.css`)."""

from __future__ import annotations

import html
import io
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spike.core.context import CHARS_PER_TOKEN, estimate_tokens

BUNDLED = Path(__file__).with_name("systems")
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
MAX_TEXT = 64 * 1024
MAX_ZIP = 4 * 1024 * 1024
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
TOKEN_COLOR = re.compile(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\b")
DESIGN_COLOR = re.compile(r"\*\*([^*]{1,40}):\*\*\s*`(#[0-9a-fA-F]{6})`")
SWATCHES = ("bg", "surface", "fg", "muted", "border", "accent", "accent-on", "success", "warn", "danger")


class DesignError(ValueError):
    pass


def _clean_name(title: str) -> str:
    name = re.sub(r"^design system (inspired by|for)\s+", "", title.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+design system$", "", name, flags=re.IGNORECASE).strip()[:80] or "Untitled"


def check_design(text: str) -> str:
    if len(text.encode("utf-8")) > MAX_TEXT:
        raise DesignError("DESIGN.md is larger than 64 KB")
    if not re.search(r"^# \S", text, re.MULTILINE):
        raise DesignError("DESIGN.md needs a title line ('# Name')")
    return text


def check_tokens(css: str) -> str:
    """Tokens are pasted into pages: CSS custom properties only, nothing that loads from the network or ends the
    page's <style>."""
    if len(css.encode("utf-8")) > MAX_TEXT:
        raise DesignError("tokens.css is larger than 64 KB")
    low = css.lower()
    for bad in ("</style", "@import", "url(", "expression(", "javascript:"):
        if bad in low:
            raise DesignError(f"tokens.css may not contain '{bad}'")
    if "--" not in css:
        raise DesignError("tokens.css has no custom properties (--name: value)")
    return css


def strip_comments(css: str) -> str:
    return re.sub(r"\n\s*\n", "\n", re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)).strip()


@dataclass
class DesignSystem:
    id: str
    name: str
    category: str
    description: str
    source: str  # "bundled" | "user"
    path: Path

    def design(self) -> str:
        return (self.path / "DESIGN.md").read_text(encoding="utf-8")

    def tokens(self) -> str:
        f = self.path / "tokens.css"
        return f.read_text(encoding="utf-8") if f.is_file() else ""

    def colors(self) -> list[dict[str, str]]:
        """Swatches for the app: the standard tokens when there is a tokens.css, else the colours DESIGN.md names."""
        tokens = dict(TOKEN_COLOR.findall(self.tokens()))
        if tokens:
            return [{"name": k, "value": tokens[k].lower()} for k in SWATCHES if k in tokens]
        seen: dict[str, str] = {}
        for name, value in DESIGN_COLOR.findall(self.design()):
            seen.setdefault(name.strip(), value.lower())
        return [{"name": k, "value": v} for k, v in list(seen.items())[:10]]

    def to_dict(self, full: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name, "category": self.category,
                               "description": self.description, "source": self.source,
                               "has_tokens": (self.path / "tokens.css").is_file(), "colors": self.colors()}
        if full:
            out |= {"design": self.design(), "tokens": self.tokens()}
        return out


def parse_system(folder: Path, source: str) -> DesignSystem:
    text = check_design((folder / "DESIGN.md").read_text(encoding="utf-8"))
    if (folder / "tokens.css").is_file():
        check_tokens((folder / "tokens.css").read_text(encoding="utf-8"))
    title = re.search(r"^# (.+)$", text, re.MULTILINE)
    quotes = [line[1:].strip() for line in text.splitlines() if line.startswith(">")]
    category = next((q.split(":", 1)[1].strip() for q in quotes if q.lower().startswith("category:")), "")
    description = next((q for q in quotes if not q.lower().startswith("category:")), "")
    return DesignSystem(id=folder.name, name=_clean_name(title.group(1) if title else folder.name),
                        category=category[:60], description=description[:300], source=source, path=folder)


def design_prompt(ds: DesignSystem, budget_tokens: int) -> str:
    """The system prompt section: tokens first (what the page must paste), then DESIGN.md cut to the budget."""
    tokens = strip_comments(ds.tokens())
    head = (f"# Design system: {ds.name}\nEverything visual you make in this conversation (HTML pages, slides, "
            "documents, charts) follows this design system.")
    if tokens:
        head += ("\nPaste this block into the first <style> of every HTML page you write, then use var(--name) "
                 "instead of raw colours, sizes and fonts:\n```css\n" + tokens + "\n```")
    head += ("\nPages are shown offline: web fonts may not load, so keep the fallback fonts of each stack.\n\n")
    body = ds.design().strip()
    room = budget_tokens - estimate_tokens(head)
    if estimate_tokens(body) > room:
        body = body[: int(max(0, room) * CHARS_PER_TOKEN)] + "\n[…design system cut to fit the context window]"
    return head + body


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:48].strip("-") or "design"


class DesignLibrary:
    def __init__(self, user_dir: Path, bundled: Path = BUNDLED):
        self.bundled, self.user_dir = bundled, user_dir
        self.errors: list[str] = []
        self._systems: dict[str, DesignSystem] = {}
        self.reload()

    def reload(self) -> None:
        systems: dict[str, DesignSystem] = {}
        self.errors = []
        for root, source in ((self.bundled, "bundled"), (self.user_dir, "user")):
            if not root.is_dir():
                continue
            for folder in sorted(p for p in root.iterdir() if p.is_dir() and (p / "DESIGN.md").is_file()):
                try:
                    systems[folder.name] = parse_system(folder, source)  # a user system replaces a bundled one
                except (DesignError, OSError, UnicodeDecodeError) as exc:
                    self.errors.append(f"{folder.name}: {exc}")
        self._systems = systems

    def all(self) -> list[DesignSystem]:
        order = {"spike": 0}
        return sorted(self._systems.values(), key=lambda d: (d.source != "user", order.get(d.id, 1), d.name.lower()))

    def get(self, ds_id: str) -> DesignSystem | None:
        return self._systems.get(ds_id)

    def install(self, design: str, tokens: str = "", ds_id: str | None = None) -> DesignSystem:
        design = check_design(design)
        if tokens:
            tokens = check_tokens(tokens)
        title = re.search(r"^# (.+)$", design, re.MULTILINE)
        ds_id = ds_id or _slug(_clean_name(title.group(1) if title else "design"))
        if not ID.match(ds_id):
            raise DesignError("the id must be lowercase letters, digits and hyphens")
        folder = self.user_dir / ds_id
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        (folder / "DESIGN.md").write_text(design, encoding="utf-8")
        if tokens:
            (folder / "tokens.css").write_text(tokens, encoding="utf-8")
        self.reload()
        return self._systems[ds_id]

    def import_blob(self, blob: bytes) -> list[DesignSystem]:
        """A DESIGN.md, or a zip with DESIGN.md (+ tokens.css) at the top or in one or more folders."""
        if not blob.startswith(b"PK"):
            try:
                return [self.install(blob.decode("utf-8"))]
            except UnicodeDecodeError as exc:
                raise DesignError("DESIGN.md must be UTF-8 text") from exc
        if len(blob) > MAX_ZIP:
            raise DesignError("the archive is larger than 4 MB")
        try:
            archive = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile as exc:
            raise DesignError("not a zip archive") from exc
        found: dict[str, dict[str, str]] = {}
        for info in archive.infolist():
            parts = info.filename.replace("\\", "/").split("/")
            if info.is_dir() or parts[-1] not in ("DESIGN.md", "tokens.css") or ".." in parts or len(parts) > 3:
                continue
            if info.file_size > MAX_TEXT:
                raise DesignError(f"{info.filename} is larger than 64 KB")
            folder = parts[-2] if len(parts) > 1 else ""
            found.setdefault(folder, {})[parts[-1]] = archive.read(info).decode("utf-8", errors="replace")
        packages = {k: v for k, v in found.items() if "DESIGN.md" in v}
        if not packages:
            raise DesignError("no DESIGN.md in the archive")
        out = []
        for folder, files in sorted(packages.items()):
            ds_id = _slug(folder) if folder and ID.match(_slug(folder)) else None
            out.append(self.install(files["DESIGN.md"], files.get("tokens.css", ""), ds_id))
        return out

    def delete(self, ds_id: str) -> None:
        ds = self._systems.get(ds_id)
        if ds is None or ds.source != "user":
            raise DesignError("only design systems you imported can be deleted")
        shutil.rmtree(ds.path)
        self.reload()


def preview_html(ds: DesignSystem) -> str:
    """A sample page in the system's own tokens, shown in the app's isolated preview."""
    tokens = strip_comments(ds.tokens())
    swatches = "".join(f'<div class="sw"><span style="background:{c["value"]}"></span><b>{html.escape(c["name"])}</b>'
                       f'<code>{c["value"]}</code></div>' for c in ds.colors())
    return f"""<style>{tokens}
body{{margin:0;background:var(--bg,#fff);color:var(--fg,#111);font-family:var(--font-body,system-ui,sans-serif);
line-height:var(--leading-body,1.5);padding:var(--space-6,24px)}}
h1,h2{{font-family:var(--font-display,inherit);line-height:var(--leading-tight,1.15);margin:0 0 var(--space-3,12px)}}
h1{{font-size:var(--text-3xl,40px)}}h2{{font-size:var(--text-xl,22px)}}p{{color:var(--fg-2,inherit);max-width:60ch}}
.muted{{color:var(--muted,#777)}}
.row{{display:flex;gap:var(--space-3,12px);flex-wrap:wrap;align-items:center;margin:var(--space-4,16px) 0}}
.btn{{font:inherit;padding:10px 18px;border-radius:var(--radius-md,8px);border:1px solid var(--border,#ddd);
background:var(--surface,#fff);color:var(--fg,#111);cursor:pointer}}
.btn.primary{{background:var(--accent,#2f6feb);color:var(--accent-on,#fff);border-color:var(--accent,#2f6feb)}}
.card{{background:var(--surface,#fff);border:1px solid var(--border,#ddd);border-radius:var(--radius-lg,12px);
padding:var(--space-6,24px);box-shadow:var(--elev-raised,none);max-width:420px}}
input{{font:inherit;padding:10px 12px;border:1px solid var(--border,#ddd);border-radius:var(--radius-md,8px);
background:var(--surface,#fff);color:var(--fg,#111);min-width:220px}}
.ok{{color:var(--success,green)}}.warn{{color:var(--warn,orange)}}.bad{{color:var(--danger,red)}}
.sw{{display:flex;align-items:center;gap:8px;font-size:var(--text-sm,14px)}}
.sw span{{width:28px;height:28px;border-radius:6px;border:1px solid rgba(0,0,0,.12)}}
code{{font-family:var(--font-mono,monospace);color:var(--muted,#777)}}</style>
<h1>{html.escape(ds.name)}</h1>
<p>{html.escape(ds.description or "Design system")}</p>
<div class="row"><button class="btn primary">Primary action</button><button class="btn">Secondary</button>
<input placeholder="Type here"></div>
<div class="card"><h2>Card title</h2><p>Body text on the surface colour, with <span class="muted">muted notes</span>.</p>
<div class="row"><span class="ok">● Success</span><span class="warn">● Warning</span><span class="bad">● Danger</span></div>
</div>
<div class="row">{swatches}</div>"""
