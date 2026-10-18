#!/usr/bin/env python3
"""Statistical check for *already evaluated* paired, quantized models.

This is a scoring utility. It NEVER executes or certifies models and cannot
establish dataset/model provenance by itself. No network or dependencies.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("evaluation must be a JSON object")
    dataset = data.get("dataset")
    models = data.get("models")
    if not isinstance(dataset, dict) or not isinstance(models, dict):
        raise ValueError("dataset and models metadata are mandatory")
    if dataset.get("held_out") is not True or dataset.get("license_review") != "approved":
        raise ValueError("held-out evaluation and documented approved data license required")
    for key, value in (("dataset.sha256", dataset.get("sha256")),
                       ("models.base_sha256", models.get("base_sha256")),
                       ("models.specialist_sha256", models.get("specialist_sha256"))):
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            raise ValueError(f"invalid or missing {key}")
    if models.get("base_quantized") is not True or models.get("specialist_quantized") is not True:
        raise ValueError("both model results must come from final quantized artifacts")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty paired cases required")
    seen = set()
    grouped = defaultdict(list)
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("every case needs stable nonempty id")
        if not isinstance(item.get("group_id"), str) or not item["group_id"]:
            raise ValueError("every case needs stable nonempty group_id for clustered bootstrap")
        if item["id"] in seen:
            raise ValueError(f"duplicate case id {item['id']}")
        seen.add(item["id"])
        if type(item.get("base_correct")) is not bool or type(item.get("specialist_correct")) is not bool:
            raise ValueError("base_correct and specialist_correct must be booleans")
        grouped[item["group_id"]].append(int(item["specialist_correct"]) - int(item["base_correct"]))
    return dict(grouped)


def bootstrap(groups, samples=10000, seed=42):
    if samples < 1000:
        raise ValueError("at least 1000 bootstrap resamples are required")
    rng = random.Random(seed)
    ids = sorted(groups)
    n = sum(len(items) for items in groups.values())
    means = []
    for _ in range(samples):
        selected = rng.choices(ids, k=len(ids))
        total = sum(sum(groups[key]) for key in selected)
        count = sum(len(groups[key]) for key in selected)
        means.append(total / count)
    means.sort()
    lower = means[int(0.025 * samples)]
    upper = means[min(samples - 1, int(0.975 * samples))]
    return {"n": n, "grouped_n": len(ids),
            "delta_accuracy_points": round(100 * sum(map(sum, groups.values())) / n, 6),
            "ci95_lower_points": round(100 * lower, 6),
            "ci95_upper_points": round(100 * upper, 6),
            "significant_improvement": lower > 0,
            "resamples": samples, "seed": seed}


def main():
    parser = argparse.ArgumentParser(description="Paired bootstrap on real quantized eval outputs (offline)")
    parser.add_argument("--input", type=Path, required=True, help="JSON manifest + held-out paired cases")
    parser.add_argument("--output", type=Path, help="unique JSON evidence in reports/phase0 by default")
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.resamples < 1000 or args.resamples > 100000:
        parser.error("resamples must be between 1000 and 100000")
    if not args.input.is_file():
        parser.error("input file missing; no evaluation was performed")
    source = args.input.read_bytes()
    try:
        metadata = json.loads(source)
        groups = validate(metadata)
        stats = bootstrap(groups, samples=args.resamples, seed=args.seed)
    except (ValueError, UnicodeDecodeError) as exc:
        parser.error(str(exc))
    now = datetime.now(timezone.utc)
    output = args.output or ROOT / "reports" / "phase0" / ("paired-eval-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    try:
        revision = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    result = {
        "schema": "spike.phase0.paired-bootstrap.v1", "timestamp_utc": now.isoformat(),
        "git_commit": revision, "input_sha256": hashlib.sha256(source).hexdigest(),
        "dataset_sha256_declared": metadata["dataset"]["sha256"],
        "base_model_sha256_declared": metadata["models"]["base_sha256"],
        "specialist_model_sha256_declared": metadata["models"]["specialist_sha256"],
        "statistical_result": stats,
        "status": "STATISTICAL_PASS_ONLY" if stats["significant_improvement"] else "STATISTICAL_FAIL",
        "publication_approved": False,
        "limitations": "Hashes/labels were supplied by caller, not independently verified; leakage, licenses, split, model execution, RAM and regressions require separate audits.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"{result['status']}: {output}")
    return 0 if stats["significant_improvement"] else 1


if __name__ == "__main__":
    sys.exit(main())
