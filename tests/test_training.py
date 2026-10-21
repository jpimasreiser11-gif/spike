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
    oasst_conversations,
    passes_quality,
)
from spike_train.distill import Task, verify  # noqa: E402
from spike_train.evaluation import (  # noqa: E402
    Client,
    Item,
    check_acceptance,
    check_pairwise_acceptance,
    eval_args,
    general_regression,
    make_item,
    pairwise_summary,
    rescore,
    reusable_rows,
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


def oasst(mid, parent, role, text, rank=None, **kw) -> dict:
    return {"message_id": mid, "parent_id": parent, "role": role, "text": text, "rank": rank, "lang": "en",
            "review_result": True, "deleted": False, "synthetic": False, **kw}


# ------------------------------------------------------------------ data
def test_oasst_trees_become_best_ranked_chats():
    rows = [
        oasst("q", None, "prompter", "What is a ledger?"),
        oasst("a0", "q", "assistant", "A record of accounts.", rank=0),
        oasst("a1", "q", "assistant", "No idea.", rank=1),
        oasst("f", "a0", "prompter", "And a journal?"),
        oasst("b", "f", "assistant", "The book of original entry."),  # only reply: kept
        oasst("g", "a1", "prompter", "Why?"),
        oasst("c", "g", "assistant", "Below a rank-1 reply: dropped.", rank=0),
        oasst("q2", None, "prompter", "Hola", lang="es"),
        oasst("d", "q2", "assistant", "Hola, ¿en qué te ayudo?", rank=0),
        oasst("q3", None, "prompter", "Unreviewed", review_result=None),
        oasst("e", "q3", "assistant", "dropped", rank=0),
        oasst("q4", None, "prompter", "Deleted reply"),
        oasst("x", "q4", "assistant", "deleted", rank=0, deleted=True),
        oasst("y", "q4", "assistant", "two unranked live replies: neither is best"),
        oasst("z", "q4", "assistant", "second unranked reply"),
    ]
    chats = oasst_conversations(rows, langs=["en"])
    assert [[m["content"] for m in c["messages"]] for c in chats] == [
        ["What is a ledger?", "A record of accounts."],
        ["What is a ledger?", "A record of accounts.", "And a journal?", "The book of original entry."],
    ]
    assert chats[1]["messages"][2]["role"] == "user"
    assert len(oasst_conversations(rows, langs=["en", "es"])) == 3


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


# Response endings seen in the first Qwen3.5-4B baseline run (evals/results/baseline-mac-20261017).
@pytest.mark.parametrize("text,expected", [
    ("*   D. $Lfh$: Incorrect order.\n*   E-J: extra symbols.\n\nThe correct translation is $Lhf$.\n\nA", "A"),
    ("Therefore, the correct option is **F**.\n\n**F**", "F"),
    ("Therefore, option B is the correct description.\n\nB", "B"),
    ("Therefore, the correct option is **C**.\n\n**Answer:** C", "C"),
    ("...the slave of the passions.\n\n**Answer:** G", "G"),
    ("*   J: $Bc$ - Matches our derivation perfectly.\n\nThe correct option is **J**.", "J"),
    ("The answer is a matter of definition, so I pick B. because it fits", "B"),
    ("Therefore, the par value is reduced to $2.\n\n**Correct Option:** I", "I"),
    ("*   Option G is incorrect because masking applies to sound.", None),
])
def test_extract_choice_real_endings(text, expected):
    assert extract_choice(text, 10) == expected


def test_extract_yes_no_bold_answer():
    assert extract_yes_no("**Answer:** no. Larger trials could still say yes.") == "no"


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


SEEDS = ["Plan a six week launch campaign for a local bakery with a small budget",
         "Write three subject lines for a B2B invoicing SaaS trial reactivation email"]


class ScriptedTeacher:
    """Stands in for the teacher. `expand(call_number)` is its answer to each task-expansion request (the only
    requests that start with a user message); every task answer is `answer`, and the rubric review gives `score`."""

    def __init__(self, expand=lambda n: "", answer="A specific and actionable answer.", score=9):
        self.expand, self.answer, self.score, self.calls = expand, answer, score, 0
        self.model = "scripted"

    async def chat(self, messages, temperature=0.7, max_tokens=4096, thinking=True):
        if messages[0]["role"] == "user":
            self.calls += 1
            return self.expand(self.calls), ""
        return self.answer, ""

    async def review(self, task, response):
        return self.score

    async def aclose(self):
        pass


def fresh_tasks(call: int, n: int = 20) -> str:
    return "\n".join(f"{i + 1}. Brief {call}-{i}: grow signups for a niche product on a small budget" for i in range(n))


async def test_expand_seeds_reaches_the_target_with_distinct_tasks():
    from distill import expand_seeds

    teacher = ScriptedTeacher(fresh_tasks)
    tasks = await expand_seeds(teacher, SEEDS, "Marketing", 50, seed=0)
    assert len(tasks) == 50 and len(set(tasks)) == 50 and tasks[:2] == SEEDS and teacher.calls == 3


async def test_expand_seeds_stops_when_the_teacher_only_returns_duplicates():
    from distill import MAX_STALLS, expand_seeds

    teacher = ScriptedTeacher(lambda n: "\n".join(SEEDS))  # the old loop never ended here
    with pytest.raises(SystemExit, match=rf"only 2 distinct tasks of the 50 asked for.*in {MAX_STALLS} calls"):
        await expand_seeds(teacher, SEEDS, "Marketing", 50, seed=0)
    assert teacher.calls == MAX_STALLS
    empty = ScriptedTeacher(lambda n: "")  # a teacher that answers nothing is the same
    with pytest.raises(SystemExit, match="distill.expand_to"):
        await expand_seeds(empty, SEEDS, "Marketing", 50, seed=0)


async def test_expand_seeds_gives_up_on_a_teacher_that_adds_one_task_per_call():
    from distill import MAX_STALLS, PER_CALL, expand_seeds

    teacher = ScriptedTeacher(lambda n: f"Brief {n}: grow signups for a niche product with a small budget")
    with pytest.raises(SystemExit, match="only 21 distinct tasks of the 100 asked for"):
        await expand_seeds(teacher, SEEDS[:1], "Marketing", 100, seed=0)
    assert teacher.calls == 3 * -(-99 // PER_CALL) + MAX_STALLS == 20
    # an occasional empty answer does not end a teacher that is making progress
    flaky = ScriptedTeacher(lambda n: "" if n % 3 == 0 else fresh_tasks(n))
    assert len(await expand_seeds(flaky, SEEDS, "Marketing", 80, seed=0)) == 80


async def test_open_ended_distillation_is_rubric_filtered_and_never_marked_verified():
    from spike_train.distill import distill_task

    open_task, gold_task = Task("t1", "q", "sys"), Task("t2", "q", "sys", {"type": "mcq", "answer": "B"})
    kept = await distill_task(ScriptedTeacher(score=8), open_task, samples=2, min_score=8, keep_reasoning=False)
    assert kept["meta"] == {"task_id": "t1", "verified": False, "source": "distill"}
    assert await distill_task(ScriptedTeacher(score=7), open_task, samples=2, min_score=8, keep_reasoning=False) is None
    verified = await distill_task(ScriptedTeacher(answer="Answer: B", score=0), gold_task, 2, 8, False)
    assert verified["meta"]["verified"] is True  # the gold match decides; the rubric is not consulted
    assert await distill_task(ScriptedTeacher(answer="Answer: A"), gold_task, 2, 8, False) is None


def distill_run(tmp_path, monkeypatch, teacher, *flags: str, hub=None):
    """training/distill.py main() for marketing with the Hub and the teacher replaced; returns the rows it wrote."""
    import distill
    import yaml

    seeds = tmp_path / "seeds.jsonl"
    seeds.write_text("".join(json.dumps({"prompt": x}) + "\n" for x in SEEDS))
    cfg = tmp_path / "marketing.yaml"
    cfg.write_text(yaml.safe_dump({"specialist": "marketing", "seed": 0,
                                   "distill": {"enabled": True, "seeds": str(seeds), "expand_to": 30, "min_score": 8}}))
    default_hub = {"mlx-community/Qwen3.6-35B-A3B-4bit": "apache-2.0"}.__getitem__  # the faked Hub: repo -> license
    monkeypatch.setattr(distill.licenses, "hub_model_license", hub or default_hub)
    monkeypatch.setattr(distill, "Teacher", lambda *a, **k: teacher)
    out = tmp_path / "out" / "distilled.jsonl"
    monkeypatch.setattr(sys, "argv", ["distill.py", str(cfg), "--out", str(out), *flags])
    assert distill.main() == 0
    return [json.loads(line) for line in out.read_text().splitlines()]


def test_distill_records_the_teacher_and_its_license_on_every_row(tmp_path, monkeypatch, capsys):
    rows = distill_run(tmp_path, monkeypatch, ScriptedTeacher(fresh_tasks))
    assert len(rows) == 30
    for row in rows:
        assert row["meta"] == {"task_id": row["meta"]["task_id"], "verified": False, "source": "distill",
                               "teacher": "mlx-community/Qwen3.6-35B-A3B-4bit", "teacher_license": "apache-2.0"}
    summary = json.loads(capsys.readouterr().out)
    assert summary["teacher_license"] == "apache-2.0" and summary["kept"] == 30


def test_distill_checks_the_repo_named_by_teacher_repo_when_the_served_name_is_an_alias(tmp_path, monkeypatch):
    rows = distill_run(tmp_path, monkeypatch, ScriptedTeacher(fresh_tasks), "--teacher-model", "local-alias",
                       "--teacher-repo", "Qwen/Qwen3.6-35B-A3B", hub={"Qwen/Qwen3.6-35B-A3B": "Apache-2.0"}.__getitem__)
    assert rows[0]["meta"]["teacher"] == "Qwen/Qwen3.6-35B-A3B" and rows[0]["meta"]["teacher_license"] == "apache-2.0"


@pytest.mark.parametrize("hub, message", [
    ("other", "teacher 'mlx-community/Qwen3.6-35B-A3B-4bit': license 'other' is not allowed for role 'train'"),
    (None, "no license declared"),
])
def test_distill_refuses_a_teacher_whose_license_is_not_allowed_or_unknown(tmp_path, monkeypatch, hub, message):
    teacher = ScriptedTeacher(fresh_tasks)
    with pytest.raises(SystemExit, match=f"refusing to distill: .*{message}"):
        distill_run(tmp_path, monkeypatch, teacher, hub=lambda repo: hub)
    assert teacher.calls == 0 and not (tmp_path / "out").exists()  # refused before a single task was sent


def test_distill_refuses_a_teacher_it_cannot_find_on_the_hub(tmp_path, monkeypatch):
    import httpx

    def missing(repo):
        raise httpx.ConnectError("no network")

    with pytest.raises(SystemExit, match="cannot read its license on the Hugging Face Hub.*--teacher-repo"):
        distill_run(tmp_path, monkeypatch, ScriptedTeacher(), hub=missing)


def test_hub_license_reads_models_and_datasets_from_their_own_endpoints(monkeypatch):
    import httpx

    pages = {"models/a/b": {"cardData": {"license": ["Apache-2.0"]}}, "models/a/tagged": {"tags": ["x", "license:mit"]},
             "models/a/none": {}, "datasets/c/d": {"cardData": {"license": "cc-by-4.0"}}}
    asked = []

    class Page:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return self

        def json(self):
            return self.data

    def get(url, timeout=None):
        asked.append(url)
        return Page(pages[url.removeprefix("https://huggingface.co/api/")])

    monkeypatch.setattr(httpx, "get", get)
    assert licenses.hub_model_license("a/b") == "Apache-2.0" and licenses.hub_license("c/d") == "cc-by-4.0"
    assert licenses.hub_model_license("a/tagged") == "mit"
    assert asked == ["https://huggingface.co/api/models/a/b", "https://huggingface.co/api/datasets/c/d",
                     "https://huggingface.co/api/models/a/tagged"]
    assert licenses.teacher_license("a/b") == "apache-2.0"  # normalized, as the allowlist spells it
    with pytest.raises(ValueError, match="no license declared"):
        licenses.teacher_license("a/none")


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


def test_eval_args_come_from_the_training_config():
    assert eval_args({}) == []  # run_eval.py keeps its own default
    assert eval_args({"eval": {"max_tokens": 2048}}) == ["--max-tokens", "2048"]
    with pytest.raises(ValueError):
        eval_args({"eval": {"max_tokens": 0}})
    with pytest.raises(ValueError):
        eval_args({"eval": {"temperature": 0.7}})  # unknown keys are not silently ignored


def test_medicine_eval_uses_2048_tokens_through_run_specialist():
    import yaml

    cfg = yaml.safe_load((ROOT / "training" / "configs" / "medicine.yaml").read_text())
    assert eval_args(cfg) == ["--max-tokens", "2048"]
    script = (ROOT / "training" / "scripts" / "run_specialist.sh").read_text()
    assert "spike_train.evaluation import eval_args" in script and '"${eval_extra[@]}"' in script


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


def test_resume_reuses_only_complete_groups():
    saved = [{"suite": "s", "task": "t", "variant": "base", "item": f"t/{i}"} for i in range(3)]
    saved += [{"suite": "s", "task": "t", "variant": "spike-x", "item": "t/0"}]  # cut off mid-group
    ids = ["t/0", "t/1", "t/2"]
    assert [r["item"] for r in reusable_rows(saved, "s", "t", "base", ids)] == ids
    assert reusable_rows(saved, "s", "t", "spike-x", ids) is None  # incomplete: generate again
    assert reusable_rows(saved, "s", "t", "base", ["t/0", "t/1", "t/9"]) is None  # other items: never mixed
    assert reusable_rows(saved, "other", "t", "base", ids) is None


def test_rescore_recomputes_parsed_and_correct_from_saved_responses():
    items = {"t/1": Item("t/1", "t", "q", "mcq", "A", 10), "t/2": Item("t/2", "t", "q", "yesno", "no")}
    rows = [
        {"item": "t/1", "variant": "base", "gold": "A", "parsed": "D", "correct": False,
         "response": "D. wrong option text\n\nA"},
        {"item": "t/2", "variant": "base", "gold": "no", "parsed": "yes", "correct": False,
         "response": "**Answer:** no. Trials could say yes."},
    ]
    out = rescore(rows, items)
    assert [(r["parsed"], r["correct"]) for r in out] == [("A", True), ("no", True)]
    assert rows[0]["parsed"] == "D"  # the input rows are not modified
    with pytest.raises(KeyError):
        rescore([{**rows[0], "item": "t/missing"}], items)


def test_pairwise_summary():
    s = pairwise_summary(["win"] * 14 + ["loss"] * 2 + ["tie"] * 4)
    assert s["win_rate"] == pytest.approx(0.8) and s["sign_test_p"] < 0.01


MARKETING_RULE = {"primary": {"suite": "marketing-pairwise", "min_win_rate": 0.60},
                  "regression": {"suite": "general", "max_drop_points": 1.5}}


def general_run(adapter_correct: list[bool], variant: str = "spike-marketing") -> dict:
    """A run_eval.py summary of the general suite: 100 items, the base model right on the first 60."""
    base = [True] * 60 + [False] * 40
    return summarize(preds("base", base, "general", "g") + preds(variant, adapter_correct, "general", "g"))


def test_general_regression_reads_the_base_vs_adapter_comparison_of_a_run():
    run = general_run([True] * 59 + [False] * 41)
    assert general_regression(run, "general", "spike-marketing") == {
        "suite": "general", "variant": "spike-marketing", "paired_n": 100, "delta_points": -1.0, "p_value": 1.0}
    with pytest.raises(ValueError, match="no suite 'general' for 'spike-other'"):
        general_regression(run, "general", "spike-other")
    with pytest.raises(ValueError, match="no suite 'law'"):
        general_regression(run, "law", "spike-marketing")


def pairwise_result(verdicts: list[str], drop_run: list[bool] | None) -> dict:
    s = {"adapter": "spike-marketing", **pairwise_summary(verdicts)}
    if drop_run is not None:
        s["general"] = general_regression(general_run(drop_run), "general", "spike-marketing")
    return s


def test_pairwise_acceptance_needs_the_win_rate_and_the_general_suite():
    wins = ["win"] * 17 + ["loss"] * 2 + ["tie"] * 5                      # 0.8125, p well under 0.05
    fine = [True] * 59 + [False] * 41                                      # -1.0 pts
    ok, reasons = check_pairwise_acceptance(pairwise_result(wins, fine), MARKETING_RULE)
    assert ok and "win rate 0.812" in reasons[0] and reasons[1] == "general: -1.00 pts (max drop 1.5)"
    lost = [True] * 56 + [False] * 44                                      # -4.0 pts: the old script accepted this
    ok, reasons = check_pairwise_acceptance(pairwise_result(wins, lost), MARKETING_RULE)
    assert not ok and reasons[1] == "general: -4.00 pts (max drop 1.5)"
    weak = ["win"] * 7 + ["loss"] * 5 + ["tie"] * 12                      # 0.54 and p ~ 0.77
    assert not check_pairwise_acceptance(pairwise_result(weak, fine), MARKETING_RULE)[0]
    ok, reasons = check_pairwise_acceptance(pairwise_result(wins, None), MARKETING_RULE)  # not evaluated = rejected
    assert not ok and reasons[-1] == "regression suite 'general' was not evaluated for spike-marketing"
    assert check_pairwise_acceptance(pairwise_result(wins, None), {"primary": MARKETING_RULE["primary"]})[0]
    assert not check_pairwise_acceptance(pairwise_result(wins, fine), {"primary": {"suite": "medicine",
                                                                                   "min_gain_points": 3.0}})[0]
    # the exact-answer rule does not read a pairwise summary: it has no variants or suites to measure
    exact = {"primary": {"suite": "m", "min_gain_points": 1}}
    assert not check_acceptance(pairwise_result(wins, fine) | {"suites": {}}, exact, "spike-marketing")[0]


class FakeServer:
    def __init__(self, config):
        self.base_url = "http://127.0.0.1:1"

    async def start(self):
        pass

    async def stop(self):
        pass


class FakeClient:
    """llama-server client: the adapter's answers are 'adapter', the base model's 'base'; every request is logged."""
    temperatures: list[float] = []

    def __init__(self, base_url, concurrency=1):
        pass

    async def adapters(self):
        return {"spike-marketing": 0}

    def lora(self, adapter):
        return [{"id": 0, "scale": 1.0 if adapter else 0.0}]

    async def chat(self, system, prompt, lora, max_tokens, temperature=0.0, seed=0, thinking=False):
        FakeClient.temperatures.append(temperature)
        return {"content": "adapter" if lora[0]["scale"] else "base"}

    async def aclose(self):
        pass


class FakeJudge:
    """Always prefers the adapter's answer, whichever position it is shown in (or always the base model's)."""
    prefers_adapter = True

    def __init__(self, *args, **kwargs):
        pass

    async def chat(self, messages, **kwargs):
        a_is_adapter = "ANSWER A:\nadapter" in messages[-1]["content"]
        return json.dumps({"better": "A" if a_is_adapter == FakeJudge.prefers_adapter else "B"}), ""

    async def aclose(self):
        pass


def run_pairwise(tmp_path, monkeypatch, *flags: str, general: Path | None = None, judge_prefers_adapter=True):
    """evals/pairwise.py main() with the model server, client and judge replaced; returns (exit code, summary)."""
    monkeypatch.syspath_prepend(str(ROOT / "evals"))
    import pairwise

    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text("".join(json.dumps({"id": f"p{i}", "prompt": f"Plan a campaign number {i}"}) + "\n"
                               for i in range(12)))
    FakeClient.temperatures = []
    FakeJudge.prefers_adapter = judge_prefers_adapter
    monkeypatch.setattr(pairwise, "Client", FakeClient)
    monkeypatch.setattr(pairwise, "Teacher", FakeJudge)
    monkeypatch.setattr("spike.runtime.llamacpp_server.LlamaServer", FakeServer)
    argv = ["pairwise.py", "--specialist", "marketing", "--prompts", str(prompts), "--model", "base.gguf",
            "--adapter", "spike-marketing.gguf", "--out", str(tmp_path / "out"), *flags]
    if general:
        argv += ["--general-eval", str(general)]
    monkeypatch.setattr(sys, "argv", argv)
    code = pairwise.main()
    return code, json.loads((tmp_path / "out" / "summary.json").read_text())


def write_run(folder: Path, run: dict) -> Path:
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps(run))
    return folder


def test_pairwise_generation_is_greedy_unless_asked(tmp_path, monkeypatch):
    code, summary = run_pairwise(tmp_path, monkeypatch)
    assert code == 0 and summary["temperature"] == 0.0 and set(FakeClient.temperatures) == {0.0}
    assert len(FakeClient.temperatures) == 24 and "accepted" not in summary  # no --acceptance: measured only
    code, summary = run_pairwise(tmp_path / "t", monkeypatch, "--temperature", "0.7")
    assert summary["temperature"] == 0.7 and set(FakeClient.temperatures) == {0.7}


def test_pairwise_round_is_accepted_only_if_the_general_suite_holds_too(tmp_path, monkeypatch):
    marketing = ["--acceptance", str(ROOT / "training" / "configs" / "marketing.yaml")]
    held = write_run(tmp_path / "held", general_run([True] * 59 + [False] * 41))
    code, summary = run_pairwise(tmp_path / "a", monkeypatch, *marketing, general=held)
    assert code == 0 and summary["accepted"] and summary["win_rate"] == 1.0
    assert summary["general"]["delta_points"] == -1.0 and Path(summary["general"]["run"]) == held / "summary.json"

    lost = write_run(tmp_path / "lost", general_run([True] * 56 + [False] * 44))
    code, summary = run_pairwise(tmp_path / "b", monkeypatch, *marketing, general=lost)
    assert code == 2 and not summary["accepted"] and summary["win_rate"] == 1.0  # exit code 2 = rejected
    assert summary["reasons"][-1] == "general: -4.00 pts (max drop 1.5)"

    code, summary = run_pairwise(tmp_path / "c", monkeypatch, *marketing, general=held, judge_prefers_adapter=False)
    assert code == 2 and not summary["accepted"] and summary["win_rate"] == 0.0


def test_pairwise_with_a_regression_limit_stops_early_without_the_general_run(tmp_path, monkeypatch):
    marketing = ["--acceptance", str(ROOT / "training" / "configs" / "marketing.yaml")]
    with pytest.raises(SystemExit, match="regression limit on 'general'.*--general-eval"):
        run_pairwise(tmp_path / "a", monkeypatch, *marketing)
    other = write_run(tmp_path / "other", general_run([True] * 60 + [False] * 40, variant="spike-medicine"))
    with pytest.raises(SystemExit, match="no suite 'general' for 'spike-marketing'"):
        run_pairwise(tmp_path / "b", monkeypatch, *marketing, general=other)
    with pytest.raises(SystemExit, match="no general eval results"):
        run_pairwise(tmp_path / "c", monkeypatch, *marketing, general=tmp_path / "missing")
    assert FakeClient.temperatures == []  # nothing was generated before any of these stops
    with pytest.raises(SystemExit):  # a general run without an acceptance rule has no suite or limit to apply
        run_pairwise(tmp_path / "d", monkeypatch, general=other)


def test_run_specialist_runs_the_general_suite_before_the_pairwise_judge():
    script = (ROOT / "training" / "scripts" / "run_specialist.sh").read_text()
    start = script.index("if [[ $spec == marketing ]]")
    marketing = script[start:script.index("\nelse\n", start)]
    assert marketing.index("python evals/run_eval.py --suites general") < marketing.index("python evals/pairwise.py")
    assert '--out "$general_out"' in marketing and '--general-eval "$general_out"' in marketing


def test_client_always_sends_explicit_scales():
    client = Client("http://127.0.0.1:1")
    client.table = {"spike-finance": 0, "spike-medicine": 1}
    assert client.lora(None) == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 0.0}]
    assert client.lora("spike-medicine") == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 1.0}]
    with pytest.raises(KeyError):
        client.lora("spike-law")


