# Training, exporting and evaluating a specialist (Apple Silicon Mac)

Everything here runs locally and costs nothing. Expected footprint on a 36 GB Mac: training ≈ 10–12 GB
(third-party reports, see ADR 0002), teacher (Qwen3.6-35B-A3B 4-bit) ≈ 20 GB, never both at once.

## 0. One-time setup

```bash
git clone <spike repo> && cd spike
python3 -m venv .venv-train && . .venv-train/bin/activate
pip install -r training/requirements-mac.txt -e .
brew install llama.cpp                                    # llama-server for export checks and evals
git clone --depth 1 https://github.com/ggml-org/llama.cpp ~/src/llama.cpp   # for convert_lora_to_gguf.py
spike models pull qwen3.5-4b --quant Q4_K_M               # base GGUF into ~/.spike/models (license + SHA-256 checked)
```

## 1. One command per specialist

```bash
training/scripts/run_specialist.sh medicine ~/src/llama.cpp ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf
```

It runs the steps below and stops at the first failure. Exit code 2 from the evaluation means the adapter
was trained but **rejected** by its acceptance criteria: keep the specialist as a prompt profile.

## 2. Steps in detail

| Step | Command | Output |
|---|---|---|
| (marketing only) start the teacher | `mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit --port 8090` | OpenAI-compatible endpoint |
| (marketing only) distill | `python training/distill.py training/configs/marketing.yaml --out training/data/marketing/distilled.jsonl` | rubric-filtered chats + summary; refuses a teacher whose Hub license is not on the training allowlist and records the teacher's repo and license on every row; stops if the teacher cannot produce `expand_to` distinct tasks |
| prepare | `python training/prepare.py training/configs/medicine.yaml [--distilled FILE]` | `training/data/<id>/{train,valid}.jsonl, mlx_lora.yaml, manifest.json` (teacher licenses included); stops when there is no domain data, e.g. marketing without `--distilled` |
| (optional) your corrections | `spike evolve dataset out/` then `prepare.py … --corrections out/spike-training.jsonl` | only approved examples of that specialist, from SPIKE's local model, with consent; counted in the manifest |
| train | `training/scripts/train_supervised.sh medicine` (what `run_specialist.sh` runs; `SPIKE_UNSUPERVISED=1` runs plain `training/train.sh medicine`) | `training/runs/<id>/{adapter/, train.log, run.json, ramguard.log}` |
| export | `python training/export_adapter.py medicine --llama-cpp ~/src/llama.cpp --check-model <base.gguf>` | `~/.spike/adapters/spike-medicine.gguf`, `training/runs/<id>/export.json` |
| evaluate | `python evals/run_eval.py --suites medicine,general --model <base.gguf> --adapter ~/.spike/adapters/spike-medicine.gguf --acceptance training/configs/medicine.yaml` | `evals/results/<run>/{summary.json,summary.md,predictions.jsonl}` |
| (marketing only) evaluate | `run_specialist.sh` runs `evals/run_eval.py --suites general …` and then `python evals/pairwise.py --specialist marketing --prompts evals/data/marketing_eval.jsonl --model <base.gguf> --adapter ~/.spike/adapters/spike-marketing.gguf --acceptance training/configs/marketing.yaml --general-eval <general run>` | `evals/results/pairwise-marketing-<time>/{summary.json,pairs.jsonl}`; accepted only if the win rate and sign test pass **and** the general suite drops by no more than `regression.max_drop_points`; exit 2 otherwise. `spike adapters install … --eval <that folder> --config training/configs/marketing.yaml` takes this summary like a `run_eval.py` one |
| install | `spike adapters install ~/.spike/adapters/spike-medicine.gguf --specialist medicine --eval evals/results/<run> --config training/configs/medicine.yaml` | refused if it fails its acceptance rule; otherwise a version in `spike models history`, undone with `spike evolve rollback adapter:medicine`; it also answers your accepted eval questions (Settings → Evolución) and rolls back if it passes fewer or loses one (`--skip-local-eval` to skip) |
| model card | `python training/model_card.py medicine --eval evals/results/<run>` | `training/runs/<id>/hf/{README.md,banner.png}`: Hugging Face card built only from the manifest, export record and eval run; exit 2 and a "rejected" notice if the adapter failed its criteria |

