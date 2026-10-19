"""Build the training set for one specialist adapter.

    python training/prepare.py training/configs/medicine.yaml [--out training/data] [--distilled FILE]
        [--corrections spike-training.jsonl]

Steps: license check per source (and per distillation teacher) -> download -> format to chat -> quality filter ->
dedupe -> 13-gram decontamination against every eval set -> blend with general replay data -> split ->
write train/valid JSONL, an mlx-lm config and a manifest with counts, licenses and file hashes.
A recipe with no domain_sources (marketing) needs --distilled data: with none, the run stops instead of writing
an empty training set.
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
    BUILDERS,
    FORMATTERS,
    ContaminationIndex,
    dedupe,
    mix_and_split,
    passes_quality,
    text_of,
    write_jsonl,
)
from spike_train.sources import filtered, origin, url_rows  # noqa: E402


def load_rows(src: dict, offset: int = 0, limit: int | None = None, per_value: int | None = None):
    if "urls" in src:  # pinned files instead of the Hub (spike_train/sources.py)
        ds = url_rows(src)
    else:
        from datasets import load_dataset

        ds = load_dataset(src["hub"], src.get("config"), split=src.get("split", "train"), streaming=True)
    for i, row in enumerate(filtered(src, ds, per_value)):  # `filter:` of the registry entry; offset, limit count kept rows
        if i < offset:
            continue
        if limit is not None and i >= offset + limit:
            break
        yield row


def load_token_counter(base_model: str):
    """Tokens of a chat as the trainer sees it (the base model's chat template), for the length filter."""
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(base_model)
    return lambda chat: len(tok(tok.apply_chat_template(chat["messages"], tokenize=False))["input_ids"])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_distilled(path: Path) -> tuple[list[dict], dict[str, str | None]]:
    """Chats of a distill.py file, and the teachers (repo -> license recorded when it wrote them) behind them.
    A row without a teacher record stops the run: its license would be unknown."""
    chats: list[dict] = []
    teachers: dict[str, str | None] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        chat = json.loads(line)
        meta = chat.pop("meta", None) or {}
        if not meta.get("teacher"):
            raise SystemExit(f"{path.name}:{n} has no teacher record; make it again with training/distill.py "
                             "(it records the teacher's repo and license)")
        teachers[meta["teacher"]] = meta.get("teacher_license")
        chats.append(chat)
    return chats, teachers


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
    ap.add_argument("--corrections", action="append", default=[],
                    help="approved corrections from `spike evolve dataset` (spike-training.jsonl); only this specialist's")
    ap.add_argument("--skip-license-check", action="store_true", help="only for offline dry runs; never for releases")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    from spike.specialists.catalog import load_catalog

    system = load_catalog().get(cfg["specialist"]).system_prompt
    out = Path(args.out) / cfg["specialist"]
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"specialist": cfg["specialist"], "config": cfg, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "sources": {}, "dropped": {"format_or_quality": 0, "duplicate": 0, "contaminated": 0, "too_long": 0}}

    def checked(name: str, role: str) -> dict:
        src = registry[name]
        if manifest["sources"].get(name, {}).get("role") == role:
            return src
        declared = src["license"]
        hub = declared if args.skip_license_check else licenses.source_license(src)
        ok, reason = licenses.check(hub, role)
        if role == "train" and src["role"] != "train":
            raise SystemExit(f"refusing source '{name}' for training: registry role is '{src['role']}'")
        if not ok:
            raise SystemExit(f"refusing source '{name}': {reason}")
        manifest["sources"][name] = {**origin(src), "license_hub": hub, "license_registry": declared,
                                     "role": role, "provenance": src.get("provenance", "")}
        return src

    def no_domain_data() -> SystemExit:  # replay alone would train on nothing of the domain, and empty files look fine
        distilled_out = f"training/data/{cfg['specialist']}/distilled.jsonl"
        fix = (f"run `python training/distill.py {args.config} --out {distilled_out}` first and pass it with "
               "--distilled" if (cfg.get("distill") or {}).get("enabled")
               else "add domain_sources to the config or pass --distilled / --corrections data")
        return SystemExit(f"no domain training data for '{cfg['specialist']}': {len(cfg.get('domain_sources', []))} "
                          f"domain sources, {len(args.distilled)} distilled and {len(args.corrections)} correction "
                          f"files gave no usable chats; {fix}")

    if not (cfg.get("domain_sources") or args.distilled or args.corrections):
        raise no_domain_data()  # marketing without distilled data: stop now, not after the eval sets are downloaded

    # 0. every license and registry role, before anything is downloaded
    for name in cfg.get("decontaminate_against", []):
        checked(name, "eval")
    for entry in cfg.get("domain_sources", []) + cfg.get("replay", {}).get("sources", []):
        checked(entry["source"], "train")
    distilled: dict[str, list[dict]] = {}
    for path in args.distilled:  # a teacher's terms travel with every example it wrote: same allowlist as datasets
        chats, teachers = load_distilled(Path(path))
        distilled[path] = chats
        record = {"role": "train", "teachers": {}}
        for repo, recorded in teachers.items():
            try:
                if args.skip_license_check:  # offline: trust the license distill.py recorded, still on the allowlist
                    ok, reason = licenses.check(recorded, "train")
                    if not ok:
                        raise ValueError(f"teacher '{repo}': {reason}")
                    lic = reason
                else:  # live from the Hub, like the datasets
                    lic = licenses.teacher_license(repo)
            except ValueError as exc:
                raise SystemExit(f"refusing {Path(path).name}: {exc}") from exc
            record["teachers"][repo] = {"license_hub": lic, "license_recorded": recorded}
        manifest["sources"][f"distilled:{Path(path).name}"] = record

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

    # mlx-lm would truncate longer chats, cutting off the answer (or all of it, giving a NaN loss): drop them
    max_len = cfg["train"].get("max_seq_length")
    n_tokens = load_token_counter(cfg["base_model"]) if max_len else None

    def too_long(chat: dict) -> bool:
        if n_tokens and n_tokens(chat) > max_len:
            manifest["dropped"]["too_long"] += 1
            return True
        return False

    def collect(entries: list[dict], sys_prompt: str | None) -> list[dict]:
        chats = []
        for entry in entries:
            src = checked(entry["source"], "train")
            start, limit = entry.get("offset", 0), entry.get("max")
            cap = {"per_value": entry["max_per_value"]} if "max_per_value" in entry else {}  # balanced filtered source
            if src["format"] in BUILDERS:  # needs every row of the source before it can emit a chat
                built = BUILDERS[src["format"]](load_rows(src, **cap), **src.get("options", {}))
                if not built:
                    raise SystemExit(f"source '{entry['source']}' produced no chats; check its schema against the builder")
                manifest["sources"][entry["source"]]["built"] = len(built)
                candidates = iter(built[start: None if limit is None else start + limit])
            else:
                fmt = FORMATTERS[src["format"]]
                candidates = (fmt(row, sys_prompt) if src["format"] != "messages" else fmt(row)
                              for row in load_rows(src, start, limit, **cap))
            kept = 0
            for chat in candidates:
                if chat is None or not passes_quality(chat):
                    manifest["dropped"]["format_or_quality"] += 1
                    continue
                if too_long(chat):
                    continue
                if index.contaminated(text_of(chat)):
                    manifest["dropped"]["contaminated"] += 1
                    continue
                chats.append(chat)
                kept += 1
            manifest["sources"][entry["source"]]["kept"] = kept
        return chats

    domain = collect(cfg.get("domain_sources", []), system)
    for path, chats in distilled.items():
        kept = 0
        for chat in chats:
            if passes_quality(chat) and not too_long(chat) and not index.contaminated(text_of(chat)):
                domain.append(chat)
                kept += 1
        manifest["sources"][f"distilled:{Path(path).name}"]["kept"] = kept
    for path in args.corrections:  # Evolution level 3: the user's approved corrections (`spike evolve dataset`)
        kept = 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            chat = json.loads(line)
            meta = chat.pop("meta", None) or {}
            if meta.get("source") != "spike-correction" or meta.get("specialist") != cfg["specialist"]:
                continue
            chat["messages"] = [{"role": "system", "content": system},
                                *(m for m in chat["messages"] if m["role"] != "system")]
            dropped = ("format_or_quality" if not passes_quality(chat) else "too_long" if too_long(chat)
                       else "contaminated" if index.contaminated(text_of(chat)) else None)
            if dropped:
                manifest["dropped"][dropped] += 1
            else:
                domain.append(chat)
                kept += 1
        manifest["sources"][f"corrections:{Path(path).name}"] = {
            "role": "train", "kept": kept,
            "license_hub": "the user's own conversations, approved one by one; answers by SPIKE's local model"}
    if not domain:
        raise no_domain_data()
    replay = collect(cfg.get("replay", {}).get("sources", []), None)

    before = len(domain)
    domain = list(dedupe(domain))
    manifest["dropped"]["duplicate"] += before - len(domain)
    train, valid = mix_and_split(domain, replay, cfg.get("replay", {}).get("ratio", 0.0), cfg.get("valid_fraction", 0.02),
                                 seed=cfg.get("seed", 0))
    n_train = write_jsonl(out / "train.jsonl", train)
    n_valid = write_jsonl(out / "valid.jsonl", valid)
    ratio = cfg.get("replay", {}).get("ratio", 0.0)
    actual = round(1 - len(domain) / max(1, n_train + n_valid), 4)
    manifest["counts"] = {"domain": len(domain), "replay_available": len(replay), "train": n_train, "valid": n_valid,
                          "replay_ratio_target": ratio, "replay_ratio_actual": actual}
    if ratio - actual > 0.02:
        print(f"warning: replay is {actual:.1%} of the mix, below the {ratio:.0%} target; add replay sources",
              file=sys.stderr)
    manifest["files"] = {f: sha256(out / f) for f in ("train.jsonl", "valid.jsonl")}

    mlx_cfg = {"model": cfg["base_model"], "train": True, "fine_tune_type": "lora", "data": str(out),
               "seed": cfg.get("seed", 0), "adapter_path": str(ROOT / "training" / "runs" / cfg["specialist"] / "adapter"),
               "steps_per_report": 10, "steps_per_eval": 200, "val_batches": 25, "save_every": 200,
               **training_schedule(cfg["train"], n_train)}
    manifest["counts"]["iters"] = mlx_cfg["iters"]
    (out / "mlx_lora.yaml").write_text(yaml.safe_dump(mlx_cfg, sort_keys=False), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest["counts"] | manifest["dropped"], indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
