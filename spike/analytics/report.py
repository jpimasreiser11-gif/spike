"""An analysis as a Word or PDF report: the question, the answer, and each query with its table and chart. The
app sends the blocks (charts as PNG images it rendered); this module checks them and lays them out with the same
document libraries as the document tools."""

from __future__ import annotations

import base64
import io
import time
from typing import Any

from spike.tools.documents import _lib, docx_markdown, markup, pdf_markdown, pdf_styles, pdf_table

MAX_BLOCKS = 100
MAX_TEXT = 200_000
MAX_ROWS = 500
MAX_COLUMNS = 40
MAX_IMAGES = 12
MAX_IMAGE = 4 * 1024**2
MAX_PIXELS = 4096
PNG = b"\x89PNG\r\n\x1a\n"


class ReportError(ValueError):
    pass


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _png(value: Any) -> tuple[bytes, int, int]:
    if not isinstance(value, str):
        raise ReportError("an image block needs a PNG")
    raw = value.split(",", 1)[1] if value.startswith("data:image/png;base64,") else value
    try:
        data = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise ReportError("an image is not valid base64") from exc
    if len(data) > MAX_IMAGE or not data.startswith(PNG):
        raise ReportError(f"images must be PNG files of at most {MAX_IMAGE // 1024**2} MB")
    image = _lib("PIL.Image").open(io.BytesIO(data))
    width, height = image.size
    if width > MAX_PIXELS or height > MAX_PIXELS:
        raise ReportError(f"images must be at most {MAX_PIXELS} pixels per side")
    image.verify()
    return data, width, height


def clean_blocks(blocks: Any) -> list[dict[str, Any]]:
    """The report's blocks, checked: text (Markdown subset), code, table, image."""
    if not isinstance(blocks, list) or not blocks or len(blocks) > MAX_BLOCKS:
        raise ReportError(f"a report has 1 to {MAX_BLOCKS} blocks")
    out, images, total = [], 0, 0
    for block in blocks:
        kind = block.get("kind") if isinstance(block, dict) else None
        title = _text(block.get("title"), 200) if isinstance(block, dict) else ""
        if kind in ("text", "code"):
            text = _text(block.get("text"))
            total += len(text)
            out.append({"kind": kind, "title": title, "text": text, "language": _text(block.get("language"), 20)})
        elif kind == "table":
            columns = [str(c)[:200] for c in (block.get("columns") or [])][:MAX_COLUMNS]
            rows = [["" if v is None else str(v)[:200] for v in (r if isinstance(r, list) else [])][:len(columns)]
                    for r in (block.get("rows") or [])[:MAX_ROWS]]
            if not columns:
                raise ReportError("a table block needs columns")
            rows = [r + [""] * (len(columns) - len(r)) for r in rows]
            out.append({"kind": "table", "title": title, "columns": columns, "rows": rows,
                        "truncated": bool(block.get("truncated")) or len(block.get("rows") or []) > MAX_ROWS})
        elif kind == "image":
            images += 1
            if images > MAX_IMAGES:
                raise ReportError(f"at most {MAX_IMAGES} images")
            data, width, height = _png(block.get("png"))
            out.append({"kind": "image", "title": title, "png": data, "width": width, "height": height})
        else:
            raise ReportError(f"unknown block kind '{kind}'")
        if total > MAX_TEXT:
            raise ReportError("the report's text is too long")
    return out


def footer() -> str:
    return f"Generado por SPIKE el {time.strftime('%Y-%m-%d %H:%M')}. Los números salen de las consultas mostradas."


def build_docx(title: str, blocks: list[dict[str, Any]]) -> bytes:
    docx = _lib("docx")
    shared = _lib("docx.shared")
    doc = docx.Document()
    doc.core_properties.title = title
    doc.add_heading(title, level=1)
    for b in blocks:
        if b["title"]:
            doc.add_heading(b["title"], level=2)
        if b["kind"] == "text":
            docx_markdown(doc, b["text"])
        elif b["kind"] == "code":
            run = doc.add_paragraph().add_run(b["text"])
            run.font.name, run.font.size = "Courier New", shared.Pt(9)
        elif b["kind"] == "table":
            table = doc.add_table(rows=len(b["rows"]) + 1, cols=len(b["columns"]))
            table.style = "Table Grid"
            for c, name in enumerate(b["columns"]):
                table.cell(0, c).text = name
                for run in table.cell(0, c).paragraphs[0].runs:
                    run.bold = True
            for r, row in enumerate(b["rows"], start=1):
                for c, value in enumerate(row):
                    table.cell(r, c).text = value
            if b["truncated"]:
                doc.add_paragraph(f"(primeras {len(b['rows'])} filas)")
        elif b["kind"] == "image":
            doc.add_picture(io.BytesIO(b["png"]), width=shared.Inches(6.3))
    doc.add_paragraph(footer()).runs[0].italic = True
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def build_pdf(title: str, blocks: list[dict[str, Any]]) -> bytes:
    platypus = _lib("reportlab.platypus")
    pagesizes = _lib("reportlab.lib.pagesizes")
    styles = pdf_styles()
    out = io.BytesIO()
    doc = platypus.SimpleDocTemplate(out, pagesize=pagesizes.A4, title=title)
    story: list[Any] = [platypus.Paragraph(markup(title), styles[1])]
    for b in blocks:
        if b["title"]:
            story.append(platypus.Paragraph(markup(b["title"]), styles[2]))
        if b["kind"] == "text":
            story += pdf_markdown(b["text"], styles)
        elif b["kind"] == "code":
            story.append(platypus.Preformatted(b["text"], styles["code"], maxLineLength=110))
        elif b["kind"] == "table":
            style = styles["small"] if len(b["columns"]) > 5 else styles["body"]
            story.append(pdf_table([b["columns"], *b["rows"]], style, doc.width))
            if b["truncated"]:
                story.append(platypus.Paragraph(f"(primeras {len(b['rows'])} filas)", styles["small"]))
        elif b["kind"] == "image":
            width = min(doc.width, b["width"] * 0.5)  # the app renders charts at twice their size
            story.append(platypus.Image(io.BytesIO(b["png"]), width=width, height=width * b["height"] / b["width"]))
        story.append(platypus.Spacer(1, 8))
    story.append(platypus.Paragraph(markup(footer()), styles["small"]))
    doc.build(story)
    return out.getvalue()
