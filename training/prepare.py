"""Build the training set for one specialist adapter.

    python training/prepare.py training/configs/medicine.yaml [--out training/data] [--distilled FILE]

Steps: license check per source -> download -> format to chat -> quality filter -> dedupe ->
13-gram decontamination against every eval set -> blend with general replay data -> split ->
write train/valid JSONL, an mlx-lm config and a manifest with counts, licenses and file hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train import licenses  # noqa: E402
from spike_train.data import (  # noqa: E402
    FORMATTERS,
    ContaminationIndex,
    dedupe,
    mix_and_split,
    passes_quality,
    text_of,
    write_jsonl,
)


def load_rows(src: dict, offset: int = 0, limit: int | None = None):
    from datasets import load_dataset

    ds = load_dataset(src["hub"], src.get("config"), split=src.get("split", "train"), streaming=True)
    for i, row in enumerate(ds):
        if i < offset:
            continue
        if limit is not None and i >= offset + limit:
            break
        yield row


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def training_schedule(train: dict, n_train: int) -> dict:
    """mlx-lm counts `iters` in micro-batches; the optimizer (and so the LR schedule) steps once every
    grad_accumulation_steps of them, so the cosine decay length is measured in optimizer updates."""
    train = dict(train)
    if "epochs" in train:
        train["iters"] = max(1, math.ceil(float(train.pop("epochs")) * n_train / train.get("batch_size", 4)))
    sched = train.get("lr_schedule")
    if sched and "auto" in sched.get("arguments", []):
        updates = train["iters"] // max(1, int(train.get("grad_accumulation_steps", 1)))
        decay = max(1, updates - int(sched.get("warmup", 0)))
        sched = dict(sched, arguments=[decay if a == "auto" else a for a in sched["arguments"]])
        train["lr_schedule"] = sched
    return train


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default=str(ROOT / "training" / "data"))
    ap.add_argument("--distilled", action="append", default=[], help="extra verified chat JSONL from distill.py")
    ap.add_argument("--skip-license-check", action="store_true", help="only for offline dry runs; never for releases")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]
    from spike.specialists.catalog import load_catalog

    system = load_catalog().get(cfg["specialist"]).system_prompt
    out = Path(args.out) / cfg["specialist"]
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"specialist": cfg["specialist"], "config": cfg, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "sources": {}, "dropped": {"format_or_quality": 0, "duplicate": 0, "contaminated": 0}}

    def checked(name: str, role: str) -> dict:
        src = registry[name]
        declared = src["license"]
        hub = declared if args.skip_license_check else licenses.hub_license(src["hub"])
        ok, reason = licenses.check(hub, role)
        if role == "train" and src["role"] != "train":
            raise SystemExit(f"refusing source '{name}' for training: registry role is '{src['role']}'")
        if not ok:
            raise SystemExit(f"refusing source '{name}': {reason}")
        manifest["sources"][name] = {"hub": src["hub"], "license_hub": hub, "license_registry": declared,
                                     "role": role, "provenance": src.get("provenance", "")}
        return src

    # 1. contamination index from every eval set
    index = ContaminationIndex()
    for name in cfg.get("decontaminate_against", []):
        src = checked(name, "eval")
        fmt = FORMATTERS[src["format"]]
        n = 0
        for row in load_rows(src):
            chat = fmt(row, system)
            if chat:
                index.add(text_of(chat))
                n += 1
        manifest["sources"][name]["indexed_prompts"] = n
    for rel in cfg.get("decontaminate_files", []):  # local held-out prompts, e.g. evals/data/*.jsonl
        rows = [json.loads(line) for line in (ROOT / rel).read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            index.add(row["prompt"])
        manifest["sources"][f"file:{rel}"] = {"role": "eval", "indexed_prompts": len(rows), "sha256": sha256(ROOT / rel)}

    def collect(entries: list[dict], sys_prompt: str | None) -> list[dict]:
        chats = []
        for entry in entries:
            src = checked(entry["source"], "train")
            fmt = FORMATTERS[src["format"]]
            kept = 0
            for row in load_rows(src, entry.get("offset", 0), entry.get("max")):
                chat = fmt(row, sys_prompt) if src["format"] != "messages" else fmt(row)
                if chat is None or not passes_quality(chat):
                    manifest["dropped"]["format_or_quality"] += 1
                    continue
                if index.contaminated(text_of(chat)):
                    manifest["dropped"]["contaminated"] += 1
                    continue
                chats.append(chat)
                kept += 1
            manifest["sources"][entry["source"]]["kept"] = kept
        return chats

    domain = collect(cfg.get("domain_sources", []), system)
    for path in args.distilled:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            chat = json.loads(line)
            chat.pop("meta", None)
            if passes_quality(chat) and not index.contaminated(text_of(chat)):
                domain.append(chat)
        manifest["sources"][f"distilled:{Path(path).name}"] = {"role": "train", "license_hub": "teacher-output (Apache-2.0 teacher)"}
    replay = collect(cfg.get("replay", {}).get("sources", []), None)

    before = len(domain)
    domain = list(dedupe(domain))
    manifest["dropped"]["duplicate"] += before - len(domain)
    train, valid = mix_and_split(domain, replay, cfg.get("replay", {}).get("ratio", 0.0), cfg.get("valid_fraction", 0.02),
                                 seed=cfg.get("seed", 0))
    n_train = write_jsonl(out / "train.jsonl", train)
    n_valid = write_jsonl(out / "valid.jsonl", valid)
    manifest["counts"] = {"domain": len(domain), "replay_available": len(replay), "train": n_train, "valid": n_valid}
    manifest["files"] = {f: sha256(out / f) for f in ("train.jsonl", "valid.jsonl")}

    mlx_cfg = {"model": cfg["base_model"], "train": True, "fine_tune_type": "lora", "data": str(out),
               "seed": cfg.get("seed", 0), "adapter_path": str(ROOT / "training" / "runs" / cfg["specialist"] / "adapter"),
               "steps_per_report": 10, "steps_per_eval": 200, "val_batches": 25, "save_every": 200,
               **training_schedule(cfg["train"], n_train)}
    manifest["counts"]["iters"] = mlx_cfg["iters"]
    (out / "mlx_lora.yaml").write_text(yaml.safe_dump(mlx_cfg, sort_keys=False))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest["counts"] | manifest["dropped"], indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
