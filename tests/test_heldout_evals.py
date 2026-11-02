"""The hand-written held-out files for Science and Data (evals/data), how they are scored and that they stay apart from
the training topics. No network and no model, except one dry run of the harness on the tiny random-weight GGUF."""

import json
import re
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "evals"))

import prepare  # noqa: E402
import run_eval  # noqa: E402
from spike_train import evalfiles, licenses, seeding, sqlsandbox  # noqa: E402
from spike_train.data import MCQ_INSTRUCTION, SQL_EXEC_INSTRUCTION, ContaminationIndex, sql_block  # noqa: E402
from spike_train.evaluation import Item, make_item, rescore, score  # noqa: E402

from spike.runtime.llamacpp_server import find_binary  # noqa: E402

SCIENCE, DATA = ROOT / "evals" / "data" / "science_eval.jsonl", ROOT / "evals" / "data" / "data_eval.jsonl"
REGISTRY = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
SUITES = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]


def write(tmp_path, records, name="eval.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


HEADER = {"kind": "header", "written_by": "a person", "purpose": "evaluation only"}


# ------------------------------------------------------------------ the files
@pytest.mark.parametrize("path", [SCIENCE, DATA])
def test_the_files_say_they_are_evaluation_only_and_were_not_written_by_a_teacher(path):
    head, _ = evalfiles.split_header(path)
    assert head["purpose"] == "evaluation only" and "not by a distillation teacher" in head["written_by"]
    assert head["file"] == path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("loader", [evalfiles.science_rows, evalfiles.data_rows])
def test_a_file_without_an_evaluation_only_header_is_refused(tmp_path, loader):
    for n, head in enumerate((None, {**HEADER, "purpose": "training"}, {"kind": "header", "purpose": "evaluation only"},
                              {**HEADER, "written_by": " "})):
        path = write(tmp_path, ([head] if head else []) + [{"kind": "item", "id": "x"}], name=f"eval{n}.jsonl")
        with pytest.raises(ValueError, match="must be a header"):
            loader(path)


def test_the_science_file_has_sixty_balanced_four_option_questions_in_three_subjects():
    rows = evalfiles.science_rows(SCIENCE)
    assert len(rows) == 60 and len({r["id"] for r in rows}) == 60 and len({r["question"] for r in rows}) == 60
    assert Counter(r["category"] for r in rows) == {"physics": 20, "chemistry": 20, "biology": 20}
    assert {r["level"] for r in rows} == {"secondary", "undergraduate"}
    assert all(c >= 12 for c in Counter(r["answer"] for r in rows).values()) and set(r["answer"] for r in rows) == set("ABCD")
    for r in rows:
        assert len({o.strip().lower() for o in r["options"]}) == 4 and r["prompt"].endswith(MCQ_INSTRUCTION)
        assert not any(re.search(r"(?i)(all|none) of the above", o) for o in r["options"])
    assert len({r["topic"] for r in rows}) == 60                       # one topic per question: no topic weighs more than 1/60


def test_the_data_file_has_five_small_databases_and_sixty_questions_whose_gold_queries_run():
    rows = evalfiles.data_rows(DATA)                                   # raises when a gold query fails or returns nothing
    databases = [r for r in evalfiles.read_records(DATA) if r.get("kind") == "database"]
    assert len(databases) == 5 >= 3 and len({d["id"] for d in databases}) == 5
    assert len(rows) == 60 and len({r["id"] for r in rows}) == 60 and len({r["question"] for r in rows}) == 60
    assert Counter(r["db"] for r in rows) == {d["id"]: 12 for d in databases}
    for d in databases:
        tables = len(re.findall(r"(?i)\bcreate\s+table\b", d["schema"]))
        assert 2 <= tables <= sqlsandbox.MAX_TABLES and len(d["schema"]) < 3000     # small seed databases
    for r in rows:
        result = sqlsandbox.run(r["schema"], r["gold_sql"])
        assert result.ok and 1 <= len(result.rows) <= 100, r["id"]
        assert re.match(r"(?i)\s*(select|with)\b", r["gold_sql"]) and r["prompt"].endswith(SQL_EXEC_INSTRUCTION)
        assert r["prompt"] == f"{sql_block(r['schema'], r['question'])}\n\n{SQL_EXEC_INSTRUCTION}"
    golds = [r["gold_sql"].lower() for r in rows]
    for feature, minimum in (("join", 15), ("group by", 15), ("order by", 10), ("having", 3), ("over (", 2)):
        assert sum(feature in g for g in golds) >= minimum, feature      # the questions are not all one shape


def test_a_data_file_with_a_broken_gold_query_is_refused(tmp_path):
    db = {"kind": "database", "id": "d", "domain": "toys", "schema": "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1);"}
    good = {"kind": "item", "id": "i1", "db": "d", "question": "Which values are stored in table t?",
            "gold_sql": "SELECT a FROM t"}
    assert len(evalfiles.data_rows(write(tmp_path, [HEADER, db, good]))) == 1
    for bad, message in (({**good, "gold_sql": "SELECT a FROM t WHERE a > 5"}, "returns no rows"),
                         ({**good, "gold_sql": "SELECT b FROM t"}, "fails"),
                         ({**good, "db": "other"}, "unknown database")):
        with pytest.raises(ValueError, match=message):
            evalfiles.data_rows(write(tmp_path, [HEADER, db, bad]))


def test_decontamination_reads_the_prompts_of_each_kind_of_eval_file():
    assert evalfiles.prompts(SCIENCE) == [r["prompt"] for r in evalfiles.science_rows(SCIENCE)]
    assert evalfiles.prompts(DATA) == [r["prompt"] for r in evalfiles.data_rows(DATA)]
    marketing = evalfiles.prompts(ROOT / "evals" / "data" / "marketing_eval.jsonl")
    assert len(marketing) >= 20 and all(isinstance(p, str) and len(p) > 40 for p in marketing)


# ------------------------------------------------------------------ apart from the training topics
STOP = {"the", "a", "an", "of", "and", "in", "on", "to", "for", "with", "by", "at", "as", "is", "its", "per"}


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower().replace("'s", ""))
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOP}


