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
| (optional) self-generated replay | start the base model alone, `llama-server -m ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf --port 8091 --jinja -c 4096 --parallel 4` (**no `--lora`**), then `python training/self_replay.py training/configs/medicine.yaml --base-url http://127.0.0.1:8091/v1 --base-repo Qwen/Qwen3.5-4B --out training/data/medicine/self_replay.jsonl [--limit N] [--concurrency 4] [--resume]`, stop the server, then `python training/prepare.py training/configs/medicine.yaml --self-replay training/data/medicine/self_replay.jsonl` | `self_replay.jsonl` and `self_replay.summary.json` (kept and dropped by reason); replay answers written by the base model itself (first user turn of each replay-source chat, specialist system prompt, greedy, thinking off) in place of the human-written ones, so replay keeps the base's own style; before sending anything it refuses a base model whose Hub license is not on the training allowlist and a server with any LoRA adapter at a non-zero scale; drops answers that hit the token budget (prompt and answer fit `train.max_seq_length`), are empty, came with reasoning or repeat a sentence or loop; each row records the generator, its license, the server build and the settings. `prepare.py` checks the license again and puts the file's sha256, row count and generator in the manifest, with `mix_and_split` and the replay ratio unchanged; a recipe with `replay: {self_generated: true}` stops without `--self-replay`. An interrupted run leaves `self_replay.jsonl.partial`; `--resume` continues it |
| train | `training/scripts/train_supervised.sh medicine` (what `run_specialist.sh` runs; `SPIKE_UNSUPERVISED=1` runs plain `training/train.sh medicine`) | `training/runs/<id>/{adapter/, train.log, run.json, ramguard.log}` |
| export | `python training/export_adapter.py medicine --llama-cpp ~/src/llama.cpp --check-model <base.gguf>` | `~/.spike/adapters/spike-medicine.gguf`, `training/runs/<id>/export.json` |
| evaluate | `python evals/run_eval.py --suites medicine,general --model <base.gguf> --adapter ~/.spike/adapters/spike-medicine.gguf --acceptance training/configs/medicine.yaml` | `evals/results/<run>/{summary.json,summary.md,predictions.jsonl}` |
| choose between runs, checkpoints or settings | `python evals/run_eval.py --suites medicine-select,general-select --model <base.gguf> --adapter <candidate.gguf> …` | the `*-select` suites take the items after each acceptance sample (`skip`), so choosing never looks at the acceptance items; run `medicine,general` once, on the chosen candidate, and report every candidate tried; finance uses `finance-select,general-select` (FinQA and TAT-QA only: `finance` uses MMLU-Pro business and economics whole) |
| sweep checkpoints and LoRA scales (the cheapest try after a rejection for forgetting; no retraining) | `python training/sweep_checkpoints.py medicine --llama-cpp ~/src/llama.cpp --model <base.gguf> [--candidate 0.125 --candidate 0.25 --candidate 0.5 --candidate 1@0.5] [--python CONVERTER_PY] [--base Qwen/Qwen3.5-4B] [--no-final]` | A candidate is `FRACTION[@SCALE]` (0 < FRACTION ≤ 1, 0 < SCALE ≤ 1): the saved checkpoint (`adapter/<iteration>_adapters.safetensors`, every 200 iterations) nearest FRACTION × the run's planned iterations (`run.json` `counts.iters`; a tie takes the earlier one; 1 is the final `adapters.safetensors`, refused when `run.json` records a run that did not finish; a checkpoint written before the run began (`run.json` `run_started_utc`, which `train.sh` keeps across the RAM guard's resumed attempts; `started_utc` in older records) is refused as left by an earlier run), with its LoRA output times SCALE (default 1), applied in the export (`lora_parameters.scale` × SCALE in a copy of `adapter_config.json`, so the GGUF's alpha is scale × SCALE × rank), not at run time. The default is the four candidates above; candidates with the same iteration and scale are one. Each is exported with `export_adapter.py --name … --work …` to `training/runs/<id>/sweep/gguf/spike-<id>-it<N>-s<S>.gguf` (the run's `export.json` and `~/.spike/adapters` are not touched); one `run_eval.py` run (`sweep/select`) answers `<id>-select,general-select` for the base model and every candidate; the recipe's own acceptance rule with the suites renamed `X` → `X-select` is applied to each, and the chosen one is the candidate that passes with the largest gain on the primary suite (a tie takes the earlier checkpoint, then the smaller scale). Unless `--no-final`, `<id>,general` then run once on the chosen candidate alone with `--acceptance training/configs/<id>.yaml` (`sweep/final`): that verdict is the round's verdict. Writes `sweep/{summary.json,summary.md}`: every candidate tried (asked, iteration, scale, select gain and regression with p-values, whether it passes and why), the chosen one and the final verdict; every number comes from the `run_eval.py` summaries. Exit 0 accepted, 2 rejected or no candidate passed the selection, 1 error; when accepted it prints the `spike adapters install <sweep GGUF> --specialist <id> --eval training/runs/<id>/sweep/final --config training/configs/<id>.yaml` command (not run). Run it again after an interruption: finished exports and finished groups of answers are kept (`run_eval.py --resume`), and results of another set of candidates are refused rather than overwritten. Recipes judged by exact-answer suites only; not wired into `run_specialist.sh` |
| fix a rejection for forgetting unattended (the sweep, then one retrain with self-generated replay; one detached command) | `nohup caffeinate -i python training/fix_forgetting.py medicine --llama-cpp ~/src/llama.cpp --model ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf > training/runs/medicine/fix_forgetting.out 2>&1 &` (`caffeinate` is macOS; drop it on other systems; `[--python CONVERTER_PY]` goes to both sweeps; `--dry-run` prints the plan and what is already done, running and writing nothing) | One heavy job at a time, stopping at the first accepted result. (1) `sweep_checkpoints.py` on the existing run: exit 0 is accepted and the end, 1 an error (stop, nothing moved), 2 goes on. (2) Round 2 changes one thing, the replay source (the base model's own answers instead of the human-written ones; ratio, learning rate, steps formula and acceptance criteria stay, and the recipe file is not edited): **archive** `adapter/` and `sweep/` to `training/runs/<id>/round<N>/` (N = 1 + the highest existing `roundK`; `run.json`, `export.json` and `training/data/<id>/manifest.json` as `data-manifest.json` are copied there, since the new round rewrites them in place; refused if `round<N>` exists); **self_replay**: `llama-server` on the base GGUF alone (no adapter, `--jinja`, 4 slots, a context per slot of 2 × `train.max_seq_length` or 2,048, q8_0 KV cache like `run_eval.py`), `self_replay.py … --concurrency 4` (`--resume` when `self_replay.jsonl.partial` exists; skipped when `self_replay.jsonl` and `self_replay.summary.json` exist), and the server is stopped however the step ends; **prepare** `--self-replay` (stops if the replay share of the mix is more than 2 points below the recipe's ratio, e.g. after a `--limit` smoke run, or if the manifest does not record the file); **train** `training/scripts/train_supervised.sh` (RAM guard, resumes from its checkpoints); then the sweep again on the new run, whose exit code is the verdict (0 accepted, 2 rejected). Refused: a recipe that already has `replay.self_generated` or no `replay.sources`, a missing `run.json`, a second instance for the same specialist (lock). Run the same command again after any interruption or error: `training/runs/<id>/fix_forgetting.json` records the archive round and the finished steps, so the first sweep does not run again once the archive began (its folder has moved), a half-done archive is finished and never repeated, and the files decide the replay and the training (`run.json` exit 0 on the sha256 of the prepared `train.jsonl` and `valid.jsonl`), so neither is redone once finished; sweeps and `self_replay.py` resume their own work. Never commits, pushes or installs (`~/.spike/adapters` is not touched) | `training/runs/<id>/fix_forgetting.{log,json}` (every step with its UTC time; the `.out` has the tools' output) and, at the end of the log, the verdict and the `summary.md` of each round: `round<N>/sweep/summary.md` for the first run, `sweep/summary.md` for the retrained one; exit 0 accepted (by either sweep), 2 nothing accepted, 1 error. Built and tested with fakes, not run on the Mac; not wired into `run_specialist.sh` |
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

First supervised run on a Mac (not yet done): `pip install -r training/requirements-mac.txt` (mlx-lm 0.32.2), then
`pytest -q tests/test_resume.py tests/test_ramguard.py tests/test_gated_delta_chunked.py`; a short real run (a copy of
the config with `iters: 48`, `save_every: 16`) stopped with SIGTERM mid-run and resumed with `SPIKE_RESUME=1`, compared
with an uninterrupted one (Metal: tiny float differences, not bit equality); the chunked gated-delta timing on 64
chats (≈ 112 s before); checkpoint size and write time; then
`SPIKE_MLX_MEMORY_GB=20 SPIKE_MLX_CACHE_GB=2 nohup training/scripts/train_supervised.sh medicine >/dev/null 2>&1 &`
and only one guard on the run.

Quick smoke run before a long one: add `--limit 50` to the evaluation and reduce `epochs` in a copy of the
config. Never report smoke-run numbers as results.

### 2b. A personal adapter (`spike evolve personal-adapter`, Evolution EV6)

A LoRA for Spike Core, the general assistant, trained only on the user's own text so that it answers more the way
they asked. **Off by default** (Settings → Evolución, or `spike evolve personal-adapter --enable`), **Apple silicon
only** (it is trained with MLX; on any other computer the command and the Settings section say it is not available and
do nothing), and everything stays on this computer.

- **What goes in, and nothing else of the user's.** The corrections they approved one by one (the same examples as
  `spike evolve dataset`; they count only while "Use my corrections to retrain" is on) and the chats they mark
  (`--mark <chat id>` or Settings). From a marked chat, each answer that SPIKE's local model wrote is one example (with up
  to 6 earlier messages as context); answers that ended in an error, came from an external service or another model
  (their terms and licenses can forbid training on their output) or that the user's next message corrected are left out.
  `--list` prints every example and `--exclude <id>` / `--include <id>` (or the checkboxes in Settings) take one out or
  put it back; an excluded text is also removed from the context of its neighbours. The same question and answer from
  two places counts once. Both places show the counts before anything runs. At least 30 examples are needed (a
  safety floor of this design, not a measured threshold).
