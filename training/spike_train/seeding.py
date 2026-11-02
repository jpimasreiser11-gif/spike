"""Where a distillation run takes its tasks from, and the rule that no AI-written text becomes training data.

The owner's hard rule: no text written by Claude, GPT, Gemini or Llama may become training data, and seeds or prompts
written by an AI assistant count as such text. A recipe's `distill` block therefore names exactly one source of tasks:

* `topics`: a YAML file of short topic labels (plain noun phrases, no tasks or prose) under a `provenance` that says who
  chose them. The open teacher writes every task from the labels and later the answers. A label is an instruction to the
  teacher: it is never copied into a task, answer or training row (the rows record only the file and its hash).
* `seeds`: example tasks the teacher expands. Only for a JSONL file whose first line declares a human author; a file
  without the declaration is refused by distill.py and by prepare.py. Nothing can detect AI text: the declaration is
  the maintainer's statement, kept in the manifest.
* `tasks_from`: human-written training questions with gold answers from a registry source (training/datasets.yaml).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

MODES = ("topics", "seeds", "tasks_from")
MAX_LABEL_WORDS, MAX_LABEL_CHARS = 8, 70
# A label that starts like a request or a question is a task, not a topic
TASKISH = {"write", "explain", "describe", "calculate", "compute", "create", "draft", "list", "give", "how", "what",
           "why", "when", "where", "which", "who", "compare", "derive", "find", "solve", "show", "propose", "suggest",
           "generate", "analyse", "analyze", "explica", "escribe", "calcula", "cómo", "qué", "cuál", "redacta",
           "diseña", "crea"}


class SeedingError(ValueError):
    """The recipe's task source is missing, invalid or not allowed."""


@dataclass(frozen=True)
class Topics:
    path: str
    sha256: str
    provenance: str
    items: tuple[tuple[str, str], ...]      # (context, label); context is "" for a group without one


@dataclass(frozen=True)
class HumanSeeds:
    path: str
    sha256: str
    author: str
    prompts: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    mode: str                               # topics | seeds | tasks_from
    record: dict                            # what each distilled row and the manifest keep about it
    topics: Topics | None = None
    seeds: HumanSeeds | None = None
    gold: dict | None = None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def check_label(label: object) -> str | None:
    """Why `label` is not a short plain noun phrase, or None when it is."""
    if not isinstance(label, str) or not label.strip():
        return "empty"
    text = label.strip()
    words = text.split()
    if len(text) > MAX_LABEL_CHARS or len(words) > MAX_LABEL_WORDS:
        return f"longer than {MAX_LABEL_WORDS} words or {MAX_LABEL_CHARS} characters, so not a short label"
    if re.search(r"[.?!:;¿¡\n]", text):
        return "has sentence punctuation, so it is prose and not a label"
    if words[0].lower() in TASKISH:
        return f"starts with '{words[0]}', so it reads as a task and not a topic"
    return None


def load_topics(path: Path, shown: str | None = None) -> Topics:
    """A topics file: `provenance` (who chose the labels) and `groups`, each with an optional `context` (a noun phrase
    such as 'introductory physics' that is told to the teacher with the label) and its `labels`."""
    shown = shown or str(path)
    if not path.is_file():
        raise SeedingError(f"distill.topics {shown}: no such file")
    raw = path.read_bytes()
    try:
        doc = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise SeedingError(f"distill.topics {shown}: not readable YAML ({exc})") from exc
    provenance = doc.get("provenance") if isinstance(doc, dict) else None
    if not isinstance(provenance, str) or len(provenance.strip()) < 30:
        raise SeedingError(f"distill.topics {shown} has no provenance: say in the file who chose the labels and that they "
                           "are instructions to the teacher only (a `provenance:` text of at least 30 characters)")
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for n, group in enumerate(doc.get("groups") or [], 1):
        context = group.get("context", "") if isinstance(group, dict) else None
        labels = group.get("labels") if isinstance(group, dict) else None
        if not isinstance(context, str) or not isinstance(labels, list):
            raise SeedingError(f"distill.topics {shown}: group {n} needs `labels:` (a list) and an optional `context:`")
        if context and (why := check_label(context)):
            raise SeedingError(f"distill.topics {shown}: context '{context}': {why}")
        for label in labels:
            if (why := check_label(label)) is not None:
                raise SeedingError(f"distill.topics {shown}: label {label!r}: {why}")
            key = re.sub(r"\s+", " ", label.strip().lower())
            if key in seen:
                raise SeedingError(f"distill.topics {shown}: label '{label}' appears twice")
            seen.add(key)
            items.append((context.strip(), label.strip()))
    if not items:
        raise SeedingError(f"distill.topics {shown} has no labels")
    return Topics(shown, _sha256(raw), provenance.strip(), tuple(items))


