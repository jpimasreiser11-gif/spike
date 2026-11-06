"""Read-only specialist runtime and catalog status for Settings (G4).

Separates the catalog adapter lifecycle (`none`, `planned`, `training`, `trained`, `evaluated`) and its verified
approval receipt from the real execution mode today (`instruction_profile` vs `adapter_loaded` in `llama-server`)
and the active context layers (`base_instructions`, `user_instructions`, `learned_instructions`, `knowledge_count`).
An adapter is reported as `adapter_accepted=True` only when both the catalog (`adapter_status == "evaluated"`) and
an approval receipt confirm acceptance with non-empty reasons — never by filename alone. Receipts, in order: the
active Evolution version (`spike adapters install`), the record shipped with SPIKE (`acceptance/<id>.json`, made from
the training run's records), then `training/runs/<id>/sweep/summary.json` in a source checkout.
`adapter_file_check` says whether the installed `<adapter>.gguf` is the accepted file: its SHA-256 against the active
accepted Evolution version or the shipped record ("verified" / "different"), "unverified" when no hash is known.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spike.evolution.adapters import component
from spike.evolution.adapters import sha256 as file_digest
from spike.evolution.prompts import active as active_learned_prompt
from spike.evolution.store import EvolutionStore
from spike.specialists.catalog import Specialist

if TYPE_CHECKING:
    from spike.server.state import AppState

DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[2] / "training" / "runs"
ACCEPTANCE_DIR = Path(__file__).resolve().parent / "acceptance"
_DIGESTS: dict[tuple[str, int, int], str] = {}   # (path, size, mtime_ns) -> SHA-256: GET /api/specialists rehashes nothing


def _reasons(data: dict) -> list[str]:
    return [str(r) for r in (data.get("reasons") or []) if str(r).strip()]


def shipped_record(spec: Specialist, directory: Path | None = None) -> dict | None:
    """The acceptance record shipped with SPIKE for this specialist, if it is well formed and says accepted."""
    path = (directory if directory is not None else ACCEPTANCE_DIR) / f"{spec.id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("specialist") != spec.id or data.get("accepted") is not True:
        return None
    return data if _reasons(data) else None


def installed_digest(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _DIGESTS:
        _DIGESTS[key] = file_digest(path)
    return _DIGESTS[key]


def adapter_file_check(spec: Specialist, evo: EvolutionStore, path: Path,
                       acceptance_dir: Path | None = None) -> str | None:
    """None without an installed file; else whether it is the accepted one, by SHA-256."""
    if not spec.adapter or not path.is_file():
        return None
    expected = set()
    version = evo.active(component(spec))
    if version and isinstance(version.get("report"), dict) and version["report"].get("accepted") is True:
        expected.add((version.get("data") or {}).get("sha256"))
    record = shipped_record(spec, acceptance_dir)
    if record:
        expected.add(record.get("sha256"))
    expected = {h for h in expected if isinstance(h, str) and len(h) == 64}
    if not expected:
        return "unverified"
    return "verified" if installed_digest(path) in expected else "different"


def approval_receipt(spec: Specialist, evo: EvolutionStore, runs_dir: Path | None = None,
                     acceptance_dir: Path | None = None) -> tuple[bool, list[str]]:
    """Return `(accepted, reasons)` only when `spec.adapter_status == 'evaluated'` and a receipt confirms it."""
    if not spec.adapter or spec.adapter_status != "evaluated":
        return False, []
    version = evo.active(f"adapter:{spec.id}")
    if version and isinstance(version.get("report"), dict):
        report = version["report"]
        if report.get("accepted") is True:
            reasons = [str(r) for r in (report.get("reasons") or []) if str(r).strip()]
            if reasons:
                return True, reasons
    record = shipped_record(spec, acceptance_dir)
    if record:
        return True, _reasons(record)
    root = runs_dir if runs_dir is not None else DEFAULT_RUNS_DIR
    summary_path = root / spec.id / "sweep" / "summary.json"
    if not summary_path.is_file():
        return False, []
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, []
    if not isinstance(data, dict) or data.get("specialist") != spec.id:
        return False, []
    final = data.get("final")
    if isinstance(final, dict) and final.get("accepted") is True:
        reasons = [str(r) for r in (final.get("reasons") or []) if str(r).strip()]
        if reasons:
            return True, reasons
    return False, []


def specialist_status(state: AppState, spec: Specialist) -> dict[str, Any]:
    """Derived read-only status fields added to `Specialist.public()` for `GET /api/specialists`."""
    settings = state.settings()
    runs_dir = getattr(state, "runs_dir", None)
    acceptance_dir = getattr(state, "acceptance_dir", None)
    accepted, reasons = approval_receipt(spec, state.evolution.store, runs_dir, acceptance_dir)
    adapter_file = state.adapters_path() / f"{spec.adapter}.gguf" if spec.adapter else None
    pid, _ = state.binding(spec)
    try:
        provider = state.provider(pid)
        supports_adapters = bool(provider.capabilities.adapters)
    except Exception:
        supports_adapters = False
    wanted = spec.adapter or (state.personal_adapter() if spec.id == "core" else None)
    loaded_for_pid = set(state.installed_adapters.get(pid, set()))
    if pid == "spike-local" and state.runtime and state.runtime.running():
        loaded_for_pid.update(p.stem for p in state.runtime.config.adapters)
    adapter_loaded = bool(wanted and supports_adapters and wanted in loaded_for_pid)
    loaded_on = sorted(
        p for p, names in state.installed_adapters.items() if spec.adapter and spec.adapter in names
    )
    if (
        spec.adapter
        and "spike-local" not in loaded_on
        and state.runtime
        and state.runtime.running()
        and any(p.stem == spec.adapter for p in state.runtime.config.adapters)
    ):
        loaded_on = sorted([*loaded_on, "spike-local"])
    learned_variant = active_learned_prompt(state.evolution.store, spec.id)
    user_instr = (settings.get("specialist_instructions") or {}).get(spec.id) or ""
    knowledge_count = len(state.memory.store.list(scope=f"specialist:{spec.id}"))
    return {
        **spec.public(),
        "base_model": state.catalog.base_model,
        "adapter_accepted": accepted,
        "adapter_reasons": reasons,
        "adapter_file_present": bool(adapter_file and adapter_file.is_file()),
        "adapter_file_check": adapter_file_check(spec, state.evolution.store, adapter_file, acceptance_dir)
        if adapter_file else None,
        "loaded_on_providers": loaded_on,
        "active_provider": pid,
        "provider_supports_adapters": supports_adapters,
        "active_mode": "adapter_loaded" if adapter_loaded else "instruction_profile",
        "layers": {
            "base_instructions": bool(spec.system_prompt.strip()),
            "user_instructions": bool(str(user_instr).strip()),
            "learned_instructions": bool(learned_variant.instructions or learned_variant.skills),
            "knowledge_count": knowledge_count,
        },
    }
