"""Tools that write Word, Excel, PowerPoint and PDF files into the workspace.

The libraries (python-docx, openpyxl, python-pptx, reportlab) are optional: `pip install 'spike-ai[docs]'`.
Text documents take a small Markdown subset — `#`/`##`/`###` headings, `-` or `1.` lists, `**bold**`, and
`| pipe | tables |` — which is what small models write most reliably.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spike.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from spike.tools.builtin import Workspace

MAX_CHARS = 200_000
MAX_CELLS = 200_000
MAX_SLIDES = 200
# Spreadsheet formulas that reach outside the file when it is opened (DDE, web calls, native code).
UNSAFE_FORMULA = re.compile(r"\||\b(WEBSERVICE|FILTERXML|CALL|REGISTER(\.ID)?|EXEC|RTD)\s*\(", re.IGNORECASE)


# PDF text needs an embedded Unicode font beyond Latin-1; the first one found is used (SPIKE_PDF_FONT overrides).
PDF_FONTS = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", ""),
    ("/Library/Fonts/Arial Unicode.ttf", ""),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
]


class MissingLibrary(Exception):
    pass


def _lib(module: str) -> Any:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingLibrary(f"error: this needs the optional document libraries; install them with "
                             f"pip install 'spike-ai[docs]' (missing: {module.split('.')[0]})") from exc


# --------------------------------------------------------------------------- markdown subset
@dataclass
class Block:
    kind: str  # heading | bullet | number | paragraph | table
    text: str = ""
    level: int = 0
    rows: list[list[str]] = field(default_factory=list)


def parse_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block("paragraph", " ".join(paragraph)))
            paragraph.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue  # the |---|---| separator
            if blocks and blocks[-1].kind == "table":
                blocks[-1].rows.append(cells)
            else:
                blocks.append(Block("table", rows=[cells]))
            continue
        if m := re.match(r"(#{1,3})\s+(.*)", line):
            flush()
            blocks.append(Block("heading", m.group(2).strip(), level=len(m.group(1))))
        elif m := re.match(r"[-*+]\s+(.*)", line):
            flush()
            blocks.append(Block("bullet", m.group(1)))
        elif m := re.match(r"\d+[.)]\s+(.*)", line):
            flush()
            blocks.append(Block("number", m.group(1)))
        else:
            paragraph.append(line)
    flush()
    for b in blocks:  # ragged tables get padded so every row has the same width
        if b.kind == "table":
            width = max(len(r) for r in b.rows)
            b.rows = [r + [""] * (width - len(r)) for r in b.rows]
    return blocks


def runs(text: str) -> list[tuple[str, bool]]:
    """`a **b** c` -> [("a ", False), ("b", True), (" c", False)]."""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    return [(p, i % 2 == 1) for i, p in enumerate(parts) if p]


def plain(text: str) -> str:
    return "".join(t for t, _ in runs(text))


# --------------------------------------------------------------------------- tools
class DocumentTool(Tool):
    extension = ""
    risk = "write"
    default_policy = "ask"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            path = self.workspace.resolve(str(args.get("path", "")))
        except PermissionError as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        if path.suffix.lower() != self.extension:
            return ToolResult(ok=False, content=f"error: the path must end in {self.extension}")
        try:
            problem = self.check(args)
            if problem:
                return ToolResult(ok=False, content=f"error: {problem}")
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self.build, path, args)
        except MissingLibrary as exc:
            return ToolResult(ok=False, content=str(exc))
        except (TypeError, ValueError, KeyError) as exc:
            return ToolResult(ok=False, content=f"error: invalid arguments: {exc}")
        rel = path.relative_to(self.workspace.root).as_posix()
        return ToolResult(ok=True, content=f"wrote {rel} ({path.stat().st_size} bytes)", data={"file": rel})

    def check(self, args: dict[str, Any]) -> str | None:
        content = args.get("content")
        if not isinstance(content, str):
            return "'content' must be a string of Markdown"
        return "'content' is too long" if len(content) > MAX_CHARS else None

    def build(self, path: Path, args: dict[str, Any]) -> None:
        raise NotImplementedError


MARKDOWN_ARGS = {"type": "object", "properties": {
    "path": {"type": "string", "description": "file path in the workspace"},
    "content": {"type": "string", "description": "the document in Markdown: # headings, - lists, **bold**, "
                                                 "| tables |"},
}, "required": ["path", "content"]}


class CreateDocx(DocumentTool):
    name = "create_docx"
    description = "Create a Word document (.docx) in the workspace from Markdown."
    parameters = MARKDOWN_ARGS
    extension = ".docx"

    def build(self, path: Path, args: dict[str, Any]) -> None:
        docx = _lib("docx")
        doc = docx.Document()
        for b in parse_markdown(args["content"]):
            if b.kind == "heading":
                doc.add_heading(plain(b.text), level=b.level)
            elif b.kind == "table":
                table = doc.add_table(rows=len(b.rows), cols=len(b.rows[0]))
                table.style = "Table Grid"
                for r, row in enumerate(b.rows):
                    for c, value in enumerate(row):
                        cell = table.cell(r, c)
                        cell.text = plain(value)
                        if r == 0:
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
            else:
                style = {"bullet": "List Bullet", "number": "List Number"}.get(b.kind)
                p = doc.add_paragraph(style=style)
                for text, bold in runs(b.text):
                    p.add_run(text).bold = bold or None
        doc.save(path)


class CreatePdf(DocumentTool):
    name = "create_pdf"
    description = "Create a PDF document in the workspace from Markdown."
    parameters = MARKDOWN_ARGS
    extension = ".pdf"

    def build(self, path: Path, args: dict[str, Any]) -> None:
        colors = _lib("reportlab.lib.colors")
        styles = _lib("reportlab.lib.styles").getSampleStyleSheet()
        platypus = _lib("reportlab.platypus")
        from xml.sax.saxutils import escape

        def markup(text: str) -> str:
            return "".join(f"<b>{escape(t)}</b>" if bold else escape(t) for t, bold in runs(text))

        regular, bold = _pdf_font()
        body = styles["BodyText"].clone("SpikeBody", fontName=regular)
        heads = {n: styles[f"Heading{n}"].clone(f"SpikeHeading{n}", fontName=bold) for n in (1, 2, 3)}
        story: list[Any] = []
        items: list[Any] = []
        kind = ""

        def close_list() -> None:
            if items:
                story.append(platypus.ListFlowable(list(items), bulletType="bullet" if kind == "bullet" else "1"))
                items.clear()

        for b in parse_markdown(args["content"]):
            if b.kind not in ("bullet", "number") or b.kind != kind:
                close_list()
            kind = b.kind
            if b.kind == "heading":
                story.append(platypus.Paragraph(markup(b.text), heads[b.level]))
            elif b.kind in ("bullet", "number"):
                items.append(platypus.ListItem(platypus.Paragraph(markup(b.text), body)))
            elif b.kind == "table":
                data = [[platypus.Paragraph(markup(f"**{v}**" if r == 0 and v else v), body)
                         for v in row] for r, row in enumerate(b.rows)]
                table = platypus.Table(data, hAlign="LEFT")
                table.setStyle(platypus.TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke)]))
                story += [table, platypus.Spacer(1, 8)]
            else:
                story.append(platypus.Paragraph(markup(b.text), body))
        close_list()
        platypus.SimpleDocTemplate(str(path), title=plain(args.get("title") or path.stem)).build(story)


class CreateXlsx(DocumentTool):
    name = "create_xlsx"
    description = ("Create an Excel workbook (.xlsx) in the workspace. Numbers stay numbers; a string that starts "
                   "with '=' is a formula, e.g. '=SUM(B2:B9)'. The first row of each sheet is bold.")
    parameters = {"type": "object", "properties": {
        "path": {"type": "string", "description": "file path in the workspace"},
        "sheets": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "rows": {"type": "array", "items": {"type": "array", "items": {}}},
        }, "required": ["rows"]}},
    }, "required": ["path", "sheets"]}
    extension = ".xlsx"

    def check(self, args: dict[str, Any]) -> str | None:
        sheets = args.get("sheets")
        if not isinstance(sheets, list) or not sheets or not all(isinstance(s, dict) for s in sheets):
            return "'sheets' must be a non-empty list of {name, rows}"
        cells = 0
        for s in sheets:
            rows = s.get("rows")
            if not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
                return "each sheet needs 'rows', a list of lists"
            for row in rows:
                for v in row:
                    if not (v is None or isinstance(v, (str, int, float, bool))):
                        return "cells must be text, numbers, booleans or null"
                    if isinstance(v, str) and v.startswith("=") and UNSAFE_FORMULA.search(v):
                        return f"formula not allowed (it would reach outside the file): {v[:60]}"
                cells += len(row)
        return "too many cells" if cells > MAX_CELLS else None

    def build(self, path: Path, args: dict[str, Any]) -> None:
        openpyxl = _lib("openpyxl")
        styles = _lib("openpyxl.styles")
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for i, sheet in enumerate(args["sheets"]):
            title = re.sub(r"[\[\]:*?/\\]", "_", str(sheet.get("name") or f"Sheet{i + 1}"))[:31]
            ws = wb.create_sheet(title=title)
            for row in sheet["rows"]:
                ws.append(row)
            for cell in ws[1] if ws.max_row and sheet["rows"] else []:
                cell.font = styles.Font(bold=True)
            for column in ws.columns:
                width = max((len(str(c.value)) for c in column if c.value is not None), default=8)
                ws.column_dimensions[column[0].column_letter].width = min(60, max(8, width + 2))
        wb.save(path)


class CreatePptx(DocumentTool):
    name = "create_pptx"
    description = "Create a PowerPoint deck (.pptx) in the workspace: a title slide, then one slide per item."
    parameters = {"type": "object", "properties": {
        "path": {"type": "string", "description": "file path in the workspace"},
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "slides": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string", "description": "speaker notes"},
        }, "required": ["title"]}},
    }, "required": ["path", "title", "slides"]}
    extension = ".pptx"

    def check(self, args: dict[str, Any]) -> str | None:
        slides = args.get("slides")
        if not isinstance(args.get("title"), str) or not isinstance(slides, list):
            return "'title' (text) and 'slides' (a list) are required"
        if len(slides) > MAX_SLIDES:
            return f"at most {MAX_SLIDES} slides"
        for s in slides:
            if not isinstance(s, dict) or not isinstance(s.get("bullets", []), list):
                return "each slide is {title, bullets: [text], notes}"
        return None

    def build(self, path: Path, args: dict[str, Any]) -> None:
        pptx = _lib("pptx")
        deck = pptx.Presentation()
        first = deck.slides.add_slide(deck.slide_layouts[0])
        first.shapes.title.text = args["title"]
        _fill_or_drop(first.placeholders[1], [args["subtitle"]] if args.get("subtitle") else [])
        for item in args["slides"]:
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = str(item.get("title", ""))
            _fill_or_drop(slide.placeholders[1], [plain(str(b)) for b in item.get("bullets", [])])
            if item.get("notes"):
                slide.notes_slide.notes_text_frame.text = str(item["notes"])
        deck.save(path)


def _pdf_font() -> tuple[str, str]:
    """Register the first Unicode TTF found as the 'SpikeSans' family; Helvetica (Latin-1 only) otherwise."""
    pdfmetrics = _lib("reportlab.pdfbase.pdfmetrics")
    if "SpikeSans" in pdfmetrics.getRegisteredFontNames():
        return "SpikeSans", "SpikeSans-Bold"
    ttfonts = _lib("reportlab.pdfbase.ttfonts")
    override = os.environ.get("SPIKE_PDF_FONT", "")
    for regular, bold in ([(override, "")] if override else []) + PDF_FONTS:
        if not os.path.isfile(regular):
            continue
        try:
            pdfmetrics.registerFont(ttfonts.TTFont("SpikeSans", regular))
            pdfmetrics.registerFont(ttfonts.TTFont("SpikeSans-Bold", bold if os.path.isfile(bold) else regular))
        except Exception:  # an unreadable or unsupported font file: try the next one
            continue
        pdfmetrics.registerFontFamily("SpikeSans", normal="SpikeSans", bold="SpikeSans-Bold",
                                      italic="SpikeSans", boldItalic="SpikeSans-Bold")
        return "SpikeSans", "SpikeSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _fill_or_drop(placeholder: Any, lines: list[str]) -> None:
    if not lines:  # an empty placeholder shows "Click to add text" in PowerPoint
        placeholder._element.getparent().remove(placeholder._element)
        return
    frame = placeholder.text_frame
    frame.text = lines[0]
    for line in lines[1:]:
        frame.add_paragraph().text = line


def document_tools(workspace: Workspace) -> list[Tool]:
    return [CreateDocx(workspace), CreateXlsx(workspace), CreatePptx(workspace), CreatePdf(workspace)]
