"""Candidate specialist recipes, row converters and held-out evaluation. No network, model or execution."""

import json
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "evals"))

import prepare  # noqa: E402
import run_eval  # noqa: E402
from spike_train import licenses  # noqa: E402
from spike_train.data import FORMATTERS  # noqa: E402
from spike_train.evaluation import make_item, score  # noqa: E402

ROWS = {
    "case_hold": {"example_id": 7, "context": "The court considered a contract.",
                  "endings": [f"Holding {i}" for i in range(5)], "label": 2},
    "openbookqa": {"id": "s1", "question_stem": "Which material conducts electricity?",
                   "choices": {"label": ["A", "B", "C", "D"], "text": ["copper", "wood", "glass", "air"]},
                   "answerKey": "A", "fact1": "Metals conduct electricity."},
    "gsm8k": {"question": "There are three pairs. How many items?", "answer": "3 * 2 = 6\n#### 6"},
    "mbpp": {"task_id": 9, "text": "Write a function to double a number.", "code": "def double(x):\n    return 2 * x",
             "test_list": ["assert double(2) == 4"], "test_setup_code": ""},
    "wikisql": {"question": "How many people are older than twenty?",
                "table": {"header": ["name", "age"], "types": ["text", "real"], "rows": [["Ada", 22]]},
                "sql": {"sel": 0, "agg": 3, "conds": {"column_index": [1], "operator_index": [1], "condition": ["20"]}}},
}
DOMAINS = {"law": ("casehold-train", "casehold-test", "case_hold"),
           "science": ("openbookqa-train", "openbookqa-test", "openbookqa"),
           "math": ("gsm8k-train", "gsm8k", "gsm8k"),
           "code": ("mbpp-train", "mbpp-test", "mbpp"),
           "data": ("wikisql-train", "wikisql-test", "wikisql")}


