"""Versioned specialist adapters (Evolution 6). `spike adapters install` puts a trained LoRA GGUF in place only if
its measured eval results pass the acceptance rule of its training config; every installed file is kept in
adapters/history by checksum, so a rollback puts the previous one back (or none: the specialist then runs as a
prompt profile on the base model). llama-server loads adapters when it starts, so the local engine is restarted
afterwards to use the change."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from spike.evolution.acceptance import check_acceptance, check_pairwise_acceptance
from spike.evolution.store import EvolutionStore
from spike.runtime.gguf import read_gguf
from spike.specialists.catalog import Specialist


def component(spec: Specialist) -> str:
    return f"adapter:{spec.id}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _place(source: Path, dest: Path) -> None:
    """Make `dest` the same file as `source` (a hard link when the disk allows it, so no space is used twice)."""
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(source, tmp)
    except OSError:
        shutil.copy2(source, tmp)
    os.replace(tmp, dest)


def _keep(path: Path, history: Path, name: str) -> tuple[Path, str]:
    digest = sha256(path)
    kept = history / f"{name}-{digest[:12]}.gguf"
    if not kept.exists():
        history.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, kept)
    return kept, digest


def load_results(eval_path: Path) -> tuple[dict[str, Any], Path]:
    """summary.json of an eval run (the run directory or the file itself)."""
    path = eval_path / "summary.json" if eval_path.is_dir() else eval_path
    if not path.is_file():
        raise FileNotFoundError(f"no eval results at {path}; run evals/run_eval.py (evals/pairwise.py for an "
                                "open-ended specialist) on this adapter first")
    return json.loads(path.read_text(encoding="utf-8")), path


def is_pairwise(summary: dict[str, Any]) -> bool:
    """evals/pairwise.py records a win rate and a sign test; evals/run_eval.py records variants and suites."""
    return "win_rate" in summary and "sign_test_p" in summary


def verdict(spec: Specialist, summary: dict[str, Any], config: Path | None, variant: str | None) -> dict[str, Any]:
    """Apply the training config's acceptance rule to the measured results (or read the verdict the eval run
    recorded with that rule when no config is given)."""
    pairwise = is_pairwise(summary)
    if pairwise:  # one adapter per pairwise run
        variants = [summary["adapter"]] if summary.get("adapter") else []
    else:
        variants = [v for v in summary.get("variants") or [] if v != "base"]
    if variant is None:
        if len(variants) != 1:
            raise ValueError(f"the eval run has {len(variants)} adapter variants ({', '.join(variants) or 'none'}); "
                             "name one with --variant")
        variant = variants[0]
    elif variant not in variants:
        raise ValueError(f"variant '{variant}' is not in the eval run ({', '.join(variants) or 'none'})")
    if config is not None:
        cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
        if cfg.get("specialist") != spec.id:
            raise ValueError(f"{config.name} is the recipe of '{cfg.get('specialist')}', not '{spec.id}'")
        wants_pairwise = "min_win_rate" in (cfg["acceptance"].get("primary") or {})
        if wants_pairwise != pairwise:  # never judge a win-rate recipe by a run that cannot show one, or the reverse
            judged = {True: "a pairwise win rate", False: "exact-answer suites"}
            script = {True: "evals/pairwise.py", False: "evals/run_eval.py"}
            raise ValueError(f"{config.name} is judged by {judged[wants_pairwise]} ({script[wants_pairwise]}), "
                             f"but this eval run is from {script[pairwise]}")
        ok, reasons = (check_pairwise_acceptance(summary, cfg["acceptance"]) if pairwise
                       else check_acceptance(summary, cfg["acceptance"], variant))
        return {"variant": variant, "accepted": ok, "reasons": reasons, "rule": cfg["acceptance"],
                "checked": "now, with " + config.name}
    if pairwise:
        if "reasons" not in summary:  # written without --acceptance, or before the general suite was part of the rule
            raise ValueError("the pairwise run has no acceptance verdict with its general-suite check; "
                             "pass the training config with --config")
        return {"variant": variant, "accepted": bool(summary["accepted"]), "reasons": summary["reasons"],
                "checked": "by the pairwise run"}
    recorded = (summary.get("acceptance") or {}).get(variant)
    if recorded is None:
        raise ValueError("the eval run has no acceptance verdict; pass the training config with --config")
    return {"variant": variant, "accepted": bool(recorded["accepted"]), "reasons": recorded.get("reasons", []),
            "checked": "by the eval run"}


def install(evo: EvolutionStore, adapters: Path, spec: Specialist, gguf: Path, eval_path: Path,
            config: Path | None = None, variant: str | None = None) -> dict[str, Any]:
    """Install a trained adapter for a specialist if its results pass acceptance; raises ValueError otherwise."""
    if not spec.adapter:
        raise ValueError(f"'{spec.id}' has no adapter in the catalog")
    meta = read_gguf(gguf).metadata
    if meta.get("general.type") != "adapter" or meta.get("adapter.type") != "lora":
        raise ValueError(f"{gguf.name} is not a LoRA adapter GGUF")
    summary, summary_path = load_results(eval_path)
    result = verdict(spec, summary, config, variant)
    if not result["accepted"]:
        raise ValueError("refused: the adapter does not pass its acceptance rule: " + "; ".join(result["reasons"]))
    history, dest, comp = adapters / "history", adapters / f"{spec.adapter}.gguf", component(spec)
    kept, digest = _keep(gguf, history, spec.adapter)
    if dest.is_file() and evo.active(comp) is None and sha256(dest) != digest:
        before, before_digest = _keep(dest, history, spec.adapter)  # installed by hand: the version to go back to
        evo.add_version(comp, {"file": str(before), "sha256": before_digest, "source": str(dest)}, {},
                        "installed before versioning")
    active = evo.active(comp)
    if active and active["data"].get("sha256") == digest:
        return {"version": active, "unchanged": True}
    _place(kept, dest)
    version = evo.add_version(comp, {"file": str(kept), "sha256": digest, "source": str(gguf.resolve()),
                                     "eval": str(summary_path.resolve())}, result,
                              f"{result['variant']} accepted ({result['checked']})")
    return {"version": version, "path": str(dest)}


def rollback(evo: EvolutionStore, adapters: Path, spec: Specialist) -> dict[str, Any] | None:
    """Put back the adapter the active one replaced, or remove it when there was none."""
    current = evo.active(component(spec))
    if current is None:
        raise LookupError(f"'{spec.id}' has no installed adapter version to roll back")
    previous = evo.version(current["replaces"]) if current["replaces"] else None
    if previous and not Path(previous["data"]["file"]).is_file():
        raise FileNotFoundError(f"the previous adapter file is gone: {previous['data']['file']}")
    evo.rollback(component(spec))
    dest = adapters / f"{spec.adapter}.gguf"
    if previous is None:
        dest.unlink(missing_ok=True)
    else:
        _place(Path(previous["data"]["file"]), dest)
    return previous


async def install_checked(evo: EvolutionStore, adapters: Path, spec: Specialist, gguf: Path, eval_path: Path,
                          questions: list[dict[str, Any]], answer, reload, config: Path | None = None,
                          variant: str | None = None) -> dict[str, Any]:
    """`install`, then the user's own eval for this specialist (Evolution level 3: never deploy without passing it).
    `answer(question)` asks the specialist; `reload()` restarts the engine so it loads the adapter in place. The
    new adapter stays only if it passes at least as many of the questions as the one before and fails none that
    one passed; otherwise the previous adapter goes back and the result says why."""
    from spike.evolution.prompts import Variant, score

    async def ask(q: dict[str, Any], _: Variant) -> tuple[str, str | None]:
        return await answer(q)

    before = await score(Variant(), questions, ask) if questions else None
    result = install(evo, adapters, spec, gguf, eval_path, config, variant)
    if before is None or result.get("unchanged"):
        return {**result, "local_eval": None}
    await reload()
    after = await score(Variant(), questions, ask)
    lost = sorted(before.passed - after.passed)
    local = {"questions": len(questions), "before": len(before.passed), "after": len(after.passed), "lost": lost,
             "failed": after.failed}
    if lost or len(after.passed) < len(before.passed):
        rollback(evo, adapters, spec)
        await reload()
        return {**result, "local_eval": local, "rolled_back": True}
    return {**result, "local_eval": local, "rolled_back": False}
