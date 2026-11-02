"""Dataset formatting, deduplication and decontamination. Pure functions: unit-tested without downloads."""

from __future__ import annotations

import hashlib
import json
import operator
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
FINQA_INSTRUCTION = ("Work out the calculation step by step, then give the final number on the last line as "
                     "'Answer: <number>' ('Answer: yes' or 'Answer: no' for a yes/no question).")
TATQA_INSTRUCTION = ("Answer from the table and the text, in the units they use (do not convert thousands or millions). "
                     "Show a calculation briefly; separate several items with '; '. "
                     "End with a final line 'Answer: <answer>'.")
# Instruction text shared by every prompt of a format. It is removed before n-gram decontamination,
# otherwise every training prompt would "overlap" every eval prompt through the template alone.
TEMPLATES = (MCQ_INSTRUCTION, PUBMEDQA_INSTRUCTION, GSM8K_INSTRUCTION, FINQA_INSTRUCTION, TATQA_INSTRUCTION)


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


# FinQA (Chen et al., 2021) in the GOLD-FACTS setting: the prompt carries the supporting facts the annotators marked
# (`gold_inds`), so no retrieval is involved. Scores are therefore not comparable with retriever-based FinQA results.
_FINQA_OPS = {"add": "+", "minus": "-", "multiply": "*", "divide": "/", "exp": "^", "compare_larger": ">"}


def finqa_prompt(row: dict[str, Any]) -> str | None:
    qa = row.get("qa") or {}
    facts = [str(f).strip() for f in (qa.get("gold_inds") or {}).values() if str(f).strip()]
    if not facts or not str(qa.get("question") or "").strip():
        return None
    return "Facts:\n" + "\n".join(facts) + f"\n\nQuestion: {qa['question'].strip()}\n\n{FINQA_INSTRUCTION}"


def finqa_answer(qa: dict[str, Any]) -> str:
    """The annotated final answer ('28%', '$ 13 million'); comparison programs have 'yes'/'no' as their result.
    The few rows with an empty answer (48 of 6,251) use the annotated result of the last step instead."""
    if isinstance(qa.get("exe_ans"), str):
        return qa["exe_ans"]
    answer = re.sub(r"(?:\\+n)+$", "", str(qa.get("answer") or "")).strip()  # a few end in a literal "\\n"
    return answer or str((qa.get("steps") or [{}])[-1].get("res") or "").strip()


def finqa_steps(steps: list[dict[str, Any]]) -> list[str] | None:
    """The annotated program as lines like '5829 - 5735 = 94'; '#0' becomes the result of that step."""
    def arg(a: str, done: list[dict[str, Any]]) -> str:
        if a.startswith("#"):
            return done[int(a[1:])]["res"]
        return ("-1" if a == "const_m1" else a[6:]) if a.startswith("const_") else a

    lines = []
    try:
        for i, step in enumerate(steps):
            op = re.sub(r"\d+-\d+$", "", step["op"])
            args = [arg(a, steps[:i]) for a in (step["arg1"], step["arg2"]) if a not in ("", "none")]
            binary = op in _FINQA_OPS and len(args) == 2
            expr = f" {_FINQA_OPS[op]} ".join(args) if binary else f"{op}({', '.join(args)})"
            lines.append(f"{expr} = {step['res']}")
    except (KeyError, IndexError, ValueError):
        return None
    return lines


_FINQA_MATH = {"add": operator.add, "minus": operator.sub, "multiply": operator.mul, "divide": operator.truediv,
               "exp": operator.pow}


def _readings(text: str, percent: bool = False) -> list[tuple[float, float]] | None:
    """A number as annotated, as (value, half a unit of its last digit); '3.2%' reads as 0.032 or as 3.2, and
    with percent=True so does '3.2' (a result written as a percentage of the value)."""
    text = text.strip()
    if text.startswith("const_"):
        text = "-1" if text == "const_m1" else text[6:]
    number = text.rstrip("%").replace(",", "").replace("$", "").strip()
    try:
        value = float(number)
    except ValueError:
        return None
    half = 0.5 * 10 ** -(len(number.split(".")[1]) if "." in number else 0)
    return [(value / 100, half / 100), (value, half)] if percent or text.endswith("%") else [(value, half)]


def _agrees(value: float, result: float, half: float) -> bool:
    """Within 0.5 % of the recomputed value, or within the rounding of the digits the annotator wrote."""
    return abs(value - result) <= max(1e-9, 0.005 * abs(value), half)