def too_close(a: str, b: str) -> bool:
    """The same subject by wording: one contains the other's content words, or at least half of the words are shared."""
    ta, tb = tokens(a), tokens(b)
    return bool(ta and tb) and (ta <= tb or tb <= ta or len(ta & tb) / len(ta | tb) >= 0.5)


def test_the_closeness_rule_catches_a_reworded_topic_and_lets_a_different_one_through():
    assert too_close("pH of a strong base", "acids, bases and pH") and too_close("Ohm's law", "Ohm's law and series circuits")
    assert too_close("Hooke's law", "springs and Hooke's law")
    assert not too_close("Gram staining", "cell structure and organelles") and not too_close("ferry timetable", "bakery")


def test_the_science_questions_are_on_topics_that_are_not_training_labels():
    labels = [label for _, label in seeding.load_topics(ROOT / "training" / "topics" / "science.yaml").items]
    rows = evalfiles.science_rows(SCIENCE)
    assert not [(r["topic"], label) for r in rows for label in labels if too_close(r["topic"], label)]
    text = " ".join(r["question"] + " " + " ".join(r["options"]) for r in rows).lower()
    assert not [label for label in labels if re.search(rf"\b{re.escape(label.lower())}\b", text)]    # no label is a question's words


def test_the_data_questions_are_about_databases_that_are_not_training_labels():
    labels = [label for _, label in seeding.load_topics(ROOT / "training" / "topics" / "data.yaml").items]
    databases = [r for r in evalfiles.read_records(DATA) if r.get("kind") == "database"]
    assert not [(d["domain"], label) for d in databases for label in labels if too_close(d["domain"], label)]
    text = " ".join(r["prompt"] for r in evalfiles.data_rows(DATA)).lower()
    assert not [label for label in labels if re.search(rf"\b{re.escape(label.lower())}\b", text)]


def seed_overlap(seed_file: Path, eval_files: list[Path]) -> list[str]:
    """Prompts of a (human-declared) seeds file that share a 13-gram or the whole text with a held-out prompt."""
    index = ContaminationIndex()
    for path in eval_files:
        for prompt in evalfiles.prompts(path):
            index.add(prompt)
    return [p for p in seeding.load_human_seeds(seed_file).prompts if index.contaminated(p)]


def test_seeds_that_overlap_a_held_out_prompt_are_found_and_the_repository_has_none(tmp_path):
    eval_files = [SCIENCE, DATA, ROOT / "evals" / "data" / "marketing_eval.jsonl"]
    question = evalfiles.science_rows(SCIENCE)[0]["prompt"]
    leaky = tmp_path / "leaky.jsonl"
    leaky.write_text(json.dumps({"declaration": {"authored_by": "human", "author": "x"}}) + "\n"
                     + json.dumps({"prompt": question}) + "\n" + json.dumps({"prompt": "A different prompt entirely"}) + "\n",
                     encoding="utf-8")
    assert seed_overlap(leaky, eval_files) == [question]
    seed_files = [*(ROOT / "training" / "seeds").glob("*.jsonl")]
    for path in sorted((ROOT / "training" / "configs").glob("*.yaml")):          # every seeds file a recipe names
        named = (yaml.safe_load(path.read_text(encoding="utf-8")).get("distill") or {}).get("seeds")
        seed_files += [ROOT / named] if named else []
    assert all(not seed_overlap(path, eval_files) for path in seed_files)


