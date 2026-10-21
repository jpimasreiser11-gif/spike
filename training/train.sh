#!/usr/bin/env bash
# Train one SPIKE adapter with mlx-lm (Apple Silicon). Run prepare.py first.
#   training/train.sh medicine
# Writes training/runs/<specialist>/{adapter/, train.log, run.json}. Never edits results by hand:
# run.json records the environment, data hashes and exit code of this exact run, and run_started_utc: when the run
# began, the same across the attempts that resume it.
# With SPIKE_RESUME=1 (set by training/scripts/train_supervised.sh) lora.py continues from its latest checkpoint
# and train.log is appended to, so it keeps every attempt.
set -euo pipefail
spec=${1:?usage: train.sh <specialist>}
root=$(cd "$(dirname "$0")/.." && pwd)
data="$root/training/data/$spec"
cfg="$data/mlx_lora.yaml"
run="$root/training/runs/$spec"
[[ -f $cfg ]] || { echo "missing $cfg; run: python training/prepare.py training/configs/$spec.yaml" >&2; exit 1; }
python -c "import mlx_lm.models.qwen3_5" 2>/dev/null || {
  echo "this mlx-lm has no qwen3_5 model; install a recent one: pip install -U mlx-lm" >&2; exit 1; }
mkdir -p "$run/adapter"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# When the run itself began, kept across resumed attempts: lora.py starts at iteration 0 unless SPIKE_RESUME finds a
# resume checkpoint, and only then does this attempt continue an earlier one (the sweep refuses older checkpoints)
if [[ -z ${SPIKE_RESUME:-} ]] || ! ls "$run"/adapter/resume/*/resume.json >/dev/null 2>&1; then
  echo "$started" > "$run/adapter/run_started_utc"
fi
run_started=$(cat "$run/adapter/run_started_utc" 2>/dev/null || true)
[[ -n ${SPIKE_RESUME:-} ]] && { log_mode=-a; echo "--- $started SPIKE_RESUME=$SPIKE_RESUME ---" >> "$run/train.log"; } || log_mode=
set +e
python "$root/training/lora.py" --config "$cfg" 2>&1 | tee ${log_mode:+$log_mode} "$run/train.log"  # mlx_lm.lora + chunked gated delta
status=${PIPESTATUS[0]}
set -e
python - "$run" "$data" "$started" "$status" "$run_started" <<'PY'
import json, os, platform, subprocess, sys, time
from importlib.metadata import version
run, data, started, status, run_started = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5] or None
def v(pkg):
    try: return version(pkg)
    except Exception: return None
def sh(*cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception: return None
manifest = json.load(open(f"{data}/manifest.json"))
json.dump({"specialist": manifest["specialist"], "started_utc": started, "run_started_utc": run_started,
           "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "exit_code": status,
           "spike_resume": os.environ.get("SPIKE_RESUME") or None,
           "data_files_sha256": manifest["files"], "counts": manifest["counts"],
           "git_commit": sh("git", "rev-parse", "HEAD"), "chip": sh("sysctl", "-n", "machdep.cpu.brand_string"),
           "memory_bytes": sh("sysctl", "-n", "hw.memsize"), "os": platform.platform(),
           "python": platform.python_version(), "mlx": v("mlx"), "mlx_lm": v("mlx-lm"),
           "gated_delta": "spike_train.gated_delta_chunked (chunk 16)"},
          open(f"{run}/run.json", "w"), indent=2)
print(f"wrote {run}/run.json (exit {status})")
PY
exit "$status"
