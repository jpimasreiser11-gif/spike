"""Build the training set for one specialist adapter.

    python training/prepare.py training/configs/medicine.yaml [--out training/data] [--distilled FILE]
        [--corrections spike-training.jsonl] [--self-replay FILE]

Steps: license check per source (and per distillation teacher) -> download -> format to chat -> quality filter ->
dedupe -> 13-gram decontamination against every eval set -> blend with general replay data -> split ->
write train/valid JSONL, an mlx-lm config and a manifest with counts, licenses and file hashes.
A recipe with no domain_sources (marketing) needs --distilled data: with none, the run stops instead of writing
an empty training set.
A recipe with `replay: {self_generated: true}` takes its replay from the base model's own answers (--self-replay FILE,
made by training/self_replay.py); with no file the run stops. Without it, replay is the human-written sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections.abc import Iterator
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


def gate_source(name: str, src: dict, role: str, offline: bool = False) -> str:
    """The license a registry source is gated on (as the Hub publishes it; the registry's own when `offline`).
    SystemExit unless `role` may use the source."""
    if src.get("license_status") == "unverified":
        raise SystemExit(f"refusing source '{name}': license is unverified; Claude must review before use")
    hub = src["license"] if offline else licenses.source_license(src)
    ok, reason = licenses.check(hub, role)
    if role == "train" and src["role"] != "train":
        raise SystemExit(f"refusing source '{name}' for training: registry role is '{src['role']}'")
    if not ok:
        raise SystemExit(f"refusing source '{name}': {reason}")
    return hub


def candidate_chats(name: str, src: dict, entry: dict, sys_prompt: str | None) -> tuple[Iterator[dict | None], int | None]:
    """The chats (None for a row its formatter rejects) of one config entry before any filter, and how many a
    whole-source builder made (None for row-by-row formats). self_replay.py takes its prompts from these chats."""
    start, limit = entry.get("offset", 0), entry.get("max")
    cap = {"per_value": entry["max_per_value"]} if "max_per_value" in entry else {}  # balanced filtered source
    if src["format"] in BUILDERS:  # needs every row of the source before it can emit a chat
        built = BUILDERS[src["format"]](load_rows(src, **cap), **src.get("options", {}))
        if not built:
            raise SystemExit(f"source '{name}' produced no chats; check its schema against the builder")
        return iter(built[start: None if limit is None else start + limit]), len(built)
    fmt = FORMATTERS[src["format"]]
    return ((fmt(row, sys_prompt) if src["format"] != "messages" else fmt(row)
             for row in load_rows(src, start, limit, **cap)), None)


def check_generators(file: str, generators: dict[str, str | None], kind: str, offline: bool) -> dict[str, dict]:
    """The license of every model that wrote a data file's answers, checked again: live from the Hub like a dataset's, or
    when `offline` the one the generator recorded, still against the allowlist. The manifest record per repo."""
    record = {}
    for repo, recorded in generators.items():
        try:
            if offline:
                ok, reason = licenses.check(recorded, "train")
                if not ok:
                    raise ValueError(f"{kind} '{repo}': {reason}")
                lic = reason
            else:
                lic = licenses.teacher_license(repo, kind)
        except ValueError as exc:
            raise SystemExit(f"refusing {Path(file).name}: {exc}") from exc
        record[repo] = {"license_hub": lic, "license_recorded": recorded}
    return record


def load_self_replay(path: Path, system: str,
                     prompt_sources: set[str]) -> tuple[list[tuple[str, dict]], dict[str, str | None]]:
    """(prompt source, chat) of every row of a self_replay.py file, and the generators (repo -> license recorded when it
    wrote them) behind them. Stops on a row that names no generator, is not (system, user, assistant) under the
    specialist's current system prompt, or has prompts from a source the recipe does not list: it is not what the
    recipe asked for, or its license would be unknown."""
    rows: list[tuple[str, dict]] = []
    generators: dict[str, str | None] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        chat = json.loads(line)
        meta = chat.pop("meta", None) or {}
        where = f"{path.name}:{n}"
        if meta.get("source") != "self_replay" or not meta.get("generator"):
            raise SystemExit(f"{where} has no self-replay record; make it again with training/self_replay.py "
                             "(it records the generator's repo and license)")
        messages = chat.get("messages") or []
        if [m.get("role") for m in messages] != ["system", "user", "assistant"] or messages[0].get("content") != system:
            raise SystemExit(f"{where} is not a (system, user, assistant) chat under the specialist's current system "
                             "prompt; make the file again with training/self_replay.py")
        if meta.get("prompt_source") not in prompt_sources:
            raise SystemExit(f"{where} has prompts from '{meta.get('prompt_source')}', which replay.sources of the config "
                             f"does not list ({', '.join(sorted(prompt_sources)) or 'none'})")
        if generators.setdefault(meta["generator"], meta.get("generator_license")) != meta.get("generator_license"):
            raise SystemExit(f"{where} records another license for '{meta['generator']}' than the rows before it")
        rows.append((meta["prompt_source"], chat))
    return rows, generators


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
    ap.add_argument("--self-replay", help="the base model's own answers to general prompts (training/self_replay.py), "
                                          "used as the replay data instead of the human-written replay sources")
    ap.add_argument("--skip-license-check", action="store_true", help="only for offline dry runs; never for releases")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    from spike.specialists.catalog import load_catalog

    system = load_catalog().get(cfg.get("system_from", cfg["specialist"])).system_prompt  # personal: Spike Core's
    out = Path(args.out) / cfg["specialist"]
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"specialist": cfg["specialist"], "config": cfg, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "sources": {}, "dropped": {"format_or_quality": 0, "duplicate": 0, "contaminated": 0, "too_long": 0}}

    def checked(name: str, role: str) -> dict:
        src = registry[name]
        if manifest["sources"].get(name, {}).get("role") == role:
            return src
        hub = gate_source(name, src, role, args.skip_license_check)
        manifest["sources"][name] = {**origin(src), "license_hub": hub, "license_registry": src["license"],
                                     "role": role, "provenance": src.get("provenance", ""),
                                     "license_status": src.get("license_status", "legacy")}
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
    if (cfg.get("replay") or {}).get("self_generated") and not args.self_replay:  # same: no human-written fallback
        raise SystemExit(f"'{cfg['specialist']}' takes its replay from the base model's own answers (replay.self_generated) "
                         "but no file was given: serve the base model with llama-server (no adapter), run "
                         f"`python training/self_replay.py {args.config} --base-url http://127.0.0.1:PORT/v1 "
                         f"--out training/data/{cfg['specialist']}/self_replay.jsonl`, then pass it with --self-replay")
    if args.self_replay and not Path(args.self_replay).is_file():
        raise SystemExit(f"--self-replay {args.self_replay}: no such file")

    # Candidate recipes must stop before checking even an already-registered source on the Hub.
    source_names = list(cfg.get("decontaminate_against", [])) + [
        e["source"] for e in cfg.get("domain_sources", []) + cfg.get("replay", {}).get("sources", [])]
    for name in source_names:
        if registry[name].get("license_status") == "unverified":
            gate_source(name, registry[name], registry[name]["role"], args.skip_license_check)

    # 0. every license and registry role, before anything is downloaded
    for name in cfg.get("decontaminate_against", []):
        checked(name, "eval")
    for entry in cfg.get("domain_sources", []) + cfg.get("replay", {}).get("sources", []):
        checked(entry["source"], "train")
    distilled: dict[str, list[dict]] = {}
    for path in args.distilled:  # a teacher's terms travel with every example it wrote: same allowlist as datasets
        chats, teachers = load_distilled(Path(path))
        distilled[path] = chats
        # offline: trust the license distill.py recorded, still on the allowlist; otherwise live from the Hub
        manifest["sources"][f"distilled:{Path(path).name}"] = {
            "role": "train", "teachers": check_generators(path, teachers, "teacher", args.skip_license_check)}
    self_rows: list[tuple[str, dict]] = []
    if args.self_replay:  # the base model's answers: its terms travel with them like a teacher's (the model card reads `teachers`)
        self_path = Path(args.self_replay)
        prompt_sources = {e["source"] for e in cfg.get("replay", {}).get("sources", [])}
        self_rows, generators = load_self_replay(self_path, system, prompt_sources)
        manifest["sources"][f"self_replay:{self_path.name}"] = {
            "role": "train", "self_generated": True, "sha256": sha256(self_path), "rows": len(self_rows),
            "teachers": check_generators(args.self_replay, generators, "generator", args.skip_license_check)}

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

    def keep(chat: dict | None) -> bool:
        """The filters every training chat passes, counting each drop once under its reason."""
        if chat is None or not passes_quality(chat):
            manifest["dropped"]["format_or_quality"] += 1
        elif n_tokens and n_tokens(chat) > max_len:
            manifest["dropped"]["too_long"] += 1
        elif index.contaminated(text_of(chat)):
            manifest["dropped"]["contaminated"] += 1
        else:
            return True
        return False

    def collect(entries: list[dict], sys_prompt: str | None) -> list[dict]:
        chats = []
        for entry in entries:
            src = checked(entry["source"], "train")
            candidates, built = candidate_chats(entry["source"], src, entry, sys_prompt)
            if built is not None:
                manifest["sources"][entry["source"]]["built"] = built
            kept = 0
            for chat in candidates:
                if keep(chat):
                    chats.append(chat)
                    kept += 1
            manifest["sources"][entry["source"]]["kept"] = kept
        return chats

    domain = collect(cfg.get("domain_sources", []), system)
    for path, chats in distilled.items():
        kept = 0
        for chat in chats:
            if keep(chat):
                domain.append(chat)
                kept += 1
        manifest["sources"][f"distilled:{Path(path).name}"]["kept"] = kept
    # Evolution level 3: the user's approved corrections (`spike evolve dataset`); for the personal adapter (EV6) the
    # file is the one `spike evolve personal-adapter` writes, with its own source tag
    wanted = "spike-personal" if cfg["specialist"] == "personal" else "spike-correction"
    for path in args.corrections:
        kept = 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            chat = json.loads(line)
            meta = chat.pop("meta", None) or {}
            if meta.get("source") != wanted or meta.get("specialist") != cfg["specialist"]:
                continue
            chat["messages"] = [{"role": "system", "content": system},
                                *(m for m in chat["messages"] if m["role"] != "system")]
            if keep(chat):
                domain.append(chat)
                kept += 1
        manifest["sources"][f"corrections:{Path(path).name}"] = {
            "role": "train", "kept": kept,
            "license_hub": "the user's own conversations, approved one by one; answers by SPIKE's local model"}
    if not domain:
        raise no_domain_data()
    if args.self_replay:  # the same filters as any chat; these prompts are decontaminated here, not when the file was made
        replay, per_source = [], dict.fromkeys(prompt_sources, 0)
        for source, chat in self_rows:
            if keep(chat):
                replay.append(chat)
                per_source[source] += 1
        for source, kept in per_source.items():
            manifest["sources"][source]["kept"] = kept
        manifest["sources"][f"self_replay:{Path(args.self_replay).name}"]["kept"] = len(replay)
    else:
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