def read_yaml(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fmt", ROWS)
def test_inline_converter_and_eval_share_prompt_and_gold(fmt):
    row = ROWS[fmt]
    chat = FORMATTERS[fmt](row, "S")
    assert [m["role"] for m in chat["messages"]] == ["system", "user", "assistant"]
    item = make_item("inline", fmt, 0, row)
    assert item.prompt == chat["messages"][1]["content"]
    assert score(item, chat["messages"][2]["content"])[1]
    assert not score(item, "Answer: incorrect")[1]
    if fmt == "mbpp":
        assert "assert double" not in item.prompt  # hidden tests are not leaked or run
        assert "def double" not in item.prompt
    if fmt == "wikisql":
        assert 'COUNT("name")' in item.gold and '"age" > \'20\'' in item.gold
        assert "Ada" not in item.prompt  # schema-only setting


@pytest.mark.parametrize("fmt", ROWS)
def test_converters_reject_missing_targets_and_questions(fmt):
    assert FORMATTERS[fmt]({}, "S") is None
    assert make_item("bad", fmt, 0, {}) is None


@pytest.mark.parametrize("fmt,change", [
    ("case_hold", {"label": -1}), ("case_hold", {"label": 5}), ("case_hold", {"endings": ["", "one", "two", "three", "four"]}),
    ("openbookqa", {"answerKey": "E"}), ("openbookqa", {"choices": {"text": ["x"], "label": []}}),
    ("gsm8k", {"answer": "no final marker"}), ("gsm8k", {"answer": "work\n#### unknown"}),
    ("mbpp", {"code": ""}), ("wikisql", {"sql": {"sel": 99, "agg": 0, "conds": {}}}),
    ("wikisql", {"sql": {"sel": 0, "agg": 99, "conds": {}}}),
])
def test_malformed_rows_are_rejected(fmt, change):
    row = {**ROWS[fmt], **change}
    assert FORMATTERS[fmt](row, "S") is None
    assert make_item("bad", fmt, 0, row) is None


def test_code_and_sql_exact_scoring_preserves_operators_case_and_indentation():
    for fmt, wrong in (("mbpp", "def double(x):\n    return 2 + x"),
                       ("wikisql", 'SELECT COUNT("name") FROM data WHERE "age" < \'20\'')):
        item = make_item("t", fmt, 0, ROWS[fmt])
        assert score(item, f"```\n{item.gold}\n```")[1]
        assert not score(item, f"```\n{wrong}\n```")[1]
        if fmt == "wikisql":
            assert not score(item, item.gold.lower())[1]
    code = make_item("t", "mbpp", 0, ROWS["mbpp"])
    assert not score(code, code.gold.replace("    return", "return"))[1]


@pytest.mark.parametrize("domain", DOMAINS)
def test_candidate_metadata_recipe_and_disjoint_selection(domain, monkeypatch):
    train, heldout, fmt = DOMAINS[domain]
    reg = read_yaml("training/datasets.yaml")["sources"]
    cfg = read_yaml(f"training/configs/{domain}.yaml")
    suites = read_yaml("evals/suites.yaml")["suites"]
    assert cfg["domain_sources"] == [{"source": train}]
    assert cfg["replay"]["sources"][0]["source"] == "oasst2"
    assert cfg["acceptance"]["primary"]["suite"] == domain
    for name in (train, heldout):
        src = reg[name]
        assert src["license"] in licenses.TRAIN_ALLOWLIST
        assert src["provenance"] and src["role"] == ("train" if name == train else "eval")
    assert reg[train]["license_status"] == "unverified"
    assert reg[train]["split"] != reg[heldout]["split"]
    assert reg[train]["hub"] == reg[heldout]["hub"]
    assert reg[train]["format"] == reg[heldout]["format"] == fmt
    eval_sources = {t["source"] for s in (domain, f"{domain}-select", "general", "general-select")
                    for t in suites[s]["tasks"]}
    assert eval_sources <= set(cfg["decontaminate_against"])
    # Exercise actual seeded sampling with enough inline rows for every acceptance/selection budget.
    monkeypatch.setattr(licenses, "source_license", lambda src: src["license"])
    for task in suites[f"{domain}-select"]["tasks"]:
        twin, = [t for t in suites[domain]["tasks"] if (t["source"], t.get("categories")) ==
                 (task["source"], task.get("categories"))]
        assert twin["n"] == task["skip"] and task["n"] > 0
        row = ROWS[fmt] if task["source"] == heldout else {
            "question": "Sample?", "options": ["one", "two"], "answer": "A", "category": task["categories"][0]}
        rows = [{**row, "id": i, "example_id": i, "question_id": i, "task_id": i}
                for i in range(task["skip"] + task["n"])]
        monkeypatch.setitem(sys.modules, "datasets", types.SimpleNamespace(load_dataset=lambda *a, inline=rows, **kw: inline))
        accept = run_eval.load_items(twin, reg, 0, None)
        select = run_eval.load_items(task, reg, 0, None)
        # Task prefixes differ; compare source identities, not prefixed IDs.
        assert not {i.id.split("/", 1)[1] for i in accept} & {i.id.split("/", 1)[1] for i in select}
        assert len(select) == task["n"]


def test_unverified_sources_stop_before_network_even_with_offline_override(monkeypatch):
    src = read_yaml("training/datasets.yaml")["sources"]["casehold-train"]
    monkeypatch.setattr(licenses, "hub_license", lambda *a: pytest.fail("network must not be attempted"))
    for offline in (True, False):
        with pytest.raises(SystemExit, match="unverified"):
            prepare.gate_source("candidate", src, "train", offline)
    with pytest.raises(SystemExit, match="unverified"):
        licenses.source_license(src)


@pytest.mark.parametrize("domain", DOMAINS)
def test_prepare_decontaminates_candidate_recipe_with_inline_rows(domain, tmp_path, monkeypatch):
    train, heldout, fmt = DOMAINS[domain]
    reg = read_yaml("training/datasets.yaml")["sources"]
    # Only the fixture's license review is simulated; production entries stay unverified.
    monkeypatch.setattr(prepare, "gate_source", lambda name, src, role, offline: src["license"])
    cfg = read_yaml(f"training/configs/{domain}.yaml")
    cfg["replay"]["ratio"] = 0
    cfg["replay"]["sources"] = []
    leak = {**ROWS[fmt]}
    qkey = {"case_hold": "context", "openbookqa": "question_stem", "gsm8k": "question",
            "mbpp": "text", "wikisql": "question"}[fmt]
    leak[qkey] = "This held out question has more than thirteen unique words to detect leakage across the entire recipe"
    clean = {**ROWS[fmt], qkey: "An unrelated training question with a different topic"}
    if fmt == "case_hold":
        clean["endings"] = [f"Distinct conclusion {i}" for i in range(5)]

    def rows(src, *args, **kwargs):
        if src["role"] == "train":
            return iter([leak, clean])
        return iter([leak] if src["format"] == fmt else [])
    monkeypatch.setattr(prepare, "load_rows", rows)
    monkeypatch.setattr(prepare, "load_token_counter", lambda base: lambda chat: 100)
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(path), "--out", str(tmp_path)])
    assert prepare.main() == 0
    manifest = json.loads((tmp_path / domain / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dropped"]["contaminated"] == 1
    assert manifest["sources"][heldout]["indexed_prompts"] == 1
    assert manifest["sources"][train]["kept"] == 1
    assert manifest["sources"][train]["license_status"] == "unverified"
    assert reg[train]["license_status"] == "unverified"


@pytest.mark.parametrize("domain", DOMAINS)
def test_real_candidate_recipe_refuses_before_any_hub_or_dataset_access(domain, tmp_path, monkeypatch):
    monkeypatch.setattr(licenses, "hub_license", lambda *a: pytest.fail("no Hub access before candidate review"))
    monkeypatch.setattr(prepare, "load_rows", lambda *a, **kw: pytest.fail("no dataset access before review"))
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(ROOT / "training" / "configs" / f"{domain}.yaml"),
                                      "--out", str(tmp_path), "--skip-license-check"])
    with pytest.raises(SystemExit, match="unverified"):
        prepare.main()


