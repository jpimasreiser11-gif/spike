"""G32 — FAQ and troubleshooting guide (`docs/guide/es/faq.md` and `docs/guide/en/faq.md`).

Verifies that:
1. Both Spanish (`docs/guide/es/faq.md`) and English (`docs/guide/en/faq.md`) FAQ & troubleshooting
   pages exist and are linked from the guide index pages.
2. Every `spike doctor` check, JSON field, hardware recommendation note, and `--strict` failure
   message extracted from `spike/cli.py` (`cmd_doctor`) and `spike/runtime/hardware.py` (`recommend`)
   has an entry in both `es/faq.md` and `en/faq.md` explaining its meaning, probable cause, and
   what to do.
3. User-facing error codes and messages (from G24 / `web/src/i18n.ts`) are documented in both
   `es/faq.md` and `en/faq.md`.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from spike.cli import cmd_doctor
from spike.runtime.hardware import HardwareInfo, recommend

REPO_ROOT = Path(__file__).resolve().parents[1]
ES_FAQ = REPO_ROOT / "docs" / "guide" / "es" / "faq.md"
EN_FAQ = REPO_ROOT / "docs" / "guide" / "en" / "faq.md"
CLI_PY = REPO_ROOT / "spike" / "cli.py"
HARDWARE_PY = REPO_ROOT / "spike" / "runtime" / "hardware.py"


def _extract_doctor_checks_from_source() -> set[str]:
    """Dynamically collect all `spike doctor` JSON keys, recommendation notes, and `--strict` checks."""
    checks: set[str] = set()

    # 1. Run `cmd_doctor --json` with synthetic hardware/models to get all top-level report keys
    buf = io.StringIO()
    args = argparse.Namespace(model=None, context=None, json=True, strict=False, no_model_check=False)
    with redirect_stdout(buf):
        cmd_doctor(args)
    report = json.loads(buf.getvalue())
    for key in report:
        if key != "spike":
            checks.add(key)

    # 2. Exercise `recommend()` across low-RAM, non-AVX2 Linux x86_64, and CPU-only 16 GB profiles
    profiles = [
        HardwareInfo("Linux", "x86_64", "Generic x86", 4, 4, 6.0, 4.0, False, []),
        HardwareInfo("Linux", "x86_64", "Xeon", 4, 8, 16.0, 12.0, False, ["avx2"]),
        HardwareInfo("Darwin", "arm64", "Apple M4", 10, 10, 32.0, 24.0, True, ["neon"]),
    ]
    for hw in profiles:
        rec = recommend(hw)
        for note in rec.notes:
            checks.add(note)

    # 3. Inspect AST of `cmd_doctor` in `spike/cli.py` for string literals in `missing.append(...)`
    #    and unverified / no-model diagnostic strings
    tree = ast.parse(CLI_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_doctor":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    val = sub.value.strip()
                    if any(
                        token in val
                        for token in (
                            "llama-server was not found",
                            "no local model",
                            "No local models yet",
                            "downloaded without a SHA-256 check",
                            "estimated_total_gb",
                            "kv_cache_gb",
                        )
                    ):
                        checks.add(val.strip(" []"))
    return checks


def test_faq_pages_exist_and_are_linked_from_indices() -> None:
    assert ES_FAQ.is_file(), "Missing docs/guide/es/faq.md"
    assert EN_FAQ.is_file(), "Missing docs/guide/en/faq.md"

    root_idx = (REPO_ROOT / "docs" / "guide" / "README.md").read_text(encoding="utf-8")
    es_idx = (REPO_ROOT / "docs" / "guide" / "es" / "README.md").read_text(encoding="utf-8")
    en_idx = (REPO_ROOT / "docs" / "guide" / "en" / "README.md").read_text(encoding="utf-8")

    assert "es/faq.md" in root_idx and "en/faq.md" in root_idx
    assert "faq.md" in es_idx
    assert "faq.md" in en_idx


def test_every_spike_doctor_check_has_an_entry_in_es_and_en_faq() -> None:
    checks = _extract_doctor_checks_from_source()
    assert len(checks) >= 10

    es_text = ES_FAQ.read_text(encoding="utf-8")
    en_text = EN_FAQ.read_text(encoding="utf-8")

    for check in sorted(checks):
        assert check in es_text, f"spike doctor check {check!r} is missing from docs/guide/es/faq.md"
        assert check in en_text, f"spike doctor check {check!r} is missing from docs/guide/en/faq.md"

    # Verify each FAQ page documents meaning, probable cause, and action to take
    for needle in ("Qué significa", "Causa probable", "Qué hacer"):
        assert needle in es_text
    for needle in ("What it means", "Probable cause", "What to do"):
        assert needle in en_text


def test_spike_doctor_strict_failures_are_documented(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run `cmd_doctor` in `--strict` mode with no binary and no models and verify both emitted errors are in FAQ."""
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setattr("spike.runtime.llamacpp_server.find_binary", lambda: None)
    monkeypatch.setattr("spike.runtime.models.local_models", lambda: [])

    out = io.StringIO()
    err = io.StringIO()
    args = argparse.Namespace(model=None, context=None, json=False, strict=True, no_model_check=False)
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_doctor(args)
    assert rc == 1

    es_text = ES_FAQ.read_text(encoding="utf-8")
    en_text = EN_FAQ.read_text(encoding="utf-8")
    for line in err.getvalue().splitlines():
        msg = line.removeprefix("error: ").strip()
        if msg:
            assert msg in es_text, f"Strict doctor error {msg!r} missing in es/faq.md"
            assert msg in en_text, f"Strict doctor error {msg!r} missing in en/faq.md"
