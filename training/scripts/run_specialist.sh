#!/usr/bin/env bash
# Full adapter pipeline for one specialist: data -> (distillation) -> training -> GGUF export -> evaluation.
#   training/scripts/run_specialist.sh medicine ~/src/llama.cpp ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf
# Distillation needs a local teacher on :8090 (see training/distill.py); the step runs only when the
# config enables it. Every step writes its own record; nothing here edits or summarizes results by hand.
set -euo pipefail
spec=${1:?specialist}; llama_cpp=${2:?llama.cpp checkout}; model=${3:?base GGUF}
root=$(cd "$(dirname "$0")/../.." && pwd); cd "$root"
cfg="training/configs/$spec.yaml"
extra=()
if python - "$cfg" <<'PY'
import sys, yaml
sys.exit(0 if (yaml.safe_load(open(sys.argv[1])).get("distill") or {}).get("enabled") else 1)
PY
then
  python training/distill.py "$cfg" --out "training/data/$spec/distilled.jsonl"
  extra=(--distilled "training/data/$spec/distilled.jsonl")
fi
eval_lines=$(PYTHONPATH=training python - "$cfg" <<'PY'
import sys, yaml
from spike_train.evaluation import eval_args
print("\n".join(eval_args(yaml.safe_load(open(sys.argv[1])))))
PY
)  # read before training so a bad `eval` block fails in seconds, not hours later
eval_extra=()
while IFS= read -r arg; do [[ -n $arg ]] && eval_extra+=("$arg"); done <<< "$eval_lines"
python training/prepare.py "$cfg" ${extra[@]+"${extra[@]}"}  # bash 3.2 (macOS) safe
training/train.sh "$spec"
python training/export_adapter.py "$spec" --llama-cpp "$llama_cpp" --check-model "$model"
adapter="$HOME/.spike/adapters/spike-$spec.gguf"
if [[ $spec == marketing ]]; then
  python evals/pairwise.py --specialist marketing --prompts evals/data/marketing_eval.jsonl \
    --model "$model" --adapter "$adapter" --acceptance "$cfg"
else
  python evals/run_eval.py --suites "$spec,general" --model "$model" --adapter "$adapter" --acceptance "$cfg" \
    ${eval_extra[@]+"${eval_extra[@]}"}
fi
