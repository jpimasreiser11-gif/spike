"""Distillation seeded by topic labels, the lockdown of human-only seeds, and the checks on teacher-written
multiple-choice and SQL tasks. A fake teacher plays the open model: no network, no model, nothing trained."""

import argparse
import hashlib
import json
import random
import re
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

import distill  # noqa: E402
import prepare  # noqa: E402
from spike_train import evalfiles, licenses, seeding, sqlsandbox, synth  # noqa: E402
from spike_train.data import LETTERS, MCQ_INSTRUCTION, SQL_EXEC_INSTRUCTION, mcq_block, sql_block  # noqa: E402
from spike_train.seeding import SeedingError  # noqa: E402

from tests.test_training import TEACHER, prepare_env  # noqa: E402

DOMAINS = ("marketing", "science", "data")
SPEC = types.SimpleNamespace(id="science", domain="Science", system_prompt="SYSTEM PROMPT")


def read_yaml(rel: str):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ a fake open teacher
class FakeTeacher:
    """Plays the teacher. It writes tasks, multiple-choice drafts and SQL exercises from the instructions it is sent (an
    instruction is the only kind of request that starts with a user message), answers questions as asked, and grades.
    `mcq`/`sql` pick how the drafts are spoiled, `answers`/`sql_answers` how the answers are, `score` the rubric grade."""

    model = "fake-teacher"

    def __init__(self, *, mcq="good", answers="agree", sql="good", sql_answers="same", score=9, tasks=None):
        self.mcq, self.answers, self.sql, self.sql_answers, self.score = mcq, answers, sql, sql_answers, score
        self.tasks = tasks or self.fresh_tasks
        self.instructions: list[str] = []
        self.requests: list[list[dict]] = []          # everything that is not an instruction: answers
        self.reviews: list[tuple] = []
        self.task_calls = self.mcq_n = self.sql_n = 0
        self.mcq_key: dict[str, str] = {}             # question -> text of the correct option
        self.sql_key: dict[str, str] = {}             # question -> the drafted query
        self.views: dict[str, list[list[str]]] = defaultdict(list)    # question -> option lists as the teacher saw them
        self.asked: Counter = Counter()

    # -- the protocol of spike_train.distill.Teacher
    async def chat(self, messages, temperature=0.7, max_tokens=4096, thinking=True):
        text = messages[-1]["content"]
        if messages[0]["role"] == "user":
            self.instructions.append(text)
            if text.startswith(("You write realistic requests", "Here are example tasks")):   # labels, or human seeds
                self.task_calls += 1
                return self.tasks(self.task_calls, text), ""
            if text.startswith("You write exam questions"):
                return self.write_mcq(text), ""
            if text.startswith("You write exercises about SQLite"):
                return self.write_sql(), ""
            raise AssertionError(f"unexpected instruction: {text[:80]}")
        self.requests.append(messages)
        if synth.MCQ_ASK in text:
            return self.answer_mcq(text), "the teacher's reasoning"
        if synth.SQL_ASK in text:
            return self.answer_sql(text), ""
        return "A specific, concrete and complete answer.", ""

    async def review(self, task, response):
        self.reviews.append((task, response))
        return self.score(task, response) if callable(self.score) else self.score

    async def aclose(self):
        pass

    # -- tasks
    @staticmethod
    def fresh_tasks(call, text):
        return "\n".join(f"{i + 1}. Brief {call}-{i}: forecast the monthly cash position of a shop with {i + 3} employees"
                         for i in range(20))

    @property
    def topics_seen(self) -> list[str]:
        return [m.group(1) for t in self.instructions if (m := re.search(r"Topic: (.*)\.\n", t))]

    # -- multiple choice
    def write_mcq(self, text):
        self.mcq_n += 1
        n = 0 if self.mcq == "same_question" else self.mcq_n
        question = f"Trial {n} of a trolley experiment records its motion; which statement about trial {n} is correct?"
        right = f"The trolley's speed in trial {n} stays constant"
        wrong = [f"The trolley's speed in trial {n} doubles every second ({k})" for k in range(3)]
        if self.mcq == "echo":
            question = re.search(r"Topic: (.*)\.\n", text).group(1)
        elif self.mcq == "missing_wrong":
            wrong = wrong[:2]
        elif self.mcq == "all_of_the_above":
            wrong[0] = "All of the above"
        elif self.mcq == "duplicate_options":
            wrong[1] = right
        elif self.mcq == "short_question":
            question = "Which one?"
        self.mcq_key[question] = right
        tag = "q" if self.mcq == "no_question_tag" else "question"
        return (f"<{tag}>{question}</{tag}>\n<correct>{right}</correct>\n"
                + "".join(f"<wrong>{w}</wrong>\n" for w in wrong))

    def answer_mcq(self, text):
        question, _, rest = text.rsplit("\n\n" + synth.MCQ_ASK, 1)[0].partition("\n\n")
        options = [o for _, o in re.findall(r"^([A-D])\. (.*)$", rest, re.MULTILINE)]
        self.views[question].append(options)
        self.asked[question] += 1
        nth = self.asked[question]
        correct = LETTERS[options.index(self.mcq_key[question])]
        wrong = next(letter for letter in LETTERS[:4] if letter != correct)
        if self.answers == "no_final_line":
            return f"The best option is {correct}, for the reasons above."
        letter = {"first_wrong": wrong if nth == 1 else correct, "second_wrong": correct if nth == 1 else wrong,
                  "always_a": "A"}.get(self.answers, correct)
        return f"Working through each option in turn.\n\nAnswer: {letter}"

    # -- SQL
    def write_sql(self):
        self.sql_n += 1
        table = f"shipment{self.sql_n}"
        schema = (f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, port TEXT, tons INTEGER);\n"
                  f"INSERT INTO {table} VALUES (1, 'Callao', 40), (2, 'Valparaiso', 15), (3, 'Callao', 25);")
        question = f"Which ports moved more than 20 tons in total in table {table}?"
        query = f"SELECT port, SUM(tons) FROM {table} GROUP BY port HAVING SUM(tons) > 20"
        explanation = "<explanation>It groups the rows by port and keeps the ports above 20 tons.</explanation>"
        if self.sql == "schema_error":
            schema = schema.replace("40)", "40, 1)")
        elif self.sql == "query_error":
            query = query.replace("port,", "harbour,")
        elif self.sql == "empty":
            query = query.replace("> 20", "> 1000")
        elif self.sql == "attach":
            query = "ATTACH DATABASE 'stolen.db' AS stolen"
        elif self.sql == "extension":
            query = "SELECT load_extension('evil')"
        elif self.sql == "two_statements":
            query += "; DROP TABLE " + table
        elif self.sql == "ordered":
            query = f"SELECT port, tons FROM {table} ORDER BY tons DESC"
        elif self.sql == "no_create":
            schema = schema.split("\n")[1]
        elif self.sql == "no_explanation":
            explanation = ""
        self.sql_key[question] = query
        return f"<schema>\n{schema}\n</schema>\n<question>{question}</question>\n<sql>\n{query}\n</sql>\n{explanation}"

    def answer_sql(self, text):
        question = text.rsplit("\n\n" + synth.SQL_ASK, 1)[0].split("```\n\n", 1)[1]
        query = self.sql_key[question]
        return {"same": f"```sql\n{query.lower()}\n```",
                "different": f"```sql\n{query.replace('> 20', '> 10')}\n```",
                "reversed": f"```sql\n{query.replace('DESC', 'ASC')}\n```",
                "error": "```sql\nSELECT harbour FROM nowhere\n```",
                "attach": "```sql\nATTACH DATABASE 'stolen.db' AS stolen\n```",
                "no_code": "```python\nprint('no query')\n```",
                "prose": "Group by port and add up the tons."}[self.sql_answers]


