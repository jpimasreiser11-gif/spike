from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _iter_markdown_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return files


def _strip_fenced_code(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def test_all_relative_links_in_docs_and_readme_exist() -> None:
    link_re = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    broken: list[str] = []

    for md_path in _iter_markdown_files():
        text = _strip_fenced_code(md_path.read_text(encoding="utf-8"))
        for match in link_re.finditer(text):
            raw_target = match.group(1).strip()
            if not raw_target or raw_target.startswith(
                ("http://", "https://", "mailto:", "tel:", "data:", "#")
            ):
                continue
            target_path_str = raw_target.split("#", 1)[0].strip()
            if not target_path_str:
                continue
            resolved = (md_path.parent / target_path_str).resolve()
            if not resolved.exists():
                rel_src = md_path.relative_to(ROOT)
                broken.append(f"{rel_src} -> {raw_target}")

    assert not broken, f"Broken relative links found: {broken}"


def test_plan_doc_has_no_stale_statuses_or_counts() -> None:
    plan_text = (ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
    stale_phrases = [
        "none trained yet",
        "first real run (medicine) on the Mac",
        "(today's installers are scripts)",
        "Status: 🟡 tools ready; measurements ⬜",
        "109 Python + 5 web tests",
        "⬜ adapters (none yet)",
    ]
    found = [p for p in stale_phrases if p in plan_text]
    assert not found, f"Stale statements remain in docs/PLAN.md: {found}"
    assert "Medicine" in plan_text or "medicine" in plan_text


def test_readme_has_no_stale_adapter_or_installer_claims() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    stale_phrases = [
        "Today none has a trained adapter that passed its acceptance test",
        "it has no packaged desktop app",
        "46/50 on a held-out set, measured",
    ]
    found = [p for p in stale_phrases if p in readme_text]
    assert not found, f"Stale statements remain in README.md: {found}"


def test_training_doc_reflects_supervised_and_forgetting_runs_on_mac() -> None:
    training_text = (ROOT / "docs" / "TRAINING.md").read_text(encoding="utf-8")
    stale_phrases = [
        "Built and tested with fakes, not run on the Mac",
        "First supervised run on a Mac (not yet done):",
    ]
    found = [p for p in stale_phrases if p in training_text]
    assert not found, f"Stale statements remain in docs/TRAINING.md: {found}"


def test_specialists_doc_reflects_m5_m6_m7_recipes_and_finance_runs() -> None:
    spec_text = (ROOT / "docs" / "SPECIALISTS.md").read_text(encoding="utf-8")
    stale_phrases = [
        "not yet: needs a permissively licensed legal QA corpus",
        "| Spike Code | writing, reviewing, debugging code | no | not yet |",
        "| Spike Education | adapted explanations, study plans, exercises | no | not yet |",
        "| Spike Writing | drafting, editing, summarizing, translating | no | not yet |",
        "| Spike Business | strategy, operations, pricing, startups | no | not yet |",
        "| Spike Security | secure design, vulnerability review, hardening, IR | **yes** | not yet |",
    ]
    found = [p for p in stale_phrases if p in spec_text]
    assert not found, f"Stale statements remain in docs/SPECIALISTS.md: {found}"
    assert "1536" in spec_text
