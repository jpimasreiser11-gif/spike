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
    kind: str = "chat"  # "chat" or "embedding"
    query_prefix: str = ""  # embedding models: text put before a search query (not before stored passages)

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
    # Neural Memory's semantic search. Official GGUF by Qwen; llama.cpp usage per the model card:
    # `--embedding --pooling last`, and an instruction before queries only.
    "qwen3-embedding-0.6b": ModelEntry(
        id="qwen3-embedding-0.6b", repo="Qwen/Qwen3-Embedding-0.6B-GGUF",
        filename_template="Qwen3-Embedding-0.6B-{quant}.gguf", license="apache-2.0", quants=("Q8_0", "f16"),
        default_quant="Q8_0", kind="embedding",
        query_prefix="Instruct: Given a question, retrieve notes and passages that help answer it\nQuery: ",
        notes="Memory search by meaning (Neural Memory); 100+ languages, 639 MB.",
    ),
}
EMBEDDING_MODEL = "qwen3-embedding-0.6b"

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
    require_hash: bool = False,
) -> tuple[Path, bool]:
    """Download a model; returns (file, whether the Hub's SHA-256 was checked). The Hub may give no hash."""
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
        if require_hash and (not info["license"] or not info["sha256"]):
            raise ValueError("A license and SHA-256 are required for desktop installation")
        await download_file(client, f"{HF}/{entry.repo}/resolve/main/{filename}", dest,
                            info["sha256"], info["size"], progress)
        return dest, bool(info["sha256"])
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


async def download_file(
    client: httpx.AsyncClient, url: str, dest: Path, digest: str | None,
    size: int | None = None, progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Shared installer transfer: resume a partial file, verify before atomic replacement.

    A server ignoring Range restarts from zero; a malformed partial response is rejected. Completed partial
    files are verified before another request (an interrupted final rename needs no re-download). A bad hash
    removes only the partial, preserving any previously installed file. Callers control the source and path.
    """
    if digest is not None and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("Invalid SHA-256")
    part = dest.with_suffix(dest.suffix + ".part")
    if dest.is_symlink() or part.is_symlink():
        raise ValueError("Refusing a symlink download destination")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and digest and sha256_file(dest) == digest:
        return dest
    if part.is_file() and digest and sha256_file(part) == digest:
        part.replace(dest)
        return dest
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    async with client.stream("GET", url, headers=headers) as response:
        response.raise_for_status()
        if response.status_code == 206:
            content_range = response.headers.get("content-range", "")
            if not content_range.startswith(f"bytes {offset}-"):
                raise ValueError("Invalid download Content-Range")
        elif offset:
            offset = 0
        total = size or int(response.headers.get("content-length", 0)) + offset
        with part.open("ab" if offset else "wb") as target:
            done = offset
            async for chunk in response.aiter_bytes(1 << 20):
                target.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if digest and sha256_file(part) != digest:
        part.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch for {dest.name}")
    if size is not None and part.stat().st_size != size:
        raise ValueError("Incomplete download")
    part.replace(dest)
    return dest
