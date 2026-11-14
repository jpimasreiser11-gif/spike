"""docs/results/specialists.json (scripts/results_index.py) and the per-question export (evals/export_questions.py):
the committed index is current, valid and says what the committed evidence says; archived rounds, unfinished rounds,
pairwise finals and per-topic counts are read right; questions get the ids run_eval.py gives them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "evals"))

import export_questions  # noqa: E402
import results_index  # noqa: E402

SCHEMA = json.loads((ROOT / "docs/schemas/specialist-results.schema.json").read_text(encoding="utf-8"))


def test_the_committed_index_is_current_and_valid():
    assert results_index.main(["--check"]) == 0, "run python scripts/results_index.py"
    data = json.loads(results_index.OUT.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)


def test_the_index_says_what_the_medicine_evidence_says():
    data = results_index.build()
    med = data["specialists"]["medicine"]
    record = json.loads((ROOT / "spike/specialists/acceptance/medicine.json").read_text(encoding="utf-8"))
    assert med["status"] == "adapter_accepted" and med["accepted"]["sha256"] == record["sha256"]
    assert [(r["round"], r["verdict"]) for r in med["rounds"]] == [(1, "rejected"), (2, "accepted")]
    final = med["rounds"][-1]["final"]
    summary = json.loads((ROOT / final["evidence"]).read_text(encoding="utf-8"))
    chosen = med["rounds"][-1]["chosen"]
    assert chosen == record["evaluated_as"]
    for name, suite in summary["suites"].items():
        assert final["suites"][name]["delta_points"] == suite["vs_base"][chosen]["delta_points"]
        assert final["suites"][name]["base"]["accuracy"] == suite["accuracy"]["base"]["accuracy"]
    assert final["tasks"]["medmcqa-val"]["base"]["unparsed"] == 409       # the extractor gap stays visible
    assert final["protocol"]["model"] == "Qwen3.5-4B-Q4_K_M.gguf"          # a file name, not a path on a person's disk
    assert data["specialists"]["finance"]["status"] == "base_profile"
    assert "core" not in data["specialists"]


def fake_eval(folder: Path, variant: str, rows: list[dict], tasks: dict) -> None:
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps({"meta": {"model": "/Users/x/m.gguf", "suites": "fin"},
                                                     "tasks": tasks, "suites": {}}))
    (folder / "questions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_archived_unfinished_and_pairwise_rounds_and_topics(tmp_path, monkeypatch):
    monkeypatch.setattr(results_index, "ROOT", tmp_path)
    monkeypatch.setattr(results_index, "specialists", lambda: ["finance", "marketing"])
    monkeypatch.setattr(results_index, "benchmarks", lambda: {})
    fin = tmp_path / "training/runs/finance"
    # round 1, archived: its summary still names training/runs/finance/sweep/final
    (fin / "round1/sweep").mkdir(parents=True)
    (fin / "round1/run.json").write_text(json.dumps({"run_started_utc": "2026-11-01T00:00:00Z"}))
    (fin / "round1/sweep/summary.json").write_text(json.dumps({
        "specialist": "finance", "candidates": [{"stem": "a", "passes": True, "reasons": []}], "chosen": "a",
        "final": {"results": "training/runs/finance/sweep/final", "accepted": False, "reasons": ["general: -3"]}}))
    tasks = {"tatqa": {"accuracy": {"base": {"n": 3, "correct": 1, "accuracy": 0.333},
                                    "a": {"n": 3, "correct": 2, "accuracy": 0.667}},
                       "vs_base": {"a": {"delta_points": 33.3, "p_value": 0.5}}}}
    rows = [{"task": "tatqa", "item": str(i), "variant": v, "topic": t, "correct": c}
            for i, (t, b, a) in enumerate([("table", 1, 1), ("table", 0, 1), ("text", 0, 0)])
            for v, c in (("base", b), ("a", a), ("other", 1))]
    fake_eval(fin / "round1/sweep/final", "a", rows, tasks)
    # round 2: two sweeps of one run, one chosen without its final yet
    (fin / "run.json").write_text(json.dumps({"run_started_utc": "2026-11-05T00:00:00Z"}))
    for name, chosen in (("sweep-default", None), ("sweep", "b")):
        (fin / name).mkdir()
        (fin / name / "summary.json").write_text(json.dumps({"specialist": "finance", "candidates": [],
                                                             "chosen": chosen, "final": None}))
    mk = tmp_path / "training/runs/marketing/sweep"
    (mk / "final").mkdir(parents=True)
    (mk / "summary.json").write_text(json.dumps({"specialist": "marketing", "candidates": [], "chosen": "m",
                                                 "final": {"results": "training/runs/marketing/sweep/final",
                                                           "accepted": True, "reasons": []}}))
    (mk / "final/summary.json").write_text(json.dumps({"n": 24, "wins": 18, "losses": 2, "ties": 4,
                                                       "win_rate": 0.83, "sign_test_p": 0.0002}))
    data = results_index.build()
    jsonschema.validate(data, SCHEMA)
    r1, r2a, r2b = data["specialists"]["finance"]["rounds"]
    assert (r1["round"], r1["sweep"], r1["verdict"], r1["reasons"]) == (1, "round1/sweep", "rejected", ["general: -3"])
    assert r1["final"]["evidence"] == "training/runs/finance/round1/sweep/final/summary.json"
    assert r1["final"]["topics"] == {"tatqa": {"table": {"n": 2, "base_correct": 1, "adapter_correct": 2},
                                               "text": {"n": 1, "base_correct": 0, "adapter_correct": 0}}}
    assert r1["final"]["tasks"]["tatqa"]["delta_points"] == 33.3 and r1["final"]["protocol"]["model"] == "m.gguf"
    assert {(r2a["round"], r2a["sweep"], r2a["verdict"]), (r2b["round"], r2b["sweep"], r2b["verdict"])} == {
        (2, "sweep", "chosen_not_final"), (2, "sweep-default", "rejected")}
    pair = data["specialists"]["marketing"]["rounds"][0]
    assert pair["verdict"] == "accepted" and pair["final"]["pairwise"]["win_rate"] == 0.83


def test_check_fails_when_the_index_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(results_index, "OUT", tmp_path / "specialists.json")
    assert results_index.main(["--check"]) == 1
    assert results_index.main([]) == 0 and results_index.main(["--check"]) == 0


def test_question_ids_match_the_eval_harness():
    import run_eval

    registry = yaml.safe_load((ROOT / "training/datasets.yaml").read_text(encoding="utf-8"))["sources"]
    task = {"name": "science-local", "source": "science-heldout"}
    asked = {it.id for it in run_eval.load_items(task, registry, seed=0, limit=None)}
    topics = export_questions.topics_by_item([task], registry)
    assert asked and asked <= set(topics)


def test_topics_come_from_the_datasets_own_labels():
    rows = {"med": ("medmcqa", [{"id": "q1", "question": "Q", "opa": "a", "opb": "b", "opc": "c", "opd": "d",
                                 "cop": 1, "choice_type": "single", "subject_name": "Anatomy"}]),
            "mp": ("mmlu_pro", [{"question_id": 7, "question": "Q", "options": ["x", "y"], "answer": "B",
                                 "category": "health", "src": "ori_mmlu-clinical_knowledge"},
                                {"question_id": 8, "question": "Q", "options": ["x", "y"], "answer": "A",
                                 "category": "business", "src": ""}])}
    topics = export_questions.topics_by_item([{"name": "med"}, {"name": "mp"}], {},
                                             load=lambda task, registry: rows[task["name"]])
    assert topics == {"med/q1": "Anatomy", "mp/7": "clinical_knowledge", "mp/8": "business"}


def test_export_writes_one_sorted_line_per_answer_without_the_text(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "summary.json").write_text(json.dumps({"meta": {"suites": "medicine"}}))
    preds = [{"suite": "medicine", "task": "medmcqa-val", "item": f"medmcqa-val/{i}", "variant": v, "gold": "A",
              "parsed": p, "correct": p == "A", "finish_reason": f, "response": "secret text", "elapsed_s": 1}
             for i, v, p, f in (("b", "base", None, "length"), ("a", "base", "A", "stop"), ("a", "x", "B", "stop"))]
    (run / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in preds))
    assert export_questions.main([str(run), "--no-topics"]) == 0
    lines = [json.loads(x) for x in (run / "questions.jsonl").read_text().splitlines()]
    assert [(r["variant"], r["item"]) for r in lines] == [("base", "a"), ("base", "b"), ("x", "a")]
    assert lines[1] == {"suite": "medicine", "task": "medmcqa-val", "item": "b", "variant": "base", "topic": "",
                        "gold": "A", "parsed": None, "correct": False, "truncated": True}
    assert json.loads((run / "questions.json").read_text())["topics"] is False
    with pytest.raises(SystemExit, match="not in the eval source"):
        export_questions.export(run, {"medmcqa-val/a": "Anatomy"})
