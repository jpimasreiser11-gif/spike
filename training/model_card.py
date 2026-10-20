"""Write the Hugging Face model card for one exported adapter, from the records the pipeline already wrote.

    python training/model_card.py medicine --eval evals/results/<run-id> [--out training/runs/medicine/hf]

Reads training/data/<id>/manifest.json (data and licenses), training/runs/<id>/export.json (adapter shape and
live check) and the eval run's summary.json + summary.md (measured results and the acceptance verdict), then
writes README.md and banner.png into --out. Nothing is typed in by hand: a missing record stops the script.
An open-ended specialist (marketing) is judged by evals/pairwise.py instead: --eval is then its folder (summary.json
with the win rate, the sign test, the judge and its caveat, the general-suite delta and the verdict; no summary.md).
The card's license is the base model's, and the script refuses to write a card when any training source or
distillation teacher in the manifest has a license outside the training allowlist.
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
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train import licenses  # noqa: E402

from spike.evolution.adapters import is_pairwise  # noqa: E402

# Licenses of the base models, as declared on their Hugging Face model cards (read 2026-10-17: THIRD_PARTY.md,
# docs/adr/0001-base-model.md). An adapter is a derivative of its base, so its card carries the same license. Neither
# the training configs nor the manifest record it, so a base model that is not listed here stops the script.
BASE_LICENSES = {"Qwen/Qwen3.5-4B": "apache-2.0"}
# Allowlisted licenses that make crediting the source a condition (the others only need their notice kept).
ATTRIBUTION_LICENSES = {"cc-by-4.0", "odc-by"}
PAIRWISE_KEYS = ("judge", "temperature", "n", "wins", "losses", "ties", "win_rate", "decided_win_share_ci95",
                 "sign_test_p", "caveat")


def load(path: Path, what: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"missing {what}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verdict_of(summary: dict) -> tuple[str, dict] | None:
    if is_pairwise(summary):  # one adapter per pairwise run; the verdict exists only if it ran with --acceptance
        if not summary.get("adapter") or "accepted" not in summary or "reasons" not in summary:
            return None
        return summary["adapter"], {"accepted": bool(summary["accepted"]), "reasons": summary["reasons"]}
    acceptance = summary.get("acceptance") or {}
    adapters = {k: v for k, v in acceptance.items() if k != "base"}
    if len(adapters) != 1:
        return None
    return next(iter(adapters.items()))


def dataset_link(v: dict) -> str:
    """A Hub dataset, or a source fetched from pinned URLs (FinQA, TAT-QA): its repository at the pinned commit."""
    if "hub" in v:
        return f"[{v['hub']}](https://huggingface.co/datasets/{v['hub']})"
    return f"[{v['repo']}]({v['repo']}) at `{v['revision'][:10]}`"


def subset_note(v: dict) -> str:
    rows = "; ".join(f"`{col}` is {' / '.join(values)}" for col, values in (v.get("filter") or {}).items())
    return f" (only rows where {rows})" if rows else ""


def training_credits(manifest: dict) -> list[dict]:
    """Every training source and distillation teacher of the manifest with its license. Refuses a license that is not
    on the training allowlist: prepare.py gated on it, but a card must not vouch for a manifest nobody re-checked."""
    credits = []
    for name, v in manifest["sources"].items():
        if v.get("role") != "train":
            continue
        if "teachers" in v:  # `distilled:<file>`: the license of the model that wrote the answers
            parts = [(f"teacher '{repo}' of {name}", f"[{repo}](https://huggingface.co/{repo})", t.get("license_hub"), {})
                     for repo, t in v["teachers"].items()]
        else:
            parts = [(f"training source '{name}'", dataset_link(v) if "hub" in v or "urls" in v else name,
                      v.get("license_hub"), v)]
        for what, link, license_id, record in parts:
            ok, reason = licenses.check(license_id, "train")
            if not ok:
                raise SystemExit(f"refusing to build the card: {what}: {reason}")
            credits.append({"link": link, "license": reason, "record": record, "teacher": "teachers" in v})
    return credits


def attribution(credit: dict) -> str:
    """The credit line for a source whose license requires one: only what the manifest recorded (link, license,
    license file, provenance)."""
    record = credit["record"]
    line = f"- {credit['link']}, `{credit['license']}`"
    if record.get("license_url"):
        line += f" ([license text]({record['license_url']}))"
    if record.get("provenance"):
        line += f". {record['provenance'].rstrip('.')}."
    return line


def run_name(path: str) -> str:
    """The run folder of a recorded summary.json path (the card names runs, not the machine's paths)."""
    p = Path(path)
    return (p.parent.name if p.name == "summary.json" else p.name) or str(p)


def pairwise_lines(summary: dict, variant: str, result: dict, run: str) -> list[str]:
    missing = [k for k in PAIRWISE_KEYS if k not in summary]
    if missing:
        raise SystemExit(f"the pairwise summary lacks {', '.join(missing)}; run evals/pairwise.py again")
    lo, hi = summary["decided_win_share_ci95"]
    general = summary.get("general")
    rows = [("prompts", summary["n"]),
            ("adapter wins / base wins / ties", f"{summary['wins']} / {summary['losses']} / {summary['ties']}"),
            ("win rate (a tie counts half)", f"{summary['win_rate']:.1%}"),
            ("95% interval of the share of decided prompts the adapter won (Wilson)", f"{lo:.1%} to {hi:.1%}"),
            ("sign test, wins against losses (exact, two-sided)", f"p = {summary['sign_test_p']:.4g}"),
            (f"general suite `{general['suite']}`, adapter minus base" if general else "general suite",
             f"{general['delta_points']:+.2f} pts over {general['paired_n']} paired items (McNemar p = "
             f"{general['p_value']:.4g}); run `{run_name(general['run'])}`" if general else "not measured in this run")]
    return ["", "## Evaluation", "",
            f"Judged pairwise: variant `{variant}` against the same base model with the same prompts"
            + (f" (run `{run}`)" if run else "") + f", both answering at temperature {summary['temperature']}. "
            f"The judge is `{summary['judge']}`; each prompt is judged twice with the answers in swapped positions, and "
            "a side wins only when both orders agree, otherwise the prompt is a tie.", "",
            f"> **Caveat:** {summary['caveat'].rstrip('.')}. A judge that also wrote the training answers can favour answers in "
            "its own style (self-preference bias), so read these numbers as a screen, not proof of quality; "
            "human review is advised.", "",
            "| measure | result |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows), "",
            f"Acceptance (criteria written before training): **{'accepted' if result['accepted'] else 'rejected'}**",
            *(f"- {reason}" for reason in result["reasons"]), ""]


def render(spec, cfg: dict, manifest: dict, export: dict, summary: dict, summary_md: str, run: str = "") -> str:
    verdict = verdict_of(summary)
    if verdict is None:
        raise SystemExit("the eval run has no acceptance verdict for exactly one adapter; run run_eval.py with "
                         "--acceptance (evals/pairwise.py with --acceptance and --general-eval for a pairwise run)")
    variant, result = verdict
    pairwise = is_pairwise(summary)
    base_license = BASE_LICENSES.get(cfg["base_model"])
    if base_license is None:
        raise SystemExit(f"no license recorded for the base model {cfg['base_model']}; check its Hub card and add it "
                         "to BASE_LICENSES in training/model_card.py")
    credits = training_credits(manifest)
    train_sources = {k: v for k, v in manifest["sources"].items() if v.get("role") == "train" and ("hub" in v or "urls" in v)}
    eval_sources = {k: v for k, v in manifest["sources"].items() if v.get("role") == "eval" and ("hub" in v or "urls" in v)}
    peft, counts, dropped = export["peft"], manifest["counts"], manifest["dropped"]
    front = {
        "license": base_license,
        "base_model": cfg["base_model"],
        "language": ["en", "es"],
        "pipeline_tag": "text-generation",
        "tags": ["spike", "lora", "gguf", spec.id],
        "datasets": sorted({v["hub"] for v in train_sources.values() if "hub" in v}),
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
        lines.append(f"| {dataset_link(v)} | {v['license_hub']} | training{subset_note(v)} |")
    for v in eval_sources.values():
        lines.append(f"| {dataset_link(v)} | {v['license_hub']} | evaluation and decontamination only |")
    teachers = [c for c in credits if c["teacher"]]
    if teachers:
        lines += ["", "Distillation teachers (a model whose answers the adapter was trained on):", "",
                  "| teacher | license | used as |", "|---|---|---|",
                  *(f"| {c['link']} | {c['license']} | wrote training answers |" for c in teachers)]
    if pairwise:
        lines += pairwise_lines(summary, variant, result, run)
    else:
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
              "- Judged by a model on open-ended prompts, not by people (see the caveat above); the general-suite "
              "check is exact-answer only." if pairwise else
              "- Measured on exact-answer benchmarks only; these do not measure the quality or safety of open-ended answers.",
              "- A 4B model makes mistakes with confidence. Check important facts against primary sources."]
    if spec.sensitive:
        lines.append(f"- {spec.name} gives general information, not professional advice"
                     + (", and it is not a medical device." if spec.id == "medicine" else "."))
    lines += ["", "## License", "",
              f"The adapter is released under `{base_license}`, like the base model. Each dataset and teacher keeps its "
              "own license (tables above). Part of the SPIKE project.", ""]
    credited = [c for c in credits if c["license"] in ATTRIBUTION_LICENSES]
    if credited:
        lines += ["Attribution required by those licenses:", "", *(attribution(c) for c in credited), ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("specialist")
    ap.add_argument("--eval", required=True, help="eval run directory written by evals/run_eval.py --acceptance, or by "
                    "evals/pairwise.py --acceptance --general-eval (marketing)")
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
    summary_md = "" if is_pairwise(summary) else (eval_dir / "summary.md").read_text(encoding="utf-8")
    banner = ROOT / "brand" / "specialists" / spec.id / f"hf-banner-{spec.id}.png"
    if not banner.is_file():
        raise SystemExit(f"missing banner: {banner}")

    card = render(spec, cfg, manifest, export, summary, summary_md, eval_dir.resolve().name)
    out = Path(args.out or run_dir / "hf")
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(card, encoding="utf-8")
    shutil.copyfile(banner, out / "banner.png")
    print(f"wrote {out / 'README.md'} and banner.png")
    return 0 if verdict_of(summary)[1]["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
