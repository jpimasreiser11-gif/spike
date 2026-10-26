"""Hybrid escalation: a low-confidence local answer can be put to an external provider for a second opinion.

Nothing here talks to a provider. It decides when an answer is low-confidence, builds what would be sent and
estimates the cost from the provider's own price settings; the call is made only after the user clicks, through the
guarded provider (paid-call permission, monthly limits, and the user's files withheld from a provider they are not
allowed to go to). What is sent: the question, the local answer and the claims SPIKE could not verify; never the
conversation, the memory or the tool results.
"""

from __future__ import annotations

from typing import Any

from spike.core.context import message_tokens
from spike.core.types import Message
from spike.providers.guard import call_cost, redact, withheld_notice

SYSTEM = ("A smaller assistant answered the user's question below, and a program could not verify some of its "
          "claims. Answer the question yourself, concisely and in the user's language. Then, for each claim listed, "
          "say whether you think it is correct, wrong or impossible to tell, with one line of reason. Do not invent "
          "sources or quotes.")
MAX_CLAIMS_SENT = 20


def low_confidence(unchecked: int, verifier_failed: bool, threshold: int) -> dict[str, Any] | None:
    """Why a local answer is low-confidence: at least `threshold` unchecked claims, or a checker that failed (could
    not check, or work it sent back was still wrong); None when it is not."""
    reasons = (["unchecked"] if unchecked >= threshold else []) + (["verifier"] if verifier_failed else [])
    return {"reasons": reasons, "unchecked": unchecked, "threshold": threshold} if reasons else None


def unchecked_claims(trust: dict[str, Any]) -> list[str]:
    return [c["text"] for c in trust.get("claims") or [] if c.get("label") == "unchecked"][:MAX_CLAIMS_SENT]


def build_messages(question: str, answer: str, claims: list[str], private: bool) -> list[Message]:
    """The request for the second opinion. When the answer quotes the user's files (`private`), it and the claims
    are marked as such, so the guard replaces them with a notice for a provider that may not receive files."""
    listed = "\n".join(f"- {c}" for c in claims) or "(none: the program that checks the run could not finish)"
    content = (f"# Question\n{question}\n\n# The answer to check\n{answer}\n\n"
               f"# Claims the program could not verify\n{listed}")
    return [Message(role="system", content=SYSTEM),
            Message(role="user", content=content, private=[answer, *claims] if private else [])]


def estimate(messages: list[Message], limits: dict[str, Any], max_tokens: int, name: str, receives_files: bool
             ) -> dict[str, Any]:
    """Tokens in (of what would really be sent), tokens out at most `max_tokens`, and the cost at the provider's
    price settings (None when it has none)."""
    sent = messages if receives_files else redact(messages, withheld_notice(name))[0]
    tokens_in = sum(message_tokens(m) for m in sent)
    cost = call_cost(limits, tokens_in, max_tokens)
    return {"tokens_in": tokens_in, "tokens_out": max_tokens, "cost": None if cost is None else round(cost, 6)}
