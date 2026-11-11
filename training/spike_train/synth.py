"""Tasks written by the open teacher from topic labels, and the checks that decide which become training rows.

The teacher is given a topic label (spike_train/seeding.py) and writes the task itself, then the answer. The label stays
in the instruction: it is never copied into a task, an answer, a row or its meta. Four kinds of task:

  open         a request and its answer; the rubric review is the only check (marketing)
  explanation  the same, for requests that ask for an explanation, a derivation or a worked calculation (science)
  mcq          a question with one correct and three wrong options. Kept only when two independent teacher answers, the
               second with the options in another order, both choose the keyed option, and the rubric passes
  sql          a SQLite schema with INSERT rows, a question and the query. Kept only when the schema and the query run in
               the sandbox (sqlsandbox.py), the result is not empty, a second teacher answer to the same schema and
               question returns the same result set, and the rubric passes

Every check is applied to teacher output only; the instructions below are never part of a row. The answer-format request
sent with a question is not part of the row either, so the only text in a row that was not written by the teacher is the
specialist's system prompt and the layout (lettered options, a fenced schema).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spike_train import sqlsandbox
from spike_train.data import LETTERS, _norm, mcq_block, sql_block
from spike_train.distill import Task, Teacher, distill_task, with_reasoning
from spike_train.metrics import strip_think

PER_CALL = 20      # tasks asked of the teacher per call
MAX_STALLS = 5     # consecutive calls that add nothing new before the teacher is judged to be out of ideas
BATCH = 32         # items in flight at a time
SPANISH_SHARE = 0.3
KINDS = ("open", "explanation", "mcq", "sql")

TOPIC_TASKS = (
    "You write realistic requests that people bring to a {domain} expert.\nTopic: {topic}.\n"
    "Write {n} different requests about this topic. {style} Each one is specific (numbers, context, constraints), "
    "self-contained and different from the others in difficulty and situation. Write about 30% of them in Spanish and the "
    "rest in English. One request per line, no numbering, no answers.{avoid}"
)
STYLES = {
    "open": "Each is something the expert is asked to produce or decide: a plan, a draft, an analysis, a diagnosis or a "
            "calculation.",
    "explanation": "Each asks for an explanation, a worked derivation, a worked calculation or a comparison; none is a "
                   "multiple-choice question.",
}
MCQ_WRITER = (
    "You write exam questions in {domain}.\nTopic: {topic}.\n"
    "Write one multiple-choice question about this topic, {angle}, in {language}. Exactly one option is correct; the three "
    "wrong options are plausible but clearly wrong to an expert, and none of them is 'all of the above' or 'none of the "
    "above'. The question must be answerable without a figure and must not name the topic as a label.\n"
    "Reply in exactly this format and nothing else:\n<question>the question</question>\n<correct>the correct option"
    "</correct>\n<wrong>a wrong option</wrong>\n<wrong>a wrong option</wrong>\n<wrong>a wrong option</wrong>"
)
ANGLES = ("a numerical calculation", "a conceptual misconception", "an application to a real situation",
          "the interpretation of an experiment or an observation", "a comparison of two cases",
          "a cause-and-effect reasoning problem")
SQL_WRITER = (
    "You write exercises about SQLite for people learning to query data.\nTopic: {topic}.\n"
    "Write one exercise on this topic that practises {facet}, with the question and the explanation in {language}.\n"
    "- schema: valid SQLite with CREATE TABLE statements (1 to 3 tables, English identifiers) and INSERT statements giving "
    "5 to 12 rows per table, realistic and varied; no other statements.\n"
    "- question: what a person would ask about this data in plain language; the answer must have at least one row.\n"
    "- sql: one SELECT (or WITH ... SELECT) statement that answers the question exactly, using only SQLite features.\n"
    "- explanation: two or three sentences saying how the query works.\n"
    "Reply in exactly this format and nothing else:\n<schema>\n...\n</schema>\n<question>...</question>\n<sql>\n...\n</sql>\n"
    "<explanation>...</explanation>"
)
FACETS = ("filtering and sorting the rows of one table", "joining two tables", "aggregating with GROUP BY and HAVING",
          "a subquery or a common table expression", "a window function or a ranking",
          "dates with strftime and CASE expressions", "finding rows with no match (LEFT JOIN or NOT EXISTS)",
          "combining results with UNION or EXCEPT", "counting and averaging per group")
# Sent with the question when the teacher answers, so its answer can be read; never part of the training row.
MCQ_ASK = "Think it through, explain briefly, and finish with a last line 'Answer: <letter>'."
SQL_ASK = "Reply with the SQLite query only, in a fenced code block."


class Rejected(Exception):
    """A drafted task that is not usable; `reason` is counted in the run summary."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


