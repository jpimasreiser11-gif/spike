"""Model manifest and verified downloads from Hugging Face."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from spike.runtime.paths import models_dir

HF = "https://huggingface.co"


@dataclass(frozen=True)
class ModelEntry:
    id: str
    repo: str
    filename_template: str
    license: str
    quants: tuple[str, ...]
    default_quant: str
    notes: str = ""

    def filename(self, quant: str) -> str:
        return self.filename_template.format(quant=quant)


# The SPIKE base model (docs/adr/0001-base-model.md). Files are community GGUF conversions of the official
# Apache-2.0 weights; the license is checked again at download time from the Hub metadata.
MODELS: dict[str, ModelEntry] = {
    "qwen3.5-4b": ModelEntry(
        id="qwen3.5-4b", repo="unsloth/Qwen3.5-4B-GGUF", filename_template="Qwen3.5-4B-{quant}.gguf",
        license="apache-2.0", quants=("Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "IQ4_XS", "Q3_K_M"), default_quant="Q4_K_M",
        notes="Text-only use; the vision projector (mmproj) is not downloaded.",
    ),
    "qwen3.5-2b": ModelEntry(
        id="qwen3.5-2b", repo="unsloth/Qwen3.5-2B-GGUF", filename_template="Qwen3.5-2B-{quant}.gguf",
        license="apache-2.0", quants=("Q4_K_M", "Q8_0"), default_quant="Q4_K_M",
        notes="Fallback for machines with 8 GB of RAM or less.",
    ),
}

ALLOWED_LICENSES = {"apache-2.0", "mit", "bsd-3-clause", "cc-by-4.0"}


async def remote_file_info(client: httpx.AsyncClient, repo: str, filename: str) -> dict:
    """Return {'size', 'sha256', 'license'} for a file in a Hub repo."""
    model = (await client.get(f"{HF}/api/models/{repo}")).raise_for_status().json()
    license_id = (model.get("cardData") or {}).get("license") or next(
        (t.split(":", 1)[1] for t in model.get("tags", []) if t.startswith("license:")), None)
    tree = (await client.get(f"{HF}/api/models/{repo}/tree/main")).raise_for_status().json()
    entry = next((f for f in tree if f.get("path") == filename), None)
    if entry is None:
        raise FileNotFoundError(f"{filename} not found in {repo}")
    lfs = entry.get("lfs") or {}
    return {"size": lfs.get("size") or entry.get("size"), "sha256": lfs.get("oid"), "license": license_id}


async def download(
    model_id: str,
    quant: str | None = None,
    dest_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    client: httpx.AsyncClient | None = None,
) -> Path:
    entry = MODELS[model_id]
    quant = quant or entry.default_quant
    if quant not in entry.quants:
        raise ValueError(f"quant must be one of {entry.quants}")
    filename = entry.filename(quant)
    dest = (dest_dir or models_dir()) / filename
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True)
    try:
        info = await remote_file_info(client, entry.repo, filename)
        if info["license"] and info["license"].lower() not in ALLOWED_LICENSES:
            raise PermissionError(f"{entry.repo} has license '{info['license']}', which is not on SPIKE's allowlist")
        if dest.exists() and info["sha256"] and sha256_file(dest) == info["sha256"]:
            return dest
        part = dest.with_suffix(dest.suffix + ".part")
        offset = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        async with client.stream("GET", f"{HF}/{entry.repo}/resolve/main/{filename}", headers=headers) as r:
            r.raise_for_status()
            if offset and r.status_code != 206:
                offset = 0  # server ignored the range: restart
            total = info["size"] or int(r.headers.get("content-length", 0)) + offset
            with part.open("ab" if offset else "wb") as f:
                done = offset
                async for chunk in r.aiter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if info["sha256"]:
            digest = sha256_file(part)
            if digest != info["sha256"]:
                part.unlink(missing_ok=True)
                raise ValueError(f"checksum mismatch for {filename}: expected {info['sha256']}, got {digest}")
        part.rename(dest)
        return dest
    finally:
        if own_client:
            await client.aclose()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def local_models() -> list[Path]:
    return sorted(models_dir().glob("*.gguf"))
