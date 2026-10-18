"""Convert an mlx-lm LoRA adapter into a Hugging Face PEFT adapter (then GGUF with llama.cpp).

mlx-lm computes  y += scale * (x @ A) @ B   with A: (in, r), B: (r, out)
PEFT computes    y += (alpha / r) * B'(A'(x)) with A'.weight: (r, in), B'.weight: (out, r)
so A' = A.T, B' = B.T and alpha = scale * r.

Module paths differ between frameworks, so the mapping is explicit and every target is verified against
the base model's own tensor names (model.safetensors.index.json) before anything is written.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import numpy as np

_DTYPES = {"F32": np.float32, "F16": np.float16, "F64": np.float64}

DEFAULT_PREFIX_MAP = [
    # mlx-lm Qwen3.5 (VLM wrapper)          -> Hugging Face Qwen3_5ForConditionalGeneration
    (r"^language_model\.model\.", "model.language_model."),
    # plain causal LM layouts
    (r"^model\.", "model."),
]


def map_module(mlx_module: str, prefix_map: list[tuple[str, str]]) -> str:
    for pattern, repl in prefix_map:
        if re.match(pattern, mlx_module):
            return re.sub(pattern, repl, mlx_module, count=1)
    raise ValueError(f"no prefix rule matches module '{mlx_module}'")


def convert(
    adapter_weights: dict[str, np.ndarray],
    adapter_config: dict,
    base_weight_names: set[str] | None = None,
    prefix_map: list[tuple[str, str]] | None = None,
    base_model_name: str = "",
) -> tuple[dict[str, np.ndarray], dict]:
    prefix_map = prefix_map or DEFAULT_PREFIX_MAP
    params = adapter_config.get("lora_parameters", {})
    rank, scale = int(params.get("rank", 8)), float(params.get("scale", 20.0))
    modules: dict[str, dict[str, np.ndarray]] = {}
    for key, value in adapter_weights.items():
        m = re.match(r"^(.*)\.(lora_a|lora_b)$", key)
        if not m:
            raise ValueError(f"unexpected tensor in adapter: {key}")
        modules.setdefault(m.group(1), {})[m.group(2)] = value

    out: dict[str, np.ndarray] = {}
    targets: set[str] = set()
    for module, ab in sorted(modules.items()):
        if set(ab) != {"lora_a", "lora_b"}:
            raise ValueError(f"{module}: needs both lora_a and lora_b")
        a, b = ab["lora_a"], ab["lora_b"]
        if a.ndim != 2 or b.ndim != 2 or a.shape[1] != rank or b.shape[0] != rank:
            raise ValueError(f"{module}: unexpected shapes A{a.shape} B{b.shape} for rank {rank}")
        hf_module = map_module(module, prefix_map)
        if base_weight_names is not None and f"{hf_module}.weight" not in base_weight_names:
            raise ValueError(f"{hf_module}.weight does not exist in the base model; fix the prefix map")
        out[f"base_model.model.{hf_module}.lora_A.weight"] = np.ascontiguousarray(a.T)
        out[f"base_model.model.{hf_module}.lora_B.weight"] = np.ascontiguousarray(b.T)
        targets.add(hf_module.rsplit(".", 1)[-1])

    peft_config = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "base_model_name_or_path": base_model_name,
        "r": rank,
        "lora_alpha": scale * rank,
        "lora_dropout": float(params.get("dropout", 0.0)),
        "target_modules": sorted(targets),
        "bias": "none",
        "fan_in_fan_out": False,
        "inference_mode": True,
    }
    return out, peft_config


def read_safetensors(path: Path) -> dict[str, np.ndarray]:
    """Minimal safetensors reader (F32/F16/F64/BF16 -> numpy). numpy has no bfloat16, so BF16 becomes F32."""
    raw = Path(path).read_bytes()
    (n,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8:8 + n])
    data = memoryview(raw)[8 + n:]
    out: dict[str, np.ndarray] = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        start, end = info["data_offsets"]
        buf = data[start:end]
        if info["dtype"] == "BF16":
            arr = (np.frombuffer(buf, dtype="<u2").astype(np.uint32) << 16).view(np.float32)
        elif info["dtype"] in _DTYPES:
            arr = np.frombuffer(buf, dtype=np.dtype(_DTYPES[info["dtype"]]).newbyteorder("<"))
        else:
            raise ValueError(f"{name}: unsupported dtype {info['dtype']}")
        out[name] = arr.reshape(info["shape"]).copy()
    return out


def write_safetensors(path: Path, tensors: dict[str, np.ndarray], metadata: dict[str, str] | None = None) -> None:
    header: dict = {"__metadata__": metadata or {"format": "pt"}}
    offset, blobs = 0, []
    for name in sorted(tensors):
        arr = np.ascontiguousarray(tensors[name], dtype=np.float32)
        blob = arr.astype("<f4").tobytes()
        header[name] = {"dtype": "F32", "shape": list(arr.shape), "data_offsets": [offset, offset + len(blob)]}
        offset += len(blob)
        blobs.append(blob)
    head = json.dumps(header, separators=(",", ":")).encode()
    head += b" " * (-len(head) % 8)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(head)))
        f.write(head)
        for blob in blobs:
            f.write(blob)


def load_base_weight_names(base_dir: Path) -> set[str]:
    index = base_dir / "model.safetensors.index.json"
    if index.exists():
        return set(json.loads(index.read_text())["weight_map"])
    names: set[str] = set()
    for f in base_dir.glob("*.safetensors"):
        with f.open("rb") as fh:
            (n,) = struct.unpack("<Q", fh.read(8))
            names |= set(json.loads(fh.read(n))) - {"__metadata__"}
    if not names:
        raise FileNotFoundError(f"no safetensors weights or index in {base_dir}")
    return names
