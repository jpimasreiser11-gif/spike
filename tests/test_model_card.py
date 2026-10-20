"""The Hugging Face model card is rendered only from pipeline records, and says when an adapter was rejected."""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

import model_card  # noqa: E402
from model_card import main, render  # noqa: E402
from spike_train.evaluation import check_pairwise_acceptance, pairwise_summary  # noqa: E402

from spike.specialists.catalog import load_catalog  # noqa: E402

CFG = {"base_model": "Qwen/Qwen3.5-4B", "seed": 0, "train": {"batch_size": 4, "learning_rate": 1e-4}}
MANIFEST = {
    "sources": {
        "medmcqa": {"hub": "openlifescienceai/medmcqa", "license_hub": "apache-2.0", "role": "train"},
        "oasst2": {"hub": "OpenAssistant/oasst2", "license_hub": "apache-2.0", "role": "train"},
        "mmlu-pro": {"hub": "TIGER-Lab/MMLU-Pro", "license_hub": "mit", "role": "eval"},
        "file:evals/data/x.jsonl": {"role": "eval", "indexed_prompts": 3},
    },
    "counts": {"domain": 700, "train": 980, "valid": 20, "iters": 245, "replay_ratio_target": 0.3,
               "replay_ratio_actual": 0.3},
    "dropped": {"format_or_quality": 5, "duplicate": 2, "contaminated": 1},
}
EXPORT = {"gguf": "/x/spike-medicine.gguf", "peft": {"r": 16, "lora_alpha": 32, "target_modules": ["q_proj", "v_proj"]},
          "live_check": {"probes": 4, "outputs_changed": 4}}
SUMMARY_MD = "# SPIKE eval r1\n\n| task | variant |\n|---|---|\n| medmcqa | spike-medicine |\n"


def summary(accepted: bool) -> dict:
    return {"meta": {"run_id": "r1"}, "acceptance": {"spike-medicine": {"accepted": accepted, "reasons": ["medicine: +4 pts"]}}}


TEACHER = "mlx-community/Qwen3.6-35B-A3B-4bit"
MARKETING_MANIFEST = {**MANIFEST, "sources": {
    **MANIFEST["sources"],
    "distilled:distilled.jsonl": {"role": "train", "kept": 900,
                                   "teachers": {TEACHER: {"license_hub": "apache-2.0", "license_recorded": "apache-2.0"}}}}}
ACCEPTANCE = {"primary": {"suite": "marketing-pairwise", "min_win_rate": 0.60},  # training/configs/marketing.yaml
              "regression": {"suite": "general", "max_drop_points": 1.5}}


def pairwise(wins: int = 22, losses: int = 8, ties: int = 10, general_delta: float = -0.5) -> dict:
    """What evals/pairwise.py --acceptance --general-eval writes, with its own statistics and verdict functions."""
    run = {"specialist": "marketing", "adapter": "spike-marketing", "judge": TEACHER, "temperature": 0.0, "seed": 0,
           **pairwise_summary(["win"] * wins + ["loss"] * losses + ["tie"] * ties),
           "caveat": "judge is also the distillation teacher; possible self-preference bias",
           "general": {"suite": "general", "variant": "spike-marketing", "paired_n": 200, "delta_points": general_delta,
                       "p_value": 0.62, "run": "/Users/me/spike/evals/results/general-marketing/summary.json"}}
    run["accepted"], run["reasons"] = check_pairwise_acceptance(run, ACCEPTANCE)
    return run


def front_matter(card: str) -> dict:
    return yaml.safe_load(card.split("---\n")[1])


def test_card_is_built_from_the_records():
    spec = load_catalog().get("medicine")
    card = render(spec, CFG, MANIFEST, EXPORT, summary(True), SUMMARY_MD)
    meta = front_matter(card)
    assert meta["license"] == "apache-2.0" and meta["base_model"] == "Qwen/Qwen3.5-4B"
    assert meta["datasets"] == ["OpenAssistant/oasst2", "openlifescienceai/medmcqa"]  # training data only
    assert "![Spike Medicine](banner.png)" in card
    assert "**Accepted by its acceptance criteria" in card and "research record" not in card
    assert "| medmcqa | spike-medicine |" in card and "# SPIKE eval" not in card  # eval table embedded, title dropped
    assert "| [TIGER-Lab/MMLU-Pro](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro) | mit | evaluation" in card
    assert "4 of 4 greedy probe answers" in card
    assert "not a medical device" in card