def finqa_steps_consistent(steps: list[dict[str, Any]]) -> bool:
    """Does every step's annotated `res` follow from its arguments? '#n' arguments are the annotated result of
    that step, constants and percentages are read as written, and a result may be written as a percentage of the
    value. Steps that cannot be recomputed here (table operations, row labels) are not a reason to say no."""
    for i, step in enumerate(steps):
        op = re.sub(r"\d+-\d+$", "", step["op"])
        if op not in _FINQA_MATH and op != "compare_larger":
            continue
        args = [_readings(steps[:i][int(a[1:])]["res"] if a.startswith("#") else a) for a in (step["arg1"], step["arg2"])]
        if None in args:
            continue
        results = _readings(step["res"], percent=True)
        if op == "compare_larger":
            if step["res"] in ("yes", "no") and not any((a > b) == (step["res"] == "yes")
                                                        for a, _ in args[0] for b, _ in args[1]):
                return False
            continue
        if results is None:
            continue
        try:
            values = [_FINQA_MATH[op](a, b) for a, _ in args[0] for b, _ in args[1]]
        except (ZeroDivisionError, OverflowError):
            continue
        if not any(_agrees(v, r, half) for v in values for r, half in results):
            return False
    return True


def fmt_finqa_train(row: dict[str, Any], system: str) -> Chat | None:
    """fmt_finqa for training sources: a row whose annotated steps contradict their own arithmetic (5.6 % of the
    steps in the train split) is dropped, so the model is not taught wrong sums. Eval items and the
    decontamination index use the unfiltered `finqa` format."""
    try:
        consistent = finqa_steps_consistent((row.get("qa") or {}).get("steps") or [])
    except (KeyError, IndexError, ValueError):
        return None
    return fmt_finqa(row, system) if consistent else None


def fmt_finqa(row: dict[str, Any], system: str) -> Chat | None:
    user, qa = finqa_prompt(row), row.get("qa") or {}
    answer, steps = finqa_answer(qa), finqa_steps(qa.get("steps") or [])
    if not user or not answer or steps is None:
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": "\n".join([*steps, f"Answer: {answer}"])},
    ]}


# TAT-QA (Zhu et al., 2021): questions over a table plus text; one row per question (the registry's `explode`).
def tatqa_prompt(row: dict[str, Any]) -> str | None:
    qa = row.get("qa") or {}
    rows = (row.get("table") or {}).get("table") or []
    table = "\n".join("| " + " | ".join(str(c).strip() for c in r) + " |" for r in rows)
    paragraphs = sorted(row.get("paragraphs") or [], key=lambda p: p.get("order", 0))
    text = "\n".join(str(p.get("text") or "").strip() for p in paragraphs).strip()
    if not str(qa.get("question") or "").strip() or not (table or text):
        return None
    sections = [f"{name}:\n{body}" for name, body in (("Table", table), ("Text", text)) if body]
    return "\n\n".join([*sections, f"Question: {qa['question'].strip()}", TATQA_INSTRUCTION])


def tatqa_target(qa: dict[str, Any]) -> str | None:
    """Derivation (arithmetic, count) and then 'Answer: ...': the number with its scale, the span, or 'a; b; c'."""
    answer, scale = qa.get("answer"), qa.get("scale") or ""
    derivation = str(qa.get("derivation") or "").strip()
    if isinstance(answer, list):
        parts = [str(a).strip() for a in answer if str(a).strip()]
        return f"Answer: {'; '.join(parts)}" if parts else None
    if answer is None or not str(answer).strip():
        return None
    if isinstance(answer, float) and answer.is_integer():
        answer = int(answer)
    lines = []
    if derivation and qa.get("answer_type") == "count":
        lines.append("Counted: " + "; ".join(x.strip() for x in derivation.split("##") if x.strip()))
    elif derivation:
        lines.append(derivation)
    lines.append(f"Answer: {str(answer).strip()} {scale}".rstrip())
    return "\n".join(lines)


def fmt_tatqa(row: dict[str, Any], system: str) -> Chat | None:
    user, target = tatqa_prompt(row), tatqa_target(row.get("qa") or {})
    if not user or not target:
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": target},
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


# Candidate human-authored specialist sources. All converters are pure; MBPP tests and SQL are never executed.
CODE_INSTRUCTION = "Return only the Python solution in a fenced code block."
SQL_INSTRUCTION = ('Return only SQL in a fenced code block, using table data, double-quoted column names and '
                   'single-quoted values. Preserve the annotated condition order.')


