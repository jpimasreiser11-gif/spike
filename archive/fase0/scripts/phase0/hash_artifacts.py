#!/usr/bin/env python3
"""Hash user-supplied existing local model artifacts offline; never download data."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def hash_file(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"fichero local ausente, enlace simbólico o no regular: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    if size == 0:
        raise ValueError(f"no se admiten artefactos vacíos: {path}")
    return {"file_name": path.name, "path": str(path.resolve()),
            "size_bytes": size, "sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description="Local SHA-256 for previously obtained GGUF/LoRA files")
    parser.add_argument("--file", action="append", type=Path, required=True, help="existing artifact; repeat flag")
    parser.add_argument("--output", type=Path, help="new JSON manifest path; never overwritten")
    parser.add_argument("--repository-revision", help="optional, externally checked 40-digit upstream commit")
    args = parser.parse_args()
    if args.repository_revision and (len(args.repository_revision) != 40 or any(
            char not in "0123456789abcdef" for char in args.repository_revision)):
        parser.error("--repository-revision requiere SHA Git hexadecimal de 40 caracteres")
    try:
        files = [hash_file(p) for p in args.file]
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    now = datetime.now(timezone.utc)
    try:
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                         text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    result = {"schema": "spike.phase0.artifact-manifest.v1", "timestamp_utc": now.isoformat(),
              "spike_commit": commit, "upstream_repository_revision_declared": args.repository_revision,
              "system": platform.platform(), "artifacts": files,
              "verified_model_or_license": False,
              "limitations": "Hash de bytes locales únicamente; cotejar SHA oficial, licencia de pesos, procedencia y compatibilidad externamente."}
    target = args.output or ROOT / "reports" / "phase0" / ("hash-artifacts-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2, ensure_ascii=False)
            out.write("\n")
    except OSError as exc:
        parser.error(f"no se puede crear manifiesto: {exc}")
    print(f"ARTIFACT_HASHED_ONLY: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