LEAKED = "which drug is first line for uncomplicated hypertension in a young adult with no other conditions today"


TEACHER = "Qwen/Qwen3.6-35B-A3B"
TEACHER_LICENSES: dict[str, str | None] = {TEACHER: "apache-2.0"}   # what the faked Hub says about each teacher repo


def run_prepare(tmp_path, monkeypatch, extra: list[str] | None = None, config: str = "medicine"):
    """prepare.py for a config on in-memory rows; returns its output folder."""
    import prepare

    out = prepare_env(tmp_path, monkeypatch, extra, config)
    assert prepare.main() == 0
    return out


def prepare_env(tmp_path, monkeypatch, extra: list[str] | None = None, config: str = "medicine"):
    """Replace everything prepare.py reads from the network with in-memory rows; returns its output folder."""
    import prepare
    import yaml

    def med(i, q=None):
        return {**MEDMCQA, "id": f"m{i}", "question": q or f"Case {i}: which vitamin deficiency causes symptom {i} in "
                f"patients who report bleeding gums and slow wound healing after months of poor diet?"}

    leaked = LEAKED
    rows = {
        "medmcqa": [med(i) for i in range(40)] + [med(99, leaked)] + [med(98, "LONG " + "word " * 30)],
        "pubmedqa-artificial": [{**PUBMED, "pubid": i, "question": f"Does treatment {i} reduce mortality?"} for i in range(10)],
        "oasst2": [r for i in range(200) for r in (oasst(f"q{i}", None, "prompter", f"general question {i}"),
                                                    oasst(f"a{i}", f"q{i}", "assistant", "a general answer", rank=0))],
        "medmcqa-eval": [med(1000, leaked)],
        "pubmedqa-labeled": [PUBMED],
        "mmlu-pro": [MMLU],
    }
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]
    by_hub = {}
    for name, src in registry.items():
        if "hub" in src:  # URL sources (FinQA, TAT-QA) are not on the Hub
            by_hub[(src["hub"], src.get("config"), src.get("split"))] = name

    def fake_rows(src, offset=0, limit=None):
        data = rows[by_hub[(src["hub"], src.get("config"), src.get("split"))]]
        return iter(data[offset: None if limit is None else offset + limit])

    monkeypatch.setattr(prepare, "load_rows", fake_rows)
    monkeypatch.setattr(prepare, "load_token_counter", lambda base_model: lambda chat: (
        100_000 if "LONG" in chat["messages"][1]["content"] else 100))
    monkeypatch.setattr(prepare.licenses, "hub_license", lambda repo: {
        s["hub"]: s["license"] for s in registry.values() if "hub" in s}[repo])
    monkeypatch.setattr(prepare.licenses, "hub_model_license", lambda repo: TEACHER_LICENSES[repo])
    cfg = ROOT / "training" / "configs" / f"{config}.yaml"
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(cfg), "--out", str(tmp_path), *(extra or [])])
    return tmp_path / config