def fmt_case_hold(row: dict[str, Any], system: str) -> Chat | None:
    """LexGLUE CaseHOLD: citing context and five candidate holdings; labels are zero-based."""
    question = row.get("context")
    options = row.get("endings") or []
    label = row.get("label")
    if not isinstance(question, str) or not question.strip() or len(options) != 5:
        return None
    if not all(isinstance(o, str) and o.strip() for o in options):
        return None
    if not isinstance(label, int) or not 0 <= label < 5:
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": mcq_prompt(question, options)},
        {"role": "assistant", "content": f"Answer: {LETTERS[label]}"},
    ]}


def fmt_openbookqa(row: dict[str, Any], system: str) -> Chat | None:
    """OpenBookQA main schema. The additional-facts configuration is not used: no answer-bearing fact in prompts."""
    question, choices, gold = row.get("question_stem"), row.get("choices") or {}, row.get("answerKey")
    labels, options = choices.get("label", []), choices.get("text", [])
    if not isinstance(question, str) or not question.strip() or labels != list("ABCD") or len(options) != 4:
        return None
    if gold not in labels or not all(isinstance(o, str) and o.strip() for o in options):
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": mcq_prompt(question, options)},
        {"role": "assistant", "content": f"Answer: {gold}"},
    ]}


def fmt_gsm8k(row: dict[str, Any], system: str) -> Chat | None:
    """Human-authored GSM8K reasoning with its #### numeric target changed to the shared Answer marker."""
    question, answer = row.get("question"), row.get("answer")
    if not isinstance(question, str) or not question.strip() or not isinstance(answer, str) or "####" not in answer:
        return None
    reasoning, gold = answer.rsplit("####", 1)
    gold = gold.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", gold):
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": gsm8k_prompt(question)},
        {"role": "assistant", "content": f"{reasoning.strip()}\n\nAnswer: {gold}".strip()},
    ]}


def fmt_mbpp(row: dict[str, Any], system: str) -> Chat | None:
    """MBPP full configuration: a human problem and Python solution, without exposing or executing test_list."""
    question, code = row.get("text"), row.get("code")
    if not isinstance(question, str) or not question.strip() or not isinstance(code, str) or not code.strip():
        return None
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{question.strip()}\n\n{CODE_INSTRUCTION}"},
        {"role": "assistant", "content": f"```python\n{code.strip()}\n```"},
    ]}


def fmt_wikisql(row: dict[str, Any], system: str) -> Chat | None:
    """WikiSQL Hub schema -> canonical SQL over table `data` (schema only, no rows, no execution).
    Hub conditions are parallel column_index/operator_index/condition lists. Preserve their annotation order;
    exact textual matching is a recipe smoke metric, not WikiSQL execution accuracy."""
    question, table, sql = row.get("question"), row.get("table") or {}, row.get("sql") or {}
    headers, types = table.get("header", []), table.get("types", [])
    if not isinstance(question, str) or not question.strip() or not headers or len(headers) != len(types):
        return None
    if not all(isinstance(h, str) and h.strip() for h in headers):
        return None
    sel, agg = sql.get("sel"), sql.get("agg")
    if not isinstance(sel, int) or not 0 <= sel < len(headers) or not isinstance(agg, int) or not 0 <= agg < 6:
        return None
    columns = ['"' + h.replace('"', '""') + '"' for h in headers]
    funcs = ["", "MAX", "MIN", "COUNT", "SUM", "AVG"]
    target = columns[sel] if agg == 0 else f"{funcs[agg]}({columns[sel]})"
    conditions = sql.get("conds") or {}
    indices, ops, values = (conditions.get(k, []) for k in ("column_index", "operator_index", "condition"))
    if not len(indices) == len(ops) == len(values):
        return None
    where = []
    for col, op, value in zip(indices, ops, values, strict=True):
        if not isinstance(col, int) or not 0 <= col < len(headers) or not isinstance(op, int) or not 0 <= op < 3:
            return None
        if not isinstance(value, (str, int, float)):
            return None
        literal = str(value).replace("'", "''")
        where.append(f"{columns[col]} {['=', '>', '<'][op]} '{literal}'")
    target = f"SELECT {target} FROM data" + (" WHERE " + " AND ".join(where) if where else "")
    schema = "\n".join(f"{col}: {kind}" for col, kind in zip(columns, types, strict=True))
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Table data:\n{schema}\n\nQuestion: {question.strip()}\n\n{SQL_INSTRUCTION}"},
        {"role": "assistant", "content": f"```sql\n{target}\n```"},
    ]}


