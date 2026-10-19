"""The Hugging Face model card is rendered only from pipeline records, and says when an adapter was rejected."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

from model_card import render  # noqa: E402

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
