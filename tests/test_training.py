"""Unit tests for the training and evaluation utilities (no downloads, no model)."""

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

from prepare import training_schedule  # noqa: E402
from spike_train import licenses  # noqa: E402
from spike_train.data import (  # noqa: E402
    ContaminationIndex,
    dedupe,
    fmt_medmcqa,
    fmt_messages,
    fmt_mmlu_pro,
    fmt_pubmedqa,
    mix_and_split,
    passes_quality,
)
from spike_train.distill import Task, verify  # noqa: E402
from spike_train.evaluation import (  # noqa: E402
    Client,
    check_acceptance,
    make_item,
    pairwise_summary,
    score,
    summarize,
)
from spike_train.export import convert, map_module, read_safetensors, write_safetensors  # noqa: E402
from spike_train.metrics import (  # noqa: E402
    extract_choice,
    extract_number,
    extract_yes_no,
    mcnemar_exact,
    wilson_interval,
)

MEDMCQA = {"id": "m1", "question": "Which vitamin deficiency causes scurvy?", "opa": "Vitamin A", "opb": "Vitamin C",
           "opc": "Vitamin D", "opd": "Vitamin K", "cop": 1, "choice_type": "single",
           "exp": "Scurvy results from vitamin C deficiency, which impairs collagen synthesis."}
PUBMED = {"pubid": 7, "question": "Does X reduce Y?", "context": {"contexts": ["Background.", "Results."]},
          "long_answer": "X reduced Y in the trial.", "final_decision": "yes"}
MMLU = {"question_id": 3, "question": "2+2?", "options": ["3", "4", "5", "N/A"], "answer": "B", "category": "math"}


def chat(user: str, answer: str = "ok") -> dict:
    return {"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": answer}]}


# ------------------------------------------------------------------ data
def test_formatters_produce_chats_with_gold_answers():
    c = fmt_medmcqa(MEDMCQA, "SYS")
    assert c["messages"][0] == {"role": "system", "content": "SYS"}
    assert "B. Vitamin C" in c["messages"][1]["content"]
    assert c["messages"][2]["content"].endswith("Answer: B. Vitamin C")
    assert fmt_medmcqa({**MEDMCQA, "exp": "short"}, "SYS") is None  # no reasoning to learn from
    assert fmt_medmcqa({**MEDMCQA, "choice_type": "multi"}, "SYS") is None
    assert fmt_pubmedqa(PUBMED, "SYS")["messages"][2]["content"].endswith("Answer: yes")
    assert fmt_mmlu_pro(MMLU, "SYS")["messages"][1]["content"].count("\n") >= 3
    assert fmt_messages({"messages": [{"role": "user", "content": "hi"}]}) is None  # must end with assistant


def test_contamination_index_catches_13gram_overlap_and_short_exact_matches():
    idx = ContaminationIndex()
    eval_q = "A 45 year old man presents with crushing chest pain radiating to the left arm and sweating for two hours"
    idx.add(eval_q)
    idx.add("What is 2+2?")
    assert idx.contaminated("Case: " + eval_q.upper() + " What is the diagnosis?")  # case/punctuation-insensitive
    assert idx.contaminated("what is 2 + 2")
    assert not idx.contaminated("A 45 year old woman presents with a headache and blurred vision since this morning")


def test_dedupe_and_quality():
    rows = [chat("Hello  world!"), chat("hello world"), chat("other")]
    assert len(list(dedupe(rows))) == 2
    assert passes_quality(chat("q", "a fine answer"))
    assert not passes_quality(chat("q", ""))
    assert not passes_quality({"messages": [{"role": "user", "content": "q"}]})


def test_mix_and_split_hits_the_replay_ratio():
    domain = [chat(f"d{i}") for i in range(700)]
    replay = [chat(f"r{i}") for i in range(1000)]
    train, valid = mix_and_split(domain, replay, 0.3, 0.02, seed=1)
    data = train + valid
    n_replay = sum(c["messages"][0]["content"].startswith("r") for c in data)
    assert len(data) == 1000 and n_replay == 300
    assert len(valid) == 20
    again = mix_and_split(domain, replay, 0.3, 0.02, seed=1)
    assert again == (train, valid)  # deterministic