def test_prepare_pipeline_end_to_end_with_fake_sources(tmp_path, monkeypatch):
    """prepare.py on in-memory rows: license gate, decontamination, replay mix, mlx-lm config, manifest."""
    import yaml

    out = run_prepare(tmp_path, monkeypatch)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["dropped"]["contaminated"] == 1  # the leaked eval question never reaches training
    assert manifest["dropped"]["too_long"] == 1  # longer than max_seq_length: dropped, never truncated
    assert manifest["sources"]["medmcqa"]["kept"] == 40
    assert manifest["sources"]["oasst2"]["built"] == 200
    assert not any(name.startswith("smoltalk") for name in manifest["sources"])  # replay is human-written only
    counts = manifest["counts"]
    domain = counts["domain"]
    replay_in_mix = counts["train"] + counts["valid"] - domain
    assert domain == 50 and replay_in_mix == int(domain * 0.3 / 0.7)
    assert abs(counts["replay_ratio_actual"] - 0.3) < 0.01
    mlx = yaml.safe_load((out / "mlx_lora.yaml").read_text())
    assert mlx["iters"] == counts["iters"] and mlx["lr_schedule"]["arguments"][1] != "auto"
    assert mlx["lora_parameters"]["keys"][0] == "self_attn.q_proj" and mlx["mask_prompt"] is True
    lines = (out / "train.jsonl").read_text().splitlines()
    assert len(lines) == counts["train"] and all(json.loads(x)["messages"][-1]["role"] == "assistant" for x in lines)


