"""Finance data: sources fetched from pinned URLs, the row filter, the FinQA and TAT-QA formatters, eval items and
their exact-answer scorers, and the finance recipe. No network, no model."""

import hashlib
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
from spike_train import licenses, sources  # noqa: E402
from spike_train.data import (  # noqa: E402
    FINQA_INSTRUCTION,
    FORMATTERS,
    TATQA_INSTRUCTION,
    finqa_steps_consistent,
    fmt_finqa,
    fmt_finqa_train,
    fmt_tatqa,
)
from spike_train.evaluation import Item, eval_args, make_item, score  # noqa: E402
from spike_train.metrics import (  # noqa: E402
    amount_matches,
    extract_final,
    normalize_span,
    parse_amount,
    span_set,
)

REV = "0f16e2867befa6840783e58be38c9efb9229d742"
BASE = f"https://raw.githubusercontent.com/czyssrs/FinQA/{REV}"


def registry() -> dict:
    return yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text())["sources"]


# ------------------------------------------------------------------ rows (shaped like the real files)
def finqa_row(question, answer, exe_ans, steps, facts, row_id="AAA/2008/page_5.pdf-1"):
    return {"id": row_id, "qa": {"question": question, "answer": answer, "exe_ans": exe_ans, "steps": steps,
                                 "gold_inds": facts}}


def step(op, arg1, arg2, res):
    return {"op": op, "arg1": arg1, "arg2": arg2, "res": res}


GROWTH = finqa_row(
    "what is the growth rate in net revenue in 2008?", "-3.2%", -0.03219,
    [step("minus1-1", "959.2", "991.1", "-31.9"), step("divide1-2", "#0", "991.1", "-3.2%")],
    {"table_6": "the 2008 net revenue of amount ( in millions ) is $ 959.2 ;",
     "table_1": "the 2007 net revenue of amount ( in millions ) is $ 991.1 ;"})
RATIO = finqa_row(  # the annotated answer is rounded: 28 % for 0.27743
    "what percentage of the total was purchased in november?", "28%", 0.27743, [step("divide1-1", "1947", "7018", "28%")],
    {"table_1": "the purchases in november were 1947 of the total 7018 ;"})
COMPARE = finqa_row(  # comparison programs: the result is yes / no, `answer` may be empty
    "did the awards in which the milestones were achieved exceed the compensation expense?", "", "yes",
    [step("multiply1-1", "607", "18.13", "11005"), step("multiply1-2", "#0", "const_1000", "11005000"),
     step("multiply1-3", "3.3", "const_1000000", "3300000"), step("compare_larger1-4", "#1", "#2", "yes")],
    {"table_2": "the granted of number of shares is 607 ; the weighted average fair value is 18.13 ;",
     "text_15": "the company recorded $ 3.3 million in stock-based compensation expense ."})
AVERAGE = finqa_row("what is the average beginning balance?", "93670", 93670.0,
                    [step("average1-1", "beginning balance", "none", "93670")],
                    {"table_1": "the beginning balance of 2016 is 90000 ; the beginning balance of 2017 is 97340 ;"})
BIG = finqa_row("what was the total operating expenses in 2018 in millions", "41932", 41932.20339,
                [step("divide2-1", "9896", "23.6%", "41932")], {"table_1": "aircraft fuel expense is $ 9896 ; 23.6% of operating expenses ;"})

TABLE = {"table": [["", "2019", "2018"], ["Software under development", "16,284", "6,509"]]}
PARAGRAPHS = [{"order": 2, "text": "Second paragraph."}, {"order": 1, "text": "First paragraph."}]


def tatqa_row(question, answer, answer_type, scale="", derivation="", uid="u1"):
    return {"table": TABLE, "paragraphs": PARAGRAPHS,
            "qa": {"uid": uid, "question": question, "answer": answer, "answer_type": answer_type, "scale": scale,
                   "derivation": derivation}}


CHANGE = tatqa_row("What was the percentage change between 2018 and 2019?", 150.18, "arithmetic", "percent",
                   "(16,284 - 6,509) / 6,509 ")
SPAN = tatqa_row("How was internally developed software capitalised?", ["at cost less accumulated amortisation."], "span")
NUMBER_SPAN = tatqa_row("How much was the closing net book amount in 2019?", ["16,284"], "span", "thousand")
MULTI = tatqa_row("What is net sales from cheese in 2018 and 2019 respectively?", ["11,486", "11,459"], "multi-span", "thousand")
COUNT = tatqa_row("In 2019, how many regions have revenues of more than $20,000 thousand?", "2", "count", "",
                  "Europe ## North America")


