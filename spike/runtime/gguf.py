"""Minimal GGUF metadata reader (header + key/value pairs only; tensor data is never loaded).

Used by `spike doctor` to compute the real memory footprint of a model file, including its KV cache,
from the architecture fields stored in the file instead of guessing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

GGUF_MAGIC = b"GGUF"
_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
STRING, ARRAY = 8, 9


def _read(f: BinaryIO, fmt: str) -> Any:
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise ValueError("truncated GGUF file")
    return struct.unpack(fmt, data)[0]


def _read_str(f: BinaryIO) -> str:
    n = _read(f, "<Q")
    if n > 1 << 24:
        raise ValueError("GGUF string too long")
    return f.read(n).decode("utf-8", "replace")


def _read_value(f: BinaryIO, vtype: int, max_array: int) -> Any:
    if vtype in _SCALARS:
        return _read(f, _SCALARS[vtype])
    if vtype == STRING:
        return _read_str(f)
    if vtype == ARRAY:
        itype, count = _read(f, "<I"), _read(f, "<Q")
        items = []
        for i in range(count):
            value = _read_value(f, itype, max_array)
            if i < max_array:
                items.append(value)
        return items if count <= max_array else {"length": count, "head": items}
    raise ValueError(f"unknown GGUF value type {vtype}")


@dataclass
class GGUFInfo:
    version: int
    tensor_count: int
    metadata: dict[str, Any]
    file_size: int

    @property
    def arch(self) -> str:
        return str(self.metadata.get("general.architecture", "unknown"))

    def field(self, name: str, default: Any = None) -> Any:
        return self.metadata.get(f"{self.arch}.{name}", default)


def read_gguf(path: str | Path, max_array: int = 64) -> GGUFInfo:
    path = Path(path)
    with path.open("rb") as f:
        if f.read(4) != GGUF_MAGIC:
            raise ValueError(f"{path} is not a GGUF file")
        version = _read(f, "<I")
        tensor_count, kv_count = _read(f, "<Q"), _read(f, "<Q")
        metadata: dict[str, Any] = {}
        for _ in range(kv_count):
            key = _read_str(f)
            metadata[key] = _read_value(f, _read(f, "<I"), max_array)
    return GGUFInfo(version=version, tensor_count=tensor_count, metadata=metadata, file_size=path.stat().st_size)


KV_BYTES = {"f16": 2.0, "bf16": 2.0, "f32": 4.0, "q8_0": 34 / 32, "q4_0": 18 / 32}


def _per_layer(value: Any, n_layers: int) -> list[int]:
    if isinstance(value, list):
        return [int(v) for v in value[:n_layers]]
    return [int(value or 0)] * n_layers


def kv_cache_bytes(info: GGUFInfo, context: int, cache_type: str = "f16") -> int:
    """KV cache size for `context` tokens.

    Hybrid models (e.g. Qwen3.5: Gated DeltaNet + full attention) only keep a KV cache in their full-attention
    layers; GGUF marks the interval with `full_attention_interval`. Recurrent state is reported separately.
    """
    n_layers = int(info.field("block_count", 0))
    heads_kv = _per_layer(info.field("attention.head_count_kv", info.field("attention.head_count", 0)), n_layers)
    key_len = int(info.field("attention.key_length", 0) or 0)
    val_len = int(info.field("attention.value_length", 0) or 0)
    if not key_len:
        embd, heads = int(info.field("embedding_length", 0)), int(info.field("attention.head_count", 1) or 1)
        key_len = val_len = embd // heads if heads else 0
    interval = int(info.field("full_attention_interval", 1) or 1)
    per_token = 0.0
    for layer in range(n_layers):
        if interval > 1 and (layer + 1) % interval != 0:
            continue  # linear-attention layer: constant-size state, no KV cache
        per_token += heads_kv[layer] * (key_len + val_len)
    return int(per_token * KV_BYTES.get(cache_type, 2.0) * context)
