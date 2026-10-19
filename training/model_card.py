"""Write the Hugging Face model card for one exported adapter, from the records the pipeline already wrote.

    python training/model_card.py medicine --eval evals/results/<run-id> [--out training/runs/medicine/hf]

Reads training/data/<id>/manifest.json (data and licenses), training/runs/<id>/export.json (adapter shape and
live check) and the eval run's summary.json + summary.md (measured results and the acceptance verdict), then
writes README.md and banner.png into --out. Nothing is typed in by hand: a missing record stops the script.
Exit code 2 when the adapter was evaluated but rejected, as in run_eval.py; the card then says so.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(path: Path, what: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"missing {what}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verdict_of(summary: dict) -> tuple[str, dict] | None:
    acceptance = summary.get("acceptance") or {}
    adapters = {k: v for k, v in acceptance.items() if k != "base"}
    if len(adapters) != 1:
        return None
    return next(iter(adapters.items()))


def render(spec, cfg: dict, manifest: dict, export: dict, summary: dict, summary_md: str) -> str:
    verdict = verdict_of(summary)
    if verdict is None:
        raise SystemExit("the eval run has no acceptance verdict for exactly one adapter; run run_eval.py with --acceptance")
    variant, result = verdict
    train_sources = {k: v for k, v in manifest["sources"].items() if v.get("role") == "train" and "hub" in v}
    eval_sources = {k: v for k, v in manifest["sources"].items() if v.get("role") == "eval" and "hub" in v}
    peft, counts, dropped = export["peft"], manifest["counts"], manifest["dropped"]
    front = {
        "license": "apache-2.0",
        "base_model": cfg["base_model"],
        "language": ["en", "es"],
        "pipeline_tag": "text-generation",
        "tags": ["spike", "lora", "gguf", spec.id],
        "datasets": sorted({v["hub"] for v in train_sources.values()}),
    }
    gguf = Path(export["gguf"]).name
    lines = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(), "---", "",
             f"![{spec.name}](banner.png)", "",
             f"# {spec.name}", "",
             f"LoRA adapter for [{cfg['base_model']}](https://huggingface.co/{cfg['base_model']}) that turns it into "
             f"SPIKE's {spec.domain.lower()} specialist. {spec.description}", "",
             f"**{'Accepted' if result['accepted'] else 'Rejected'} by its acceptance criteria, which were written "
             f"before training** (see Evaluation).", ""]
    if not result["accepted"]:
        lines += ["> This adapter did not meet its acceptance criteria. It is published only as a research record; "
                  "SPIKE keeps using the base model with a prompt profile for this specialist.", ""]
    lines += ["## Use", "",
              f"In SPIKE: put `{gguf}` in `~/.spike/adapters/`; the app loads it next to the base model and routes "
              f"{spec.domain.lower()} requests to it.", "",
              "With llama.cpp directly:", "", "```bash",
              f"llama-server -m Qwen3.5-4B-Q4_K_M.gguf --lora {gguf}", "```", "",
              "## Training", "",
              f"- Method: LoRA, rank {peft['r']}, alpha {peft['lora_alpha']}, on "
              f"{', '.join(f'`{m}`' for m in peft['target_modules'])}; trained in bf16 with mlx-lm.",
              f"- Steps: {counts['iters']} micro-batches of {cfg['train']['batch_size']}, learning rate "
              f"{cfg['train']['learning_rate']}, seed {cfg.get('seed', 0)}.",
              f"- Examples: {counts['train']} train, {counts['valid']} validation; {counts['domain']} domain chats, "
              f"general replay {counts['replay_ratio_actual']:.0%} of the mix (target {counts['replay_ratio_target']:.0%}).",
              f"- Removed before training: {dropped['format_or_quality']} by format or quality filters, "
              f"{dropped['duplicate']} duplicates, {dropped['contaminated']} that shared a 13-gram with an eval set.", "",
              "| dataset | license | used as |", "|---|---|---|"]
    for v in train_sources.values():
        lines.append(f"| [{v['hub']}](https://huggingface.co/datasets/{v['hub']}) | {v['license_hub']} | training |")
    for v in eval_sources.values():
        lines.append(f"| [{v['hub']}](https://huggingface.co/datasets/{v['hub']}) | {v['license_hub']} | "
                     "evaluation and decontamination only |")
    body = summary_md.split("\n", 1)[1].strip() if summary_md.startswith("# ") else summary_md.strip()
    lines += ["", "## Evaluation", "",
              f"Variant `{variant}` against the same base model with the same prompts (run "
              f"`{summary['meta']['run_id']}`). Accuracy is exact-answer scoring; the 95% interval is Wilson's, "
              "the paired test is McNemar's.", "", body, ""]
    live = export.get("live_check")
    if live:
        lines += [f"Export check: with the adapter loaded in llama-server, {live['outputs_changed']} of "
                  f"{live['probes']} greedy probe answers differed from the base model.", ""]
    lines += ["## Limitations", "",
              "- Measured on exact-answer benchmarks only; these do not measure the quality or safety of open-ended answers.",
              "- A 4B model makes mistakes with confidence. Check important facts against primary sources."]
    if spec.sensitive:
        lines.append(f"- {spec.name} gives general information, not professional advice"
                     + (", and it is not a medical device." if spec.id == "medicine" else "."))
    lines += ["", "## License", "",
              "The adapter is released under Apache-2.0, like the base model. Each dataset keeps its own license "
              "(table above). Part of the SPIKE project.", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("specialist")
    ap.add_argument("--eval", required=True, help="eval run directory written by evals/run_eval.py --acceptance")
    ap.add_argument("--config", help="training config (default training/configs/<specialist>.yaml)")
    ap.add_argument("--data", default=str(ROOT / "training" / "data"))
    ap.add_argument("--out", help="default training/runs/<specialist>/hf")
    args = ap.parse_args()

    from spike.specialists.catalog import load_catalog

    spec = load_catalog().get(args.specialist)
    cfg = yaml.safe_load(Path(args.config or ROOT / "training" / "configs" / f"{spec.id}.yaml").read_text(encoding="utf-8"))
    run_dir = ROOT / "training" / "runs" / spec.id
    manifest = load(Path(args.data) / spec.id / "manifest.json", "data manifest (run training/prepare.py)")
    export = load(run_dir / "export.json", "export record (run training/export_adapter.py)")
    eval_dir = Path(args.eval)
    summary = load(eval_dir / "summary.json", "eval summary (run evals/run_eval.py)")
    summary_md = (eval_dir / "summary.md").read_text(encoding="utf-8")
    banner = ROOT / "brand" / "specialists" / spec.id / f"hf-banner-{spec.id}.png"
    if not banner.is_file():
        raise SystemExit(f"missing banner: {banner}")

    card = render(spec, cfg, manifest, export, summary, summary_md)
    out = Path(args.out or run_dir / "hf")
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(card, encoding="utf-8")
    shutil.copyfile(banner, out / "banner.png")
    print(f"wrote {out / 'README.md'} and banner.png")
    return 0 if verdict_of(summary)[1]["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
