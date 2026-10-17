"""Evolution in the app: records what the user's own use teaches (corrections, route corrections, failures),
turns it into eval candidates, learns the router behind its gate and keeps every version so it can be undone.
Temporary chats are never recorded, and nothing here is sent anywhere."""

from __future__ import annotations

import platform
import re
from typing import Any

from spike import __version__
from spike.evolution import candidates as cand
from spike.evolution.router_learning import apply_overlay, evaluate, gate, learn_overlay, load_labeled
from spike.evolution.store import EvolutionStore
from spike.specialists.catalog import Catalog

TOOL_CRASH = re.compile(r"^error: [A-Z]\w*(Error|Exception)\b")
MAX_TEXT = 4000
ROUTER = "router"


def _clip(text: str | None, limit: int = MAX_TEXT) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def _specialists(meta: dict[str, Any]) -> list[str]:
    return [s["id"] for s in (meta.get("route") or {}).get("specialists") or [] if s.get("id")]


class Evolution:
    def __init__(self, store: EvolutionStore):
        self.store = store

    # ------------------------------------------------------------------ E1 corrections
    def record_correction(self, thread: list[dict[str, Any]], correction_id: str, rule: str,
                          memory_id: str | None) -> dict[str, Any] | None:
        """A rule the user saved from a correction: the question, the answer it corrected and the correction, kept
        as an example and proposed as an eval candidate."""
        at = next(i for i, m in enumerate(thread) if m["id"] == correction_id)
        wrong = next((m for m in reversed(thread[:at]) if m["role"] == "assistant"), None)
        if wrong is None:
            return None
        before = thread[:thread.index(wrong)]
        question = next((m for m in reversed(before) if m["role"] == "user"), None)
        if question is None:
            return None
        existing = self.store.find("correction", message=correction_id)
        data = {"conversation": thread[at]["conversation_id"], "message": correction_id,
                "question": _clip(question["content"]), "wrong_answer": _clip(wrong["content"]),
                "correction": _clip(thread[at]["content"]), "rule": rule, "memory": memory_id,
                "specialists": _specialists(wrong["meta"])}
        if existing:
            return self.store.update(existing["id"], **data)
        item = self.store.add("correction", data, status="saved")
        self.propose(item)
        return item

    def forget_correction(self, correction_id: str) -> None:
        """Undo of a saved rule: its example goes, and so does its candidate if the user had not decided on it."""
        item = self.store.find("correction", message=correction_id)
        if item is None:
            return
        for c in self.store.items("candidate", "proposed"):
            if c.get("source") == item["id"]:
                self.store.delete(c["id"])
        self.store.delete(item["id"])

    # ------------------------------------------------------------------ E2 route corrections
    def record_route(self, query: str, routed: list[str], specialist: str, conversation: str,
                     message: str) -> dict[str, Any] | None:
        """The user retried an answer with another specialist than the router picked."""
        if not routed or routed[0] == specialist:
            return None
        data = {"query": _clip(query, 2000), "routed": routed, "specialist": specialist,
                "conversation": conversation, "message": message}
        existing = self.store.find("route", message=message)
        return self.store.update(existing["id"], status="new", **data) if existing else self.store.add("route", data)

    def route_corrections(self) -> list[dict[str, Any]]:
        return [i for i in self.store.items("route") if i["status"] != "ignored"]

    def router_overlay(self) -> dict[str, dict[str, float]]:
        active = self.store.active(ROUTER)
        return active["data"].get("overlay", {}) if active else {}

    def learn_router(self, base: Catalog) -> dict[str, Any]:
        """Learn keywords from every route correction; the new overlay becomes active only if it passes the gate.
        Every attempt is kept in the history, accepted or not."""
        corrections = [{"query": i["query"], "specialist": i["specialist"], "created": i["created"]}
                       for i in self.route_corrections()]
        overlay = learn_overlay(base, corrections, load_labeled("dev")) if corrections else {}
        report = gate(base, overlay, corrections)
        report["learned_from"] = len(corrections)
        last = next(iter(self.store.versions(ROUTER)), None)
        if last and last["data"].get("overlay") == overlay and last["active"] == report["accepted"]:
            return {**report, "version": last["id"], "unchanged": True}
        if not overlay and not self.store.active(ROUTER):
            return {**report, "version": None}
        reason = (f"learned from {len(corrections)} route corrections" if report["accepted"]
                  else "rejected: " + "; ".join(report["reasons"]))
        version = self.store.add_version(ROUTER, {"overlay": overlay, "items": [i["id"] for i in self.route_corrections()]},
                                         report, reason, activate=report["accepted"])
        return {**report, "version": version["id"]}

    def router_status(self, base: Catalog) -> dict[str, Any]:
        active = self.store.active(ROUTER)
        return {"active": active, "pending": len(self.store.items("route", "new")),
                "built_in": {s: evaluate(base, load_labeled(s)) for s in ("dev", "test")},
                **({"current": {s: evaluate(apply_overlay(base, active["data"]["overlay"]), load_labeled(s))
                                for s in ("dev", "test")}} if active else {})}

    # ------------------------------------------------------------------ E3 failures
    def record_failures(self, question: str, meta: dict[str, Any], conversation: str,
                        message: str | None) -> list[dict[str, Any]]:
        """A run that ended in an error, and tools that crashed (not the ones the user denied)."""
        found = []
        context = {"question": _clip(question, 2000), "conversation": conversation, "message": message,
                   "specialists": _specialists(meta), "spike": __version__, "platform": platform.platform(),
                   "cause": "", "fix": "", "verified": False}
        if meta.get("error") and not meta.get("cancelled"):
            found.append({"what": "run", "error": _clip(meta["error"], 1000), **context})
        for ev in meta.get("tools") or []:
            if ev.get("type") == "tool_result" and not ev.get("ok") and TOOL_CRASH.match(ev.get("content") or ""):
                found.append({"what": "tool", "tool": ev.get("name"),
                              "error": _clip((ev["content"] or "").splitlines()[0], 1000), **context})
        return [self.store.add("failure", f, status="open") for f in found]

    def update_failure(self, item_id: str, **fields: Any) -> dict[str, Any]:
        item = self.store.get(item_id)
        if item is None or item["kind"] != "failure":
            raise LookupError("failure not found")
        allowed = {k: v for k, v in fields.items() if k in ("cause", "fix", "verified") and v is not None}
        status = "fixed" if allowed.get("verified", item.get("verified")) else "open"
        item = self.store.update(item_id, status=status, **allowed)
        if status == "fixed" and not any(c.get("source") == item_id for c in self.store.items("candidate")):
            self.propose(item)  # a fixed failure is worth a question that checks it stays fixed
        return item  # type: ignore[return-value]

    @staticmethod
    def issue_markdown(item: dict[str, Any]) -> str:
        """The failure as a bug report the user can paste where they choose. It leaves out the chat itself."""
        lines = [f"### {'Tool ' + item['tool'] if item.get('what') == 'tool' else 'Run'} failed: "
                 f"{item['error'].splitlines()[0][:120]}", "",
                 f"- SPIKE {item.get('spike')} on {item.get('platform')}",
                 f"- Specialists: {', '.join(item.get('specialists') or []) or 'none recorded'}", "",
                 "**Error**", "", "```", item["error"], "```", ""]
        if item.get("cause"):
            lines += ["**Cause**", "", item["cause"], ""]
        if item.get("fix"):
            lines += [f"**Fix{' (verified)' if item.get('verified') else ''}**", "", item["fix"], ""]
        lines += ["_The question that failed is not included; add it if you want to share it._"]
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ E4 candidates
    def propose(self, item: dict[str, Any]) -> dict[str, Any]:
        data = cand.from_correction(item) if item["kind"] == "correction" else cand.from_failure(item)
        data["contamination"] = cand.contamination(data["question"], cand.references(self.store.items("candidate", "accepted")))
        return self.store.add("candidate", data, status="proposed")

    def review_candidate(self, item_id: str, status: str | None = None, question: str | None = None,
                         checks: dict[str, list[str]] | None = None) -> dict[str, Any]:
        item = self.store.get(item_id)
        if item is None or item["kind"] != "candidate":
            raise LookupError("candidate not found")
        fields: dict[str, Any] = {}
        if question is not None:
            if not question.strip():
                raise ValueError("the question cannot be empty")
            fields["question"] = question.strip()
        if checks is not None:
            fields["checks"] = {k: [s.strip() for s in checks.get(k) or [] if s.strip()][:20]
                                for k in ("include", "exclude")}
        if "question" in fields or status == "accepted":
            others = [c for c in self.store.items("candidate", "accepted") if c["id"] != item_id]
            fields["contamination"] = cand.contamination(fields.get("question", item["question"]), cand.references(others))
        if status == "accepted" and fields["contamination"]:
            c = fields["contamination"]
            raise ValueError(f"too close to a question in the {c['with']} ({c['score']:.0%} of its words in a row); "
                             "reword it or reject it")
        if status not in (None, "proposed", "accepted", "rejected"):
            raise ValueError(f"unknown status '{status}'")
        return self.store.update(item_id, status=status, **fields)  # type: ignore[return-value]

    def export(self) -> str:
        return cand.export_jsonl(list(reversed(self.store.items("candidate", "accepted"))))

    # ------------------------------------------------------------------ overview
    def overview(self, base: Catalog) -> dict[str, Any]:
        counts: dict[str, dict[str, int]] = {}
        for it in self.store.items():
            counts.setdefault(it["kind"], {}).setdefault(it["status"], 0)
            counts[it["kind"]][it["status"]] += 1
        return {"counts": counts, "router": self.router_status(base), "versions": self.store.versions()}