@pytest.mark.parametrize("agg,expected", list(enumerate(["\"name\"", 'MAX("name")', 'MIN("name")',
                                                   'COUNT("name")', 'SUM("name")', 'AVG("name")'])))
def test_sql_aggregates_and_empty_conditions(agg, expected):
    row = {**ROWS["wikisql"], "sql": {"sel": 0, "agg": agg, "conds": {}}}
    item = make_item("sql", "wikisql", 0, row)
    assert item.gold == f"SELECT {expected} FROM data"


def test_sql_quotes_and_condition_order_are_preserved():
    row = {**ROWS["wikisql"], "table": {"header": ['a"b'], "types": ["text"]},
           "sql": {"sel": 0, "agg": 0, "conds": {"column_index": [0, 0], "operator_index": [0, 2],
                                                  "condition": ["O'Brien", "Z"]}}}
    item = make_item("sql", "wikisql", 0, row)
    assert item.gold == 'SELECT "a""b" FROM data WHERE "a""b" = \'O\'\'Brien\' AND "a""b" < \'Z\''
    row["sql"]["conds"]["operator_index"] = [0]
    assert FORMATTERS["wikisql"](row, "S") is None


def test_science_choices_do_not_leak_supporting_fact_and_math_keeps_human_reasoning():
    chat = FORMATTERS["openbookqa"](ROWS["openbookqa"], "S")
    assert "Metals conduct" not in chat["messages"][1]["content"]
    math = FORMATTERS["gsm8k"]({**ROWS["gsm8k"], "answer": "A thousand plus two.\n#### 1,002"}, "S")
    assert math["messages"][-1]["content"] == "A thousand plus two.\n\nAnswer: 1002"
    assert make_item("m", "gsm8k", 0, {**ROWS["gsm8k"], "answer": "A thousand plus two.\n#### 1,002"}).gold == "1002"