# ------------------------------------------------------------------ URL sources
def url_source(payload: bytes, **extra) -> dict:
    return {"urls": [{"url": f"{BASE}/dataset/test.json", "sha256": hashlib.sha256(payload).hexdigest()}],
            "revision": REV, "license": "mit", "license_url": f"{BASE}/LICENSE", "role": "eval", "format": "finqa", **extra}


def test_url_source_is_downloaded_once_then_read_from_the_cache_and_verified_on_every_load(tmp_path, monkeypatch):
    payload = json.dumps([GROWTH, RATIO]).encode()
    src = url_source(payload)
    calls = []
    monkeypatch.setattr(sources, "_get", lambda url: calls.append(url) or payload)
    assert [r["id"] for r in sources.url_rows(src, tmp_path)] == [GROWTH["id"], RATIO["id"]]
    assert list(sources.url_rows(src, tmp_path)) and calls == [src["urls"][0]["url"]]  # second load: cache only
    cached = next(tmp_path.iterdir())
    assert cached.name.startswith(src["urls"][0]["sha256"])
    cached.write_bytes(payload.replace(b"-3.2%", b"-9.9%"))  # a changed cache file is a hard error, not a re-download
    with pytest.raises(ValueError, match="sha256 mismatch.*delete it"):
        list(sources.url_rows(src, tmp_path))
    assert calls == [src["urls"][0]["url"]]


def test_url_source_refuses_bytes_that_do_not_match_the_pinned_sha256(tmp_path, monkeypatch):
    src = url_source(b"[]")
    monkeypatch.setattr(sources, "_get", lambda url: b'[{"tampered": true}]')
    with pytest.raises(ValueError, match="sha256 mismatch"):
        list(sources.url_rows(src, tmp_path))
    assert not list(tmp_path.iterdir())  # nothing unverified reaches the cache


@pytest.mark.parametrize("change", [
    {"license_url": ""}, {"license": ""}, {"revision": ""},
    {"urls": [{"url": f"http://raw.githubusercontent.com/o/r/{REV}/a.json", "sha256": "0" * 64}]},   # not https
    {"urls": [{"url": "https://raw.githubusercontent.com/o/r/main/a.json", "sha256": "0" * 64}]},      # not pinned
    {"urls": [{"url": f"{BASE}/a.json", "sha256": "ABC"}]},                                            # no sha256
])
def test_url_source_must_be_pinned_and_name_its_license(change):
    src = {**url_source(b"[]"), **change}
    with pytest.raises(ValueError):
        sources.validate(src)


def test_exploded_sources_give_one_row_per_question(tmp_path, monkeypatch):
    doc = {"table": TABLE, "paragraphs": PARAGRAPHS, "questions": [CHANGE["qa"], SPAN["qa"]]}
    payload = json.dumps([doc]).encode()
    monkeypatch.setattr(sources, "_get", lambda url: payload)
    rows = list(sources.url_rows(url_source(payload, explode="questions", format="tatqa"), tmp_path))
    assert [r["qa"]["question"] for r in rows] == [CHANGE["qa"]["question"], SPAN["qa"]["question"]]
    assert all(r["table"] == TABLE and "questions" not in r for r in rows)


def test_row_filter_keeps_listed_values_and_a_filter_matching_nothing_is_an_error():
    rows = [{"dataset": "zeroshot/twitter-financial-news-topic", "n": 1}, {"dataset": "gbharti/finance-alpaca", "n": 2},
            {"n": 3}, {"dataset": "yixuantt/FinEntity", "n": 4}]
    src = {"filter": {"dataset": ["zeroshot/twitter-financial-news-topic", "yixuantt/FinEntity"]}}
    assert [r["n"] for r in sources.filtered(src, rows)] == [1, 4]  # others and rows without the column are out
    assert [r["n"] for r in sources.filtered({}, rows)] == [1, 2, 3, 4]
    with pytest.raises(ValueError, match="matched no row"):
        list(sources.filtered({"filter": {"dataset": ["misspelled/name"]}}, rows))


def test_load_rows_counts_offset_and_limit_over_the_kept_rows(tmp_path, monkeypatch):
    payload = json.dumps([{"id": i, "kind": "keep" if i % 2 else "drop"} for i in range(10)]).encode()
    monkeypatch.setattr(sources, "_get", lambda url: payload)
    monkeypatch.setenv("HF_DATASETS_CACHE", str(tmp_path))
    src = url_source(payload, filter={"kind": ["keep"]})
    assert [r["id"] for r in prepare.load_rows(src)] == [1, 3, 5, 7, 9]
    assert [r["id"] for r in prepare.load_rows(src, offset=1, limit=2)] == [3, 5]