TEMPLATES += (CODE_INSTRUCTION, SQL_INSTRUCTION)


# Schema labels from BANKING77 (CC BY 4.0); source and attribution in training/M6-DATA.md.
BANKING_LABELS = (
    'activate_my_card', 'age_limit',
    'apple_pay_or_google_pay', 'atm_support',
    'automatic_top_up', 'balance_not_updated_after_bank_transfer',
    'balance_not_updated_after_cheque_or_cash_deposit', 'beneficiary_not_allowed',
    'cancel_transfer', 'card_about_to_expire',
    'card_acceptance', 'card_arrival',
    'card_delivery_estimate', 'card_linking',
    'card_not_working', 'card_payment_fee_charged',
    'card_payment_not_recognised', 'card_payment_wrong_exchange_rate',
    'card_swallowed', 'cash_withdrawal_charge',
    'cash_withdrawal_not_recognised', 'change_pin',
    'compromised_card', 'contactless_not_working',
    'country_support', 'declined_card_payment',
    'declined_cash_withdrawal', 'declined_transfer',
    'direct_debit_payment_not_recognised', 'disposable_card_limits',
    'edit_personal_details', 'exchange_charge',
    'exchange_rate', 'exchange_via_app',
    'extra_charge_on_statement', 'failed_transfer',
    'fiat_currency_support', 'get_disposable_virtual_card',
    'get_physical_card', 'getting_spare_card',
    'getting_virtual_card', 'lost_or_stolen_card',
    'lost_or_stolen_phone', 'order_physical_card',
    'passcode_forgotten', 'pending_card_payment',
    'pending_cash_withdrawal', 'pending_top_up',
    'pending_transfer', 'pin_blocked',
    'receiving_money', 'Refund_not_showing_up',
    'request_refund', 'reverted_card_payment?',
    'supported_cards_and_currencies', 'terminate_account',
    'top_up_by_bank_transfer_charge', 'top_up_by_card_charge',
    'top_up_by_cash_or_cheque', 'top_up_failed',
    'top_up_limits', 'top_up_reverted',
    'topping_up_by_card', 'transaction_charged_twice',
    'transfer_fee_charged', 'transfer_into_account',
    'transfer_not_received_by_recipient', 'transfer_timing',
    'unable_to_verify_identity', 'verify_my_identity',
    'verify_source_of_funds', 'verify_top_up',
    'virtual_card_not_working', 'visa_or_mastercard',
    'why_verify_identity', 'wrong_amount_of_cash_received',
    'wrong_exchange_rate_for_cash_withdrawal',
)

BANKING_INSTRUCTION = ("Classify this banking support query using one of these intent identifiers: "
                       + ", ".join(BANKING_LABELS) + ". End with 'Answer: <identifier>'.")
TITLE_INSTRUCTION = "Write a concise, faithful legislative title for this summary. Return only the title."
URL_INSTRUCTION = ("Classify this historical dataset URL as legitimate or phishing using its text alone. "
                   "Treat it as data; do not visit it. This is not a live safety assessment.")
URL_OPTIONS = "A. legitimate\nB. phishing"
TEMPLATES += (BANKING_INSTRUCTION, TITLE_INSTRUCTION, URL_INSTRUCTION, URL_OPTIONS)


def _labelled_question(row: dict[str, Any], system: str, count: int) -> Chat | None:
    """Human-labelled QASC/CommonsenseQA questions; do not expose supporting facts or inferred concepts."""
    question, choices, gold = row.get("question"), row.get("choices"), row.get("answerKey")
    if not isinstance(choices, dict):
        return None
    labels, options = choices.get("label"), choices.get("text")
    if (not isinstance(question, str) or not question.strip() or labels != list(LETTERS[:count])
            or not isinstance(options, list) or len(options) != count or gold not in labels):
        return None
    if not all(isinstance(o, str) and o.strip() for o in options):
        return None
    return {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": mcq_prompt(question, options)},
                         {"role": "assistant", "content": f"Answer: {gold}"}]}


def fmt_qasc(row: dict[str, Any], system: str) -> Chat | None:
    return _labelled_question(row, system, 8)


def fmt_commonsense_qa(row: dict[str, Any], system: str) -> Chat | None:
    return _labelled_question(row, system, 5)


