#!/usr/bin/env bash
# Train one specialist under the RAM guard (training/ramguard.py): training stops when swap grows or free memory
# gets low, and restarts from its last checkpoint once memory has been free for a while. Run prepare.py first.
#   nohup training/scripts/train_supervised.sh finance >/dev/null 2>&1 &     # survives the terminal closing
#   tail -f training/runs/finance/ramguard.log
# Thresholds are env vars (SWAP_GROWTH_GB, MIN_FREE_GB, RESUME_FREE_GB, RESUME_STABLE_MIN, MAX_RESTARTS...), listed at
# the top of training/ramguard.py. Exit code: training's own (0 = finished), or 75 after MAX_RESTARTS restarts.
set -euo pipefail
spec=${1:?usage: train_supervised.sh <specialist>}
root=$(cd "$(dirname "$0")/../.." && pwd)
exec python "$root/training/ramguard.py" "$spec"
