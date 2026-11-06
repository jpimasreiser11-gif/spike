"""Tests for specialist catalog status vs real active mode, approval receipts, and active context layers (G4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.evolution.adapters import sha256
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.status import ACCEPTANCE_DIR
from tests.helpers import ScriptedProvider


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id, adapters=cfg.kind == "llamacpp"))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    return TestClient(create_app(state)), state, scripts


def test_medicine_accepted_only_with_catalog_and_receipt(env, tmp_path: Path):
    client, state, _ = env
    specs = {s["id"]: s for s in client.get("/api/specialists").json()}

    med = specs["medicine"]
    assert med["adapter"] == "spike-medicine"
    assert med["adapter_status"] == "evaluated"
    assert med["adapter_accepted"] is True
    assert any("+35.07" in r for r in med["adapter_reasons"])
    assert any("-0.62" in r for r in med["adapter_reasons"])
    assert med["active_mode"] == "instruction_profile"

    code = specs["code"]
    assert code["adapter"] == "spike-code"
    assert code["adapter_status"] == "planned"
    assert code["adapter_accepted"] is False
    assert code["adapter_reasons"] == []
    assert code["active_mode"] == "instruction_profile"


def test_filename_or_catalog_alone_never_marks_adapter_accepted(env, tmp_path: Path):
    client, state, _ = env
    adapters_dir = state.adapters_path()
    adapters_dir.mkdir(parents=True, exist_ok=True)
    # 1. Placing spike-code.gguf and spike-medicine.gguf on disk must never imply acceptance
    (adapters_dir / "spike-code.gguf").write_bytes(b"GGUF-fake")
    (adapters_dir / "spike-medicine.gguf").write_bytes(b"GGUF-fake")

    # Point runs_dir to an empty directory so no sweep receipt exists on disk
    empty_runs = tmp_path / "empty_runs"
    empty_runs.mkdir()
    state.runs_dir = empty_runs
    state.acceptance_dir = empty_runs   # and no record shipped with SPIKE either

    specs = {s["id"]: s for s in client.get("/api/specialists").json()}
    assert specs["medicine"]["adapter_file_present"] is True
    assert specs["medicine"]["adapter_status"] == "evaluated"
    # Even though adapter_status == "evaluated" and spike-medicine.gguf exists, there is no approval receipt!
    assert specs["medicine"]["adapter_accepted"] is False
    assert specs["medicine"]["adapter_reasons"] == []

    # 2. A valid receipt on disk for a specialist whose catalog status is NOT "evaluated" must not be accepted
    code_sweep = empty_runs / "code" / "sweep"
    code_sweep.mkdir(parents=True)
    (code_sweep / "summary.json").write_text(
        json.dumps({
            "specialist": "code",
            "chosen": "spike-code-it1000-s1",
            "final": {"accepted": True, "reasons": ["code: +5.00 pts", "general: -0.10 pts"]},
        }),
        encoding="utf-8",
    )
    specs = {s["id"]: s for s in client.get("/api/specialists").json()}
    assert specs["code"]["adapter_status"] == "planned"
    assert specs["code"]["adapter_file_present"] is True
    assert specs["code"]["adapter_accepted"] is False
    assert specs["code"]["adapter_reasons"] == []

    # 3. A receipt with accepted=False when catalog is "evaluated" must not be accepted
    med_sweep = empty_runs / "medicine" / "sweep"
    med_sweep.mkdir(parents=True)
    (med_sweep / "summary.json").write_text(
        json.dumps({
            "specialist": "medicine",
            "chosen": "spike-medicine-it1600-s1",
            "final": {"accepted": False, "reasons": ["general: -11.75 pts (max drop 1.5)"]},
        }),
        encoding="utf-8",
    )
    specs = {s["id"]: s for s in client.get("/api/specialists").json()}
    assert specs["medicine"]["adapter_accepted"] is False
    assert specs["medicine"]["adapter_reasons"] == []

    # 4. EvolutionStore active adapter receipt marks an evaluated specialist as accepted
    state.evolution.store.add_version(
        "adapter:medicine",
        {"file": str(adapters_dir / "spike-medicine.gguf"), "sha256": "abc"},
        {"variant": "spike-medicine-it13270-s0.5", "accepted": True,
         "reasons": ["medicine: +35.07 pts", "general: -0.62 pts"]},
        "installed accepted adapter",
    )
    specs = {s["id"]: s for s in client.get("/api/specialists").json()}
    assert specs["medicine"]["adapter_accepted"] is True
    assert specs["medicine"]["adapter_reasons"] == ["medicine: +35.07 pts", "general: -0.62 pts"]


def test_active_mode_and_context_layers_reflect_live_state(env):
    client, state, _ = env
    # Default: instruction_profile, only base_instructions active
    specs = {s["id"]: s for s in client.get("/api/specialists").json()}
    med = specs["medicine"]
    assert med["active_mode"] == "instruction_profile"
    assert med["layers"] == {
        "base_instructions": True,
        "user_instructions": False,
        "learned_instructions": False,
        "knowledge_count": 0,
    }

    # Add user instructions, learned prompt, and specialist knowledge document
    client.put("/api/settings", json={"specialist_instructions": {"medicine": "Cita siempre guías clínicas."}})
    state.evolution.store.add_version(
        "prompt:medicine",
        {"instructions": ["Resume hallazgos clave al final."], "skills": {}},
        {"passed": 3},
        "learned prompt",
    )
    r = client.post(
        "/api/specialist-documents",
        json={"specialist": "medicine", "filename": "protocolo.md", "text": "Protocolo de triaje."},
    )
    assert r.status_code == 200

    # Mark spike-medicine as loaded on spike-local (which supports adapters)
    state.installed_adapters["spike-local"] = {"spike-medicine"}

    specs = {s["id"]: s for s in client.get("/api/specialists").json()}
    med = specs["medicine"]
    assert med["active_provider"] == "spike-local"
    assert med["provider_supports_adapters"] is True
    assert med["loaded_on_providers"] == ["spike-local"]
    assert med["active_mode"] == "adapter_loaded"
    assert med["layers"] == {
        "base_instructions": True,
        "user_instructions": True,
        "learned_instructions": True,
        "knowledge_count": 1,
    }

    # Binding medicine to a remote provider without adapter support switches active_mode back to instruction_profile
    client.post("/api/providers", json={"preset": "deepseek", "api_key": "sk-test", "model": "deepseek-chat"})
    client.put("/api/settings", json={"specialist_bindings": {"medicine": {"provider_id": "deepseek"}}})
    specs = {s["id"]: s for s in client.get("/api/specialists").json()}
    med = specs["medicine"]
    assert med["active_provider"] == "deepseek"
    assert med["provider_supports_adapters"] is False
    assert med["active_mode"] == "instruction_profile"


ROOT = Path(__file__).resolve().parents[1]


def test_the_shipped_medicine_record_matches_the_training_records():
    shipped = json.loads((ACCEPTANCE_DIR / "medicine.json").read_text(encoding="utf-8"))
    final = ROOT / "training" / "runs" / "medicine" / "sweep" / "final"
    adapter = json.loads((final / "adapter.json").read_text(encoding="utf-8"))
    summary = json.loads((final / "summary.json").read_text(encoding="utf-8"))
    verdict = summary["acceptance"][adapter["evaluated_as"]]
    assert shipped["accepted"] is True and verdict["accepted"] is True
    assert shipped["reasons"] == verdict["reasons"]
    assert (shipped["sha256"], shipped["bytes"], shipped["file"]) == (adapter["sha256"], adapter["bytes"], adapter["file"])
    assert shipped["evidence"] == (final / "summary.json").relative_to(ROOT).as_posix()


def test_an_installed_package_without_training_runs_still_has_the_receipt(env, tmp_path: Path):
    client, state, _ = env
    state.runs_dir = tmp_path / "no-runs"   # a wheel or the desktop app ships no training/runs
    med = {s["id"]: s for s in client.get("/api/specialists").json()}["medicine"]
    assert med["adapter_accepted"] is True and any("+35.07" in r for r in med["adapter_reasons"])
    assert med["adapter_file_present"] is False and med["adapter_file_check"] is None


def test_the_installed_file_is_checked_against_the_accepted_hash(env, tmp_path: Path):
    client, state, _ = env
    adapters_dir = state.adapters_path()
    adapters_dir.mkdir(parents=True, exist_ok=True)
    installed = adapters_dir / "spike-medicine.gguf"
    installed.write_bytes(b"GGUF round 1, the rejected adapter")

    def check() -> str | None:
        return {s["id"]: s for s in client.get("/api/specialists").json()}["medicine"]["adapter_file_check"]

    assert check() == "different"   # the shipped record's hash is the accepted file's, not this one

    records = tmp_path / "records"
    records.mkdir()
    state.acceptance_dir = records
    record = {"specialist": "medicine", "accepted": True, "reasons": ["medicine: +35.07 pts"]}
    (records / "medicine.json").write_text(json.dumps(record), encoding="utf-8")
    assert check() == "unverified"   # accepted, but no hash to compare with

    (records / "medicine.json").write_text(json.dumps({**record, "sha256": sha256(installed)}), encoding="utf-8")
    assert check() == "verified"

    installed.write_bytes(b"GGUF replaced by hand afterwards")
    assert check() == "different"   # the cache follows the file, not its name

    state.evolution.store.add_version("adapter:medicine", {"file": str(installed), "sha256": sha256(installed)},
                                      {"accepted": True, "reasons": ["medicine: +2.0 pts"]}, "a personal retrain")
    assert check() == "verified"    # what `spike adapters install` accepted and recorded