def test_prepare_adds_the_users_approved_corrections_for_its_specialist(tmp_path, monkeypatch):
    """Evolution level 3: `spike evolve dataset` output joins the domain data, only for the config's specialist,
    under its system prompt, decontaminated like the rest."""
    from spike.specialists.catalog import load_catalog

    def example(specialist, question, answer="Una respuesta corregida y completa sobre la dosis adecuada."):
        return json.dumps({"messages": [{"role": "system", "content": "otro prompt"}, {"role": "user", "content": question},
                                        {"role": "assistant", "content": answer}],
                           "meta": {"specialist": specialist, "source": "spike-correction"}})

    corrections = tmp_path / "spike-training.jsonl"
    corrections.write_text("\n".join([example("medicine", "¿Qué dosis de paracetamol es segura para un adulto sano?"),
                                      example("medicine", LEAKED), example("finance", "¿Qué es el EBITDA?")]) + "\n")
    out = run_prepare(tmp_path / "data", monkeypatch, ["--corrections", str(corrections)])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sources"]["corrections:spike-training.jsonl"]["kept"] == 1  # the leaked one and finance's are out
    assert manifest["counts"]["domain"] == 51 and manifest["dropped"]["contaminated"] == 2
    chats = [json.loads(x) for x in [*(out / "train.jsonl").read_text().splitlines(),
                                     *(out / "valid.jsonl").read_text().splitlines()]]
    mine = [c for c in chats if "paracetamol" in c["messages"][1]["content"]]
    assert len(mine) == 1 and mine[0]["messages"][0]["content"] == load_catalog().get("medicine").system_prompt


