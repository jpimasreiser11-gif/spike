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
| (marketing only) distill | `python training/distill.py training/configs/marketing.yaml --out training/data/marketing/distilled.jsonl` | verified chats + summary |
| prepare | `python training/prepare.py training/configs/medicine.yaml [--distilled FILE]` | `training/data/<id>/{train,valid}.jsonl, mlx_lora.yaml, manifest.json` |
| (optional) your corrections | `spike evolve dataset out/` then `prepare.py … --corrections out/spike-training.jsonl` | only approved examples of that specialist, from SPIKE's local model, with consent; counted in the manifest |
| train | `training/train.sh medicine` | `training/runs/<id>/{adapter/, train.log, run.json}` |
| export | `python training/export_adapter.py medicine --llama-cpp ~/src/llama.cpp --check-model <base.gguf>` | `~/.spike/adapters/spike-medicine.gguf`, `training/runs/<id>/export.json` |
| evaluate | `python evals/run_eval.py --suites medicine,general --model <base.gguf> --adapter ~/.spike/adapters/spike-medicine.gguf --acceptance training/configs/medicine.yaml` | `evals/results/<run>/{summary.json,summary.md,predictions.jsonl}` |
| install | `spike adapters install ~/.spike/adapters/spike-medicine.gguf --specialist medicine --eval evals/results/<run> --config training/configs/medicine.yaml` | refused if it fails its acceptance rule; otherwise a version in `spike models history`, undone with `spike evolve rollback adapter:medicine`; it also answers your accepted eval questions (Settings → Evolución) and rolls back if it passes fewer or loses one (`--skip-local-eval` to skip) |
| model card | `python training/model_card.py medicine --eval evals/results/<run>` | `training/runs/<id>/hf/{README.md,banner.png}`: Hugging Face card built only from the manifest, export record and eval run; exit 2 and a "rejected" notice if the adapter failed its criteria |

Quick smoke run before a long one: add `--limit 50` to the evaluation and reduce `epochs` in a copy of the
config. Never report smoke-run numbers as results.

## 3. What makes a result valid

- The eval compares the base model **with the same system prompt** against base + adapter, same items,
  greedy decoding, thinking off, explicit adapter scales (ADR 0004).
- Training data was decontaminated against every eval source listed in the config (see `manifest.json`:
  `dropped.contaminated`).
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