# ------------------------------------------------------------------ suites and the registry
def test_the_held_out_files_are_registered_as_evaluation_only_sources():
    for name, fmt, path in (("science-heldout", "science_local", SCIENCE), ("data-heldout", "sql_exec", DATA)):
        src = REGISTRY[name]
        assert src["file"] == path.relative_to(ROOT).as_posix() and src["format"] == fmt and src["role"] == "eval"
        assert fmt in evalfiles.FORMATS and "license_status" not in src
        assert licenses.check(licenses.source_license(src), "eval")[0]
        with pytest.raises(SystemExit, match="registry role is 'eval'"):
            prepare.gate_source(name, src, "train", offline=True)


def test_the_data_suites_take_forty_and_twenty_disjoint_questions_at_any_seed():
    assert SUITES["data"]["specialist"] == SUITES["data-select"]["specialist"] == "data"
    assert [t["source"] for t in SUITES["data"]["tasks"]] == [t["source"] for t in SUITES["data-select"]["tasks"]] == ["data-heldout"]
    for seed in (0, 1, 7):
        acceptance = run_eval.load_items(SUITES["data"]["tasks"][0], REGISTRY, seed, None)
        select = run_eval.load_items(SUITES["data-select"]["tasks"][0], REGISTRY, seed, None)
        assert len(acceptance) == 40 and len(select) == 20 and not {i.id for i in acceptance} & {i.id for i in select}
        assert {i.kind for i in acceptance + select} == {"sql"} and all(i.schema and i.gold for i in acceptance + select)


def test_science_local_reports_the_sixty_questions_beside_the_unchanged_mmlu_pro_acceptance_suites():
    items = run_eval.load_items(SUITES["science-local"]["tasks"][0], REGISTRY, 0, None)
    assert len(items) == 60 and {i.kind for i in items} == {"mcq"} and {i.n_options for i in items} == {4}
    assert SUITES["science-local"]["specialist"] == "science"
    for suite in ("science", "science-select"):                       # the acceptance and selection suites did not change
        assert {t["source"] for t in SUITES[suite]["tasks"]} == {"mmlu-pro"}
        assert [t["categories"] for t in SUITES[suite]["tasks"]] == [["physics"], ["chemistry"], ["biology"]]
    assert [t["n"] for t in SUITES["science"]["tasks"]] == [400, 400, 400]
    assert [(t["skip"], t["n"]) for t in SUITES["science-select"]["tasks"]] == [(400, 200)] * 3


@pytest.mark.parametrize("domain", ["science", "data"])
def test_each_recipe_is_accepted_on_a_suite_that_exists(domain):
    cfg = yaml.safe_load((ROOT / "training" / "configs" / f"{domain}.yaml").read_text(encoding="utf-8"))
    assert cfg["acceptance"]["primary"]["suite"] in SUITES and cfg["acceptance"]["regression"]["suite"] in SUITES
    assert SUITES[cfg["acceptance"]["primary"]["suite"]]["specialist"] == domain


# ------------------------------------------------------------------ scoring
SCHEMA = "CREATE TABLE t (n INTEGER, s TEXT); INSERT INTO t VALUES (3, 'c'), (1, 'a'), (2, 'b');"


def sql_item(gold, **kw):
    return Item("d/1", "d", "prompt", "sql", gold, schema=SCHEMA, ordered=sqlsandbox.has_order_by(gold), **kw)


def test_a_sql_answer_is_scored_by_running_it_and_comparing_the_rows_with_the_gold_queries():
    item = sql_item("SELECT s FROM t WHERE n >= 2")
    assert score(item, "```sql\nSELECT s FROM t WHERE n > 1;\n```\nThe rows with n of 2 and 3.") == ("SELECT s FROM t WHERE n > 1;", True)
    assert score(item, "```sql\nselect s from t where n in (3, 2) order by n desc\n```")[1] is True     # rows, not text
    assert score(item, "SELECT s FROM t WHERE n >= 2")[1] is True                                         # no fence
    for wrong in ("```sql\nSELECT s FROM t\n```", "```sql\nSELECT s FROM t WHERE n > 2\n```",
                  "```sql\nSELECT n FROM t WHERE n >= 2\n```", "```sql\nSELECT s FROM t WHERE n >= 2 UNION ALL SELECT 'c'\n```"):
        assert score(item, wrong)[1] is False
    assert score(item, "I would filter on n.") == ("I would filter on n.", False)       # prose is not a query
    assert score(item, "```python\nprint(1)\n```") == (None, False)
    assert score(item, "") == (None, False)


