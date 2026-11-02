"""Evaluation items, scoring and comparison statistics, plus a minimal llama-server client.

Every variant (the base model with the specialist's system prompt, or the base model plus an adapter) answers
the same items with the same prompt, greedy decoding and thinking disabled, so differences come from the
weights alone. Accuracy carries a Wilson 95 % interval; base-vs-adapter differences use the exact McNemar
test on the paired items.
"""

from __future__ import annotations

import asyncio
import re
import socket
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from spike_train.data import (
    FORMATTERS,
    LETTERS,
    finqa_answer,
    finqa_prompt,
    mcq_prompt,
    pubmedqa_prompt,
    tatqa_prompt,
)
from spike_train.metrics import (
    amount_matches,
    extract_choice,
    extract_final,
    extract_number,
    extract_yes_no,
    mcnemar_exact,
    normalize_span,
    numbers_match,
    parse_amount,
    span_set,
    wilson_interval,
)


@dataclass
class Item:
    id: str
    task: str
    prompt: str
    kind: str  # mcq | yesno | numeric | amount | span | spans | literal
    gold: str  # amount: a number; spans: 'a; b; c'
    n_options: int = 0
    alt: str = ""  # amount: a second accepted number (FinQA's rounded annotated answer)


def make_item(task: str, fmt: str, index: int, row: dict[str, Any]) -> Item | None:
    if fmt == "medmcqa":
        options = [row.get(k) or "" for k in ("opa", "opb", "opc", "opd")]
        if row.get("cop") is None or not all(options) or row.get("choice_type") == "multi":
            return None
        return Item(f"{task}/{row.get('id', index)}", task, mcq_prompt(row["question"], options), "mcq",
                    LETTERS[int(row["cop"])], 4)
    if fmt == "pubmedqa":
        prompt = pubmedqa_prompt(row)
        if not prompt or row.get("final_decision") not in ("yes", "no", "maybe"):
            return None
        return Item(f"{task}/{row.get('pubid', index)}", task, prompt, "yesno", row["final_decision"])
    if fmt == "mmlu_pro":
        options = [o for o in row.get("options", []) if o and o != "N/A"]
        if not options or row.get("answer") not in LETTERS[: len(options)]:
            return None
        return Item(f"{task}/{row.get('question_id', index)}", task, mcq_prompt(row["question"], options), "mcq",
                    row["answer"], len(options))
    if fmt in ("case_hold", "openbookqa", "gsm8k", "mbpp", "wikisql"):
        chat = FORMATTERS[fmt](row, "")
        if not chat:
            return None
        prompt, target = (m["content"] for m in chat["messages"][1:])
        key = {"case_hold": "example_id", "openbookqa": "id", "gsm8k": "id",
               "mbpp": "task_id", "wikisql": "id"}[fmt]
        item_id = f"{task}/{row.get(key, index)}"
        if fmt in ("case_hold", "openbookqa"):
            return Item(item_id, task, prompt, "mcq", target.rsplit("Answer: ", 1)[-1],
                        5 if fmt == "case_hold" else 4)
        if fmt == "gsm8k":
            return Item(item_id, task, prompt, "numeric", target.rsplit("Answer: ", 1)[-1])
        return Item(item_id, task, prompt, "literal", literal_answer(target))
    if fmt in ("qasc", "commonsense_qa", "banking77", "phishing_url", "billsum_title"):
        chat = FORMATTERS[fmt](row, "")
        if not chat:
            return None
        prompt, target = (m["content"] for m in chat["messages"][1:])
        item_id = f"{task}/{row.get('id', index)}"
        if fmt in ("qasc", "commonsense_qa", "phishing_url"):
            return Item(item_id, task, prompt, "mcq", target.rsplit("Answer: ", 1)[-1],
                        {"qasc": 8, "commonsense_qa": 5, "phishing_url": 2}[fmt])
        if fmt == "banking77":
            return Item(item_id, task, prompt, "span", target.rsplit("Answer: ", 1)[-1])
        # A literal title match is a diagnostic only. Writing acceptance uses the existing pairwise evaluator.
        return Item(item_id, task, prompt, "literal", target)
    if fmt == "finqa":  # gold-facts setting, see data.py
        qa = row.get("qa") or {}
        prompt, exe = finqa_prompt(row), qa.get("exe_ans")
        if not prompt or exe is None:
            return None
        item_id = f"{task}/{row.get('id', index)}"
        if isinstance(exe, str):
            return Item(item_id, task, prompt, "yesno", exe) if exe in ("yes", "no") else None
        # exe_ans is the program's exact result; the annotated answer is rounded ('28%' for 0.27743) and is what
        # training teaches, so a prediction may match either
        alt = parse_amount(finqa_answer(qa))
        return Item(item_id, task, prompt, "amount", repr(float(exe)),
                    alt=repr(alt[0] / 100 if alt[1] else alt[0]) if alt else "")
    if fmt == "tatqa":
        qa = row.get("qa") or {}
        prompt, answer = tatqa_prompt(row), qa.get("answer")
        item_id = f"{task}/{qa.get('uid', index)}"
        if not prompt or answer is None:
            return None
        if isinstance(answer, list):
            parts = [str(a).strip() for a in answer if str(a).strip()]
            if not parts:
                return None
            return Item(item_id, task, prompt, "span" if len(parts) == 1 else "spans", "; ".join(parts))
        try:
            return Item(item_id, task, prompt, "amount", repr(float(str(answer).replace(",", ""))))
        except ValueError:
            return None
    raise ValueError(f"no evaluation format '{fmt}'")