def test_license_gate_checks_the_recorded_license_of_url_sources_and_asks_the_hub_for_the_rest(monkeypatch):
    monkeypatch.setattr(licenses, "hub_license", lambda repo: "apache-2.0")
    assert licenses.source_license(url_source(b"[]")) == "mit"
    assert licenses.check(licenses.source_license(url_source(b"[]")), "train")[0]
    assert not licenses.check(licenses.source_license({**url_source(b"[]"), "license": "cc-by-nc-4.0"}), "train")[0]
    assert licenses.source_license({"hub": "x/y", "license": "mit"}) == "apache-2.0"  # a Hub source: as published


def test_prepare_refuses_a_url_source_whose_recorded_license_is_not_allowed(tmp_path, monkeypatch):
    reg = {"sources": registry()}
    reg["sources"]["finqa-train"]["license"] = "cc-by-nc-4.0"
    (tmp_path / "training").mkdir()
    (tmp_path / "training" / "datasets.yaml").write_text(yaml.safe_dump(reg))
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    monkeypatch.setattr(prepare.licenses, "hub_license", lambda repo: "mit")
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(ROOT / "training/configs/finance.yaml"), "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit, match="refusing source 'finqa-train': license 'cc-by-nc-4.0'"):
        prepare.main()


def test_registered_url_sources_are_pinned_to_the_verified_files():
    expected = {
        "finqa-train": "49f237eb9779b569473b26b08048867d04635a7cc39ad6a7a5664c55bb428db6",
        "finqa-test": "831dbfb2e785dbc227f895ce3f24046433467aec67b09db2bd6ac7692a8a30dc",
        "tatqa-train": "2df6e722cdbaaa37efcbfb280f5c9a15be29a6ec18f618ef936fe63cc6d07c69",
        "tatqa-test": "c4d08418359c1d76468dec420ee748a37f48c06b63cb8ec2766f19d5d314b597",
    }
    reg = registry()
    for name, sha in expected.items():
        src = reg[name]
        sources.validate(src)
        assert [u["sha256"] for u in src["urls"]] == [sha], name
        assert licenses.check(licenses.source_license(src), src["role"])[0], name
        assert src["format"] in FORMATTERS and src["license_url"].endswith("/LICENSE"), name
    assert {reg[n]["role"] for n in ("finqa-train", "tatqa-train")} == {"train"}
    assert {reg[n]["role"] for n in ("finqa-test", "tatqa-test")} == {"eval"}
    assert reg["tatqa-train"]["explode"] == reg["tatqa-test"]["explode"] == "questions"


# ------------------------------------------------------------------ formatters
def test_finqa_chat_shows_the_gold_facts_and_the_annotated_calculation():
    chat = fmt_finqa(GROWTH, "SYS")
    assert chat["messages"][0] == {"role": "system", "content": "SYS"}
    assert chat["messages"][1]["content"] == (
        "Facts:\nthe 2008 net revenue of amount ( in millions ) is $ 959.2 ;\n"  # as given, one per line
        "the 2007 net revenue of amount ( in millions ) is $ 991.1 ;\n\n"
        "Question: what is the growth rate in net revenue in 2008?\n\n" + FINQA_INSTRUCTION)
    assert chat["messages"][2]["content"] == "959.2 - 991.1 = -31.9\n-31.9 / 991.1 = -3.2%\nAnswer: -3.2%"


def test_finqa_programs_render_references_constants_comparisons_and_table_operations():
    assert fmt_finqa(COMPARE, "S")["messages"][2]["content"] == (
        "607 * 18.13 = 11005\n11005 * 1000 = 11005000\n3.3 * 1000000 = 3300000\n11005000 > 3300000 = yes\nAnswer: yes")
    assert fmt_finqa(AVERAGE, "S")["messages"][2]["content"] == "average(beginning balance) = 93670\nAnswer: 93670"
    minus_one = finqa_row("q?", "-5", -5.0, [step("divide1-1", "5", "const_m1", "-5")], {"text_1": "a fact"})
    assert fmt_finqa(minus_one, "S")["messages"][2]["content"] == "5 / -1 = -5\nAnswer: -5"


