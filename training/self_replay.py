"""Generate the base model's own answers as replay data for one specialist.

    # 1. serve the BASE model alone (no --lora), e.g. on the Mac
    llama-server -m ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf --port 8091 --jinja -c 4096 --parallel 4
    # 2. generate
    python training/self_replay.py training/configs/medicine.yaml --base-url http://127.0.0.1:8091/v1 \
        --base-repo Qwen/Qwen3.5-4B --out training/data/medicine/self_replay.jsonl
    # 3. build the training set from it
    python training/prepare.py training/configs/medicine.yaml --self-replay training/data/medicine/self_replay.jsonl

Prompts are the first user turn of each chat the config's `replay.sources` give (the chats prepare.py builds), once
per distinct text. Each is answered by the server under the specialist's system prompt, greedy, thinking off, within
the tokens `train.max_seq_length` leaves; answers that hit the limit, are empty or repeat themselves are dropped
(spike_train/self_replay.py). Before any prompt is sent: the model's Hub license must be on the training allowlist
(--base-repo names the Hub repo of the weights; it must be the recipe's base_model), and if the server has llama-server's
GET /lora-adapters, no adapter may have a non-zero scale. Every row records the generator, its license, the server
build and the settings; prepare.py checks the license again and records the file's sha256. Writes OUT, and
OUT.summary.json with the kept and dropped counts. An interrupted run leaves OUT.partial; --resume continues it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from prepare import candidate_chats, gate_source, load_token_counter  # noqa: E402
from spike_train import licenses  # noqa: E402
from spike_train.distill import Teacher  # noqa: E402
from spike_train.self_replay import DROP_REASONS, Prompt, check_server, first_user_prompts, self_answer  # noqa: E402

BATCH = 32   # prompts answered, then appended to OUT.partial, at a time


def load_prompts(cfg: dict, registry: dict) -> list[Prompt]:
    seen: set[str] = set()
    prompts: list[Prompt] = []
    for entry in cfg["replay"]["sources"]:
        name = entry["source"]
        gate_source(name, registry[name], "train")  # the prompts are training data: same gate as prepare.py
        chats, _ = candidate_chats(name, registry[name], entry, None)
        prompts += first_user_prompts(chats, name, seen)
    return prompts


def read_partial(path: Path, identity: dict) -> dict[str, dict]:
    """The prompts an interrupted run finished (kept or dropped), by id. Refuses a file made with other settings. A last
    line cut by the interruption is discarded."""
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed: list[dict] = []
    for n, line in enumerate(lines):
        try:
            parsed.append(json.loads(line))
        except ValueError:
            if n != len(lines) - 1:
                raise SystemExit(f"{path.name}:{n + 1} is not JSON; delete {path} to start over") from None
    if not parsed or parsed[0].get("run") != identity:
        raise SystemExit(f"{path.name} was made with other settings (generator, server or limits); delete {path} to start over")
    with path.open("w", encoding="utf-8") as f:  # without the cut line, so new lines start on a line of their own
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in parsed)
    return {p["prompt_id"]: p for p in parsed[1:]}


async def run(args: argparse.Namespace) -> int:
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    from spike.specialists.catalog import load_catalog

    spec = load_catalog().get(cfg["specialist"])
    max_len = (cfg.get("train") or {}).get("max_seq_length")
    if not (cfg.get("replay") or {}).get("sources") or not max_len:
        raise SystemExit("the config needs replay.sources (where the prompts come from) and train.max_seq_length "
                         "(how many tokens a prompt and its answer may take)")
    repo = args.base_repo or cfg["base_model"]
    if repo != cfg["base_model"]:
        raise SystemExit(f"--base-repo {repo} is not the recipe's base model ({cfg['base_model']}): self-generated "
                         "replay is the model being trained answering for itself")
    try:  # before the server is asked anything: the generator's terms apply to everything it writes
        generator_license = licenses.teacher_license(repo, "generator")
    except ValueError as exc:
        raise SystemExit(f"refusing to generate: {exc} (--base-repo names the Hub repo of the weights)") from exc
    teacher = Teacher(args.base_url, repo, concurrency=args.concurrency)
    try:
        try:
            server = await check_server(teacher)
        except ValueError as exc:
            raise SystemExit(f"refusing to generate: {exc}") from exc
        settings = {"specialist": cfg["specialist"], "temperature": 0.0, "thinking": False, "max_seq_length": max_len}
        identity = {"generator": repo, "generator_license": generator_license, "server": server, "settings": settings}
        prompts = load_prompts(cfg, registry)
        prompts = prompts[: args.limit] if args.limit else prompts
        count_tokens = load_token_counter(cfg["base_model"])
        out = Path(args.out)
        partial = out.with_name(out.name + ".partial")
        done: dict[str, dict] = {}
        if partial.exists():
            if not args.resume:
                raise SystemExit(f"{partial} is left by an interrupted run: --resume continues it; delete it to start over")
            done = read_partial(partial, identity)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text(json.dumps({"run": identity}, ensure_ascii=False) + "\n", encoding="utf-8")
        resumed = sum(p.id in done for p in prompts)
        todo = [p for p in prompts if p.id not in done]
        print(f"{len(prompts)} prompts, {resumed} already done", file=sys.stderr)
        record = {"source": "self_replay", **identity}
        with partial.open("a", encoding="utf-8") as f:
            for i in range(0, len(todo), BATCH):
                batch = todo[i:i + BATCH]
                answers = await asyncio.gather(*[
                    self_answer(teacher, spec.system_prompt, p, count_tokens, max_len, record) for p in batch])
                for p, (row, why) in zip(batch, answers, strict=True):
                    done[p.id] = {"prompt_id": p.id, **({"row": row} if row else {"dropped": why})}
                    f.write(json.dumps(done[p.id], ensure_ascii=False) + "\n")
                f.flush()
                kept = sum("row" in done[p.id] for p in prompts if p.id in done)
                print(f"  {resumed + i + len(batch)}/{len(prompts)} processed, {kept} kept", file=sys.stderr)
    finally:
        await teacher.aclose()
    rows = [done[p.id]["row"] for p in prompts if "row" in done[p.id]]
    dropped = Counter(done[p.id]["dropped"] for p in prompts if "dropped" in done[p.id])
    summary = {**identity, "prompts": len(prompts), "kept": len(rows), "resumed_prompts": resumed,
               "dropped": {reason: dropped[reason] for reason in DROP_REASONS}, "out": str(out)}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not rows:
        raise SystemExit(f"no answer was kept ({dict(dropped)}); nothing written beyond {partial.name}; if 'thinking' or "
                         "'hit_length_limit' dominates, serve the model with --jinja so thinking is switched off")
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    partial.unlink()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--base-url", required=True, help="OpenAI-compatible endpoint of llama-server serving the base model "
                                                       "alone, e.g. http://127.0.0.1:8091/v1")
    ap.add_argument("--base-repo", help="Hugging Face repo of the served weights, whose license governs the answers "
                                        "(default and only allowed value: the config's base_model)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, help="only the first N distinct prompts (a smoke run, too few rows to train on)")
    ap.add_argument("--concurrency", type=int, default=4, help="requests in flight; llama-server needs --parallel >= this")
    ap.add_argument("--resume", action="store_true", help="continue the OUT.partial of an interrupted run")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