def test_rejected_adapter_says_so():
    card = render(load_catalog().get("medicine"), CFG, MANIFEST, EXPORT, summary(False), SUMMARY_MD)
    assert "**Rejected by its acceptance criteria" in card and "research record" in card


def test_card_needs_an_acceptance_verdict():
    with pytest.raises(SystemExit, match="acceptance verdict"):
        render(load_catalog().get("medicine"), CFG, MANIFEST, EXPORT, {"meta": {"run_id": "r1"}}, SUMMARY_MD)


def test_card_lists_url_sources_and_says_when_a_hub_dataset_is_used_in_part():
    finqa = {"urls": [{"url": "https://raw.githubusercontent.com/czyssrs/FinQA/0f16e2867b/dataset/train.json", "sha256": "0" * 64}],
             "repo": "https://github.com/czyssrs/FinQA", "revision": "0f16e2867befa6840783e58be38c9efb9229d742",
             "license_url": "https://raw.githubusercontent.com/czyssrs/FinQA/0f16e2867b/LICENSE", "license_hub": "mit"}
    manifest = {**MANIFEST, "sources": {
        **MANIFEST["sources"],
        "sujet-finance": {"hub": "sujet-ai/Sujet-Finance-Instruct-177k", "license_hub": "apache-2.0", "role": "train",
                          "filter": {"dataset": ["yixuantt/FinEntity", "zeroshot/twitter-financial-news-topic"]}},
        "finqa-train": {**finqa, "role": "train"},
        "finqa-test": {**finqa, "role": "eval"},
    }}
    card = render(load_catalog().get("finance"), CFG, manifest, EXPORT, summary(True), SUMMARY_MD)
    assert "| [https://github.com/czyssrs/FinQA](https://github.com/czyssrs/FinQA) at `0f16e2867b` | mit | training |" in card
    assert "| mit | evaluation and decontamination only |" in card
    assert ("[sujet-ai/Sujet-Finance-Instruct-177k](https://huggingface.co/datasets/sujet-ai/Sujet-Finance-Instruct-177k) | "
            "apache-2.0 | training (only rows where `dataset` is yixuantt/FinEntity / zeroshot/twitter-financial-news-topic)") in card
    assert "sujet-ai/Sujet-Finance-Instruct-177k" in front_matter(card)["datasets"]
    assert not any("github" in d for d in front_matter(card)["datasets"])  # the front matter lists Hub ids only


def test_non_sensitive_specialist_has_no_advice_disclaimer():
    card = render(load_catalog().get("marketing"), CFG, MANIFEST, EXPORT, summary(True), SUMMARY_MD)
    assert "professional advice" not in card


@pytest.mark.parametrize("spec_id", sorted(load_catalog().specialists))
def test_every_specialist_has_its_brand_assets(spec_id):
    folder = ROOT / "brand" / "specialists" / spec_id
    assert (folder / f"hf-banner-{spec_id}.png").is_file()
    assert (ROOT / "web" / "public" / "specialists" / f"{spec_id}.png").is_file()


def test_pairwise_card_shows_the_judge_its_caveat_and_both_halves_of_the_verdict():
    run = pairwise()
    assert run["accepted"]
    card = render(load_catalog().get("marketing"), CFG, MARKETING_MANIFEST, EXPORT, run, "", "pairwise-marketing-1")
    assert front_matter(card)["license"] == "apache-2.0"
    assert "**Accepted by its acceptance criteria" in card and "research record" not in card
    assert f"The judge is `{TEACHER}`" in card and "run `pairwise-marketing-1`" in card and "temperature 0.0" in card
    assert "> **Caveat:** judge is also the distillation teacher; possible self-preference bias." in card
    assert "self-preference bias" in card and "human review is advised" in card
    assert "| adapter wins / base wins / ties | 22 / 8 / 10 |" in card
    assert "| win rate (a tie counts half) | 67.5% |" in card
    lo, hi = run["decided_win_share_ci95"]
    assert f"| {lo:.1%} to {hi:.1%} |" in card and f"| p = {run['sign_test_p']:.4g} |" in card
    assert "| general suite `general`, adapter minus base | -0.50 pts over 200 paired items (McNemar p = 0.62); " \
           "run `general-marketing` |" in card  # the run's folder, not the machine's path
    assert "/Users/me" not in card
    assert "Acceptance (criteria written before training): **accepted**" in card
    assert all(f"- {reason}" in card for reason in run["reasons"])
    assert f"| [{TEACHER}](https://huggingface.co/{TEACHER}) | apache-2.0 | wrote training answers |" in card
    assert "exact-answer benchmarks only" not in card and "professional advice" not in card