def literal_answer(response: str) -> str:
    """A single fenced code/SQL block or the entire bare answer; preserve case, operators and indentation.
    No execution and no whitespace/punctuation normalization that could change program meaning."""
    blocks = re.findall(r"```(?:python|sql)?[ \t]*\r?\n(.*?)```", response, re.DOTALL)
    return (blocks[0] if len(blocks) == 1 else response).strip().replace("\r\n", "\n")


def score(item: Item, response: str) -> tuple[str | None, bool]:
    if item.kind == "literal":
        parsed = literal_answer(response)
        return parsed or None, bool(parsed) and parsed == item.gold
    if item.kind == "mcq":
        parsed = extract_choice(response, item.n_options or 10)
        return parsed, parsed == item.gold
    if item.kind == "yesno":
        parsed = extract_yes_no(response)
        return parsed, parsed == item.gold
    if item.kind == "numeric":
        value = extract_number(response)
        return (None if value is None else f"{value:g}"), numbers_match(value, float(item.gold))
    answer = extract_final(response)
    if item.kind == "amount":  # 0.5 % tolerance, '%' allowed, scale words and $ ignored (metrics.amount_matches)
        parsed = parse_amount(answer)
        correct = any(amount_matches(parsed, float(g)) for g in (item.gold, item.alt) if g)
        return (None if parsed is None else f"{parsed[0]:.10g}{'%' if parsed[1] else ''}"), correct
    if item.kind == "span":  # normalized exact match
        parsed = None if answer is None else normalize_span(answer)
        return parsed, parsed is not None and parsed == normalize_span(item.gold)
    if item.kind == "spans":  # the same items in any order
        found = None if answer is None else span_set(answer)
        return ("; ".join(sorted(found)) if found else None), found is not None and found == span_set(item.gold)
    raise ValueError(item.kind)


def rescore(predictions: list[dict], items: dict[str, Item]) -> list[dict]:
    """Score saved responses again with the current extractors (for a fixed parser: no new generation).
    Every prediction must match an item, otherwise KeyError: a rescore never drops rows silently."""
    out = []
    for p in predictions:
        item = items[p["item"]]
        parsed, correct = score(item, p["response"])
        out.append({**p, "parsed": parsed, "correct": correct})
    return out


def reusable_rows(saved: list[dict], suite: str, task: str, variant: str, item_ids: list[str]) -> list[dict] | None:
    """Rows of an interrupted run that can stand in for generating (suite, task, variant) again: only when they
    cover exactly the same items (greedy decoding with identical settings gives the same answers)."""
    rows = [r for r in saved if (r["suite"], r["task"], r["variant"]) == (suite, task, variant)]
    if sorted(r["item"] for r in rows) != sorted(item_ids):
        return None
    order = {item_id: i for i, item_id in enumerate(item_ids)}
    return sorted(rows, key=lambda r: order[r["item"]])