- **The mix.** The examples are the domain data of `training/configs/personal.yaml` (`system_from: core`: they are trained
  under Spike Core's system prompt, since `personal` has no catalog entry) and `prepare.py` adds the same public,
  human-written general replay as for every specialist (OASST2, ratio 0.3) and decontaminates against MMLU-Pro. The
  replay is public data, not the user's.
- **The pipeline is the specialists' one**, run by the command with these steps (and `--yes` to skip the question):

  | Step | Command (paths under `~/.spike/personal/`) |
  |---|---|
  | prepare | `python training/prepare.py training/configs/personal.yaml --corrections ~/.spike/personal/spike-personal.jsonl` |
  | train | `training/scripts/train_supervised.sh personal` (the RAM guard; `SPIKE_UNSUPERVISED=1` runs `train.sh`); the command refuses to start on a Mac with less memory than the guard waits for (`RESUME_FREE_GB`, 22 GB) |
  | export | `python training/export_adapter.py personal --llama-cpp <llama.cpp> --check-model <base.gguf> --out ~/.spike/personal/stage --work ~/.spike/personal/stage/work --name spike-personal --system-from core` (staging only: nothing reaches `~/.spike/adapters` before acceptance) |
  | select | `python evals/run_eval.py --model <base.gguf> --adapter <stage>/spike-personal.gguf --max-tokens 2048 --suites general-select`; if general knowledge already dropped by more than the limit here, the run ends (rejected) before the longer one |
  | evaluate | the same with `--suites general --acceptance training/configs/personal.yaml` |
  | install | `adapters.install`: applies the recipe's rule to the measured numbers itself (not to run_eval's exit code), then versions the adapter as `adapter:personal` in `spike models history` |

  `--llama-cpp` (or `$SPIKE_LLAMA_CPP`) and `--model` (or the local-engine model in Settings) say where llama.cpp and the
  base GGUF are. Exit code 0 accepted, 2 rejected, 1 anything else (including 75 from the RAM guard, after which running
  the command again resumes training from its last checkpoint).
