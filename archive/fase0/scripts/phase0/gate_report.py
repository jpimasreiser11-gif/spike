#!/usr/bin/env python3
"""Fail-closed evidence inventory for Phase 0, never a substitute for model evals.

Uses only standard library; reports are informational and cannot approve Phase 1.
"""
import json
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
CHECKS = {
    "plan_full": "PLAN.md completo y legible",
    "s1": "Qwen3.5-4B vs Gemma 4 E4B: evals, tok/s, RAM en CPU 16 GB",
    "s2": "Multi-LoRA real en llama.cpp: cambio <=500 ms y cero contaminación",
    "s3": "Entrenar 4B con MLX-LM ~200 ejemplos, exportar GGUF LoRA y servir",
    "s4": "Inventario datos/licencias 0€, profesor local, descontaminación",
    "s5": "UX mediante REA sobre objetivos autorizados y specs clean-room",
    "s6": "Spike decidido; disponibilidad y marca verificadas",
    "s7": "Speculative Qwen3.5-0.8B y routing embeddings CPU",
    "tier1": "8 especialistas cuantizados con eval/IC 95%",
}


def git_revision(root):
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def inspect(root):
    records = []
    for path in sorted((root / "reports" / "phase0").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("schema"), str) and data["schema"].startswith("spike.phase0."):
            records.append({
                "path": str(path.relative_to(root)),
                "status": data.get("status"),
                "commit": data.get("git_commit"),
                "model_id": data.get("server", {}).get("model_id") if isinstance(data.get("server"), dict) else None,
            })
    gates = {key: {"status": "NOT_VERIFIED", "criterion": value} for key, value in CHECKS.items()}
    # A report from a fake server may satisfy an HTTP contract test; never auto-certify
    # actual model inference, LoRA isolation or RAM from that alone.
    plan = root / "PLAN.md"
    if plan.is_file() and plan.stat().st_size:
        checksum_file = root / "PLAN.sha256"
        expected = checksum_file.read_text(encoding="utf-8").split()[0] if checksum_file.is_file() else None
        content = plan.read_bytes()
        required = all(f"## {n}. ".encode() in content for n in range(18))
        if expected == hashlib.sha256(content).hexdigest() and required:
            gates["plan_full"]["status"] = "SOURCE_PRESENT_HASH_VERIFIED"
        else:
            gates["plan_full"]["status"] = "MANUAL_REVIEW_REQUIRED"
    else:
        gates["plan_full"]["status"] = "BLOCKED_MISSING_SOURCE"
    return {"gates": gates, "phase0_reports": records}


def main():
    root = ROOT
    now = datetime.now(timezone.utc)
    output = root / "reports" / "phase0" / ("gate-audit-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    inventory = inspect(root)
    result = {
        "schema": "spike.phase0.gate-audit.v1",
        "timestamp_utc": now.isoformat(),
        "commit": git_revision(root),
        "system": platform.platform(),
        "purpose": "evidence_inventory_only_no_model_evaluation",
        **inventory,
        "phase0_approved": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"PHASE0 BLOCKED: {output}")
    for key, record in result["gates"].items():
        print(f"  {key}: {record['status']}")
    print("Fase 1 permanece bloqueada; este target no ejecuta pruebas de calidad de modelos.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