def test_finqa_answers_with_artifacts_or_missing_use_what_the_dataset_has_and_broken_rows_are_dropped():
    literal = finqa_row("q?", "431.7\\\\n", 431.7, [step("add1-1", "400", "31.7", "431.7")], {"text_1": "fact"})
    assert fmt_finqa(literal, "S")["messages"][2]["content"].endswith("Answer: 431.7")  # trailing literal "\\n" removed
    empty = finqa_row("q?", "", 3.0, [step("add1-1", "1", "2", "3")], {"text_1": "fact"})
    assert fmt_finqa(empty, "S")["messages"][2]["content"].endswith("Answer: 3")  # the last step's annotated result
    dangling = finqa_row("q?", "2", 2.0, [step("add1-1", "#3", "1", "2")], {"text_1": "fact"})
    assert fmt_finqa(dangling, "S") is None
    assert fmt_finqa(finqa_row("q?", "2", 2.0, [step("add1-1", "1", "1", "2")], {}), "S") is None  # no facts, no prompt


def test_finqa_steps_that_follow_from_their_arguments_are_consistent():
    for row in (GROWTH, COMPARE, AVERAGE, BIG):
        assert finqa_steps_consistent(row["qa"]["steps"]), row["qa"]["question"]
    for steps in (
        [step("divide1-1", "100", "100", "1%"), step("divide1-2", "3.8", "#0", "380")],   # 3.8 / 1 % = 380
        [step("divide1-1", "1947", "7018", "28%")],                                       # rounded to whole percent
        [step("divide1-1", "116", "1683", "6.9")],                                        # a percentage without the sign
        [step("multiply1-1", "607", "18.13", "11005")],                                   # within 0.5 %
        [step("minus1-1", "5829", "5735", "94"), step("divide1-2", "#0", "5735", "1.6%")],
        [step("minus1-1", "5", "7", "-2"), step("compare_larger1-2", "#0", "const_m1", "no")],
        [step("add1-1", "const_1", "2.0%", "1.02"), step("exp1-2", "#0", "const_6", "1.126")],
        [step("max1-1", "beginning balance", "", "506127")],                             # table operations: not recomputed
    ):
        assert finqa_steps_consistent(steps), steps


def test_finqa_steps_that_contradict_their_arguments_are_not():
    for steps in (
        [step("divide1-1", "2.5", "1.6", "0.9"), step("divide1-2", "#0", "1.6", "56.25%")],      # the step is a subtraction
        [step("minus1-1", "10", "12", "-2"), step("divide1-2", "#0", "12", "16.7%")],            # lost minus sign
        [step("add1-1", "130", "294", "44.2%")],
        [step("multiply1-1", "5000", "106.32", "-531600")],
        [step("compare_larger1-1", "5", "7", "yes")],
        [step("minus1-1", "10", "4", "6"), step("add1-2", "#0", "1", "8")],                       # uses the result above
    ):
        assert not finqa_steps_consistent(steps), steps


def test_the_training_format_drops_inconsistent_rows_and_the_eval_format_keeps_them():
    wrong = finqa_row("what is the ratio?", "56.25%", 0.97656,
                      [step("divide1-1", "2.5", "1.6", "0.9"), step("divide1-2", "#0", "1.6", "56.25%")], {"text_1": "a fact"})
    assert fmt_finqa_train(wrong, "S") is None
    assert fmt_finqa(wrong, "S") is not None and make_item("t", "finqa", 0, wrong) is not None  # eval and index unaffected
    assert fmt_finqa_train(GROWTH, "S") == fmt_finqa(GROWTH, "S")
    dangling = finqa_row("q?", "2", 2.0, [step("add1-1", "#3", "1", "2")], {"text_1": "fact"})
    assert fmt_finqa_train(dangling, "S") is None
    reg = registry()
    assert (reg["finqa-train"]["format"], reg["finqa-test"]["format"]) == ("finqa_train", "finqa")


def test_tatqa_prompt_has_the_table_as_pipe_rows_the_ordered_paragraphs_and_the_question():
    chat = fmt_tatqa(CHANGE, "SYS")
    assert chat["messages"][1]["content"] == (
        "Table:\n|  | 2019 | 2018 |\n| Software under development | 16,284 | 6,509 |\n\n"
        "Text:\nFirst paragraph.\nSecond paragraph.\n\n"
        "Question: What was the percentage change between 2018 and 2019?\n\n" + TATQA_INSTRUCTION)