def make(kinds, teacher, target=12, topics=None, seed=0, **kw):
    """synth.generate for the fake specialist; returns (rows, kept, dropped)."""
    import asyncio

    topics = topics or [("", f"zeppelin ballast trimming {i}") for i in range(4)]
    kw = {"min_score": 8, "samples": 2, "keep_reasoning": False} | kw
    return asyncio.run(synth.generate(teacher, SPEC, topics, kinds, target, seed, **kw))


# ------------------------------------------------------------------ topic files
def write_topics(tmp_path, doc, name="topics.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


TEACHER_CFG = {"repo": "Qwen/Qwen3.6-35B-A3B", "served_as": "mlx-community/Qwen3.6-35B-A3B-4bit"}
PROVENANCE = "Labels chosen by the maintainer as instructions to the open teacher, never copied into a row."


def test_a_topics_file_gives_labels_with_their_context_and_a_hash(tmp_path):
    doc = {"provenance": PROVENANCE, "groups": [{"context": "introductory physics", "labels": ["projectile motion", "Hooke's law"]},
                                                 {"labels": ["tipos de interés"]}]}
    path = write_topics(tmp_path, doc)
    topics = seeding.load_topics(path)
    assert topics.items == (("introductory physics", "projectile motion"), ("introductory physics", "Hooke's law"),
                            ("", "tipos de interés"))
    assert topics.provenance == PROVENANCE and topics.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("doc, message", [
    ({"groups": [{"labels": ["market segmentation"]}]}, "has no provenance"),
    ({"provenance": "short", "groups": [{"labels": ["market segmentation"]}]}, "has no provenance"),
    ({"provenance": PROVENANCE, "groups": []}, "has no labels"),
    ({"provenance": PROVENANCE, "groups": [{"context": "x"}]}, "needs `labels:`"),
    ({"provenance": PROVENANCE, "groups": [{"labels": ["Write a launch email for a bakery"]}]}, "reads as a task"),
    ({"provenance": PROVENANCE, "groups": [{"labels": ["How should I price a product"]}]}, "reads as a task"),
    ({"provenance": PROVENANCE, "groups": [{"labels": ["Qué es el margen bruto"]}]}, "reads as a task"),
    ({"provenance": PROVENANCE, "groups": [{"labels": ["What is churn?"]}]}, "reads as a task|sentence punctuation"),
    ({"provenance": PROVENANCE, "groups": [{"labels": ["a plan for a launch with a budget and a calendar of events"]}]},
     "not a short label"),
    ({"provenance": PROVENANCE, "groups": [{"labels": ["pricing. Then discounts"]}]}, "sentence punctuation"),
    ({"provenance": PROVENANCE, "groups": [{"labels": ["pricing", "Pricing "]}]}, "appears twice"),
    ({"provenance": PROVENANCE, "groups": [{"labels": [""]}]}, "empty"),
    ({"provenance": PROVENANCE, "groups": [{"labels": [42]}]}, "empty"),
    ({"provenance": PROVENANCE, "groups": [{"context": "Explain this to me", "labels": ["pricing"]}]}, "reads as a task"),
])
def test_a_topics_file_without_provenance_or_with_task_like_labels_is_refused(tmp_path, doc, message):
    with pytest.raises(SeedingError, match=message):
        seeding.load_topics(write_topics(tmp_path, doc))


def test_a_missing_or_unreadable_topics_file_is_refused(tmp_path):
    with pytest.raises(SeedingError, match="no such file"):
        seeding.load_topics(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("provenance: [unclosed", encoding="utf-8")
    with pytest.raises(SeedingError, match="not readable YAML"):
        seeding.load_topics(bad)


@pytest.mark.parametrize("domain, minimum", [("marketing", 60), ("science", 80), ("data", 50)])
def test_the_topic_files_of_the_recipes_are_short_labels_with_a_provenance(domain, minimum):
    topics = seeding.load_topics(ROOT / "training" / "topics" / f"{domain}.yaml")
    assert len(topics.items) >= minimum
    assert all(seeding.check_label(label) is None for _, label in topics.items)
    assert "AI assistant" in topics.provenance and "instructions" in topics.provenance      # who chose them, and what for
    assert max(len(label.split()) for _, label in topics.items) <= seeding.MAX_LABEL_WORDS


def test_science_labels_cover_physics_chemistry_and_biology_at_several_levels():
    contexts = {context for context, _ in seeding.load_topics(ROOT / "training/topics/science.yaml").items}
    for subject in ("physics", "chemistry", "biology"):
        assert {c for c in contexts if subject in c} >= {f"secondary school {subject}", f"undergraduate {subject}"}


# ------------------------------------------------------------------ seeds are for humans only
def write_seeds(tmp_path, head, prompts=("Plan a six week launch for a bakery with a small budget",), name="seeds.jsonl"):
    path = tmp_path / name
    lines = ([json.dumps(head)] if head is not None else []) + [json.dumps({"prompt": p}) for p in prompts]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


HUMAN = {"declaration": {"authored_by": "human", "author": "Ana Perez"}}


def test_a_seeds_file_is_read_only_when_it_declares_a_human_author(tmp_path):
    path = write_seeds(tmp_path, HUMAN, ["first prompt", "second prompt"])
    seeds = seeding.load_human_seeds(path)
    assert seeds.author == "Ana Perez" and seeds.prompts == ("first prompt", "second prompt")
    assert seeds.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("head", [
    None,                                                                               # the old marketing.jsonl layout
    {"declaration": {"authored_by": "ai", "author": "an assistant"}},
    {"declaration": {"authored_by": "human"}},
    {"declaration": {"authored_by": "human", "author": "  "}},
    {"declaration": "human"},
    {"author": "Ana Perez"},
])
def test_a_seeds_file_without_a_human_declaration_is_refused_with_the_way_out(tmp_path, head):
    with pytest.raises(SeedingError, match=r"refusing distill\.seeds .*declare a human author.*distill\.topics"):
        seeding.load_human_seeds(write_seeds(tmp_path, head))
    # the first prompt may not double as the declaration
    with pytest.raises(SeedingError, match="declare a human author"):
        seeding.load_human_seeds(write_seeds(tmp_path, {"prompt": "Plan a launch"}, name="two.jsonl"))


def test_the_recipe_names_exactly_one_source_of_tasks(tmp_path):
    topics = write_topics(tmp_path, {"provenance": PROVENANCE, "groups": [{"labels": ["pricing"]}]})
    seeds = write_seeds(tmp_path, HUMAN)
    for dcfg in ({}, {"enabled": True}, {"topics": str(topics), "seeds": str(seeds)}):
        with pytest.raises(SeedingError, match="exactly one of topics, seeds and tasks_from"):
            seeding.resolve(dcfg, ROOT)
    plan = seeding.resolve({"topics": str(topics)}, ROOT)
    assert plan.mode == "topics" and plan.record["mode"] == "topics" and plan.record["sha256"] == plan.topics.sha256
    assert "labels" not in json.dumps(plan.record) and "pricing" not in json.dumps(plan.record)
    plan = seeding.resolve({"seeds": str(seeds)}, ROOT)
    assert plan.record == {"mode": "seeds", "file": str(seeds), "sha256": plan.seeds.sha256, "author": "human"}
    assert seeding.resolve({"tasks_from": {"source": "medmcqa-train"}}, ROOT).record == {"mode": "gold",
                                                                                          "source": "medmcqa-train"}


def run_distill(tmp_path, monkeypatch, cfg_path, teacher, *flags, hub=None):
    """training/distill.py main() on a recipe, with the Hub and the teacher replaced; returns the rows it wrote."""
    fake_hub(monkeypatch, {"Qwen/Qwen3.6-35B-A3B": "Apache-2.0"} if hub is None else hub)
    monkeypatch.setattr(distill, "Teacher", lambda *a, **k: teacher)
    out = tmp_path / "out" / "distilled.jsonl"
    monkeypatch.setattr(sys, "argv", ["distill.py", str(cfg_path), "--out", str(out), *flags])
    assert distill.main() == 0
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


class Page:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return self

    def json(self):
        return self.data


def fake_hub(monkeypatch, models: dict[str, object]):
    """The Hub's /api/models/<repo> answers: a license string, a dict (the whole page) or None (a page with none)."""
    asked: list[str] = []

    def get(url, timeout=None, **kw):
        asked.append(url)
        repo = url.removeprefix("https://huggingface.co/api/models/")
        if repo not in models:
            raise httpx.ConnectError(f"no such repo in the fake hub: {url}")
        page = models[repo]
        return Page(page if isinstance(page, dict) else {"id": repo, "cardData": {"license": page} if page else {}})

    monkeypatch.setattr(httpx, "get", get)
    return asked


def recipe(tmp_path, dcfg, specialist="marketing"):
    cfg = read_yaml(f"training/configs/{specialist}.yaml")
    cfg["distill"] = dcfg
    path = tmp_path / f"{specialist}-recipe.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_distill_py_refuses_seeds_that_do_not_declare_a_human_author(tmp_path, monkeypatch):
    seeds = write_seeds(tmp_path, None)
    teacher = FakeTeacher()
    cfg = recipe(tmp_path, {"enabled": True, "seeds": str(seeds), "expand_to": 30, "min_score": 8})
    asked = fake_hub(monkeypatch, {"Qwen/Qwen3.6-35B-A3B": "Apache-2.0"})
    monkeypatch.setattr(distill, "Teacher", lambda *a, **k: teacher)
    monkeypatch.setattr(sys, "argv", ["distill.py", str(cfg), "--out", str(tmp_path / "out.jsonl")])
    with pytest.raises(SystemExit, match=r"refusing distill\.seeds .*declare a human author"):
        distill.main()
    assert not teacher.instructions and not asked and not (tmp_path / "out.jsonl").exists()    # refused at once


def test_distill_py_refuses_a_recipe_with_two_sources_of_tasks_or_none(tmp_path, monkeypatch):
    topics = write_topics(tmp_path, {"provenance": PROVENANCE, "groups": [{"labels": ["pricing"]}]})
    for dcfg in ({"enabled": True, "expand_to": 10}, {"topics": str(topics), "seeds": str(write_seeds(tmp_path, HUMAN))}):
        with pytest.raises(SystemExit, match="exactly one of topics, seeds and tasks_from"):
            run_distill(tmp_path, monkeypatch, recipe(tmp_path, dcfg), FakeTeacher())


def test_distill_py_still_expands_seeds_that_declare_a_human_author(tmp_path, monkeypatch):
    seeds = write_seeds(tmp_path, HUMAN, ["Plan a six week launch campaign for a local bakery with a small budget"])
    cfg = recipe(tmp_path, {"enabled": True, "teacher": TEACHER_CFG, "seeds": str(seeds), "expand_to": 25, "min_score": 8})
    rows = run_distill(tmp_path, monkeypatch, cfg, FakeTeacher())
    assert len(rows) == 25
    assert rows[0]["meta"]["seeding"] == {"mode": "seeds", "file": str(seeds), "author": "human",
                                          "sha256": hashlib.sha256(seeds.read_bytes()).hexdigest()}


def distilled(tmp_path, record, n=40):
    """A distill.py output for marketing with `record` as every row's seeding record (None: the key is absent)."""
    rows = [{"messages": [{"role": "system", "content": "marketing system prompt"},
                          {"role": "user", "content": f"Task {i}: plan the launch of product number {i} for a bakery "
                                                      f"chain with a budget of {i * 100 + 500} euros"},
                          {"role": "assistant", "content": f"A specific plan {i} with channels, budget, weekly KPIs."}],
             "meta": {"task_id": f"marketing-{i}", "verified": False, "source": "distill", "teacher": TEACHER,
                      "teacher_license": "apache-2.0", **({"seeding": record} if record is not None else {})}}
            for i in range(n)]
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "distilled.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def prepare_with(tmp_path, monkeypatch, dcfg, record, domain="marketing"):
    """prepare.py on a copy of a recipe whose distill block is `dcfg`, with distilled rows carrying `record`."""
    prepare_env(tmp_path, monkeypatch, ["--distilled", str(distilled(tmp_path / "rows", record))], config=domain)
    cfg = recipe(tmp_path, dcfg, domain)
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(cfg), "--out", str(tmp_path), "--distilled",
                                      str(tmp_path / "rows" / "distilled.jsonl")])
    return prepare.main()