def test_training_schedule_counts_micro_batches_and_optimizer_updates():
    cfg = {"epochs": 2.0, "batch_size": 4, "grad_accumulation_steps": 4,
           "lr_schedule": {"name": "cosine_decay", "warmup": 10, "arguments": [1e-4, "auto", 1e-5]}}
    out = training_schedule(cfg, n_train=1000)
    assert out["iters"] == 500  # 2 epochs * 1000 examples / batch 4
    assert out["lr_schedule"]["arguments"] == [1e-4, 500 // 4 - 10, 1e-5]
    assert "epochs" not in out and cfg["lr_schedule"]["arguments"][1] == "auto"  # input untouched


def test_license_policy():
    assert licenses.check("Apache-2.0", "train") == (True, "apache-2.0")
    assert not licenses.check("cc-by-nc-4.0", "train")[0]
    assert licenses.check("cc-by-nc-4.0", "eval")[0]
    assert not licenses.check(None, "eval")[0]
    assert not licenses.check("apache-2.0", "excluded")[0]


# ------------------------------------------------------------------ export
def mlx_adapter(rank=4, scale=2.0):
    rng = np.random.default_rng(0)
    w = {
        "language_model.model.layers.3.self_attn.q_proj.lora_a": rng.standard_normal((16, rank)).astype(np.float32),
        "language_model.model.layers.3.self_attn.q_proj.lora_b": rng.standard_normal((rank, 32)).astype(np.float32),
        "language_model.model.layers.0.mlp.down_proj.lora_a": rng.standard_normal((48, rank)).astype(np.float32),
        "language_model.model.layers.0.mlp.down_proj.lora_b": rng.standard_normal((rank, 16)).astype(np.float32),
    }
    return w, {"lora_parameters": {"rank": rank, "scale": scale, "dropout": 0.05}}


def test_convert_mlx_to_peft_preserves_the_lora_delta():
    w, cfg = mlx_adapter()
    names = {"model.language_model.layers.3.self_attn.q_proj.weight", "model.language_model.layers.0.mlp.down_proj.weight"}
    out, peft = convert(w, cfg, names, base_model_name="Qwen/Qwen3.5-4B")
    assert peft["r"] == 4 and peft["lora_alpha"] == 8.0 and peft["target_modules"] == ["down_proj", "q_proj"]
    a_peft = out["base_model.model.model.language_model.layers.3.self_attn.q_proj.lora_A.weight"]
    b_peft = out["base_model.model.model.language_model.layers.3.self_attn.q_proj.lora_B.weight"]
    assert a_peft.shape == (4, 16) and b_peft.shape == (32, 4)
    x = np.random.default_rng(1).standard_normal((5, 16)).astype(np.float32)
    mlx_y = 2.0 * (x @ w["language_model.model.layers.3.self_attn.q_proj.lora_a"]) @ w[
        "language_model.model.layers.3.self_attn.q_proj.lora_b"]
    peft_y = (peft["lora_alpha"] / peft["r"]) * (x @ a_peft.T) @ b_peft.T
    assert np.allclose(mlx_y, peft_y, atol=1e-5)


def test_convert_rejects_names_missing_from_the_base_and_bad_shapes():
    w, cfg = mlx_adapter()
    with pytest.raises(ValueError, match="does not exist in the base model"):
        convert(w, cfg, {"model.layers.0.mlp.down_proj.weight"})
    w["language_model.model.layers.0.mlp.down_proj.lora_a"] = np.zeros((48, 8), np.float32)
    with pytest.raises(ValueError, match="unexpected shapes"):
        convert(w, cfg, None)
    with pytest.raises(ValueError, match="no prefix rule"):
        map_module("transformer.h.0.attn", [(r"^model\.", "model.")])


def test_safetensors_roundtrip_including_bf16(tmp_path):
    tensors = {"a": np.arange(6, dtype=np.float32).reshape(2, 3), "b": np.array([1.5, -2.25], np.float32)}
    write_safetensors(tmp_path / "x.safetensors", tensors)
    back = read_safetensors(tmp_path / "x.safetensors")
    assert set(back) == {"a", "b"} and np.array_equal(back["a"], tensors["a"])
    # hand-built BF16 file: bf16 is the top half of float32
    values = np.array([1.0, -3.5, 0.15625], np.float32)
    raw = (values.view(np.uint32) >> 16).astype("<u2").tobytes()
    header = json.dumps({"w": {"dtype": "BF16", "shape": [3], "data_offsets": [0, len(raw)]}}).encode()
    (tmp_path / "bf16.safetensors").write_bytes(struct.pack("<Q", len(header)) + header + raw)
    assert np.array_equal(read_safetensors(tmp_path / "bf16.safetensors")["w"], values)


# ------------------------------------------------------------------ metrics and verification
@pytest.mark.parametrize("text,expected", [
    ("Reasoning...\n\nAnswer: C. something", "C"),
    ("<think>maybe A</think>The answer is (B).", "B"),
    ("I pick D. because", "D"),
    ("no idea", None),
])
def test_extract_choice(text, expected):
    assert extract_choice(text, 4) == expected


def test_extract_yes_no_and_number():
    assert extract_yes_no("The trial shows benefit.\nAnswer: no") == "no"
    assert extract_yes_no("<think>yes?</think>Probably maybe.") == "maybe"
    assert extract_number("She has 3 apples, buys 4 more.\nAnswer: 7") == 7.0
    assert extract_number("Total cost: $1,250.50") == 1250.5
    assert extract_number("#### 42") == 42.0
    assert extract_number("none") is None


def test_statistics():
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 0.0)
    assert mcnemar_exact(0, 10) == pytest.approx(2 / 1024)
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 0) == 1.0