def distilled_file(tmp_path, n: int = 40, **meta) -> Path:
    """What training/distill.py writes for marketing: open-ended chats with the teacher recorded on every row."""
    meta = {"task_id": "marketing-0", "verified": False, "source": "distill", "teacher": TEACHER,
            "teacher_license": "apache-2.0", **meta}
    rows = [{"messages": [{"role": "system", "content": "marketing system prompt"},
                          {"role": "user", "content": f"Task {i}: plan the launch of product number {i} for a bakery "
                                                      f"chain with a budget of {i * 100 + 500} euros"},
                          {"role": "assistant", "content": f"A specific plan {i} with channels, budget, weekly KPIs."}],
             "meta": {k: v for k, v in meta.items() if v is not None}} for i in range(n)]
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "distilled.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_prepare_stops_when_the_recipe_has_no_domain_data(tmp_path, monkeypatch):
    """marketing has no domain_sources: without distilled data the old run wrote empty train/valid and went on."""
    import prepare

    out = prepare_env(tmp_path, monkeypatch, config="marketing")
    real_rows, downloads = prepare.load_rows, []
    monkeypatch.setattr(prepare, "load_rows", lambda *a, **k: downloads.append(a) or real_rows(*a, **k))
    with pytest.raises(SystemExit, match=r"no domain training data for 'marketing'.*training/distill.py .*--distilled"):
        prepare.main()
    assert not downloads and not (out / "train.jsonl").exists() and not (out / "manifest.json").exists()  # at once
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")  # a distillation that kept nothing is the same problem
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--distilled", str(empty)])
    with pytest.raises(SystemExit, match="no domain training data"):
        prepare.main()
    assert not (out / "train.jsonl").exists()


