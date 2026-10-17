#!/usr/bin/env bash
# Train one SPIKE adapter with mlx-lm (Apple Silicon). Run prepare.py first.
#   training/train.sh medicine
# Writes training/runs/<specialist>/{adapter/, train.log, run.json}. Never edits results by hand:
# run.json records the environment, data hashes and exit code of this exact run.
set -euo pipefail
spec=${1:?usage: train.sh <specialist>}
root=$(cd "$(dirname "$0")/.." && pwd)
data="$root/training/data/$spec"
cfg="$data/mlx_lora.yaml"
run="$root/training/runs/$spec"
[[ -f $cfg ]] || { echo "missing $cfg; run: python training/prepare.py training/configs/$spec.yaml" >&2; exit 1; }
python -c "import mlx_lm.models.qwen3_5" 2>/dev/null || {
  echo "this mlx-lm has no qwen3_5 model; install a recent one: pip install -U mlx-lm" >&2; exit 1; }
mkdir -p "$run"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
set +e
python -m mlx_lm.lora --config "$cfg" 2>&1 | tee "$run/train.log"
status=${PIPESTATUS[0]}
set -e
python - "$run" "$data" "$started" "$status" <<'PY'
import json, platform, subprocess, sys, time
from importlib.metadata import version
run, data, started, status = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
def v(pkg):
    try: return version(pkg)
    except Exception: return None
def sh(*cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception: return None
manifest = json.load(open(f"{data}/manifest.json"))
json.dump({"specialist": manifest["specialist"], "started_utc": started,
           "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "exit_code": status,
           "data_files_sha256": manifest["files"], "counts": manifest["counts"],
           "git_commit": sh("git", "rev-parse", "HEAD"), "chip": sh("sysctl", "-n", "machdep.cpu.brand_string"),
           "memory_bytes": sh("sysctl", "-n", "hw.memsize"), "os": platform.platform(),
           "python": platform.python_version(), "mlx": v("mlx"), "mlx_lm": v("mlx-lm")},
          open(f"{run}/run.json", "w"), indent=2)
print(f"wrote {run}/run.json (exit {status})")
PY
exit "$status"