def test_prepare_py_refuses_a_recipe_whose_seeds_do_not_declare_a_human_author(tmp_path, monkeypatch):
    seeds = write_seeds(tmp_path, None)
    with pytest.raises(SystemExit, match=r"refusing distill\.seeds .*declare a human author"):
        prepare_with(tmp_path, monkeypatch, {"enabled": True, "seeds": str(seeds), "expand_to": 30},
                     {"mode": "seeds", "file": str(seeds), "author": "human", "sha256": "0" * 64})
    assert not (tmp_path / "marketing" / "train.jsonl").exists()


def test_prepare_py_refuses_rows_whose_seeds_have_no_human_author_or_whose_tasks_have_no_record(tmp_path, monkeypatch):
    seeds = write_seeds(tmp_path, HUMAN)
    dcfg = {"enabled": True, "seeds": str(seeds), "expand_to": 30}
    with pytest.raises(SystemExit, match=r"refusing distilled\.jsonl:1: its tasks came from seeds that do not declare"):
        prepare_with(tmp_path / "a", monkeypatch, dcfg, {"mode": "seeds", "file": "x", "sha256": "0" * 64})
    with pytest.raises(SystemExit, match=r"refusing distilled\.jsonl:1: its tasks came from seeds that do not declare"):
        prepare_with(tmp_path / "b", monkeypatch, dcfg, {"mode": "seeds", "file": "x", "author": "ai"})
    with pytest.raises(SystemExit, match=r"distilled\.jsonl:1 has no seeding record"):
        prepare_with(tmp_path / "c", monkeypatch, dcfg, None)
    with pytest.raises(SystemExit, match=r"distilled\.jsonl:1 has no seeding record"):
        prepare_with(tmp_path / "d", monkeypatch, dcfg, {"mode": "invented"})


