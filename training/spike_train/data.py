"""Dataset formatting, deduplication and decontamination. Pure functions: unit-tested without downloads."""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections.abc import Iterable, Iterator
from typing import Any

Chat = dict[str, Any]  # {"messages": [...]} in the mlx-lm chat format
LETTERS = "ABCDEFGHIJ"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


MCQ_INSTRUCTION = "Answer with the letter of the correct option, after a short justification."
PUBMEDQA_INSTRUCTION = "Read the abstract and answer the research question with yes, no or maybe."
GSM8K_INSTRUCTION = "Solve step by step, then give the final number on the last line as 'Answer: <number>'."
# Instruction text shared by every prompt of a format. It is removed before n-gram decontamination,
# otherwise every training prompt would "overlap" every eval prompt through the template alone.
TEMPLATES = (MCQ_INSTRUCTION, PUBMEDQA_INSTRUCTION, GSM8K_INSTRUCTION)


def content_text(text: str) -> str:
    for template in TEMPLATES:
        text = text.replace(template, " ")
    return text


def mcq_prompt(question: str, options: list[str]) -> str:
    opts = "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(options))
    return f"{question.strip()}\n\n{opts}\n\n{MCQ_INSTRUCTION}"


# ------------------------------------------------------------------ formatters (source row -> chat)
def fmt_medmcqa(row: dict[str, Any], system: str) -> Chat | None:
    options = [row.get(k) or "" for k in ("opa", "opb", "opc", "opd")]
    cop = row.get("cop")
    if cop is None or not all(options) or row.get("choice_type") == "multi":
        return None
    explanation = (row.get("exp") or "").strip()
    if len(explanation) < 40:  # keep only examples that teach reasoning, not bare labels
        return None
    answer = f"{explanation}\n\nAnswer: {LETTERS[int(cop)]}. {options[int(cop)]}"
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": mcq_prompt(row["question"], options)},
        {"role": "assistant", "content": answer},
    ]}


def pubmedqa_prompt(row: dict[str, Any]) -> str | None:
    ctx = row.get("context") or {}
    contexts = ctx.get("contexts") if isinstance(ctx, dict) else ctx
    if not contexts:
        return None
    abstract = "\n".join(contexts)
    return f"{PUBMEDQA_INSTRUCTION}\n\nAbstract:\n{abstract}\n\nQuestion: {row['question']}"


def gsm8k_prompt(question: str) -> str:
    return f"{question.strip()}\n\n{GSM8K_INSTRUCTION}"


def fmt_pubmedqa(row: dict[str, Any], system: str) -> Chat | None:
    user = pubmedqa_prompt(row)
    if not user or not row.get("long_answer") or row.get("final_decision") not in ("yes", "no", "maybe"):
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": f"{row['long_answer'].strip()}\n\nAnswer: {row['final_decision']}"},
    ]}


def fmt_sujet(row: dict[str, Any], system: str) -> Chat | None:
    user = (row.get("user_prompt") or row.get("inputs") or "").strip()
    answer = str(row.get("answer") or "").strip()
    if not user or not answer:
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": answer},
    ]}


def fmt_messages(row: dict[str, Any], system: str | None = None) -> Chat | None:
    msgs = row.get("messages")
    if not isinstance(msgs, list) or not msgs or msgs[-1].get("role") != "assistant":
        return None
    clean = [{"role": m["role"], "content": str(m["content"])} for m in msgs if m.get("role") in ("system", "user", "assistant")]
    return {"messages": clean}


def fmt_mmlu_pro(row: dict[str, Any], system: str) -> Chat | None:
    options = [o for o in row.get("options", []) if o and o != "N/A"]
    if not options or row.get("answer") is None:
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": mcq_prompt(row["question"], options)},
        {"role": "assistant", "content": f"Answer: {row['answer']}"},
    ]}


FORMATTERS = {
    "medmcqa": fmt_medmcqa,
    "pubmedqa": fmt_pubmedqa,
    "sujet": fmt_sujet,
    "messages": fmt_messages,
    "mmlu_pro": fmt_mmlu_pro,
}


# ------------------------------------------------------------------ quality, dedup, contamination
def text_of(chat: Chat, roles: tuple[str, ...] = ("user",)) -> str:
    return "\n".join(m["content"] for m in chat["messages"] if m["role"] in roles)


def fingerprint(chat: Chat) -> str:
    return hashlib.sha1(_norm(text_of(chat, ("user", "assistant"))).encode()).hexdigest()


def dedupe(chats: Iterable[Chat]) -> Iterator[Chat]:
    seen: set[str] = set()
    for chat in chats:
        fp = fingerprint(chat)
        if fp not in seen:
            seen.add(fp)
            yield chat


def ngrams(text: str, n: int = 13) -> set[str]:
    words = _norm(text).split()
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


class ContaminationIndex:
    """13-gram overlap index over evaluation prompts (the standard used by GPT-3/Llama decontamination)."""

    def __init__(self, n: int = 13):
        self.n = n
        self.grams: set[str] = set()
        self.short: set[str] = set()  # prompts shorter than n words are matched exactly

    def add(self, text: str) -> None:
        text = content_text(text)
        grams = ngrams(text, self.n)
        if grams:
            self.grams |= grams
        else:
            self.short.add(_norm(text))

    def contaminated(self, text: str) -> bool:
        text = content_text(text)
        if _norm(text) in self.short:
            return True
        return any(g in self.grams for g in ngrams(text, self.n))


def passes_quality(chat: Chat, min_answer_chars: int = 2, max_chars: int = 24_000) -> bool:
    msgs = chat["messages"]
    if not msgs or msgs[-1]["role"] != "assistant":
        return False
    answer = msgs[-1]["content"].strip()
    total = sum(len(m["content"]) for m in msgs)
    return len(answer) >= min_answer_chars and total <= max_chars and "�" not in answer


def mix_and_split(domain: list[Chat], replay: list[Chat], replay_ratio: float, valid_fraction: float,
                  seed: int = 0) -> tuple[list[Chat], list[Chat]]:
    """Blend domain data with general replay data so that replay is `replay_ratio` of the training set."""
    rng = random.Random(seed)
    domain, replay = domain[:], replay[:]
    rng.shuffle(domain)
    rng.shuffle(replay)
    n_replay = int(len(domain) * replay_ratio / max(1e-9, 1 - replay_ratio)) if replay_ratio > 0 else 0
    data = domain + replay[:n_replay]
    rng.shuffle(data)
    n_valid = max(1, int(len(data) * valid_fraction)) if data else 0
    return data[n_valid:], data[:n_valid]


def write_jsonl(path, chats: Iterable[Chat]) -> int:
    count = 0
    with open(path, "w", encoding="utf-8") as f:
        for chat in chats:
            f.write(json.dumps(chat, ensure_ascii=False) + "\n")
            count += 1
    return count
