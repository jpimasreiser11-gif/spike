"""Export a trained mlx-lm adapter as a llama.cpp GGUF LoRA that the SPIKE runtime loads next to the base model.

    python training/export_adapter.py medicine --llama-cpp ~/src/llama.cpp \
        [--adapter training/runs/medicine/adapter] [--base Qwen/Qwen3.5-4B] [--out ~/.spike/adapters] \
        [--check-model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf]

1. MLX -> PEFT: transpose A/B, alpha = scale * r, module names mapped and checked against the base checkpoint.
2. PEFT -> GGUF with llama.cpp's own convert_lora_to_gguf.py (needs the base config only, not its weights).
3. GGUF metadata check (adapter type, alpha, tensor count).
4. --check-model: load base + adapter in llama-server and require that the adapter changes greedy outputs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train.export import convert, load_base_weight_names, read_safetensors, write_safetensors  # noqa: E402

PROBES = [
    "Give three concrete recommendations for the most common problem in your field, with a reason for each.",
    "Explica en cuatro frases un concepto básico de tu especialidad a alguien que empieza.",
    "What is a frequent mistake beginners make in your domain, and how do you avoid it?",
    "List the first questions you would ask a new client before giving any advice.",
]


def resolve_base(base: str) -> Path:
    path = Path(base).expanduser()
    if path.is_dir():
        return path
    from huggingface_hub import snapshot_download

    # config, tokenizer files and the weight index only: the converter needs no weights
    return Path(snapshot_download(base, allow_patterns=["*.json", "*.txt", "*.model", "*.jinja"]))


def to_peft(adapter_dir: Path, base_dir: Path, base_id: str, peft_dir: Path) -> dict:
    cfg = json.loads((adapter_dir / "adapter_config.json").read_text())
    if cfg.get("fine_tune_type", "lora") != "lora":
        raise SystemExit(f"only LoRA adapters can be exported, got {cfg.get('fine_tune_type')}")
    weights = read_safetensors(adapter_dir / "adapters.safetensors")
    tensors, peft_cfg = convert(weights, cfg, load_base_weight_names(base_dir), base_model_name=base_id)
    peft_dir.mkdir(parents=True, exist_ok=True)
    write_safetensors(peft_dir / "adapter_model.safetensors", tensors)
    (peft_dir / "adapter_config.json").write_text(json.dumps(peft_cfg, indent=2))
    return peft_cfg | {"tensors": len(tensors)}


def check_gguf(path: Path, peft: dict) -> dict:
    from spike.runtime.gguf import read_gguf

    info = read_gguf(path)
    meta = info.metadata
    problems = []
    if meta.get("general.type") != "adapter" or meta.get("adapter.type") != "lora":
        problems.append(f"not a LoRA adapter GGUF (general.type={meta.get('general.type')}, adapter.type={meta.get('adapter.type')})")
    alpha = meta.get("adapter.lora.alpha")
    if alpha is None or abs(float(alpha) - float(peft["lora_alpha"])) > 1e-6:
        problems.append(f"alpha {alpha} != expected {peft['lora_alpha']}")
    if info.tensor_count == 0:
        problems.append("no tensors")
    if problems:
        raise SystemExit("GGUF check failed: " + "; ".join(problems))
    return {"arch": info.arch, "tensors": info.tensor_count, "alpha": alpha, "bytes": info.file_size}


async def live_check(model: Path, adapter: Path, system: str, ngl: int) -> dict:
    """The adapter must change greedy outputs; identical outputs mean it was not applied or is empty."""
    from spike_train.evaluation import Client, free_port

    from spike.runtime.llamacpp_server import LlamaServer, ServerConfig

    server = LlamaServer(ServerConfig(model=model, adapters=[adapter], port=free_port(), context=4096, gpu_layers=ngl))
    await server.start()
    client = Client(server.base_url)
    try:
        (stem, _), = (await client.adapters()).items()
        rows = []
        for probe in PROBES:
            base = (await client.chat(system, probe, client.lora(None), 64))["content"]
            tuned = (await client.chat(system, probe, client.lora(stem), 64))["content"]
            again = (await client.chat(system, probe, client.lora(None), 64))["content"]
            rows.append({"probe": probe, "base": base, "adapter": tuned, "base_repeat_identical": base == again,
                         "changed": base != tuned})
        changed = sum(r["changed"] for r in rows)
        if not all(r["base_repeat_identical"] for r in rows):
            raise SystemExit("base outputs are not deterministic; cannot judge the adapter (check the server)")
        if changed == 0:
            raise SystemExit("the adapter did not change any output: export or loading is broken")
        return {"adapter": stem, "probes": len(rows), "outputs_changed": changed, "samples": rows}
    finally:
        await client.aclose()
        await server.stop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("specialist")
    ap.add_argument("--llama-cpp", required=True, help="llama.cpp checkout containing convert_lora_to_gguf.py")
    ap.add_argument("--adapter", help="mlx-lm adapter dir (default training/runs/<specialist>/adapter)")
    ap.add_argument("--base", default="Qwen/Qwen3.5-4B", help="HF repo id or local dir of the training base")
    ap.add_argument("--out", default="~/.spike/adapters")
    ap.add_argument("--outtype", default="f16", choices=["f32", "f16", "bf16", "q8_0"])
    ap.add_argument("--python", default=sys.executable, help="interpreter with the converter's requirements")
    ap.add_argument("--check-model", help="base GGUF for the live check")
    ap.add_argument("--ngl", type=int, default=99)
    args = ap.parse_args()

    run_dir = ROOT / "training" / "runs" / args.specialist
    adapter_dir = Path(args.adapter or run_dir / "adapter")
    base_dir = resolve_base(args.base)
    peft = to_peft(adapter_dir, base_dir, args.base, run_dir / "peft")
    print(f"PEFT adapter: r={peft['r']} alpha={peft['lora_alpha']} targets={peft['target_modules']} tensors={peft['tensors']}")

    out = Path(args.out).expanduser() / f"spike-{args.specialist}.gguf"
    out.parent.mkdir(parents=True, exist_ok=True)
    converter = Path(args.llama_cpp).expanduser() / "convert_lora_to_gguf.py"
    subprocess.run([args.python, str(converter), str(run_dir / "peft"), "--base", str(base_dir),
                    "--outfile", str(out), "--outtype", args.outtype], check=True)
    report = {"gguf": str(out), "peft": {k: v for k, v in peft.items() if k != "tensors"}, "check": check_gguf(out, peft)}
    print(f"GGUF adapter: {out} ({report['check']['tensors']} tensors, arch {report['check']['arch']})")

    if args.check_model:
        from spike.specialists.catalog import load_catalog

        system = load_catalog().get(args.specialist).system_prompt
        report["live_check"] = asyncio.run(live_check(Path(args.check_model).expanduser(), out, system, args.ngl))
        print(f"live check: adapter changed {report['live_check']['outputs_changed']}/{len(PROBES)} greedy outputs")
    (run_dir / "export.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
