"""Self-generated replay: the base model's own answers to general prompts, as anti-forgetting data.

Human-written replay (oasst2) has a style of its own, unlike the base model's, and training on it pulls the adapter
away from the base's persona and format. Here the replay target is what the base model itself answers to the same
prompt, under the specialist's system prompt and the chat settings SPIKE uses at inference (greedy, thinking off),
so a replay row asks the adapter to keep doing what the base already does.
The generator's terms apply to what it wrote: its Hub license must be on the training allowlist (licenses.py), it
is recorded on every row, and prepare.py checks it again. The server must be the base model alone, no adapter applied.
training/self_replay.py is the command line; this module is the part that needs no dataset and no Hub.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

import httpx

from spike_train.data import fingerprint
from spike_train.distill import Teacher

MIN_ANSWER_TOKENS = 16   # a prompt that leaves less room than this for an answer is skipped
TOKEN_MARGIN = 8         # left free below max_seq_length: the answer's end-of-turn tokens are counted by the trainer
# Repetition, on the answer alone. A sentence or line this long that occurs twice is a loop, not a figure of speech.
REPEAT_MIN_WORDS = 6
# Loops no punctuation separates: this share of the word 4-grams of a text of 20 words or more are repeats.
REPEAT_NGRAM, REPEAT_NGRAM_MIN_WORDS, REPEAT_NGRAM_RATIO = 4, 20, 0.3
DROP_REASONS = ("prompt_too_long", "thinking", "hit_length_limit", "unfinished", "empty", "repeated_sentence",
                "repeated_ngrams", "too_long")
NOT_EXPOSED = (404, 405, 501)   # what a server without llama-server's LoRA endpoint answers

_WORDS = re.compile(r"\w+")
_UNITS = re.compile(r"(?<=[.!?…。])\s+|\n+")


@dataclass
class Prompt:
    id: str
    source: str
    text: str


def first_user_prompts(chats: Iterable[dict | None], source: str, seen: set[str]) -> list[Prompt]:
    """The first user turn of each chat (a chat of several turns shares it with the shorter ones), once per distinct
    text across every source that shares `seen`."""
    out = []
    for chat in chats:
        text = next((m["content"] for m in (chat or {}).get("messages", []) if m["role"] == "user"), "").strip()
        pid = fingerprint({"messages": [{"role": "user", "content": text}]})[:16]
        if text and pid not in seen:
            seen.add(pid)
            out.append(Prompt(pid, source, text))
    return out


def repetition(text: str) -> str | None:
    """Why `text` repeats itself, or None. `repeated_sentence`: a sentence or line of REPEAT_MIN_WORDS words or more occurs
    twice, ignoring case and punctuation (the loop the first medicine adapter fell into). `repeated_ngrams`: at least
    REPEAT_NGRAM_RATIO of its word 4-grams are repeats. List markers, table rules and 'Answer: B' are below both limits."""
    seen: set[str] = set()
    for unit in _UNITS.split(text):
        words = _WORDS.findall(unit.lower())
        if len(words) >= REPEAT_MIN_WORDS:
            if " ".join(words) in seen:
                return "repeated_sentence"
            seen.add(" ".join(words))
    words = _WORDS.findall(text.lower())
    grams = [tuple(words[i:i + REPEAT_NGRAM]) for i in range(len(words) - REPEAT_NGRAM + 1)]
    if len(words) >= REPEAT_NGRAM_MIN_WORDS and 1 - len(set(grams)) / len(grams) >= REPEAT_NGRAM_RATIO:
        return "repeated_ngrams"
    return None


async def check_server(teacher: Teacher) -> dict[str, Any]:
    """Refuse (ValueError) unless the server answers as the base model alone: llama-server's GET /lora-adapters must list
    no adapter with a non-zero scale (a request without `lora` runs at those global scales). A server without that
    endpoint (mlx_lm.server, vLLM) cannot be asked; that is recorded. Returns what to record about the server."""
    root = teacher.base_url.removesuffix("/v1")
    try:
        loras = await teacher.client.get(f"{root}/lora-adapters", headers=teacher.headers)
        props = await teacher.client.get(f"{root}/props", headers=teacher.headers)
    except httpx.HTTPError as exc:
        raise ValueError(f"cannot reach the server at {root} ({exc})") from exc
    asked = loras.status_code not in NOT_EXPOSED
    if asked:
        try:
            adapters = loras.json() if loras.status_code == 200 else None
        except ValueError:
            adapters = None
        if not isinstance(adapters, list):
            raise ValueError(f"GET {root}/lora-adapters gave no list of adapters (HTTP {loras.status_code}); "
                             "cannot tell whether the server runs the base model")
        applied = [a for a in adapters if not isinstance(a, dict) or not isinstance(a.get("scale"), int | float)
                   or a["scale"] != 0]
        if applied:
            raise ValueError(f"the server has LoRA adapters applied: {applied}; the replay must come from the base model "
                             "alone: start llama-server without --lora, or set every scale to 0 (POST /lora-adapters)")
    info = props.json() if props.status_code == 200 and props.content else {}
    info = info if isinstance(info, dict) else {}
    model_path = info.get("model_path")
    return {"build": info.get("build_info"), "model_file": PurePath(model_path).name if model_path else None,
            "adapters_checked": asked}


async def self_answer(teacher: Teacher, system: str, prompt: Prompt, count_tokens: Callable[[dict], int], max_len: int,
                      record: dict[str, Any]) -> tuple[dict | None, str | None]:
    """The base model's answer to one prompt as a training chat (with `record` and the prompt's origin in `meta`), or
    (None, why it was dropped). The prompt and the answer together fit `max_len` tokens as the trainer counts them;
    an answer that hit the limit, was empty, came with reasoning, or repeats itself is dropped."""
    chat = [{"role": "system", "content": system}, {"role": "user", "content": prompt.text}]
    budget = max_len - count_tokens({"messages": [*chat, {"role": "assistant", "content": ""}]}) - TOKEN_MARGIN
    if budget < MIN_ANSWER_TOKENS:
        return None, "prompt_too_long"
    done = await teacher.complete(chat, temperature=0.0, max_tokens=budget, thinking=False)
    if done["reasoning"]:  # the server ignored enable_thinking: these are not the answers SPIKE gives
        return None, "thinking"
    if done["finish_reason"] != "stop":
        return None, "hit_length_limit" if done["finish_reason"] == "length" else "unfinished"
    if not done["content"]:
        return None, "empty"
    if why := repetition(done["content"]):
        return None, why
    row: dict[str, Any] = {"messages": [*chat, {"role": "assistant", "content": done["content"]}]}
    if count_tokens(row) > max_len:
        return None, "too_long"
    row["meta"] = {**record, "prompt_source": prompt.source, "prompt_id": prompt.id, "max_tokens": budget,
                   "completion_tokens": done["completion_tokens"], "finish_reason": done["finish_reason"]}
    return row, None