@pytest.mark.parametrize(("row", "target"), [
    (CHANGE, "(16,284 - 6,509) / 6,509\nAnswer: 150.18 percent"),
    (SPAN, "Answer: at cost less accumulated amortisation."),
    (NUMBER_SPAN, "Answer: 16,284"),
    (MULTI, "Answer: 11,486; 11,459"),
    (COUNT, "Counted: Europe; North America\nAnswer: 2"),
    (tatqa_row("How much is the total?", 5.0, "arithmetic", "million", "2 + 3"), "2 + 3\nAnswer: 5 million"),
    (tatqa_row("What was the change?", -4400, "arithmetic", "thousand", "-4,400 - 0"), "-4,400 - 0\nAnswer: -4400 thousand"),
])
def test_tatqa_targets(row, target):
    assert fmt_tatqa(row, "S")["messages"][2]["content"] == target


# ------------------------------------------------------------------ answer extraction and matching
def test_final_answer_is_the_text_after_the_last_answer_marker():
    assert extract_final("3 + 4 = 7\nAnswer: 7") == "7"
    assert extract_final("**Answer:** $1,234 million") == "$1,234 million"
    assert extract_final("Answer:\n94") == "94"
    assert extract_final("Answer: 1\nchecking again\nanswer: 2") == "2"
    assert extract_final("<think>Answer: 9</think>\nAnswer: 7") == "7"
    assert extract_final("no marker, so the last line\nrevenue grew 12 %") == "revenue grew 12 %"
    assert extract_final("") is None and extract_final("Answer:") is None