**Unattended training on a shared Mac (RAM guard + exact resume).** To survive closing the terminal:
`nohup training/scripts/train_supervised.sh finance >/dev/null 2>&1 &`, then `tail -f training/runs/finance/ramguard.log`.
The guard samples memory every 5 s and stops training (SIGTERM, SIGKILL after 30 s) if swap grew by more than
`SWAP_GROWTH_GB` (2) since the attempt started or available memory drops below `MIN_FREE_GB` (2.5). It waits until
`RESUME_FREE_GB` (22) has been available for `RESUME_STABLE_MIN` (10) minutes, also before the first attempt, and
relaunches with `SPIKE_RESUME=1`, up to `MAX_RESTARTS` (20), then exits 75; a training exit is passed through. Every
decision is logged with the numbers, and `caffeinate -i` keeps the Mac awake. Resume is exact: each adapter checkpoint
(at the first optimizer-update boundary on or after each `save_every`) also writes
`training/runs/<id>/adapter/resume/<iteration>/` with the adapters, the full optimizer state and `resume.json`
(iteration, optimizer step, data position, PRNG key, sha256 of `train.jsonl` and the mlx config, mlx and mlx-lm
versions); a resumed run refuses to start if any of those changed (delete that `resume` folder to start over). By
hand: `SPIKE_RESUME=1 training/train.sh <id>`. It needs mlx-lm 0.32.2 (pinned); with another version a fresh run
trains with mlx-lm's own loop and no resume checkpoints. Tested with real mlx on Linux CPU (a run stopped and resumed
ends with the same adapter and optimizer state as an uninterrupted one); not yet on Apple silicon.

Quick smoke run before a long one: add `--limit 50` to the evaluation and reduce `epochs` in a copy of the
config. Never report smoke-run numbers as results.

## 3. What makes a result valid

- The eval compares the base model **with the same system prompt** against base + adapter, same items,
  greedy decoding, thinking off, explicit adapter scales (ADR 0004); `pairwise.py` generates greedily too
  (`--temperature` changes it and is recorded in its summary).
- Training data was decontaminated against every eval source listed in the config (see `manifest.json`:
  `dropped.contaminated`).
- A source is a Hub dataset (`hub:`) or JSON files from URLs (`urls: [{url, sha256}]` with `revision`, `license`
  and `license_url`, used when a dataset is only published as files, like FinQA and TAT-QA). Every URL must contain
  the pinned commit; the sha256 of every file is checked on each load, cached or not, and a mismatch stops the
  run. For a URL source the license gate checks the license recorded in `datasets.yaml`. A Hub source that mixes
  upstream licenses can carry `filter: {column: [values]}`, and its config entry `max_per_value: N` keeps the
  first N rows of each value in stream order (a value with fewer rows is not topped up). `format: finqa_train`
  drops FinQA rows whose own calculation steps disagree with their arguments; the eval keeps every row.
- `summary.json` (with llama.cpp build, host, settings) and `run.json` (data hashes, versions, chip) are
  committed together. Only then may `adapter_status` change to `trained` in the catalogue.

## 4. Benchmarks on the target hardware

```bash
spike doctor                                              # memory plan for this machine
spike bench --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf --gpu-layers 0 --contexts 1024,8192,32768 --out bench-cpu.json
spike bench --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf --gpu-layers 99 --out bench-metal.json
```

`--gpu-layers 0` measures the CPU path, but a Mac CPU is not a 16 GB x86 laptop: the 16 GB claim needs a run
on such a machine. Reports include TTFT, prompt and generation tok/s from server timings, peak RSS, load time
and the llama.cpp build.