def load_human_seeds(path: Path, shown: str | None = None) -> HumanSeeds:
    """A seeds file: JSONL whose first line is {"declaration": {"authored_by": "human", "author": "..."}} followed by
    {"id", "prompt"} lines. Refused without the declaration."""
    shown = shown or str(path)
    if not path.is_file():
        raise SeedingError(f"distill.seeds {shown}: no such file")
    raw = path.read_bytes()
    lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    try:
        head = json.loads(lines[0]).get("declaration") if lines else None
        rows = [json.loads(line) for line in lines[1:]]
    except (ValueError, AttributeError) as exc:
        raise SeedingError(f"distill.seeds {shown}: not JSONL ({exc})") from exc
    if not isinstance(head, dict) or head.get("authored_by") != "human" or not str(head.get("author") or "").strip():
        raise SeedingError(
            f"refusing distill.seeds {shown}: its first line must declare a human author, "
            '{"declaration": {"authored_by": "human", "author": "<who wrote the prompts>"}}. Seeds written by an AI '
            "assistant must not become training data: use distill.topics (short labels the open teacher turns into tasks)")
    prompts = tuple(str(r["prompt"]).strip() for r in rows if isinstance(r, dict) and str(r.get("prompt") or "").strip())
    if not prompts:
        raise SeedingError(f"distill.seeds {shown} has no prompts")
    return HumanSeeds(shown, _sha256(raw), str(head["author"]).strip(), prompts)


def resolve(dcfg: dict, root: Path) -> Plan:
    """The task source of a recipe's `distill` block, validated: exactly one of topics, seeds, tasks_from."""
    named = [m for m in MODES if dcfg.get(m)]
    if len(named) != 1:
        raise SeedingError("the distill block needs exactly one of topics, seeds and tasks_from "
                           f"({', '.join(named) if named else 'none'} given)")
    mode = named[0]
    if mode == "topics":
        topics = load_topics(root / dcfg["topics"], dcfg["topics"])
        return Plan(mode, {"mode": mode, "file": dcfg["topics"], "sha256": topics.sha256}, topics=topics)
    if mode == "seeds":
        seeds = load_human_seeds(root / dcfg["seeds"], dcfg["seeds"])
        return Plan(mode, {"mode": mode, "file": dcfg["seeds"], "sha256": seeds.sha256, "author": "human"}, seeds=seeds)
    return Plan(mode, {"mode": "gold", "source": dcfg["tasks_from"]["source"]}, gold=dcfg["tasks_from"])


def check_record(record: object, where: str) -> dict:
    """The seeding record of a distilled row, or SystemExit when it is missing or names an author that is not human."""
    mode = record.get("mode") if isinstance(record, dict) else None
    if mode not in ("topics", "seeds", "gold"):
        raise SystemExit(f"{where} has no seeding record (how its tasks were made); make it again with training/distill.py")
    if mode == "seeds" and record.get("author") != "human":
        raise SystemExit(f"refusing {where}: its tasks came from seeds that do not declare a human author")
    return record