def _accuracy(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    correct = sum(r["correct"] for r in rows)
    lo, hi = wilson_interval(correct, n)
    return {"n": n, "correct": correct, "accuracy": round(correct / n, 4) if n else 0.0,
            "ci95": [round(lo, 4), round(hi, 4)], "unparsed": sum(r["parsed"] is None for r in rows),
            "truncated": sum(r.get("finish_reason") == "length" for r in rows)}


def _paired(rows: list[dict], variant: str, baseline: str) -> dict[str, Any]:
    by_item: dict[str, dict[str, bool]] = defaultdict(dict)
    for r in rows:
        by_item[r["item"]][r["variant"]] = r["correct"]
    pairs = [(v[baseline], v[variant]) for v in by_item.values() if baseline in v and variant in v]
    b = sum(1 for base, var in pairs if base and not var)  # only the baseline was right
    c = sum(1 for base, var in pairs if var and not base)  # only the variant was right
    n = len(pairs)
    return {"paired_n": n, "delta_points": round(100 * (c - b) / n, 2) if n else 0.0,
            "baseline_only": b, "variant_only": c, "p_value": round(mcnemar_exact(b, c), 6)}


def summarize(predictions: list[dict], baseline: str = "base") -> dict[str, Any]:
    """Per task and pooled per suite: accuracy per variant and paired comparison against the baseline."""
    variants = sorted({p["variant"] for p in predictions}, key=lambda v: (v != baseline, v))
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in predictions:
        groups[("task", p["task"])].append(p)
        groups[("suite", p["suite"])].append(p)
    out: dict[str, Any] = {"variants": variants, "tasks": {}, "suites": {}}
    for (level, name), rows in sorted(groups.items()):
        entry: dict[str, Any] = {"accuracy": {}, "vs_" + baseline: {}}
        for v in variants:
            mine = [r for r in rows if r["variant"] == v]
            if mine:
                entry["accuracy"][v] = _accuracy(mine)
            if v != baseline and mine:
                entry["vs_" + baseline][v] = _paired(rows, v, baseline)
        out["tasks" if level == "task" else "suites"][name] = entry
    return out


def check_acceptance(summary: dict[str, Any], acceptance: dict[str, Any], variant: str,
                     baseline: str = "base") -> tuple[bool, list[str]]:
    """Apply a training config's `acceptance` block to measured results. Missing suites fail."""
    reasons: list[str] = []
    ok = True
    primary = acceptance.get("primary") or {}
    if "min_win_rate" in primary:
        return False, ["this recipe requires pairwise evaluation; regression or literal matches cannot accept it"]
    if "min_gain_points" in primary:
        cmp = summary["suites"].get(primary["suite"], {}).get("vs_" + baseline, {}).get(variant)
        if not cmp:
            return False, [f"suite '{primary['suite']}' was not evaluated for {variant}"]
        gain_ok = cmp["delta_points"] >= primary["min_gain_points"]
        p_ok = cmp["p_value"] <= primary.get("max_p_value", 0.05)
        ok &= gain_ok and p_ok
        reasons.append(f"{primary['suite']}: {cmp['delta_points']:+.2f} pts (need ≥ {primary['min_gain_points']}), "
                       f"p = {cmp['p_value']:.4g} (need ≤ {primary.get('max_p_value', 0.05)})")
    regression = acceptance.get("regression") or {}
    if regression:
        cmp = summary["suites"].get(regression["suite"], {}).get("vs_" + baseline, {}).get(variant)
        if not cmp:
            return False, reasons + [f"regression suite '{regression['suite']}' was not evaluated for {variant}"]
        drop_ok = -cmp["delta_points"] <= regression["max_drop_points"]
        ok &= drop_ok
        reasons.append(f"{regression['suite']}: {cmp['delta_points']:+.2f} pts (max drop {regression['max_drop_points']})")
    return ok, reasons


def pairwise_summary(verdicts: list[str]) -> dict[str, Any]:
    """verdicts: 'win' | 'loss' | 'tie' for the candidate, one per prompt (already position-debiased)."""
    wins, losses, ties = (verdicts.count(k) for k in ("win", "loss", "tie"))
    n = len(verdicts)
    rate = (wins + 0.5 * ties) / n if n else 0.0
    lo, hi = wilson_interval(wins, wins + losses)
    return {"n": n, "wins": wins, "losses": losses, "ties": ties, "win_rate": round(rate, 4),
            "decided_win_share_ci95": [round(lo, 4), round(hi, 4)], "sign_test_p": round(mcnemar_exact(losses, wins), 6)}


def general_regression(run: dict[str, Any], suite: str, variant: str, baseline: str = "base") -> dict[str, Any]:
    """The base-vs-adapter comparison of the regression suite, from a run_eval.py summary, to store in a pairwise
    summary (so the pairwise run alone carries both halves of the verdict)."""
    cmp = run.get("suites", {}).get(suite, {}).get("vs_" + baseline, {}).get(variant)
    if not cmp:
        raise ValueError(f"the general eval run has no suite '{suite}' for '{variant}' "
                         f"(variants: {', '.join(run.get('variants') or []) or 'none'})")
    return {"suite": suite, "variant": variant, **{k: cmp[k] for k in ("paired_n", "delta_points", "p_value")}}


def check_pairwise_acceptance(summary: dict[str, Any], acceptance: dict[str, Any]) -> tuple[bool, list[str]]:
    """Apply a pairwise recipe's `acceptance` block to a pairwise summary: win rate and sign test on the open-ended
    prompts, and the general-suite drop (`summary["general"]`, see `general_regression`). Both must pass; a
    missing general result fails, as a missing suite does in `check_acceptance`."""
    primary = acceptance.get("primary") or {}
    if "min_win_rate" not in primary:
        return False, ["the recipe's primary criterion is not a pairwise win rate (primary.min_win_rate)"]
    max_p = primary.get("max_p_value", 0.05)
    ok = summary["win_rate"] >= primary["min_win_rate"] and summary["sign_test_p"] <= max_p
    reasons = [f"{primary.get('suite', 'pairwise')}: win rate {summary['win_rate']:.3f} "
               f"(need ≥ {primary['min_win_rate']}), sign test p = {summary['sign_test_p']:.4g} (need ≤ {max_p})"]
    regression = acceptance.get("regression") or {}
    if regression:
        general = summary.get("general") or {}
        if general.get("suite") != regression["suite"]:
            return False, reasons + [f"regression suite '{regression['suite']}' was not evaluated for "
                                     f"{summary.get('adapter', 'this adapter')}"]
        ok &= -general["delta_points"] <= regression["max_drop_points"]
        reasons.append(f"{regression['suite']}: {general['delta_points']:+.2f} pts "
                       f"(max drop {regression['max_drop_points']})")
    return ok, reasons


# ------------------------------------------------------------------ llama-server client
EVAL_OPTIONS = {"max_tokens": "--max-tokens"}


def eval_args(config: dict[str, Any]) -> list[str]:
    """run_eval.py arguments fixed by a training config's `eval` block, so an adapter's evaluation settings
    are part of its recipe. Base and adapter are scored in the same run and therefore share them."""
    out: list[str] = []
    for key, value in (config.get("eval") or {}).items():
        if key not in EVAL_OPTIONS:
            raise ValueError(f"unknown eval option '{key}' (known: {', '.join(EVAL_OPTIONS)})")
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"eval.{key} must be a positive integer, got {value!r}")
        out += [EVAL_OPTIONS[key], str(value)]
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    """OpenAI-compatible chat against llama-server with an explicit per-request LoRA selection.

    Every request carries a scale for every loaded adapter: an empty `lora` list makes llama-server use its
    global scales (1.0 per `--lora` file), not the base model. cache_prompt is off, so no KV state is shared
    between requests (and therefore between adapters).
    """

    def __init__(self, base_url: str, concurrency: int = 1, timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(timeout=timeout)
        self.sem = asyncio.Semaphore(concurrency)
        self.table: dict[str, int] = {}

    async def adapters(self) -> dict[str, int]:
        r = await self.http.get(f"{self.base_url}/lora-adapters")
        r.raise_for_status()
        from pathlib import PurePath

        self.table = {PurePath(a["path"]).stem: int(a["id"]) for a in r.json()}
        return self.table

    def lora(self, adapter: str | None) -> list[dict[str, Any]]:
        """Scales for one variant: `adapter` at 1.0 (None = base model), every other loaded adapter at 0.0."""
        if adapter is not None and adapter not in self.table:
            raise KeyError(f"adapter '{adapter}' is not loaded (loaded: {sorted(self.table)})")
        selected = self.table.get(adapter) if adapter else None
        return [{"id": i, "scale": 1.0 if i == selected else 0.0} for i in sorted(self.table.values())]

    async def chat(self, system: str, prompt: str, lora: list[dict[str, Any]], max_tokens: int,
                   temperature: float = 0.0, seed: int = 0, thinking: bool = False) -> dict[str, Any]:
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": temperature, "max_tokens": max_tokens, "seed": seed, "cache_prompt": False,
                "chat_template_kwargs": {"enable_thinking": thinking}}
        if lora:
            body["lora"] = lora
        async with self.sem:
            t0 = time.perf_counter()
            r = await self.http.post(f"{self.base_url}/v1/chat/completions", json=body)
            elapsed = time.perf_counter() - t0
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        return {"content": choice["message"].get("content") or "", "finish_reason": choice.get("finish_reason"),
                "completion_tokens": (data.get("usage") or {}).get("completion_tokens"), "elapsed_s": round(elapsed, 3)}

    async def aclose(self) -> None:
        await self.http.aclose()


def item_dict(item: Item) -> dict[str, Any]:
    return asdict(item)