Topic = tuple[str, str]     # (context, label)


def topic_text(topic: Topic) -> str:
    context, label = topic
    return f"{label} ({context})" if context else label


def tagged(text: str, tag: str) -> list[str]:
    return [m.strip() for m in re.findall(rf"<{tag}>(.*?)</{tag}>", strip_think(text), re.DOTALL | re.IGNORECASE)]


def one(text: str, tag: str) -> str | None:
    found = tagged(text, tag)
    return found[0] if len(found) == 1 and found[0] else None


def allocate(shares: dict[str, float], total: int) -> dict[str, int]:
    """`total` split by `shares` (largest remainder), in the order given."""
    if not shares or any(k not in KINDS or not isinstance(v, (int, float)) or v <= 0 for k, v in shares.items()):
        raise ValueError(f"distill.kinds must map kinds ({', '.join(KINDS)}) to positive shares, got {shares!r}")
    whole = sum(shares.values())
    exact = {k: total * v / whole for k, v in shares.items()}
    counts = {k: int(x) for k, x in exact.items()}
    for k in sorted(exact, key=lambda k: exact[k] - counts[k], reverse=True)[: total - sum(counts.values())]:
        counts[k] += 1
    return counts


async def topic_tasks(teacher: Teacher, topics: list[Topic], domain: str, style: str, target: int,
                      seed: int) -> list[str]:
    """`target` distinct requests the teacher writes from the labels, one label per call in turn. Stops with an error
    when the teacher keeps returning duplicates (or nothing): MAX_STALLS calls in a row without a new request, or three
    times the calls a duplicate-free teacher needs."""
    rng = random.Random(seed)
    order: list[Topic] = []
    tasks: list[str] = []
    seen: set[str] = set()
    recent: dict[str, list[str]] = {}
    max_calls = 3 * math.ceil(target / PER_CALL) + MAX_STALLS
    calls = stalls = 0
    while len(tasks) < target:
        if stalls >= MAX_STALLS or calls >= max_calls:
            raise SystemExit(f"the teacher gave only {len(tasks)} distinct tasks of the {target} asked for "
                             f"(distill.expand_to) in {calls} calls; lower expand_to, add topic labels, or check the teacher")
        if not order:
            order = list(topics)
            rng.shuffle(order)
        topic = order.pop()
        calls += 1
        done = recent.get(topic[1], [])[-6:]
        avoid = ("\nRequests already written for this topic; do not repeat or paraphrase them:\n"
                 + "\n".join(f"- {t}" for t in done)) if done else ""
        prompt = TOPIC_TASKS.format(domain=domain, topic=topic_text(topic), n=PER_CALL, style=style, avoid=avoid)
        content, _ = await teacher.chat([{"role": "user", "content": prompt}], temperature=1.0, thinking=False)
        before = len(tasks)
        for line in content.splitlines():
            line = line.strip().lstrip("-•*0123456789. ").strip()
            key = line.lower()
            if len(line) > 25 and key not in seen and _norm(line) != _norm(topic[1]):  # a label is not a task
                seen.add(key)
                tasks.append(line)
                recent.setdefault(topic[1], []).append(line)
        stalls = 0 if len(tasks) > before else stalls + 1
    return tasks[:target]


