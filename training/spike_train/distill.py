"""Teacher distillation with verification (rejection sampling).

A larger open-weight teacher (default: Qwen3.6-35B-A3B, Apache-2.0, runs locally on a 36 GB Mac) answers
domain tasks. Answers are kept only when they can be verified:
  * tasks with a gold label (MCQ, yes/no, numeric) must match it;
  * open-ended tasks must pass a rubric review by the teacher (score >= threshold). That is the teacher grading
    its own answer, so they are never counted as verified (meta.verified stays false). There is no cap on their
    share: one distillation run takes either seeds (all open-ended) or gold-labelled questions (all verified).
The teacher runs behind any OpenAI-compatible endpoint (mlx_lm.server, llama-server, vLLM).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from spike_train.metrics import extract_choice, extract_number, extract_yes_no, numbers_match, strip_think

RUBRIC = (
    "You are a strict reviewer. Score the RESPONSE to the TASK from 1 to 10 for correctness, depth, "
    "specificity and honesty about uncertainty. Penalize invented facts, numbers or sources heavily. "
    'Reply with JSON only: {"score": <int>, "issues": "<short>"}'
)


@dataclass
class Task:
    id: str
    prompt: str
    system: str
    gold: dict[str, Any] | None = None  # {"type": "mcq"|"yesno"|"numeric", "answer": ...}


def verify(task: Task, response: str) -> bool | None:
    """True/False when verifiable against gold, None when the task is open-ended."""
    if not task.gold:
        return None
    kind, answer = task.gold.get("type"), task.gold.get("answer")
    if kind == "mcq":
        return extract_choice(response) == str(answer).upper()
    if kind == "yesno":
        return extract_yes_no(response) == str(answer).lower()
    if kind == "numeric":
        return numbers_match(extract_number(response), float(answer), float(task.gold.get("rel_tol", 0.01)))
    raise ValueError(f"unknown gold type {kind}")


class Teacher:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, concurrency: int = 2,
                 timeout: float = 900.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.sem = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(timeout=timeout)

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.7, max_tokens: int = 4096,
                   thinking: bool = True) -> tuple[str, str]:
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": thinking}}
        async with self.sem:
            r = await self.client.post(f"{self.base_url}/chat/completions", json=body, headers=self.headers)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        reasoning = msg.get("reasoning_content") or ""
        content = msg.get("content") or ""
        if not reasoning and "<think>" in content:
            m = re.search(r"(?s)<think>(.*?)</think>", content)
            reasoning = m.group(1).strip() if m else ""
            content = strip_think(content)
        return content.strip(), reasoning.strip()

    async def review(self, task: Task, response: str) -> int:
        content, _ = await self.chat(
            [{"role": "system", "content": RUBRIC},
             {"role": "user", "content": f"TASK:\n{task.prompt}\n\nRESPONSE:\n{response}"}],
            temperature=0.0, max_tokens=300, thinking=False,
        )
        m = re.search(r"\{.*\}", content, re.DOTALL)
        try:
            return int(json.loads(m.group(0))["score"]) if m else 0
        except (ValueError, KeyError, TypeError):
            return 0

    async def aclose(self) -> None:
        await self.client.aclose()


async def distill_task(teacher: Teacher, task: Task, samples: int, min_score: int, keep_reasoning: bool,
                       max_reasoning_chars: int = 6000) -> dict[str, Any] | None:
    for _ in range(samples):
        content, reasoning = await teacher.chat(
            [{"role": "system", "content": task.system}, {"role": "user", "content": task.prompt}])
        if not content:
            continue
        verdict = verify(task, content)
        if verdict is False:
            continue
        if verdict is None and await teacher.review(task, content) < min_score:
            continue
        answer = content
        if keep_reasoning and reasoning and len(reasoning) <= max_reasoning_chars:
            answer = f"<think>\n{reasoning}\n</think>\n\n{content}"
        return {"messages": [
            {"role": "system", "content": task.system},
            {"role": "user", "content": task.prompt},
            {"role": "assistant", "content": answer},
        ], "meta": {"task_id": task.id, "verified": verdict is True, "source": "distill"}}
    return None