def test_distillation_verification():
    assert verify(Task("1", "q", "s", {"type": "mcq", "answer": "b"}), "...\nAnswer: B") is True
    assert verify(Task("1", "q", "s", {"type": "mcq", "answer": "A"}), "Answer: B") is False
    assert verify(Task("1", "q", "s", {"type": "numeric", "answer": 100}), "Answer: 100.5") is True  # 1 % tolerance
    assert verify(Task("1", "q", "s", {"type": "numeric", "answer": 100, "rel_tol": 0.001}), "Answer: 100.5") is False
    assert verify(Task("1", "q", "s"), "anything") is None  # open-ended: goes to rubric review


# ------------------------------------------------------------------ evaluation
def test_items_and_scoring():
    item = make_item("medmcqa-val", "medmcqa", 0, MEDMCQA)
    assert item.gold == "B" and item.n_options == 4 and item.id == "medmcqa-val/m1"
    assert score(item, "Vitamin C.\nAnswer: B") == ("B", True)
    assert make_item("mmlu", "mmlu_pro", 0, MMLU).n_options == 3  # N/A dropped
    gsm = make_item("gsm8k", "gsm8k", 5, {"question": "1+1?", "answer": "steps\n#### 1,002"})
    assert gsm.gold == "1002" and score(gsm, "Answer: 1002") == ("1002", True)
    assert make_item("pq", "pubmedqa", 0, PUBMED).gold == "yes"


def preds(variant, results, suite="medicine", task="t"):
    return [{"suite": suite, "task": task, "item": f"{task}/{i}", "variant": variant, "correct": c,
             "parsed": "A", "finish_reason": "stop"} for i, c in enumerate(results)]


def test_summarize_and_acceptance():
    base = [True] * 50 + [False] * 50
    tuned = [True] * 50 + [True] * 12 + [False] * 38  # +12 points, 12 discordant pairs all in favour
    general_base = [True] * 60 + [False] * 40
    general_tuned = [True] * 59 + [False] * 41
    p = (preds("base", base) + preds("spike-medicine", tuned)
         + preds("base", general_base, "general", "g") + preds("spike-medicine", general_tuned, "general", "g"))
    s = summarize(p)
    cmp = s["suites"]["medicine"]["vs_base"]["spike-medicine"]
    assert cmp["delta_points"] == 12.0 and cmp["baseline_only"] == 0 and cmp["variant_only"] == 12
    assert cmp["p_value"] == pytest.approx(2 / 4096, rel=1e-3)
    assert s["suites"]["medicine"]["accuracy"]["base"]["accuracy"] == 0.5
    acceptance = {"primary": {"suite": "medicine", "min_gain_points": 3.0, "max_p_value": 0.05},
                  "regression": {"suite": "general", "max_drop_points": 1.5}}
    ok, reasons = check_acceptance(s, acceptance, "spike-medicine")
    assert ok, reasons
    acceptance["regression"]["max_drop_points"] = 0.5
    assert not check_acceptance(s, acceptance, "spike-medicine")[0]
    assert not check_acceptance(s, {"primary": {"suite": "finance", "min_gain_points": 3}}, "spike-medicine")[0]


