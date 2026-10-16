#!/usr/bin/env python3
"""Phase-0 cross-split collision detector for already-approved manifests.

No downloads, raw content, model calls or PII ingestion. Does not claim to
detect semantic paraphrases or contamination in unknown pretraining.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SHA = re.compile(r"^[0-9a-f]{64}$")


def check(data):
    if not isinstance(data, dict):
        raise ValueError("se exige un manifiesto JSON objeto")
    train, evaluation = data.get("train"), data.get("eval")
    if not isinstance(train, list) or not isinstance(evaluation, list) or not evaluation:
        raise ValueError("train y eval deben ser listas; eval no puede estar vacía")
    indexes = {"id": set(), "family_id": set(), "normalized_sha256": set(), "raw_sha256": set()}
    items = set()
    for category, rows in (("train", train), ("eval", evaluation)):
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{category} contiene elemento no objeto")
            for key in indexes:
                val = row.get(key)
                if not isinstance(val, str) or not val.strip():
                    raise ValueError(f"{category}: falta {key}")
                if key.endswith("sha256") and not SHA.fullmatch(val):
                    raise ValueError(f"{category}: hash {key} inválido")
            if type(row.get("license_approved")) is not bool or not row["license_approved"]:
                raise ValueError(f"{category}: derechos no aprobados para {row['id']}")
            if row["id"] in items:
                raise ValueError(f"ID duplicado en manifiesto: {row['id']}")
            items.add(row["id"])
            if category == "train":
                for key in indexes:
                    indexes[key].add(row[key])
    collisions = []
    for row in evaluation:
        overlap = [field for field in indexes if row[field] in indexes[field]]
        if overlap:
            collisions.append({"eval_id": row["id"], "collision_fields": overlap})
    return {
        "status": "FAIL_CONTAMINATION_DETECTED" if collisions else "PASS_EXACT_AND_FAMILY_CHECK_ONLY",
        "train_count": len(train), "eval_count": len(evaluation),
        "collisions": collisions, "checked_fields": list(indexes),
        "limitations": "El manifiesto se acepta como declarado. No verifica datos originales, similitud semántica, traducciones, derivados sin family_id, PII ni contaminación en pretraining.",
    }


def main():
    parser = argparse.ArgumentParser(description="Detecta cruces entre train y eval en metadatos locales ya autorizados")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.manifest.is_file() or args.manifest.is_symlink():
        parser.error("manifiesto no encontrado o es enlace simbólico")
    content = args.manifest.read_bytes()
    try:
        result = check(json.loads(content))
    except (ValueError, UnicodeDecodeError) as exc:
        parser.error(str(exc))
    now = datetime.now(timezone.utc)
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        commit = None
    result.update({
        "schema": "spike.phase0.decontamination.v1",
        "timestamp_utc": now.isoformat(), "git_commit": commit,
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "phase0_passed": False,
    })
    output = args.output or ROOT / "reports" / "phase0" / (
        "decontamination-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"{result['status']}: {output}")
    return 0 if result["status"] == "PASS_EXACT_AND_FAMILY_CHECK_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