def test_row_order_counts_only_when_the_gold_query_sorts():
    assert score(sql_item("SELECT n FROM t ORDER BY n"), "```sql\nSELECT n FROM t ORDER BY n\n```")[1] is True
    assert score(sql_item("SELECT n FROM t ORDER BY n"), "```sql\nSELECT n FROM t ORDER BY n DESC\n```")[1] is False
    assert score(sql_item("SELECT n FROM t"), "```sql\nSELECT n FROM t ORDER BY n DESC\n```")[1] is True
    assert sql_item("SELECT n FROM t ORDER BY n").ordered and not sql_item("SELECT n FROM t").ordered


def test_an_answer_that_attaches_loads_extensions_or_never_ends_is_wrong_and_does_not_stop_the_run():
    item = sql_item("SELECT s FROM t WHERE n >= 2")
    for bad in ("ATTACH DATABASE 'x.db' AS x", "SELECT load_extension('x')", "DELETE FROM t", "DROP TABLE t",
                "SELECT 1; SELECT 2", "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT count(*) FROM n"):
        assert score(item, f"```sql\n{bad}\n```")[1] is False


def test_a_gold_query_that_cannot_run_never_marks_an_answer_right():
    broken = Item("d/2", "d", "prompt", "sql", "SELECT missing FROM t", schema=SCHEMA)
    assert score(broken, "```sql\nSELECT missing FROM t\n```")[1] is False


def test_every_gold_query_of_the_file_scores_itself_right_and_a_constant_wrong():
    rows = evalfiles.data_rows(DATA)
    items = [make_item("data-sql-exec", "sql_exec", i, r) for i, r in enumerate(rows)]
    assert len(items) == 60 and all(it.id.startswith("data-sql-exec/data-") for it in items)
    assert all(score(it, f"```sql\n{it.gold}\n```")[1] for it in items)
    assert not any(score(it, "```sql\nSELECT 1\n```")[1] for it in items)
    assert sum(it.ordered for it in items) >= 10


def test_science_local_questions_score_like_every_other_multiple_choice_task():
    rows = evalfiles.science_rows(SCIENCE)
    items = [make_item("science-local", "science_local", i, r) for i, r in enumerate(rows)]
    assert all(score(it, f"Reasoning.\nAnswer: {it.gold}") == (it.gold, True) for it in items)
    assert not any(score(it, "Answer: " + ("A" if it.gold != "A" else "B"))[1] for it in items)


def test_saved_sql_predictions_can_be_scored_again():
    item = sql_item("SELECT s FROM t WHERE n >= 2")
    saved = [{"item": "d/1", "response": "```sql\nSELECT s FROM t\n```", "parsed": None, "correct": True, "variant": "base"}]
    again = rescore(saved, {"d/1": item})
    assert again[0]["correct"] is False and again[0]["parsed"] == "SELECT s FROM t" and again[0]["variant"] == "base"


# ------------------------------------------------------------------ the harness
class ScriptedClient:
    """Stands in for the llama-server client: the adapter answers every question correctly, the base model never does."""
    answers: dict[str, str] = {}      # prompt -> the correct answer, as a model would write it

    def __init__(self, base_url, concurrency=1):
        self.http = self

    async def get(self, url):
        return types.SimpleNamespace(json=lambda: {"build_info": "scripted"})

    async def adapters(self):
        return {"spike-data": 0}

    def lora(self, adapter):
        return [{"id": 0, "scale": 1.0 if adapter else 0.0}]

    async def chat(self, system, prompt, lora, max_tokens, temperature=0.0, seed=0, thinking=False):
        content = ScriptedClient.answers[prompt] if lora[0]["scale"] else "I do not know."
        return {"content": content, "finish_reason": "stop", "completion_tokens": 5, "elapsed_s": 0.0}

    async def aclose(self):
        pass


def synthetic(suite, variant, correct):
    return [{"suite": suite, "task": "t", "item": f"t/{i}", "variant": variant, "correct": c, "parsed": "x",
             "finish_reason": "stop"} for i, c in enumerate(correct)]