def test_prepare_records_the_real_teacher_license_of_distilled_data(tmp_path, monkeypatch):
    out = run_prepare(tmp_path, monkeypatch, ["--distilled", str(distilled_file(tmp_path))], config="marketing")
    manifest = json.loads((out / "manifest.json").read_text())
    record = manifest["sources"]["distilled:distilled.jsonl"]
    lic = {"license_hub": "apache-2.0", "license_recorded": "apache-2.0"}
    assert record == {"role": "train", "teachers": {TEACHER: lic}, "kept": 40}
    assert "Apache-2.0 teacher" not in json.dumps(manifest) and manifest["counts"]["domain"] == 40
    trained = [json.loads(line) for line in (out / "train.jsonl").read_text().splitlines()]
    assert all("meta" not in chat for chat in trained)  # the provenance stays in the manifest


@pytest.mark.parametrize("hub, reason", [
    ("other", "license 'other' is not allowed for role 'train'"),
    ("cc-by-nc-4.0", "license 'cc-by-nc-4.0' is not allowed for role 'train'"),
    (None, "no license declared"),
])
def test_prepare_refuses_a_teacher_whose_license_is_not_allowed_or_unknown(tmp_path, monkeypatch, hub, reason):
    import prepare

    prepare_env(tmp_path, monkeypatch, ["--distilled", str(distilled_file(tmp_path))], config="marketing")
    monkeypatch.setitem(TEACHER_LICENSES, TEACHER, hub)  # the Hub says so now, whatever distill.py recorded
    with pytest.raises(SystemExit, match=f"refusing distilled.jsonl: teacher '{TEACHER}': {reason}"):
        prepare.main()
    assert not (tmp_path / "marketing" / "train.jsonl").exists()