def test_pairwise_summary():
    s = pairwise_summary(["win"] * 14 + ["loss"] * 2 + ["tie"] * 4)
    assert s["win_rate"] == pytest.approx(0.8) and s["sign_test_p"] < 0.01


def test_client_always_sends_explicit_scales():
    client = Client("http://127.0.0.1:1")
    client.table = {"spike-finance": 0, "spike-medicine": 1}
    assert client.lora(None) == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 0.0}]
    assert client.lora("spike-medicine") == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 1.0}]
    with pytest.raises(KeyError):
        client.lora("spike-law")


def test_prepare_pipeline_end_to_end_with_fake_sources(tmp_path, monkeypatch):
    """prepare.py on in-memory rows: license gate, decontamination, replay mix, mlx-lm config, manifest."""
    import prepare
    import yaml

    def med(i, q=None):
        return {**MEDMCQA, "id": f"m{i}", "question": q or f"Case {i}: which vitamin deficiency causes symptom {i} in "
                f"patients who report bleeding gums and slow wound healing after months of poor diet?"}

    leaked = "which drug is first line for uncomplicated hypertension in a young adult with no other conditions today"
    rows = {
        "medmcqa": [med(i) for i in range(40)] + [med(99, leaked)],
        "pubmedqa-artificial": [{**PUBMED, "pubid": i, "question": f"Does treatment {i} reduce mortality?"} for i in range(10)],
        "smoltalk-magpie-ultra": [chat(f"general question {i}", "a general answer") for i in range(200)],
        "smoltalk-constraints": [chat(f"constraint task {i}", "done") for i in range(50)],
        "medmcqa-eval": [med(1000, leaked)],
        "pubmedqa-labeled": [PUBMED],
        "mmlu-pro": [MMLU],
    }
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]
    by_hub = {}
    for name, src in registry.items():
        by_hub[(src["hub"], src.get("config"), src.get("split"))] = name

    def fake_rows(src, offset=0, limit=None):
        data = rows[by_hub[(src["hub"], src.get("config"), src.get("split"))]]
        return iter(data[offset: None if limit is None else offset + limit])

    monkeypatch.setattr(prepare, "load_rows", fake_rows)
    monkeypatch.setattr(prepare.licenses, "hub_license", lambda repo: {
        s["hub"]: s["license"] for s in registry.values()}[repo])
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(ROOT / "training/configs/medicine.yaml"), "--out", str(tmp_path)])
    assert prepare.main() == 0
    out = tmp_path / "medicine"
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["dropped"]["contaminated"] == 1  # the leaked eval question never reaches training
    assert manifest["sources"]["medmcqa"]["kept"] == 40
    counts = manifest["counts"]
    domain = counts["domain"]
    replay_in_mix = counts["train"] + counts["valid"] - domain
    assert domain == 50 and replay_in_mix == int(domain * 0.3 / 0.7)
    mlx = yaml.safe_load((out / "mlx_lora.yaml").read_text())
    assert mlx["iters"] == counts["iters"] and mlx["lr_schedule"]["arguments"][1] != "auto"
    assert mlx["lora_parameters"]["keys"][0] == "self_attn.q_proj" and mlx["mask_prompt"] is True
    lines = (out / "train.jsonl").read_text().splitlines()
    assert len(lines) == counts["train"] and all(json.loads(x)["messages"][-1]["role"] == "assistant" for x in lines)


def test_shared_prompt_templates_do_not_count_as_contamination():
    from spike_train.data import mcq_prompt, pubmedqa_prompt

    idx = ContaminationIndex()
    idx.add(mcq_prompt("Which nerve supplies the deltoid muscle in the shoulder?", ["Axillary", "Radial", "Ulnar", "None"]))
    idx.add(pubmedqa_prompt(PUBMED))
    other = mcq_prompt("Which enzyme is deficient in classic phenylketonuria?", ["PAH", "G6PD", "HGPRT", "None"])
    assert not idx.contaminated(other)
    assert not idx.contaminated(pubmedqa_prompt({**PUBMED, "context": {"contexts": ["Other abstract text."]}}))