@pytest.mark.parametrize(("text", "expected"), [
    ("27.74%", (27.74, True)), ("27.74 %", (27.74, True)), ("12.5 percent", (12.5, True)), ("12.5 per cent", (12.5, True)),
    ("-3.2%", (-3.2, True)), ("−3.2%", (-3.2, True)), ("(3.2)%", (-3.2, True)), ("(3.2%)", (-3.2, True)),
    ("$ (1,234) million", (-1234.0, False)), ("-$4,400 thousand", (-4400.0, False)), ("$-4,400", (-4400.0, False)),
    ("41,932.2", (41932.2, False)), ("1,234,567", (1234567.0, False)), ("1.5 billion", (1.5, False)), (".5", (0.5, False)),
    ("5829 - 5735 = 94", (94.0, False)), ("approximately 12 (about 3%)", (12.0, False)), ("(about 12)", (12.0, False)),
    ("yes", None), ("n/a", None), (None, None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_amounts_match_within_half_a_percent_or_as_the_fraction_of_a_percentage():
    assert amount_matches((100.4, False), 100.0) and not amount_matches((100.6, False), 100.0)
    assert amount_matches((-99.7, False), -100.0)
    assert amount_matches((27.74, True), 0.27743)  # 27.74 % for 0.27743
    assert not amount_matches((27.74, False), 0.27743)  # without the percent sign the fraction is not assumed
    assert not amount_matches((28.0, True), 0.27743)  # 0.9 % off
    assert amount_matches((0.0, False), 0.0) and not amount_matches((0.001, False), 0.0)
    assert not amount_matches(None, 1.0)


@pytest.mark.parametrize(("text", "other", "same"), [
    ("The Rate of Inflation.", "rate of inflation", True),
    ("At cost, less accumulated amortisation", "at cost less accumulated amortisation.", True),
    ("16,284 thousand", "$16,284", True), ("2.9%", "2.9", True), ("(4,400)", "-4,400", True),
    ("16.284", "16,284", False), ("4,400", "(4,400)", False), ("U.S. Dollars", "us dollars", True),
    ("Class B shares", "Class A shares", False),
])
def test_span_normalization(text, other, same):
    assert (normalize_span(text) == normalize_span(other)) is same


def test_multi_span_is_an_unordered_set():
    assert span_set("11,459; 11,486") == span_set("11,486;11,459 ;")
    assert span_set("x; y") != span_set("x") != span_set("x; y; z")
    assert span_set(" ; ") == set()


# ------------------------------------------------------------------ eval items
def test_finqa_items_carry_the_program_result_and_the_rounded_annotated_answer():
    item = make_item("finqa-test", "finqa", 0, RATIO)
    assert (item.kind, item.gold, item.alt, item.id) == ("amount", "0.27743", "0.28", "finqa-test/AAA/2008/page_5.pdf-1")
    assert item.prompt == fmt_finqa(RATIO, "S")["messages"][1]["content"]  # the training prompt, so eval = training format
    compare = make_item("finqa-test", "finqa", 1, COMPARE)
    assert (compare.kind, compare.gold, compare.alt) == ("yesno", "yes", "")
    assert make_item("t", "finqa", 0, finqa_row("q?", "", None, [], {"text_1": "fact"})) is None  # no gold, no item
    assert make_item("t", "finqa", 0, finqa_row("q?", "", "maybe", [], {"text_1": "fact"})) is None
    assert make_item("t", "finqa", 0, finqa_row("q?", "1", 1.0, [], {})) is None  # no facts


@pytest.mark.parametrize(("response", "correct", "parsed"), [
    ("1947 / 7018 = 0.27743\nAnswer: 27.74%", True, "27.74%"),
    ("Answer: 28%", True, "28%"),            # the rounded annotated answer, which is what training teaches
    ("Answer: 0.28", True, "0.28"),
    ("Answer: 0.2774", True, "0.2774"),
    ("Answer: 27%", False, "27%"),
    ("Answer: 28", False, "28"),            # 28, not 28 %: not read as a fraction
    ("The share is about 28 %", True, "28%"),  # no marker: the last line
    ("Answer: unknown", False, None),
])
def test_finqa_amount_scoring(response, correct, parsed):
    item = make_item("finqa-test", "finqa", 0, RATIO)
    assert score(item, response) == (parsed, correct)


def test_finqa_negative_and_comma_formats():
    growth = make_item("t", "finqa", 0, GROWTH)  # exe_ans -0.03219, annotated -3.2%
    assert growth.alt == "-0.032"
    for ok in ("Answer: -3.2%", "Answer: (3.2)%", "Answer: −3.22%", "Answer: -0.032", "Answer: -0.0322"):
        assert score(growth, ok)[1], ok
    for wrong in ("Answer: 3.2%", "Answer: 0.032", "Answer: -4%"):
        assert not score(growth, wrong)[1], wrong
    big = make_item("t", "finqa", 0, BIG)
    assert score(big, "Answer: $41,932 million")[1] and score(big, "Answer: 41,932.2")[1]
    assert not score(big, "Answer: 41,000")[1]


def test_finqa_yes_no_uses_the_existing_extractor():
    item = make_item("t", "finqa", 0, COMPARE)
    assert score(item, "11005000 > 3300000.\nAnswer: yes") == ("yes", True)
    assert score(item, "Answer: **No**") == ("no", False)


def test_tatqa_items_by_answer_type():
    kinds = {name: make_item("tatqa-test", "tatqa", 0, row) for name, row in
             {"change": CHANGE, "span": SPAN, "number_span": NUMBER_SPAN, "multi": MULTI, "count": COUNT}.items()}
    assert [(i.kind, i.gold) for i in kinds.values()] == [
        ("amount", "150.18"), ("span", "at cost less accumulated amortisation."), ("span", "16,284"),
        ("spans", "11,486; 11,459"), ("amount", "2.0")]
    assert kinds["change"].id == "tatqa-test/u1"
    assert make_item("t", "tatqa", 0, tatqa_row("When?", "31 January 2029", "arithmetic")) is None  # not a number
    assert make_item("t", "tatqa", 0, tatqa_row("What?", [], "span")) is None


def test_tatqa_number_scoring_ignores_scale_words_percent_and_dollar_signs():
    change = make_item("t", "tatqa", 0, CHANGE)
    for ok in ("(16,284 - 6,509) / 6,509 = 1.5018\nAnswer: 150.18%", "Answer: 150.18 percent", "Answer: 150.2",
               "Answer: 150.18"):
        assert score(change, ok)[1], ok
    for wrong in ("Answer: 1.5018", "Answer: 140%", "Answer: -150.18"):
        assert not score(change, wrong)[1], wrong
    count = make_item("t", "tatqa", 0, COUNT)
    assert score(count, "Counted: Europe; North America\nAnswer: 2")[1] and not score(count, "Answer: 3")[1]
    negative = make_item("t", "tatqa", 0, tatqa_row("Change?", -4400, "arithmetic", "thousand", "-4,400 - 0"))
    assert score(negative, "Answer: $(4,400) thousand")[1] and not score(negative, "Answer: 4,400")[1]


def test_tatqa_span_and_multi_span_scoring():
    span = make_item("t", "tatqa", 0, SPAN)
    assert score(span, "It says it is held at cost.\nAnswer: At cost, less accumulated amortisation") == (
        "at cost less accumulated amortisation", True)
    assert not score(span, "Answer: at fair value")[1]
    number = make_item("t", "tatqa", 0, NUMBER_SPAN)
    assert score(number, "Answer: $16,284 thousand")[1] and score(number, "Answer: 16,284")[1]
    assert not score(number, "Answer: 16.284")[1]
    multi = make_item("t", "tatqa", 0, MULTI)
    assert score(multi, "Answer: 11,486; 11,459")[1] and score(multi, "Answer: 11,459 ; 11,486")[1]  # any order
    assert not score(multi, "Answer: 11,486")[1] and not score(multi, "Answer: 11,486; 11,459; 11,000")[1]
    assert not score(multi, "Answer: 11,486 and 11,459")[1]  # items are separated by ';'
    assert score(multi, "") == (None, False)


def test_existing_scoring_is_unchanged_by_the_new_kinds():
    assert score(Item("g", "gsm8k", "p", "numeric", "1002"), "Answer: 1,002") == ("1002", True)
    assert score(Item("m", "mmlu", "p", "mcq", "B", 4), "Answer: B") == ("B", True)
    assert Item("x", "t", "p", "amount", "1.0").alt == ""


# ------------------------------------------------------------------ the recipe
def test_finance_recipe_trains_on_audited_sources_and_is_scored_on_the_held_out_tests():
    reg = registry()
    cfg = yaml.safe_load((ROOT / "training" / "configs" / "finance.yaml").read_text())
    suites = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text())["suites"]
    assert [(e["source"], e.get("max")) for e in cfg["domain_sources"]] == [
        ("sujet-finance", 8000), ("finqa-train", None), ("tatqa-train", None)]
    assert cfg["replay"]["ratio"] == 0.3 and [e["source"] for e in cfg["replay"]["sources"]] == ["oasst2"]
    assert set(cfg["decontaminate_against"]) == {"mmlu-pro", "finqa-test", "tatqa-test"}
    assert cfg["train"]["max_seq_length"] == 768 and eval_args(cfg) == ["--max-tokens", "2048"]
    keep = {"ugursa/Yahoo-Finance-News-Sentences", "zeroshot/twitter-financial-news-topic",
            "zeroshot/twitter-financial-news-sentiment", "yixuantt/FinEntity"}
    assert reg["sujet-finance"]["role"] == "train" and set(reg["sujet-finance"]["filter"]["dataset"]) == keep
    for excluded in ("finance-alpaca", "ehc-contrived", "lmsys-finance", "phrasebank", "FPB", "FiQA", "Headline", "ConvFinQA",
                     "llama-2-finance", "FinTalk", "financial-classification", "finqabench", "FinRiskAnalysis"):
        assert excluded in reg["sujet-finance"]["provenance"], excluded  # the audit is written down
    tasks = {t["name"]: t for t in suites["finance"]["tasks"]}
    assert list(tasks) == ["mmlu-pro-business", "mmlu-pro-economics", "finqa-test", "tatqa-test"]
    assert tasks["finqa-test"]["n"] == tasks["tatqa-test"]["n"] == 600
    assert all(reg[t["source"]]["role"] == "eval" for t in tasks.values())
    train_urls = {u["url"] for n in ("finqa-train", "tatqa-train") for u in reg[n]["urls"]}
    assert not train_urls & {u["url"] for n in ("finqa-test", "tatqa-test") for u in reg[n]["urls"]}  # disjoint files


def test_run_eval_loads_items_from_a_url_source_with_the_suite_sampling(tmp_path, monkeypatch):
    rows = [finqa_row(f"what is the ratio {i}?", "1.5", 1.5, [step("divide1-1", "3", "2", "1.5")],
                      {"text_1": f"fact {i}"}, row_id=f"R/{i}") for i in range(5)]
    payload = json.dumps(rows).encode()
    reg = {"finqa-test": url_source(payload)}
    monkeypatch.setattr(sources, "_get", lambda url: payload)
    monkeypatch.setenv("HF_DATASETS_CACHE", str(tmp_path))
    task = {"name": "finqa-test", "source": "finqa-test", "n": 3}
    items = run_eval.load_items(task, reg, 0, None)
    assert len(items) == 3 and [i.id for i in items] == sorted(i.id for i in items)
    assert [i.id for i in run_eval.load_items(task, reg, 0, None)] == [i.id for i in items]  # seeded
    with pytest.raises(SystemExit, match="not an eval source"):
        run_eval.load_items(task, {"finqa-test": {**reg["finqa-test"], "role": "train"}}, 0, None)
    with pytest.raises(SystemExit, match="not an eval source"):
        run_eval.load_items(task, {"finqa-test": {**reg["finqa-test"], "license": "proprietary"}}, 0, None)


def test_prepare_builds_the_finance_mix_from_filtered_hub_rows_and_pinned_files(tmp_path, monkeypatch):
    reg = registry()
    keep = reg["sujet-finance"]["filter"]["dataset"]
    sujet = [{"dataset": keep[i % 4], "user_prompt": f"Classify the sentiment of headline {i}: shares of company {i} rose",
              "answer": "positive"} for i in range(20)]
    sujet += [{"dataset": "gbharti/finance-alpaca", "user_prompt": f"EXCLUDED prompt {i} about budgeting", "answer": "a reply"}
              for i in range(5)]
    oasst = [{"message_id": f"{k}{i}", "parent_id": None if k == "q" else f"q{i}", "role": "prompter" if k == "q" else "assistant",
              "text": f"general {'question' if k == 'q' else 'answer'} {i}", "rank": None if k == "q" else 0, "lang": "en",
              "review_result": True, "deleted": False, "synthetic": False} for i in range(40) for k in "qa"]
    hub = {"sujet-ai/Sujet-Finance-Instruct-177k": sujet, "OpenAssistant/oasst2": oasst,
           "TIGER-Lab/MMLU-Pro": [{"question_id": 1, "question": "2+2?", "options": ["3", "4"], "answer": "B", "category": "math"}]}
    monkeypatch.setitem(sys.modules, "datasets", types.SimpleNamespace(
        load_dataset=lambda repo, config=None, split=None, streaming=False: iter(hub[repo])))
    leaked_finqa = finqa_row("what was the exact change in the number of shares repurchased during the fourth quarter?", "2.5",
                             2.5, [step("minus1-1", "10", "7.5", "2.5")],
                             {"text_1": "the company repurchased 10 million shares in the fourth quarter of the year and "
                                        "7.5 million shares in the third quarter of the same year ."})
    leaked_tatqa = tatqa_row("What was the exact amount of deferred revenue recognised in fiscal 2019 for the segment?", "7", "span")
    leaked_tatqa["paragraphs"] = [{"order": 1, "text": "Deferred revenue recognised in fiscal 2019 for the reportable segment "
                                                      "was entirely related to multi year support contracts signed earlier ."}]
    files = {
        "train.json": [leaked_finqa, *[finqa_row(f"what is the ratio of item {i} to item {i + 1}?", "1.5", 1.5,
                                                 [step("divide1-1", "3", "2", "1.5")],
                                                 {"text_1": f"item {i} was 3 and item {i + 1} was 2"}) for i in range(6)]],
        "test.json": [leaked_finqa],
        "tatqa_dataset_train.json": [leaked_tatqa, *[tatqa_row(f"How many items did segment {i} have?", "4", "count", "", "a ## b")
                                                     for i in range(4)]],
        "tatqa_dataset_test_gold.json": [leaked_tatqa],
    }
    monkeypatch.setattr(prepare, "url_rows", lambda src: iter(files[src["urls"][0]["url"].rsplit("/", 1)[-1]]))
    monkeypatch.setattr(prepare.licenses, "hub_license", lambda repo: {s["hub"]: s["license"] for s in reg.values() if "hub" in s}[repo])
    monkeypatch.setattr(prepare, "load_token_counter", lambda base_model: lambda chat: 100)
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(ROOT / "training/configs/finance.yaml"), "--out", str(tmp_path)])
    assert prepare.main() == 0
    manifest = json.loads((tmp_path / "finance" / "manifest.json").read_text())
    srcs = manifest["sources"]
    assert srcs["sujet-finance"]["kept"] == 20 and srcs["sujet-finance"]["filter"] == reg["sujet-finance"]["filter"]
    assert srcs["finqa-train"]["kept"] == 6 and srcs["tatqa-train"]["kept"] == 4  # the two leaked test questions are out
    assert manifest["dropped"]["contaminated"] == 2
    assert srcs["finqa-train"]["urls"] == reg["finqa-train"]["urls"] and srcs["finqa-train"]["revision"] == REV
    assert srcs["finqa-train"]["license_hub"] == "mit" and srcs["tatqa-test"]["role"] == "eval"
    assert "hub" not in srcs["finqa-train"] and srcs["sujet-finance"]["hub"] == "sujet-ai/Sujet-Finance-Instruct-177k"
    written = (tmp_path / "finance" / "train.jsonl").read_text() + (tmp_path / "finance" / "valid.jsonl").read_text()
    assert "EXCLUDED" not in written and "repurchased 10 million" not in written
    counts = manifest["counts"]
    assert counts["domain"] == 30 and counts["train"] + counts["valid"] - 30 == int(30 * 0.3 / 0.7)