def test_prepare_refuses_distilled_rows_that_do_not_name_their_teacher(tmp_path, monkeypatch):
    import prepare

    prepare_env(tmp_path, monkeypatch, ["--distilled", str(distilled_file(tmp_path, teacher=None))], config="marketing")
    with pytest.raises(SystemExit, match=r"distilled.jsonl:1 has no teacher record"):
        prepare.main()


def test_prepare_offline_trusts_the_recorded_teacher_license_but_still_applies_the_allowlist(tmp_path, monkeypatch):
    import prepare

    def no_hub(repo):
        raise AssertionError("the Hub must not be asked")

    ok = distilled_file(tmp_path / "ok")
    out = prepare_env(tmp_path / "ok", monkeypatch, ["--distilled", str(ok), "--skip-license-check"],
                      config="marketing")
    monkeypatch.setattr(prepare.licenses, "hub_model_license", no_hub)
    assert prepare.main() == 0
    assert json.loads((out / "manifest.json").read_text())["sources"]["distilled:distilled.jsonl"]["teachers"][TEACHER][
        "license_hub"] == "apache-2.0"
    for recorded, reason in (("other", "license 'other' is not allowed"), (None, "no license declared")):
        bad = distilled_file(tmp_path / str(recorded), teacher_license=recorded)  # None: row names no license
        prepare_env(tmp_path / str(recorded), monkeypatch, ["--distilled", str(bad), "--skip-license-check"],
                    config="marketing")
        monkeypatch.setattr(prepare.licenses, "hub_model_license", no_hub)
        with pytest.raises(SystemExit, match=f"refusing distilled.jsonl: teacher '{TEACHER}': {reason}"):
            prepare.main()