def test_prepare_py_records_the_task_source_in_the_manifest(tmp_path, monkeypatch):
    seeds = write_seeds(tmp_path, HUMAN, ["first prompt", "second prompt", "third prompt"])
    record = {"mode": "seeds", "file": str(seeds), "sha256": "ab" * 32, "author": "human"}
    assert prepare_with(tmp_path, monkeypatch, {"enabled": True, "seeds": str(seeds), "expand_to": 30}, record) == 0
    manifest = json.loads((tmp_path / "marketing" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["task_source"] == {"mode": "seeds", "file": str(seeds),
                                       "sha256": hashlib.sha256(seeds.read_bytes()).hexdigest(), "author": "Ana Perez",
                                       "prompts": 3}
    assert manifest["sources"]["distilled:distilled.jsonl"]["tasks_made_by"] == [record]


def test_no_ai_written_seed_file_is_left_in_the_repository():
    assert not (ROOT / "training" / "seeds" / "marketing.jsonl").exists()
    for path in (ROOT / "training" / "seeds").glob("*.jsonl"):       # whatever else is there must declare its author
        seeding.load_human_seeds(path)
    for path in sorted((ROOT / "training" / "configs").glob("*.yaml")):
        dcfg = yaml.safe_load(path.read_text(encoding="utf-8")).get("distill") or {}
        if dcfg:
            plan = seeding.resolve(dcfg, ROOT)           # every recipe that distills names one valid source of tasks
            assert plan.mode == "topics" or plan.mode == "tasks_from", f"{path.name}: {plan.mode}"


# ------------------------------------------------------------------ tasks written from labels
def test_allocate_splits_the_tasks_by_share_and_rejects_nonsense():
    assert synth.allocate({"mcq": 0.6, "explanation": 0.4}, 10) == {"mcq": 6, "explanation": 4}
    assert synth.allocate({"mcq": 1, "explanation": 1, "sql": 1}, 10) == {"mcq": 4, "explanation": 3, "sql": 3}
    assert sum(synth.allocate({"mcq": 0.7, "sql": 0.3}, 7).values()) == 7
    for bad in ({}, {"poem": 1}, {"mcq": 0}, {"mcq": -1}, {"mcq": "x"}):
        with pytest.raises(ValueError, match="distill.kinds"):
            synth.allocate(bad, 10)


async def test_the_teacher_writes_the_tasks_from_the_labels_and_is_told_what_it_wrote_already():
    teacher = FakeTeacher()
    topics = [("secondary school physics", "projectile motion"), ("", "tipos de interés")]
    tasks = await synth.topic_tasks(teacher, topics, "Science", synth.STYLES["explanation"], 100, seed=0)
    assert len(tasks) == len(set(tasks)) == 100 and teacher.task_calls == 5
    assert sorted(set(teacher.topics_seen)) == ["projectile motion (secondary school physics)", "tipos de interés"]
    later = [t for t in teacher.instructions if "already written" in t]
    assert later and all("- Brief " in t for t in later)           # the teacher's own earlier lines, not ours
    assert all("Science" in t and "Spanish" in t for t in teacher.instructions)


async def test_a_task_that_is_only_the_label_is_dropped():
    label = "customer lifetime value modelling"
    teacher = FakeTeacher(tasks=lambda call, text: label + "\n" + label.upper() + "\n" + FakeTeacher.fresh_tasks(call, text))
    tasks = await synth.topic_tasks(teacher, [("", label)], "Marketing", synth.STYLES["open"], 30, seed=0)
    assert len(tasks) == 30 and not any(synth._norm(t) == synth._norm(label) for t in tasks)


async def test_task_writing_stops_when_the_teacher_only_repeats_itself():
    teacher = FakeTeacher(tasks=lambda call, text: "Brief 0: forecast the monthly cash position of a shop")
    with pytest.raises(SystemExit, match=r"only 1 distinct tasks of the 50 asked for.*add topic labels"):
        await synth.topic_tasks(teacher, [("", "pricing")], "Marketing", synth.STYLES["open"], 50, seed=0)
    assert teacher.task_calls == synth.MAX_STALLS + 1
    with pytest.raises(SystemExit, match="distill.expand_to"):
        await synth.topic_tasks(FakeTeacher(tasks=lambda call, text: ""), [("", "pricing")], "Marketing",
                                synth.STYLES["open"], 50, seed=0)


def test_open_and_explanation_tasks_are_rubric_filtered_and_never_marked_verified():
    rows, kept, dropped = make({"open": 1}, FakeTeacher(), target=24)
    assert len(rows) == 24 and kept == {"open": 24} and not dropped
    for row in rows:
        assert row["meta"]["verified"] is False and row["meta"]["kind"] == "open" and row["meta"]["checks"] == "rubric"
        assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
        assert row["messages"][0]["content"] == "SYSTEM PROMPT" and row["messages"][1]["content"].startswith("Brief ")
    rows, kept, dropped = make({"open": 1}, FakeTeacher(score=7), target=24)
    assert not rows and dropped == {"open:rubric_or_empty": 24}
    rows, kept, _ = make({"mcq": 0.5, "explanation": 0.5}, FakeTeacher(), target=10)
    assert kept == {"mcq": 5, "explanation": 5}


# ------------------------------------------------------------------ multiple choice
def test_multiple_choice_rows_are_kept_only_for_a_keyed_option_two_answers_agree_on():
    teacher = FakeTeacher()
    rows, kept, dropped = make({"mcq": 1}, teacher, target=16)
    assert kept == {"mcq": 16} and not dropped
    for row in rows:
        system, user, assistant = (m["content"] for m in row["messages"])
        question, _, rest = user.partition("\n\n")
        options = re.findall(r"^([A-D])\. (.*)$", rest, re.MULTILINE)
        assert [letter for letter, _ in options] == ["A", "B", "C", "D"] and user == mcq_block(question, [o for _, o in options])
        key = LETTERS[[o for _, o in options].index(teacher.mcq_key[question])]
        assert assistant.endswith(f"Answer: {key}")
        assert MCQ_INSTRUCTION not in user and synth.MCQ_ASK not in user          # the format request is not training text
        assert row["meta"]["verified"] is False and row["meta"]["kind"] == "mcq"
        assert "two agreeing answers" in row["meta"]["checks"]
    assert len({a["messages"][2]["content"][-1] for a in rows}) >= 3                # the keyed letter is not a habit


def test_the_second_answer_sees_the_options_in_another_order():
    teacher = FakeTeacher()
    make({"mcq": 1}, teacher, target=10)
    assert len(teacher.views) == 10
    for first, second in teacher.views.values():
        assert sorted(first) == sorted(second) and first != second


@pytest.mark.parametrize("answers, reason", [("first_wrong", "first_answer_off_key"),
                                             ("second_wrong", "second_answer_off_key"),
                                             ("no_final_line", "first_answer_off_key")])
def test_a_multiple_choice_row_is_dropped_when_an_answer_misses_the_key(answers, reason):
    rows, kept, dropped = make({"mcq": 1}, FakeTeacher(answers=answers), target=8)
    assert not rows and dropped == {f"mcq:{reason}": 8}


def test_a_teacher_with_a_favourite_letter_loses_most_of_its_questions():
    rows, _, dropped = make({"mcq": 1}, FakeTeacher(answers="always_a"), target=40)
    assert len(rows) < 20 and sum(dropped.values()) == 40 - len(rows)               # the reordered second view sees to that


def test_a_multiple_choice_row_is_dropped_when_the_rubric_fails():
    rows, _, dropped = make({"mcq": 1}, FakeTeacher(score=7), target=6)
    assert not rows and dropped == {"mcq:rubric": 6}
    by_task = FakeTeacher(score=lambda task, response: 9 if task.id.endswith(("0", "2", "4")) else 3)
    rows, kept, dropped = make({"mcq": 1}, by_task, target=6)
    assert kept == {"mcq": 3} and dropped == {"mcq:rubric": 3}


@pytest.mark.parametrize("mcq", ["missing_wrong", "all_of_the_above", "duplicate_options", "short_question", "no_question_tag"])
def test_badly_formed_multiple_choice_drafts_are_dropped_before_any_answer_is_asked(mcq):
    teacher = FakeTeacher(mcq=mcq)
    rows, _, dropped = make({"mcq": 1}, teacher, target=6)
    assert not rows and dropped == {"mcq:bad_format": 6} and not teacher.requests


def test_a_repeated_question_counts_once():
    rows, kept, dropped = make({"mcq": 1}, FakeTeacher(mcq="same_question"), target=6)
    assert kept == {"mcq": 1} and dropped == {"mcq:duplicate": 5}


def test_a_question_that_is_only_the_label_is_dropped():
    labels = [("", "equilibrium of a rigid body")]
    rows, _, dropped = make({"mcq": 1}, FakeTeacher(mcq="echo"), target=4, topics=labels)
    assert not rows and dropped == {"mcq:label_echoed": 4}


def test_final_choice_reads_only_a_closing_answer_line():
    assert synth.final_choice("steps\n\nAnswer: B") == "B"
    assert synth.final_choice("steps\n\n**Answer: C**") == "C"
    assert synth.final_choice("steps\n\nAnswer: (D)") == "D"
    assert synth.final_choice("<think>Answer: A</think>\nsteps\nAnswer: B\n") == "B"
    for text in ("Answer: B\nbut on reflection it is a tie", "The answer is B", "Answer: E", "Answer: Because", "", "B"):
        assert synth.final_choice(text) is None


def test_parse_mcq_shuffles_the_options_and_names_the_correct_one():
    draft = "<question>Which gas makes up most of the air?</question><correct>Nitrogen</correct><wrong>Oxygen</wrong>" \
            "<wrong>Argon</wrong><wrong>Carbon dioxide</wrong>"
    keys = Counter()
    for seed in range(60):
        question, options, key = synth.parse_mcq(draft, random.Random(seed))
        assert question.startswith("Which gas") and options[LETTERS.index(key)] == "Nitrogen" and len(set(options)) == 4
        keys[key] += 1
    assert set(keys) == set("ABCD") and max(keys.values()) < 30


# ------------------------------------------------------------------ SQL
def test_sql_rows_are_kept_only_when_everything_runs_returns_rows_and_a_second_answer_agrees():
    rows, kept, dropped = make({"sql": 1}, FakeTeacher(), target=8)
    assert kept == {"sql": 8} and not dropped
    for row in rows:
        system, user, assistant = (m["content"] for m in row["messages"])
        schema = re.match(r"```sql\n(.*?)\n```\n\n(.*)$", user, re.DOTALL)
        assert user == sql_block(schema.group(1), schema.group(2))
        assert synth.SQL_ASK not in user and SQL_EXEC_INSTRUCTION not in user      # the format request is not training text
        query = sqlsandbox.extract_sql(assistant)
        assert assistant.startswith("```sql\n") and assistant.endswith("keeps the ports above 20 tons.")
        assert sqlsandbox.run(schema.group(1), query).rows == (("Callao", 65),)    # what was checked is what is trained on
        assert row["meta"]["verified"] is False and row["meta"]["kind"] == "sql"
        assert "executed" in row["meta"]["checks"] and "second answer" in row["meta"]["checks"]


@pytest.mark.parametrize("sql, reason", [
    ("schema_error", "schema_error"), ("query_error", "query_error"), ("empty", "empty_result"),
    ("attach", "not_a_select"), ("extension", "query_error"), ("two_statements", "query_error"),
    ("no_create", "bad_format"), ("no_explanation", "bad_format"),
])
def test_a_sql_draft_that_does_not_run_or_returns_nothing_is_dropped_before_the_second_answer(sql, reason):
    teacher = FakeTeacher(sql=sql)
    rows, _, dropped = make({"sql": 1}, teacher, target=4)
    assert not rows and dropped == {f"sql:{reason}": 4} and not teacher.requests


@pytest.mark.parametrize("sql_answers, reason", [
    ("different", "second_answer_differs"), ("error", "second_answer_error"), ("attach", "second_answer_error"),
    ("prose", "second_answer_error"), ("no_code", "second_answer_missing"),
])
def test_a_sql_row_is_dropped_when_the_second_answer_disagrees_or_fails(sql_answers, reason):
    rows, _, dropped = make({"sql": 1}, FakeTeacher(sql_answers=sql_answers), target=4)
    assert not rows and dropped == {f"sql:{reason}": 4}


def test_row_order_counts_only_when_a_query_sorts():
    same, _, _ = make({"sql": 1}, FakeTeacher(sql="ordered", sql_answers="same"), target=3)
    assert len(same) == 3
    rows, _, dropped = make({"sql": 1}, FakeTeacher(sql="ordered", sql_answers="reversed"), target=3)
    assert not rows and dropped == {"sql:second_answer_differs": 3}


def test_a_sql_row_is_dropped_when_the_rubric_fails_and_a_repeated_exercise_counts_once():
    rows, _, dropped = make({"sql": 1}, FakeTeacher(score=5), target=4)
    assert not rows and dropped == {"sql:rubric": 4}

    class Repeats(FakeTeacher):
        def write_sql(self):
            self.sql_n = 0
            return super().write_sql()

    rows, kept, dropped = make({"sql": 1}, Repeats(), target=4)
    assert kept == {"sql": 1} and dropped == {"sql:duplicate": 3}


# ------------------------------------------------------------------ labels are instructions, not training text
KINDS_ALL = {"open": 1, "explanation": 1, "mcq": 1, "sql": 1}


def test_labels_reach_the_teacher_as_instructions_and_never_a_row_or_an_answer_request():
    labels = ["zeppelin ballast trimming", "quokka husbandry", "obsidian knapping", "theremin tuning"]
    topics = [("", label) for label in labels]
    teacher = FakeTeacher()
    rows, kept, _ = make(KINDS_ALL, teacher, target=40, topics=topics)
    assert set(kept) == {"open", "explanation", "mcq", "sql"} and len(rows) == 40
    seen = " ".join(teacher.instructions).lower()
    assert all(label in seen for label in labels)                         # the labels did reach the teacher...
    everything = json.dumps(rows, ensure_ascii=False).lower()
    asked = json.dumps([teacher.requests, [(t.prompt, r) for t, r in teacher.reviews]], ensure_ascii=False).lower()
    for label in labels:                                                  # ...and nothing else, not even its words
        assert label not in everything and label not in asked
        assert not any(word in everything for word in label.split() if len(word) > 6)
    assert set(rows[0]["meta"]) == {"task_id", "verified", "source", "kind", "checks"}


# ------------------------------------------------------------------ the teacher gate
def args(model=None, repo=None):
    return argparse.Namespace(teacher_model=model, teacher_repo=repo)


@pytest.mark.parametrize("domain", DOMAINS)
def test_each_recipe_names_its_teacher_and_the_served_alias_is_never_licensed_under_it(domain):
    dcfg = read_yaml(f"training/configs/{domain}.yaml")["distill"]
    assert dcfg["teacher"] == TEACHER_CFG
    assert distill.resolve_teacher(args(), dcfg) == ("mlx-community/Qwen3.6-35B-A3B-4bit", "Qwen/Qwen3.6-35B-A3B")
    assert distill.resolve_teacher(args("another-model"), dcfg) == ("another-model", "another-model")
    assert distill.resolve_teacher(args("another-model", "org/another-model"), dcfg) == ("another-model", "org/another-model")
    assert distill.resolve_teacher(args(repo="org/other"), dcfg)[1] == "org/other"
    assert distill.resolve_teacher(args(), {}) == (distill.DEFAULT_TEACHER, distill.DEFAULT_TEACHER)
    with pytest.raises(SystemExit, match="distill.teacher must be"):
        distill.resolve_teacher(args(), {"teacher": {"served_as": "x"}})


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_teacher_license_gate_reads_the_hub_page_of_the_recipes_teacher(domain, monkeypatch):
    repo = read_yaml(f"training/configs/{domain}.yaml")["distill"]["teacher"]["repo"]
    asked = fake_hub(monkeypatch, {repo: "Apache-2.0"})
    assert licenses.teacher_license(repo) == "apache-2.0" and asked == [f"https://huggingface.co/api/models/{repo}"]
    fake_hub(monkeypatch, {repo: {"tags": ["text-generation", "license:mit"]}})            # the license only as a tag
    assert licenses.teacher_license(repo) == "mit"
    fake_hub(monkeypatch, {repo: {"cardData": {"license": ["apache-2.0", "other"]}}})
    assert licenses.teacher_license(repo) == "apache-2.0"


@pytest.mark.parametrize("page, message", [
    ("llama3.1", "license 'llama3.1' is not allowed for role 'train'"),
    ("other", "license 'other' is not allowed"),
    ("cc-by-nc-4.0", "license 'cc-by-nc-4.0' is not allowed"),
    ({"id": "x", "cardData": {}, "tags": ["text-generation"]}, "no license declared"),
    (None, "no license declared"),
])
@pytest.mark.parametrize("domain", DOMAINS)
def test_a_teacher_without_a_trainable_license_stops_every_recipe_before_a_task_is_sent(domain, page, message,
                                                                                         tmp_path, monkeypatch):
    teacher = FakeTeacher()
    with pytest.raises(SystemExit, match=f"refusing to distill: .*Qwen/Qwen3.6-35B-A3B.*{message}"):
        run_distill(tmp_path, monkeypatch, ROOT / "training" / "configs" / f"{domain}.yaml", teacher,
                    hub={"Qwen/Qwen3.6-35B-A3B": page})
    assert not teacher.instructions and not (tmp_path / "out").exists()


def test_an_unreachable_hub_or_an_unknown_teacher_repo_is_a_refusal_too(tmp_path, monkeypatch):
    cfg = ROOT / "training" / "configs" / "science.yaml"
    with pytest.raises(SystemExit, match="cannot read its license on the Hugging Face Hub"):
        run_distill(tmp_path, monkeypatch, cfg, FakeTeacher(), hub={})
    with pytest.raises(SystemExit, match="cannot read its license"):        # a different served model: its own repo is asked
        run_distill(tmp_path, monkeypatch, cfg, FakeTeacher(), "--teacher-model", "local-alias")
    rows = run_distill(tmp_path, monkeypatch, cfg, FakeTeacher(), "--teacher-model", "local-alias", "--limit", "6",
                       "--teacher-repo", "Qwen/Qwen3.6-35B-A3B")
    assert rows and rows[0]["meta"]["teacher"] == "Qwen/Qwen3.6-35B-A3B"


# ------------------------------------------------------------------ end to end: distill.py, then prepare.py
@pytest.mark.parametrize("domain, kinds", [("marketing", {"open"}), ("science", {"mcq", "explanation"}), ("data", {"sql"})])
def test_a_recipe_runs_from_topic_labels_to_the_training_files(domain, kinds, tmp_path, monkeypatch, capsys):
    cfg = ROOT / "training" / "configs" / f"{domain}.yaml"
    topics_file = ROOT / "training" / "topics" / f"{domain}.yaml"
    topics = seeding.load_topics(topics_file)
    teacher = FakeTeacher()
    rows = run_distill(tmp_path, monkeypatch, cfg, teacher, "--limit", "40")
    summary = json.loads(capsys.readouterr().out)

    assert len(rows) == 40 and set(summary["kept_by_kind"]) == kinds and summary["dropped"] == {}
    record = {"mode": "topics", "file": f"training/topics/{domain}.yaml", "sha256": topics.sha256}
    assert summary["seeding"] == record and summary["teacher_license"] == "apache-2.0"
    for row in rows:
        assert row["meta"]["seeding"] == record and row["meta"]["teacher"] == "Qwen/Qwen3.6-35B-A3B"
        assert row["meta"]["teacher_license"] == "apache-2.0" and row["meta"]["verified"] is False
    labels = [label for _, label in topics.items]
    assert set(teacher.topics_seen) <= {f"{label} ({context})" if context else label for context, label in topics.items}
    text = json.dumps(rows, ensure_ascii=False).lower()
    assert not any(label.lower() in text for label in labels)             # no label in any row, meta included

    # a hand-written held-out question that the teacher happened to write too must not reach the training files
    eval_file = read_yaml(f"training/configs/{domain}.yaml")["decontaminate_files"][0]
    leaked = evalfiles.prompts(ROOT / eval_file)[0]
    path = tmp_path / "out" / "distilled.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"messages": [{"role": "system", "content": rows[0]["messages"][0]["content"]},
                                         {"role": "user", "content": leaked},
                                         {"role": "assistant", "content": "A long enough and complete answer text."}],
                            "meta": rows[0]["meta"]}) + "\n")
    out = tmp_path / "prepared"
    prepare_env(out, monkeypatch, ["--distilled", str(path)], config=domain)
    assert prepare.main() == 0
    manifest = json.loads((out / domain / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dropped"]["contaminated"] >= 1
    assert manifest["task_source"] == record | {"provenance": topics.provenance, "labels": len(labels)}
    entry = manifest["sources"]["distilled:distilled.jsonl"]
    assert entry["tasks_made_by"] == [record] and entry["teachers"][TEACHER]["license_hub"] == "apache-2.0"
    assert manifest["sources"][f"file:{eval_file}"]["indexed_prompts"] == len(evalfiles.prompts(ROOT / eval_file))
    train = (out / domain / "train.jsonl").read_text(encoding="utf-8") + (out / domain / "valid.jsonl").read_text(encoding="utf-8")
    assert leaked not in train and not any(label.lower() in train.lower() for label in labels)
    assert "task_source" in manifest and json.dumps(labels[:3]) not in json.dumps(manifest)    # labels stay out of it too


def test_the_science_and_data_recipes_keep_the_regression_gate_and_have_no_human_domain_source():
    for domain, suite in (("science", "science"), ("data", "data")):
        cfg = read_yaml(f"training/configs/{domain}.yaml")
        assert cfg["domain_sources"] == [] and cfg["distill"]["enabled"] is True
        assert cfg["acceptance"] == {"primary": {"suite": suite, "min_gain_points": 3.0, "max_p_value": 0.05},
                                     "regression": {"suite": "general", "max_drop_points": 1.5}}
        assert "BLOCKED" not in (ROOT / "training" / "configs" / f"{domain}.yaml").read_text(encoding="utf-8")
        assert cfg["decontaminate_against"] == ["mmlu-pro"] and "seeds" not in cfg["distill"]
    assert read_yaml("training/configs/science.yaml")["decontaminate_files"] == ["evals/data/science_eval.jsonl"]
    assert read_yaml("training/configs/data.yaml")["decontaminate_files"] == ["evals/data/data_eval.jsonl"]
    assert read_yaml("training/configs/science.yaml")["distill"]["kinds"] == {"mcq": 0.6, "explanation": 0.4}
    assert read_yaml("training/configs/data.yaml")["distill"]["kinds"] == {"sql": 1}


def test_the_hub_gate_for_the_default_teacher_is_not_a_license_claim_of_this_repository():
    # nothing here states a license for a model: the recipes name the repo and the Hub page is read before every run
    for domain in DOMAINS:
        text = (ROOT / "training" / "configs" / f"{domain}.yaml").read_text(encoding="utf-8")
        assert "license read from the Hub first" in text and "Apache" not in text


# ------------------------------------------------------------------ checkpoint and resume (long teacher runs)
class CrashingTeacher(FakeTeacher):
    """Breaks (like a killed server) once it has answered `crash_after` requests that are not instructions."""

    def __init__(self, crash_after=None, **kw):
        super().__init__(**kw)
        self.crash_after = crash_after

    async def chat(self, messages, temperature=0.7, max_tokens=4096, thinking=True):
        if messages[0]["role"] != "user" and self.crash_after is not None and len(self.requests) >= self.crash_after:
            raise RuntimeError("teacher went away")
        return await super().chat(messages, temperature, max_tokens, thinking)


def test_an_open_run_resumes_from_its_checkpoint_without_asking_again(tmp_path, monkeypatch):
    monkeypatch.setattr(synth, "BATCH", 4)
    ckpt = tmp_path / "parts"
    first = CrashingTeacher(crash_after=6)
    with pytest.raises(RuntimeError):
        make({"open": 1}, first, target=12, checkpoint=ckpt)
    written = len(first.instructions)
    saved = [json.loads(line) for line in (ckpt / "open.jsonl").read_text(encoding="utf-8").splitlines()]
    assert saved and len(saved) % 4 == 0 and len(saved) < 12        # whole batches only

    second = CrashingTeacher()
    rows, kept, dropped = make({"open": 1}, second, target=12, checkpoint=ckpt)
    assert second.instructions == []                               # the tasks were not written again
    assert len(second.requests) < len(first.requests) + 12           # answered tasks were not asked again
    assert kept["open"] + sum(dropped.values()) == 12
    fresh, fresh_kept, _ = make({"open": 1}, FakeTeacher(), target=12)
    assert sorted(r["messages"][1]["content"] for r in rows) == sorted(r["messages"][1]["content"] for r in fresh)
    assert written > 0 and kept == fresh_kept


def test_a_checkpoint_from_another_run_is_refused(tmp_path):
    ckpt = tmp_path / "parts"
    make({"open": 1}, FakeTeacher(), target=8, checkpoint=ckpt)
    with pytest.raises(SystemExit, match="checkpoint"):
        make({"open": 1}, FakeTeacher(), target=8, seed=1, checkpoint=ckpt)
    with pytest.raises(SystemExit, match="checkpoint"):
        make({"open": 1}, FakeTeacher(), target=9, checkpoint=ckpt)


def test_without_a_checkpoint_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make({"open": 1}, FakeTeacher(), target=4)
    assert list(tmp_path.iterdir()) == []


def test_distill_py_resumes_a_topics_run_from_out_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(synth, "BATCH", 4)
    topics = write_topics(tmp_path, {"provenance": PROVENANCE, "groups": [{"labels": [f"pricing {i}" for i in range(4)]}]})
    cfg = recipe(tmp_path, {"enabled": True, "teacher": TEACHER_CFG, "topics": str(topics), "kinds": {"open": 1},
                            "expand_to": 12, "min_score": 8})
    with pytest.raises(RuntimeError):
        run_distill(tmp_path, monkeypatch, cfg, CrashingTeacher(crash_after=6))
    parts = tmp_path / "out" / "distilled.jsonl.parts"
    assert (parts / "open.prompts.json").exists() and not (tmp_path / "out" / "distilled.jsonl").exists()
    again = CrashingTeacher()
    rows = run_distill(tmp_path, monkeypatch, cfg, again)
    assert again.instructions == [] and len(rows) == 12