# ------------------------------------------------------------------ multiple choice
def final_choice(text: str) -> str | None:
    """The letter of a closing 'Answer: X' line (markdown allowed), the form the teacher is asked for; nothing else is
    read as its choice, so a letter inside the explanation never counts."""
    lines = [ln for ln in strip_think(text).splitlines() if ln.strip()]
    m = re.match(r"[\s*_>#-]*(?i:answer)[\s*_:：]*\(?([ABCD])(?![A-Za-z])", lines[-1]) if lines else None
    return m.group(1) if m else None


def parse_mcq(text: str, rng: random.Random) -> tuple[str, list[str], str]:
    """(question, the four options in presentation order, the letter of the correct one) from the teacher's draft. The
    options are shuffled here, so the keyed letter is not the teacher's habit."""
    question, correct, wrong = one(text, "question"), one(text, "correct"), tagged(text, "wrong")
    options = [correct or "", *wrong]
    if not question or len(question) < 20 or len(wrong) != 3 or not all(options):
        raise Rejected("bad_format")
    if len({_norm(o) for o in options}) != 4 or any(len(o) > 300 for o in options):
        raise Rejected("bad_format")
    if any(re.search(r"(?i)\b(all|none) of the above\b|todas las anteriores|ninguna de las anteriores", o) for o in options):
        raise Rejected("bad_format")
    order = list(range(4))
    rng.shuffle(order)
    return question, [options[i] for i in order], LETTERS[order.index(0)]


async def make_mcq(teacher: Teacher, system: str, domain: str, task_id: str, topic: Topic, rng: random.Random,
                   seen: set[str], min_score: int, keep_reasoning: bool) -> tuple[dict | None, str]:
    """One multiple-choice row, or (None, why not)."""
    language = "Spanish" if rng.random() < SPANISH_SHARE else "English"
    prompt = MCQ_WRITER.format(domain=domain, topic=topic_text(topic), angle=rng.choice(ANGLES), language=language)
    draft, _ = await teacher.chat([{"role": "user", "content": prompt}], temperature=1.0, thinking=False)
    try:
        question, options, key = parse_mcq(draft, rng)
    except Rejected as exc:
        return None, exc.reason
    if _norm(question) == _norm(topic[1]):
        return None, "label_echoed"
    if _norm(question) in seen:
        return None, "duplicate"
    seen.add(_norm(question))
    correct_text = options[LETTERS.index(key)]
    again = list(range(4))
    while again == list(range(4)):          # the second answer sees the options in another order
        rng.shuffle(again)
    options2 = [options[i] for i in again]

    def ask(q: str, opts: list[str]) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}, {"role": "user", "content": f"{mcq_block(q, opts)}\n\n{MCQ_ASK}"}]

    (first, reasoning), (second, _) = await asyncio.gather(teacher.chat(ask(question, options)),
                                                           teacher.chat(ask(question, options2)))
    if final_choice(first) != key:
        return None, "first_answer_off_key"
    letter = final_choice(second)
    if letter is None or options2[LETTERS.index(letter)] != correct_text:
        return None, "second_answer_off_key"
    block = mcq_block(question, options)
    if await teacher.review(Task(task_id, block, system), first) < min_score:
        return None, "rubric"
    return _row(system, block, with_reasoning(first, reasoning, keep_reasoning), task_id, "mcq",
                "keyed by two agreeing answers + rubric"), "kept"


# ------------------------------------------------------------------ SQL
def parse_sql(text: str) -> tuple[str, str, str, str]:
    """(schema, question, query, explanation) from the teacher's draft."""
    schema, question, query, explanation = (one(text, t) for t in ("schema", "question", "sql", "explanation"))
    schema, query = (sqlsandbox.extract_sql(x) if x else None for x in (schema, query))
    if not (schema and question and query and explanation) or len(question) < 15 or not re.search(
            r"(?i)\bcreate\s+table\b", schema):
        raise Rejected("bad_format")
    if not re.match(r"(?i)\s*(select|with)\b", sqlsandbox.blank(query)):
        raise Rejected("not_a_select")
    return schema, question, query, explanation


