"""Registry sources that are not on the Hub: JSON files fetched from URLs pinned to a commit.

A source with `urls: [{url, sha256}]` records its own `license`, `license_url` (the LICENSE file at the pinned
`revision`) and, when each file holds documents with several questions, `explode: <key>` to get one row per
question. The Hub cannot be asked about such a source, so the license gate checks the recorded license. Every
load checks every file against its registry sha256, cached or not; a mismatch is a hard error and is never
retried or repaired. Downloaded files are untrusted data: they are only ever parsed as JSON.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import urlparse


def cache_dir() -> Path:
    """Next to the Hugging Face datasets cache, so one setting (HF_DATASETS_CACHE / HF_HOME) moves both."""
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return Path(os.environ.get("HF_DATASETS_CACHE") or hf_home / "datasets") / "spike-urls"


def _get(url: str) -> bytes:
    import httpx

    return httpx.get(url, follow_redirects=True, timeout=120).raise_for_status().content


def validate(src: dict) -> None:
    """A URL source must be pinned (commit in every URL, sha256 per file) and carry a license and where to read it."""
    for key in ("urls", "revision", "license", "license_url"):
        if not src.get(key):
            raise ValueError(f"URL source needs '{key}'")
    for entry in src["urls"]:
        if urlparse(entry.get("url", "")).scheme != "https" or src["revision"] not in entry["url"]:
            raise ValueError(f"{entry.get('url')}: must be an https URL containing the pinned revision {src['revision']}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            raise ValueError(f"{entry['url']}: sha256 must be 64 lowercase hex characters")


def read_verified(entry: dict, cache: Path | None = None) -> bytes:
    """The file's bytes, from the cache or else downloaded; only bytes that match the registry sha256 are returned
    or cached."""
    cache = cache or cache_dir()
    path = cache / f"{entry['sha256']}-{Path(urlparse(entry['url']).path).name}"
    cached = path.is_file()
    data = path.read_bytes() if cached else _get(entry["url"])
    got = hashlib.sha256(data).hexdigest()
    if got != entry["sha256"]:
        raise ValueError(f"sha256 mismatch for {entry['url']}: registry {entry['sha256']}, got {got}"
                         + (f" (cached copy {path}; delete it to download again)" if cached else ""))
    if not cached:
        cache.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return data


def url_rows(src: dict, cache: Path | None = None) -> Iterator[dict]:
    validate(src)
    explode = src.get("explode")
    for entry in src["urls"]:
        docs = json.loads(read_verified(entry, cache).decode("utf-8"))
        if not isinstance(docs, list):
            raise ValueError(f"{entry['url']}: expected a JSON list of rows")
        for doc in docs:
            if explode:  # one row per item of doc[explode], the rest of the document repeated, the item as "qa"
                rest = {k: v for k, v in doc.items() if k != explode}
                yield from ({**rest, "qa": item} for item in doc[explode])
            else:
                yield doc


def filtered(src: dict, rows: Iterable[dict], per_value: int | None = None) -> Iterator[dict]:
    """Apply `filter: {column: [allowed values]}` (a Hub dataset that aggregates sources of different licenses, such
    as Sujet-Finance, is kept per upstream source). A filter that matches no row at all is an error, not an empty
    source; rows without the column are dropped.

    `per_value` (a config entry's `max_per_value`) keeps at most that many rows for each allowed value of the
    filter's one column: the first ones in stream order, so the cap is deterministic and no value can crowd out
    the others. Streaming stops once every value has its share; a value with no row at all is an error. Nothing
    is redistributed when a value has fewer rows than the cap."""
    allowed = src.get("filter")
    if per_value is not None and (not allowed or len(allowed) != 1):
        raise ValueError("max_per_value needs a source whose filter names exactly one column")
    if not allowed:
        yield from rows
        return
    column, values = next(iter(allowed.items()))
    counts = dict.fromkeys(values, 0)
    kept = 0
    for row in rows:
        if not all(row.get(c) in vs for c, vs in allowed.items()):
            continue
        if per_value is not None:
            if counts[row[column]] >= per_value:
                continue
            counts[row[column]] += 1
        kept += 1
        yield row
        if per_value is not None and all(n >= per_value for n in counts.values()):
            return
    if not kept:
        raise ValueError(f"filter {allowed} matched no row; check the column and values against the dataset")
    if per_value is not None and (missing := [v for v, n in counts.items() if not n]):
        raise ValueError(f"filter value(s) {missing} matched no row; check them against the dataset")


def origin(src: dict) -> dict:
    """Where a source's rows come from, as written to the training manifest and the model card."""
    out = {"hub": src["hub"]} if "hub" in src else {
        "urls": src["urls"], "revision": src["revision"], "repo": src.get("repo"), "license_url": src["license_url"]}
    if src.get("filter"):
        out["filter"] = src["filter"]
    return out