def test_the_harness_scores_the_data_and_science_local_suites_and_the_acceptance_rule_reads_them(tmp_path, monkeypatch):
    ScriptedClient.answers = ({r["prompt"]: f"Working it out.\n```sql\n{r['gold_sql']}\n```" for r in evalfiles.data_rows(DATA)}
                              | {r["prompt"]: f"Reasoning.\nAnswer: {r['answer']}" for r in evalfiles.science_rows(SCIENCE)})
    monkeypatch.setattr(run_eval, "Client", ScriptedClient)
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--suites", "data,data-select,science-local",
                                      "--server-url", "http://scripted", "--out", str(out)])
    assert run_eval.main() == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    for suite, n in (("data", 40), ("data-select", 20), ("science-local", 60)):
        entry = summary["suites"][suite]
        assert entry["accuracy"]["base"]["n"] == n and entry["accuracy"]["base"]["correct"] == 0
        assert entry["accuracy"]["spike-data"]["correct"] == n
        assert entry["vs_base"]["spike-data"]["delta_points"] == 100.0 and entry["vs_base"]["spike-data"]["p_value"] < 1e-4
    predictions = [json.loads(line) for line in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(predictions) == 2 * (40 + 20 + 60) and not {p["item"] for p in predictions if p["suite"] == "data"} & {
        p["item"] for p in predictions if p["suite"] == "data-select"}
    sql = next(p for p in predictions if p["suite"] == "data" and p["variant"] == "spike-data")
    assert sql["parsed"] == sql["gold"] and sql["response"].startswith("Working it out.")

    from spike_train.evaluation import check_acceptance, summarize

    acceptance = yaml.safe_load((ROOT / "training" / "configs" / "data.yaml").read_text(encoding="utf-8"))["acceptance"]
    same = [True] * 70 + [False] * 30
    general = synthetic("general", "base", same) + synthetic("general", "spike-data", same)
    assert check_acceptance(summarize(predictions + general), acceptance, "spike-data")[0]
    assert not check_acceptance(summarize(predictions), acceptance, "spike-data")[0]      # no general suite: not accepted


def test_forty_questions_need_six_net_gains_for_the_data_recipe_to_be_accepted():
    """McNemar's exact test on 40 paired questions: five gains and no loss is p = 0.0625, six is p = 0.03125 (docs)."""
    from spike_train.evaluation import check_acceptance, summarize

    acceptance = yaml.safe_load((ROOT / "training" / "configs" / "data.yaml").read_text(encoding="utf-8"))["acceptance"]
    held = [True] * 70 + [False] * 30
    verdicts = {}
    for gains in (5, 6):
        base, tuned = [False] * 40, [True] * gains + [False] * (40 - gains)
        run = (synthetic("data", "base", base) + synthetic("data", "spike-data", tuned)
               + synthetic("general", "base", held) + synthetic("general", "spike-data", held))
        verdicts[gains] = check_acceptance(summarize(run), acceptance, "spike-data")[0]
    assert verdicts == {5: False, 6: True}
    run = (synthetic("data", "base", [True] + [False] * 39) + synthetic("data", "spike-data", [False] + [True] * 6 + [False] * 33)
           + synthetic("general", "base", held) + synthetic("general", "spike-data", held))
    assert not check_acceptance(summarize(run), acceptance, "spike-data")[0]            # six gains with one loss: p = 0.0625


@pytest.mark.skipif(find_binary() is None, reason="llama-server not installed")
def test_the_harness_runs_a_held_out_file_on_the_tiny_random_weight_model(tmp_path, monkeypatch):
    """A real llama-server and the GGUF of the integration tests: it writes nonsense, the harness must still load the
    file source, ask, score and summarize. science-local is used because the data prompts (a schema each, about 2,300
    tokens for this model's byte-level vocabulary) are longer than its 2,048-token context; the SQL path above is scripted."""
    models = tmp_path / "models"
    subprocess.run([sys.executable, str(ROOT / "tests" / "fixtures" / "make_tiny_gguf.py"), str(models)], check=True,
                   capture_output=True)
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--suites", "science-local", "--model", str(models / "spike-tiny.gguf"),
                                      "--limit", "3", "--max-tokens", "6", "--parallel", "1", "--ctx-per-slot", "2048",
                                      "--ngl", "0", "--kv-cache-type", "f16", "--out", str(out)])
    assert run_eval.main() == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["suites"]["science-local"]["accuracy"]["base"]["n"] == 3
    predictions = [json.loads(line) for line in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(predictions) == 3 and all(p["suite"] == "science-local" and p["variant"] == "base" for p in predictions)
    assert all(p["gold"] in "ABCD" and p["correct"] == (p["parsed"] == p["gold"]) for p in predictions)