def test_pairwise_card_needs_the_run_to_have_a_verdict_and_its_statistics():
    spec, run = load_catalog().get("marketing"), pairwise()
    undecided = {k: v for k, v in run.items() if k not in ("accepted", "reasons")}  # run without --acceptance
    with pytest.raises(SystemExit, match="acceptance verdict"):
        render(spec, CFG, MARKETING_MANIFEST, EXPORT, undecided, "")
    with pytest.raises(SystemExit, match="lacks caveat"):
        render(spec, CFG, MARKETING_MANIFEST, EXPORT, {k: v for k, v in run.items() if k != "caveat"}, "")


def test_card_license_is_the_base_models_and_unknown_bases_are_refused():
    with pytest.raises(SystemExit, match="no license recorded for the base model acme/Tiny-1B"):
        render(load_catalog().get("medicine"), {**CFG, "base_model": "acme/Tiny-1B"}, MANIFEST, EXPORT, summary(True), SUMMARY_MD)


@pytest.mark.parametrize("name, record, refused", [
    ("distilled:d.jsonl", {"role": "train", "teachers": {"acme/Teacher": {"license_hub": "cc-by-nc-4.0"}}},
     "teacher 'acme/Teacher' of distilled:d.jsonl: license 'cc-by-nc-4.0' is not allowed"),
    ("distilled:d.jsonl", {"role": "train", "teachers": {"acme/Teacher": {"license_hub": None}}},
     "teacher 'acme/Teacher' of distilled:d.jsonl: no license declared"),
    ("gpl-set", {"hub": "acme/gpl-set", "license_hub": "gpl-3.0", "role": "train"},
     "training source 'gpl-set': license 'gpl-3.0' is not allowed"),
    ("corrections:x.jsonl", {"role": "train", "license_hub": "the user's own conversations"},
     "training source 'corrections:x.jsonl': license"),
])
def test_card_is_refused_when_a_training_license_is_not_on_the_allowlist(name, record, refused):
    manifest = {**MANIFEST, "sources": {**MANIFEST["sources"], name: record}}
    with pytest.raises(SystemExit, match="refusing to build the card: " + re.escape(refused)):
        render(load_catalog().get("marketing"), CFG, manifest, EXPORT, summary(True), SUMMARY_MD)


def test_an_evaluation_only_license_does_not_stop_the_card():
    manifest = {**MANIFEST, "sources": {**MANIFEST["sources"], "sharealike": {
        "hub": "acme/eval-set", "license_hub": "cc-by-sa-4.0", "role": "eval"}}}
    card = render(load_catalog().get("medicine"), CFG, manifest, EXPORT, summary(True), SUMMARY_MD)
    assert "| [acme/eval-set](https://huggingface.co/datasets/acme/eval-set) | cc-by-sa-4.0 | evaluation" in card


def test_attribution_lines_come_from_the_manifest_for_licenses_that_require_credit():
    zhu = {"urls": [{"url": "https://example.org/d.json", "sha256": "0" * 64}], "repo": "https://github.com/acme/qa",
           "revision": "a" * 40, "license_url": "https://example.org/LICENSE", "license_hub": "cc-by-4.0",
           "role": "train", "provenance": "Acme QA (Doe et al., 2021): questions written by experts."}
    teacher = {"role": "train", "teachers": {"acme/Teacher": {"license_hub": "cc-by-4.0", "license_recorded": "cc-by-4.0"}}}
    manifest = {**MANIFEST, "sources": {**MANIFEST["sources"], "acme-qa": zhu, "distilled:d.jsonl": teacher}}
    card = render(load_catalog().get("finance"), CFG, manifest, EXPORT, summary(True), SUMMARY_MD)
    tail = card.split("Attribution required by those licenses:")[1]
    assert ("- [https://github.com/acme/qa](https://github.com/acme/qa) at `aaaaaaaaaa`, `cc-by-4.0` "
            "([license text](https://example.org/LICENSE)). Acme QA (Doe et al., 2021): questions written by experts.") in tail
    assert "- [acme/Teacher](https://huggingface.co/acme/Teacher), `cc-by-4.0`" in tail
    assert "oasst2" not in tail and "medmcqa" not in tail  # apache-2.0 sources need no credit line
    assert "Attribution required" not in render(load_catalog().get("finance"), CFG, MANIFEST, EXPORT, summary(True), SUMMARY_MD)


