"""Sample projects shipped with SPIKE (G39): six small projects, each in Spanish and English, ready to try.

They live as plain files under `data/<id>/`: `sample.json` (name, description, instructions, default specialist and
project notes per language) and `data/<id>/<lang>/` (the project's files, copied as they are). `build_archive` packs one
language of one sample into a normal project archive (the format of `spike.projects`), so importing a sample is exactly
importing a project: no second code path. All content is invented for this repository: no real people, companies or
brands, and no text from other sources. The finance case is paper trading only.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from spike.projects import FORMAT, VERSION, _entry

DATA = Path(__file__).parent / "data"
SAMPLE_IDS = ("expenses", "report", "webpage", "handbook", "workflow", "finance")
LANGS = ("es", "en")


def norm_lang(lang: str | None) -> str:
    return lang if lang in LANGS else "en"


def _meta(sample_id: str) -> dict[str, Any]:
    if sample_id not in SAMPLE_IDS:
        raise KeyError(sample_id)
    return json.loads((DATA / sample_id / "sample.json").read_text(encoding="utf-8"))


def _files(sample_id: str, lang: str) -> list[Path]:
    base = DATA / sample_id / lang
    return sorted(p for p in base.rglob("*") if p.is_file())


def list_samples(lang: str | None) -> list[dict[str, Any]]:
    lang = norm_lang(lang)
    out = []
    for sid in SAMPLE_IDS:
        meta = _meta(sid)
        files = _files(sid, lang)
        out.append({"id": sid, "name": meta[lang]["name"], "description": meta[lang]["description"],
                    "feature": meta["feature"], "files": len(files), "bytes": sum(p.stat().st_size for p in files)})
    return out


def build_archive(sample_id: str, lang: str | None) -> bytes:
    """The sample as a project archive (zip). Raises KeyError for an unknown sample."""
    lang = norm_lang(lang)
    meta = _meta(sample_id)
    text = meta[lang]
    manifest = {"format": FORMAT, "version": VERSION,
                "project": {"name": text["name"], "instructions": text["instructions"], "mode": text["mode"],
                            "design": ""},
                "conversations": [], "memories": text.get("memories", [])}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_entry("project.json"), json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
        base = DATA / sample_id / lang
        for path in _files(sample_id, lang):
            z.writestr(_entry(f"files/{path.relative_to(base).as_posix()}"), path.read_bytes())
    return buf.getvalue()