@pytest.mark.parametrize("source", ["smoltalk-constraints", "smoltalk-magpie-ultra"])
def test_prepare_refuses_excluded_replay_sources(tmp_path, monkeypatch, source):
    import prepare
    import yaml

    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]
    assert registry[source]["role"] == "excluded"
    cfg = yaml.safe_load((ROOT / "training" / "configs" / "medicine.yaml").read_text())
    cfg["replay"]["sources"].append({"source": source, "max": 10})
    (tmp_path / "cfg.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(prepare, "load_rows", lambda src, offset=0, limit=None: iter([]))
    monkeypatch.setattr(prepare.licenses, "hub_license", lambda repo: "apache-2.0")
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(tmp_path / "cfg.yaml"), "--out", str(tmp_path)])
    with pytest.raises(SystemExit, match=f"refusing source '{source}'"):
        prepare.main()


def test_training_configs_fit_a_36gb_mac_with_the_same_effective_batch():
    """batch 4 x 2048 tokens ran out of Metal memory on the first step: training memory grows ~19 MB per token
    (measured 11 GB at 128 tokens, 23 GB at 768). Batch 1 x 16 accumulation keeps the effective batch and the
    update count; prepare.py drops chats longer than max_seq_length instead of letting mlx-lm truncate them."""
    import prepare
    import yaml

    for path in (ROOT / "training" / "configs").glob("*.yaml"):
        train = yaml.safe_load(path.read_text())["train"]
        assert train["batch_size"] == 1 and train["grad_accumulation_steps"] == 16, path.name
        assert train["max_seq_length"] <= 768, path.name  # measured: 18.7 GB peak RSS at 768, OOM at 1024
        sched = prepare.training_schedule(train, 26050)
        assert sched["iters"] // 16 == prepare.training_schedule({**train, "batch_size": 4,
                                                                   "grad_accumulation_steps": 4}, 26050)["iters"] // 4


def test_no_training_config_uses_an_excluded_source():
    import yaml

    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]
    for path in (ROOT / "training" / "configs").glob("*.yaml"):
        cfg = yaml.safe_load(path.read_text())
        used = [s["source"] for s in cfg.get("domain_sources", []) + (cfg.get("replay") or {}).get("sources", [])]
        assert all(registry[name]["role"] == "train" for name in used), path.name


def test_shared_prompt_templates_do_not_count_as_contamination():
    from spike_train.data import mcq_prompt, pubmedqa_prompt

    idx = ContaminationIndex()
    idx.add(mcq_prompt("Which nerve supplies the deltoid muscle in the shoulder?", ["Axillary", "Radial", "Ulnar", "None"]))
    idx.add(pubmedqa_prompt(PUBMED))
    other = mcq_prompt("Which enzyme is deficient in classic phenylketonuria?", ["PAH", "G6PD", "HGPRT", "None"])
    assert not idx.contaminated(other)
    assert not idx.contaminated(pubmedqa_prompt({**PUBMED, "context": {"contexts": ["Other abstract text."]}}))