# ------------------------------------------------------------------ the command, on records written to a temp tree
def build(tmp_path, monkeypatch, run: dict, manifest: dict = MARKETING_MANIFEST, summary_md: str | None = None):
    """Run `model_card.py marketing --eval ...` on a tree of hand-built records; returns (exit code, README or None)."""
    monkeypatch.setattr(model_card, "ROOT", tmp_path)
    (tmp_path / "brand" / "specialists" / "marketing").mkdir(parents=True)
    shutil.copyfile(ROOT / "brand" / "specialists" / "marketing" / "hf-banner-marketing.png",
                    tmp_path / "brand" / "specialists" / "marketing" / "hf-banner-marketing.png")
    for path, record in {"data/marketing/manifest.json": manifest, "training/runs/marketing/export.json": EXPORT,
                         "eval/summary.json": run}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(json.dumps(record), encoding="utf-8")
    if summary_md is not None:
        (tmp_path / "eval" / "summary.md").write_text(summary_md, encoding="utf-8")
    (tmp_path / "cfg.yaml").write_text(yaml.safe_dump(CFG), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["model_card.py", "marketing", "--eval", str(tmp_path / "eval"), "--config",
                                      str(tmp_path / "cfg.yaml"), "--data", str(tmp_path / "data"),
                                      "--out", str(tmp_path / "hf")])
    code = main()
    readme = tmp_path / "hf" / "README.md"
    return code, readme.read_text(encoding="utf-8") if readme.is_file() else None


def test_command_builds_a_pairwise_card_and_exits_0_when_accepted(tmp_path, monkeypatch):
    code, card = build(tmp_path, monkeypatch, pairwise())  # a pairwise folder has no summary.md
    assert code == 0 and "**Accepted by its acceptance criteria" in card and "run `eval`" in card
    assert (tmp_path / "hf" / "banner.png").is_file()


def test_command_exits_2_and_says_rejected_when_the_pairwise_verdict_is_a_rejection(tmp_path, monkeypatch):
    run = pairwise(general_delta=-3.0)  # wins the comparison but forgets too much of the general suite
    assert not run["accepted"] and "general: -3.00 pts (max drop 1.5)" in run["reasons"]
    code, card = build(tmp_path, monkeypatch, run)
    assert code == 2
    assert "**Rejected by its acceptance criteria" in card and "research record" in card
    assert "Acceptance (criteria written before training): **rejected**" in card and "- general: -3.00 pts" in card


def test_command_exits_2_for_a_rejected_exact_answer_run_as_before(tmp_path, monkeypatch):
    code, card = build(tmp_path, monkeypatch, summary(False), MANIFEST, SUMMARY_MD)
    assert code == 2 and "**Rejected by its acceptance criteria" in card and "| medmcqa | spike-medicine |" in card


def test_command_writes_nothing_for_a_teacher_license_outside_the_allowlist(tmp_path, monkeypatch):
    bad = {**MARKETING_MANIFEST["sources"], "distilled:distilled.jsonl": {
        "role": "train", "teachers": {TEACHER: {"license_hub": "cc-by-nc-4.0", "license_recorded": "cc-by-nc-4.0"}}}}
    with pytest.raises(SystemExit, match="refusing to build the card: teacher .* license 'cc-by-nc-4.0' is not allowed"):
        build(tmp_path, monkeypatch, pairwise(), {**MARKETING_MANIFEST, "sources": bad})
    assert not (tmp_path / "hf").exists()
