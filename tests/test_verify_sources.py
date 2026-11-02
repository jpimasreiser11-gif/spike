"""training/verify_sources.py: the evidence it records for reviewing unverified sources, without the network."""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

import verify_sources  # noqa: E402

SRC = {"hub": "openai/gsm8k", "config": "main", "split": "train", "license": "mit", "role": "train", "format": "gsm8k",
       "license_status": "unverified"}
ROWS = [{"question": "2+2?", "answer": "Two and two.\n#### 4"}, {"question": "Bad", "answer": "no marker"},
        {"question": "3*3?", "answer": "Nine.\n#### 9"}]


def meta(lic):
    return lambda repo: {"license_hub": lic, "gated": False, "sha": "abc", "last_modified": None, "card": "# card"}


def test_counts_every_row_and_the_ones_the_formatter_accepts():
    out = verify_sources.verify("gsm8k-train", SRC, meta("mit"), lambda src: iter(ROWS))
    assert out["rows"] == 3 and out["rows_formatted"] == 2 and "error" not in out
    assert out["license_gate"] == {"ok": True, "reason": "mit", "matches_registry": True}
    assert out["columns"] == ["answer", "question"] and len(out["examples"]) == 2
    assert out["examples"][0]["messages"][-1]["content"].endswith("Answer: 4")


def test_a_hub_license_off_the_allowlist_or_different_from_the_registry_is_flagged():
    out = verify_sources.verify("gsm8k-train", SRC, meta("cc-by-nc-4.0"), lambda src: iter(ROWS))
    assert out["license_gate"]["ok"] is False and out["license_gate"]["matches_registry"] is False


def test_a_failure_is_recorded_and_keeps_what_was_read():
    def broken(src):
        raise RuntimeError("Dataset scripts are no longer supported")
        yield  # pragma: no cover

    out = verify_sources.verify("gsm8k-train", SRC, meta("mit"), broken)
    assert out["error"].startswith("RuntimeError: Dataset scripts") and out["sha"] == "abc" and "rows" not in out
    assert "error" in verify_sources.verify("x", {"urls": [], "role": "train"})


def test_main_reports_every_unverified_source_and_fails_on_any_error(tmp_path, monkeypatch):
    reg = tmp_path / "datasets.yaml"
    reg.write_text(yaml.safe_dump({"sources": {"gsm8k-train": SRC, "kept": {**SRC, "license_status": None}}}),
                   encoding="utf-8")
    monkeypatch.setattr(verify_sources, "hub_metadata", meta("mit"))
    monkeypatch.setattr(verify_sources, "stream_rows", lambda src: iter(ROWS))
    out = tmp_path / "r.json"
    assert verify_sources.main(["--registry", str(reg), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [s["name"] for s in report["sources"]] == ["gsm8k-train"]
    monkeypatch.setattr(verify_sources, "stream_rows", lambda src: (_ for _ in ()).throw(OSError("offline")))
    assert verify_sources.main(["--registry", str(reg), "--out", str(out)]) == 1


def test_every_unverified_source_in_the_registry_has_a_formatter():
    registry = yaml.safe_load((ROOT / "training" / "datasets.yaml").read_text(encoding="utf-8"))["sources"]
    from spike_train.data import FORMATTERS

    unverified = {n: s for n, s in registry.items() if s.get("license_status") == "unverified"}
    assert unverified and all(s["format"] in FORMATTERS and "hub" in s for s in unverified.values())