- **Acceptance.** The only criterion is that the general suite (MMLU-Pro) does not drop by more than **1.5 points**, the
  specialists' limit. There is no public benchmark for "your way of working", so no gain is demanded, claimed or measured:
  an accepted personal adapter means it did not make general knowledge worse on that sample, not that it is better for the
  user. The recipe is refused if it loosens the rule. Without acceptance nothing is installed or activated.
- **Files.** The examples file, the staged adapter, `training/data/personal` and `training/runs/personal` (weights trained
  on the user's text) are deleted when a run ends, whatever the verdict; only a run that stopped while training keeps them,
  so that running the command again can resume. The eval runs (`~/.spike/personal/eval-select`, `eval-general`: public
  questions and the adapter's answers to them) are kept as the evidence of the verdict.
- **Use.** Spike Core loads `spike-personal.gguf` only while the setting is on and an accepted version is installed (the
  specialists keep their own adapters). Go back with `spike evolve rollback adapter:personal`; restart the local engine to
  load or unload it.
- **Not measured.** The pipeline is tested with the commands stubbed (`tests/test_personal_adapter.py`: dataset rules, the
  two gates, clean-up, platform message) and `prepare.py` with the personal recipe on in-memory rows
  (`tests/test_training.py`). It has never trained on real weights here (no Apple silicon): the hyperparameters (rank 8,
  learning rate 5e-5, 2 epochs, effective batch 4 against 16 for the specialists: 40 examples plus their replay make about
  25 optimizer updates, about 6 with a batch of 16) are conservative guesses, and nothing says yet how large or small the effect is.

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