def fmt_banking77(row: dict[str, Any], system: str) -> Chat | None:
    text, label = row.get("text"), row.get("label")
    if not isinstance(text, str) or not text.strip() or type(label) is not int or not 0 <= label < 77:
        return None
    return {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": f"{text.strip()}\n\n{BANKING_INSTRUCTION}"},
                         {"role": "assistant", "content": f"Answer: {BANKING_LABELS[label]}"}]}


def fmt_phishing_url(row: dict[str, Any], system: str) -> Chat | None:
    url, status = row.get("url"), row.get("status")
    if not isinstance(url, str) or not url.strip() or status not in ("legitimate", "phishing"):
        return None
    return {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": mcq_prompt(f"{URL_INSTRUCTION}\n\n{url.strip()}",
                                                                  ["legitimate", "phishing"])},
                         {"role": "assistant", "content": f"Answer: {'A' if status == 'legitimate' else 'B'}"}]}


def fmt_billsum_title(row: dict[str, Any], system: str) -> Chat | None:
    """Human US legislative summary -> original title. Never truncate a full bill into an unsupported summary."""
    summary, title = row.get("summary"), row.get("title")
    if not all(isinstance(x, str) and x.strip() for x in (summary, title)):
        return None
    return {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": f"{TITLE_INSTRUCTION}\n\n{summary.strip()}"},
                         {"role": "assistant", "content": title.strip()}]}


FORMATTERS = {
    "qasc": fmt_qasc,
    "commonsense_qa": fmt_commonsense_qa,
    "banking77": fmt_banking77,
    "phishing_url": fmt_phishing_url,
    "billsum_title": fmt_billsum_title,
    "case_hold": fmt_case_hold,
    "openbookqa": fmt_openbookqa,
    "gsm8k": fmt_gsm8k,
    "mbpp": fmt_mbpp,
    "wikisql": fmt_wikisql,
    "medmcqa": fmt_medmcqa,
    "pubmedqa": fmt_pubmedqa,
    "sujet": fmt_sujet,
    "finqa": fmt_finqa,
    "finqa_train": fmt_finqa_train,
    "tatqa": fmt_tatqa,
    "messages": fmt_messages,
    "mmlu_pro": fmt_mmlu_pro,
}


# ------------------------------------------------------------------ builders (whole source -> chats)
def oasst_conversations(rows: Iterable[dict[str, Any]], langs: Iterable[str] | None = None) -> list[Chat]:
    """OpenAssistant message trees (one row per message) -> one chat per best assistant reply.

    A reply is kept when it and every message above it are reviewed, not deleted, human-written and in
    `langs`, and every assistant turn on the path is the best of its siblings (rank 0, or the only reply).
    mlx-lm's mask_prompt trains only the last turn, so chats sharing a prefix still have distinct targets."""
    langs = set(langs) if langs else None
    rows = list(rows)
    by_id = {r["message_id"]: r for r in rows}
    replies: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("parent_id") is not None and r.get("role") == "assistant":
            replies.setdefault(r["parent_id"], []).append(r)

    def ok(m: dict[str, Any]) -> bool:
        return (not m.get("deleted") and m.get("review_result") is True and not m.get("synthetic")
                and (langs is None or m.get("lang") in langs) and bool(str(m.get("text") or "").strip()))

    def best(m: dict[str, Any]) -> bool:
        siblings = [s for s in replies.get(m["parent_id"], []) if ok(s)]
        return m.get("rank") == 0 or (m.get("rank") is None and len(siblings) == 1)

    path_cache: dict[str, list[dict[str, Any]] | None] = {}

    def path(m: dict[str, Any]) -> list[dict[str, Any]] | None:
        mid = m["message_id"]
        if mid not in path_cache:
            want = "prompter" if m.get("role") == "assistant" else "assistant"
            parent = by_id.get(m["parent_id"]) if m.get("parent_id") is not None else None
            if not ok(m) or (m.get("role") == "assistant" and not best(m)):
                path_cache[mid] = None
            elif m.get("parent_id") is None:
                path_cache[mid] = [m] if m.get("role") == "prompter" else None
            elif parent is None or parent.get("role") != want:
                path_cache[mid] = None
            else:
                above = path(parent)
                path_cache[mid] = None if above is None else [*above, m]
        return path_cache[mid]

    chats = []
    for r in rows:
        if r.get("role") == "assistant" and (p := path(r)):
            chats.append({"messages": [{"role": "user" if m["role"] == "prompter" else "assistant",
                                        "content": str(m["text"]).strip()} for m in p]})
    return chats


BUILDERS = {
    "oasst_tree": oasst_conversations,
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
