"""G44: every specialist in the catalog is complete and its adapter status matches its approval receipt.

Each built-in specialist needs a training recipe (or a documented reason), evaluation and selection suites, an avatar,
its name in the Spanish and English guides, router keywords, a row in docs/SPECIALISTS.md and tools that exist. A gap
that is known and cannot be fixed without new hand-written evaluation data is pinned in KNOWN_GAPS with its reason, so
the test fails (and the entry must go) the day it is closed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from spike.specialists.catalog import load_catalog
from spike.specialists.status import shipped_record

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog()
SPECS = list(CATALOG.specialists.values())
SUITES = yaml.safe_load((ROOT / "evals" / "suites.yaml").read_text(encoding="utf-8"))["suites"]
SPECIALISTS_MD = (ROOT / "docs" / "SPECIALISTS.md").read_text(encoding="utf-8")

# Pairwise-judged specialists need held-out prompts (evals/data/<id>_eval.jsonl) before their adapter can be accepted.
KNOWN_GAPS = {
    "writing": "writing-pairwise has no held-out prompts yet: evals/data/writing_eval.jsonl must be written by hand "
               "before Writing can be trained and accepted (M8)",
}


def recipe(spec_id: str) -> dict:
    return yaml.safe_load((ROOT / "training" / "configs" / f"{spec_id}.yaml").read_text(encoding="utf-8"))


def short_name(spec) -> str:
    return spec.name.removeprefix("Spike ").strip()


def doc_row(spec) -> str:
    rows = [line for line in SPECIALISTS_MD.splitlines() if line.startswith(f"| {spec.name} |")]
    assert len(rows) == 1, f"{spec.id}: expected one row for {spec.name} in docs/SPECIALISTS.md, found {len(rows)}"
    return rows[0]


def test_the_catalog_has_the_thirteen_built_in_specialists():
    assert len(SPECS) == 13 and CATALOG.core.id == "core"


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_every_specialist_has_a_recipe_with_the_shared_regression_rule(spec):
    rule = recipe(spec.id)
    assert rule["specialist"] == spec.id
    assert rule["acceptance"]["regression"] == {"suite": "general", "max_drop_points": 1.5}
    assert "suite" in rule["acceptance"]["primary"]


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_every_primary_suite_can_be_measured_and_selected_on(spec):
    suite = recipe(spec.id)["acceptance"]["primary"]["suite"]
    if suite.endswith("-pairwise"):  # judged by evals/pairwise.py on held-out prompts, not by a suites.yaml entry
        prompts = ROOT / "evals" / "data" / f"{spec.id}_eval.jsonl"
        if spec.id in KNOWN_GAPS:
            assert not prompts.exists(), f"{spec.id}: the gap is closed, remove it from KNOWN_GAPS"
            return
        assert prompts.exists() and prompts.stat().st_size > 0
        return
    assert suite in SUITES and f"{suite}-select" in SUITES
    assert "general" in SUITES and "general-select" in SUITES


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_every_specialist_has_its_avatar(spec):
    assert (ROOT / "web" / "public" / "specialists" / f"{spec.id}.png").is_file()


def test_the_app_draws_an_avatar_for_exactly_the_catalog():
    source = (ROOT / "web" / "src" / "components" / "SpecMark.tsx").read_text(encoding="utf-8")
    listed = set(re.findall(r'"([a-z]+)"', re.search(r"AVATARS = new Set\(\[(.*?)\]\)", source, re.S).group(1)))
    assert listed == set(CATALOG.specialists)


@pytest.mark.parametrize("lang", ["es", "en"])
def test_both_guides_name_every_specialist(lang):
    guide = (ROOT / "docs" / "guide" / lang / "specialists.md").read_text(encoding="utf-8")
    assert [s.id for s in SPECS if f"`{short_name(s)}`" not in guide] == []
    assert f"{len(SPECS)} " in guide


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_every_specialist_but_core_has_router_keywords(spec):
    assert bool(spec.keywords) is (spec.id != "core")


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_every_specialist_has_one_row_in_the_specialists_doc(spec):
    doc_row(spec)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_the_adapter_name_follows_the_specialist(spec):
    if spec.id == "core":
        assert spec.adapter is None and spec.adapter_status == "none"
    else:
        assert spec.adapter == f"spike-{spec.id}"


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_evaluated_means_a_shipped_acceptance_receipt_and_nothing_else_does(spec):
    record = shipped_record(spec)
    assert (spec.adapter_status == "evaluated") is (record is not None)
    if record is not None:
        assert re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) and record["bytes"] > 0
        assert "accepted" in doc_row(spec)


def test_a_receipt_on_disk_always_names_its_own_specialist():
    for path in (ROOT / "spike" / "specialists" / "acceptance").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["specialist"] == path.stem and data["specialist"] in CATALOG.specialists


def test_every_tool_a_specialist_lists_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    from spike.server.state import AppState

    known = set(AppState().tools.names())
    assert {s.id: missing for s in SPECS if (missing := sorted(set(s.tools) - known))} == {}