async def make_sql(teacher: Teacher, system: str, task_id: str, topic: Topic, rng: random.Random, seen: set[str],
                   min_score: int) -> tuple[dict | None, str]:
    """One SQL row, or (None, why not)."""
    language = "Spanish" if rng.random() < SPANISH_SHARE else "English"
    prompt = SQL_WRITER.format(topic=topic_text(topic), facet=rng.choice(FACETS), language=language)
    draft, _ = await teacher.chat([{"role": "user", "content": prompt}], temperature=1.0, thinking=False)
    try:
        schema, question, query, explanation = parse_sql(draft)
    except Rejected as exc:
        return None, exc.reason
    key = hashlib.sha1(f"{_norm(question)}|{_norm(schema)}".encode()).hexdigest()
    if _norm(question) == _norm(topic[1]):
        return None, "label_echoed"
    if key in seen:
        return None, "duplicate"
    seen.add(key)
    first = sqlsandbox.run(schema, query)
    if not first.ok:
        return None, "schema_error" if first.stage == "schema" else "query_error"
    if not first.rows:
        return None, "empty_result"
    block = sql_block(schema, question)
    second_text, _ = await teacher.chat([{"role": "system", "content": system},
                                         {"role": "user", "content": f"{block}\n\n{SQL_ASK}"}])
    second_sql = sqlsandbox.extract_sql(second_text)
    if not second_sql:
        return None, "second_answer_missing"
    second = sqlsandbox.run(schema, second_sql)
    if not second.ok:
        return None, "second_answer_error"
    ordered = sqlsandbox.has_order_by(query) or sqlsandbox.has_order_by(second_sql)
    if not sqlsandbox.same_result(first.rows, second.rows, ordered):
        return None, "second_answer_differs"
    answer = f"```sql\n{query}\n```\n\n{explanation}"
    if await teacher.review(Task(task_id, block, system), answer) < min_score:
        return None, "rubric"
    return _row(system, block, answer, task_id, "sql",
                "executed, non-empty, second answer returns the same rows + rubric"), "kept"


def _row(system: str, prompt: str, answer: str, task_id: str, kind: str, checks: str) -> dict[str, Any]:
    """verified stays False: that flag means 'matches a human gold answer' (distill.py); these rows are checked by the
    teacher's own agreement and by execution, which `checks` says."""
    return {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt},
                         {"role": "assistant", "content": answer}],
            "meta": {"task_id": task_id, "verified": False, "source": "distill", "kind": kind, "checks": checks}}


# ------------------------------------------------------------------ the whole run
async def generate(teacher: Teacher, spec: Any, topics: list[Topic], kinds: dict[str, float], target: int, seed: int, *,
                   min_score: int, samples: int, keep_reasoning: bool,
                   progress: Callable[[str], None] = lambda message: None,
                   checkpoint: Path | None = None) -> tuple[list[dict], Counter, Counter]:
    """Rows for `target` tasks split over `kinds` (see allocate), the rows kept per kind and the tasks dropped per reason.
    `spec` is the specialist (id, domain, system_prompt).

    With `checkpoint` (a folder), the tasks the teacher writes for a style kind (open, explanation) are saved once, and
    every finished batch of answers is appended, so a run that stops resumes where it was: nothing saved is asked again.
    The folder is bound to this run's settings and topics; a folder from another run is refused. mcq and sql tasks are
    not checkpointed (their duplicate checks live in memory)."""
    rows: list[dict] = []
    kept: Counter = Counter()
    dropped: Counter = Counter()
    system = spec.system_prompt
    if checkpoint is not None:
        bind_checkpoint(checkpoint, {"specialist": spec.id, "kinds": kinds, "target": target, "seed": seed,
                                     "min_score": min_score, "samples": samples, "keep_reasoning": keep_reasoning,
                                     "topics": [list(t) for t in topics]})
    for kind, n in allocate(kinds, target).items():
        if n == 0:
            continue
        saved: dict[int, tuple[dict | None, str]] = {}
        log = None
        if kind in STYLES:
            if checkpoint is not None:
                prompts = await saved_tasks(checkpoint / f"{kind}.prompts.json", n, lambda kind=kind, n=n: topic_tasks(
                    teacher, topics, spec.domain, STYLES[kind], n, seed))
                log = checkpoint / f"{kind}.jsonl"
                saved = read_answers(log)
            else:
                prompts = await topic_tasks(teacher, topics, spec.domain, STYLES[kind], n, seed)

            async def job(i: int, kind: str = kind, prompts: list[str] = prompts) -> tuple[dict | None, str]:
                task = Task(id=f"{spec.id}-{kind}-{i}", prompt=prompts[i], system=system)
                row = await distill_task(teacher, task, samples=samples, min_score=min_score, keep_reasoning=keep_reasoning)
                if row:
                    row["meta"].update(kind=kind, checks="rubric")
                return row, "kept" if row else "rubric_or_empty"
        else:
            order = list(topics)
            random.Random(f"{seed}-{kind}").shuffle(order)
            seen: set[str] = set()

            async def job(i: int, kind: str = kind, order: list[Topic] = order, seen: set[str] = seen):
                rng, task_id, topic = random.Random(f"{seed}-{kind}-{i}"), f"{spec.id}-{kind}-{i}", order[i % len(order)]
                if kind == "mcq":
                    return await make_mcq(teacher, system, spec.domain, task_id, topic, rng, seen, min_score, keep_reasoning)
                return await make_sql(teacher, system, task_id, topic, rng, seen, min_score)

        results: dict[int, tuple[dict | None, str]] = dict(saved)
        if saved:
            progress(f"  {kind}: {len(saved)}/{n} restored from the checkpoint, "
                     f"{sum(1 for row, _ in saved.values() if row)} kept")
        todo = [i for i in range(n) if i not in saved]
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            answers = dict(zip(batch, await asyncio.gather(*(job(i) for i in batch)), strict=True))
            if log is not None:
                append_answers(log, answers)
            results.update(answers)
            progress(f"  {kind}: {len(results)}/{n} processed, {sum(1 for row, _ in results.values() if row)} kept")
        for i in range(n):          # task order, so a resumed run gives the same file as one that never stopped
            row, reason = results[i]
            if row:
                rows.append(row)
                kept[kind] += 1
            else:
                dropped[f"{kind}:{reason}"] += 1
    return rows, kept, dropped


def bind_checkpoint(folder: Path, settings: dict) -> None:
    """Create `folder` for this run, or check that it was made by a run with exactly these settings."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "run.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != json.loads(json.dumps(settings)):
            raise SystemExit(f"the checkpoint {folder} belongs to another run (different settings or topics); "
                             "move it away or pass another folder")
    else:
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")


async def saved_tasks(path: Path, n: int, write: Callable[[], Any]) -> list[str]:
    """The `n` tasks saved at `path`, or the teacher's new ones, saved before any is answered."""
    if path.exists():
        tasks = json.loads(path.read_text(encoding="utf-8"))
        if len(tasks) != n:
            raise SystemExit(f"the checkpoint {path} holds {len(tasks)} tasks, this run needs {n}")
        return tasks
    tasks = await write()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return tasks


def append_answers(path: Path, answers: dict[int, tuple[dict | None, str]]) -> None:
    """Append one finished batch and flush it to disk. A line cut by an earlier crash is closed first, so the new lines
    stay readable."""
    cut = False
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            cut = f.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as f:
        if cut:
            f.write("\n")
        for i, (row, reason) in answers.items():
            f.write(json.dumps({"i": i, "row": row, "reason": reason}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_answers(path: Path) -> dict[int, tuple[dict | None, str]]:
    """Answers saved by earlier batches, by task index. A last line cut by a crash is ignored (asked again)."""
    saved: dict[int, tuple[dict | None, str]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            saved[int(item["i"])] = (item["row"], str(item["reason"]))
    return saved
