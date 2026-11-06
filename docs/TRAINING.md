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
| (marketing, science, data) start the teacher | `mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit --port 8090` | OpenAI-compatible endpoint |
| (marketing, science, data) distill | `python training/distill.py training/configs/science.yaml --out training/data/science/distilled.jsonl` (marketing and data the same way; `run_specialist.sh` does it for any recipe with `distill.enabled`) | chats + a summary (kept per kind, dropped per reason). The teacher writes every task from the recipe's topic labels, and then the answers (2d); the Hub license of the teacher must be on the training allowlist, checked before any task is sent; every row records the teacher's repo and license and how its tasks were made; `distill.seeds` that do not declare a human author are refused; stops if the teacher cannot produce `expand_to` distinct tasks |
| prepare | `python training/prepare.py training/configs/medicine.yaml [--distilled FILE]` | `training/data/<id>/{train,valid}.jsonl, mlx_lora.yaml, manifest.json` (teacher licenses and the recipe's `task_source` included); stops when there is no domain data, e.g. marketing, science or data without `--distilled`, and when the recipe's task source is not valid or a row says nothing about how its tasks were made (2d) |
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

### 2c. License review of the M5 and M6 sources (M7, 2026-11-02)

The sources Codex proposed for the other specialists were reviewed with evidence gathered on a GitHub runner,
because the cloud session cannot reach the Hub: `training/verify_sources.py` (workflow `sources.yml`, manual)
records the Hub license metadata, the dataset card, the Hub commit, every row of the split streamed and counted and
how many the formatter accepts. Run: https://github.com/jpimasreiser11-gif/spike/actions/runs/41407296157
(`datasets` 5.1.0). Each entry of `training/datasets.yaml` keeps its numbers in `license_review`.

| Specialist | Source | Hub license | Rows (train / eval), all formatted | Decision |
|---|---|---|---|---|
| Law | coastalcph/lex_glue, case_hold | cc-by-4.0 | 45,000 / 3,600 | verified: holdings come from the citing opinions; court opinions are public-domain works |
| Math | openai/gsm8k | mit | 7,473 / (eval `gsm8k`) | verified: written by human contractors, not model outputs |
| Code | google-research-datasets/mbpp | cc-by-4.0 | 374 / 500 | verified: crowd-written problems, programs and tests |
| Education | allenai/qasc | cc-by-4.0 | 8,134 / 926 | verified |
| Core | tau/commonsense_qa | mit | 9,741 / 1,221 | verified: ConceptNet concepts are single words and never shown |
| Business | PolyAI/banking77 | cc-by-4.0 | 10,003 / 3,080 | verified |
| Security | pirocheto/phishing-url | cc-by-4.0 | 7,658 / 3,772 | verified: URL text only; leakage removed by decontamination |
| Writing | FiscalNote/billsum | cc0-1.0 | 18,949 / 3,269 | verified: US bills are public-domain works |
| Science | allenai/openbookqa | unknown | 4,957 / 500 | **rejected**: the Hub declares no license and the gate reads the Hub |
| Data | Salesforce/wikisql | unknown | does not load | **rejected**: no license on the Hub, a loading script `datasets` 5 no longer runs, tables from Wikipedia under CC BY-SA |

Candidates probed for Science and Data (`verify_sources.py --probe`, run 41407299426), none usable for training:
allenai/scitail (no license), allenai/sciq and bigbio/sciq (cc-by-nc-3.0), allenai/ai2_arc,
derek-thomas/ScienceQA and xlangai/spider (cc-by-sa-4.0), Idavidrein/gpqa (cc-by-4.0 but gated, 448 questions,
meant for evaluation), b-mc2/sql-create-context (cc-by-4.0 but built from WikiSQL and Spider) and
gretelai/synthetic_text_to_sql (apache-2.0 but written by a model whose generator is not named). The Science and Data
recipes therefore have `domain_sources: []`; their domain data is verified distillation from an open teacher, seeded by
topic labels (2d), and `prepare.py` still stops without it. Science keeps its MMLU-Pro physics, chemistry and biology
acceptance suite and gains a local one; Data gets a held-out file of its own (2d).

### 2d. Distillation seeded by topic labels (M10, 2026-11-02): Marketing, Science and Data

**The rule.** No text written by Claude, GPT, Gemini or Llama may become training data, and seeds or prompts written by
an AI assistant count as such text. The 24 "hand-written" marketing seeds (`training/seeds/marketing.jsonl`) were written
by an AI assistant, and `expand_seeds` put the seeds themselves into the task list, so they would have been trained on.
The file is removed. Nothing had been distilled or trained from it: no real teacher run has happened for any recipe.

**Where the tasks of a recipe come from.** The `distill` block names exactly one source (`spike_train/seeding.py`):

| Source | What it is | Enforcement |
|---|---|---|
| `topics: FILE` | A YAML file of short topic labels (at most 8 words, no sentence punctuation, not starting like a request) under a `provenance:` text that says who chose them. The open teacher writes every task from the labels, and then the answers. A label is an instruction to the teacher: it is never copied into a task, an answer, a row or its `meta` | `distill.py` and `prepare.py` refuse a file without a provenance or with a label that reads as a task; rows and the manifest record the file and its sha256 (and, in the manifest, the provenance and the number of labels, never the labels) |
| `seeds: FILE` | Example tasks the teacher expands, **only for a human author**: the first line of the JSONL must be `{"declaration": {"authored_by": "human", "author": "..."}}` | `distill.py` and `prepare.py` refuse a file without it (the message points to `topics`); `prepare.py` also refuses a distilled file whose rows say their seeds had no human author, or say nothing about how their tasks were made. Nothing can detect AI text: the declaration is the maintainer's statement, kept in the manifest |
| `tasks_from: {source: …}` | Training-split questions with gold answers from a registry source, verified by exact match (as before) | the registry's license gate |

The topic files are `training/topics/{marketing,science,data}.yaml`: 90 labels in 7 groups, 107 labels in 6 groups
(physics, chemistry and biology, each at secondary-school and undergraduate level) and 64 labels in 6 groups (what a
database is about: bookstore orders, ferry bookings...). The labels were chosen by an AI assistant (Claude) at the
maintainer's request and say so in their provenance: they are AI-written text that is used only as an instruction to the
teacher. Be aware of two limits. A teacher-written task may use the same ordinary words as its label (a question about
"projectile motion" may say so); the pipeline never copies a label and drops a task or question that is only the label,
but it does not forbid a shared phrase. The system prompt of each specialist (`spike/specialists/catalog.yaml`, repository
text that every recipe's rows already carried) and the layout (lettered options, a fenced schema) are the only text in a
row that the teacher did not write; the answer-format requests sent with a question ("finish with `Answer: <letter>`") are
not stored. Decision (builder, 2026-11-02): the catalog's system prompts stay. They are the same instructions the app
sends at run time, and every recipe trains with `mask_prompt: true`, so no loss is computed on them and the model is
not trained to write them.

**The teacher.** `distill.teacher` in each recipe: `Qwen/Qwen3.6-35B-A3B`, served as
`mlx-community/Qwen3.6-35B-A3B-4bit` (the teacher the docs, ADR 0001 and 0002 and `THIRD_PARTY.md` already name). Its Hub
license is read live before any task is sent and must be on the training allowlist; `prepare.py` reads it again.
This document claims no license for it beyond what those records say. `openai/gpt-oss-20b` is the alternative named in
`docs/PLAN.md`: `distill.py … --teacher-model <served name> --teacher-repo openai/gpt-oss-20b` licenses it under that repo,
whatever its Hub page says on the day (a served name with no `--teacher-repo` is licensed under its own name, never under
the recipe's).

**Science.** `kinds: {mcq: 0.6, explanation: 0.4}`, `expand_to: 6000` tasks (rows kept will be fewer; not measured).
*mcq*: the teacher writes a question, the correct option and three wrong ones from a label; the options are shuffled
here. A row is kept only when two independent teacher answers agree with the keyed option (the second sees the options in
another order and must name the same option; each must end with `Answer: <letter>`) and the rubric review passes. The
row is the question with lettered options and the teacher's own answer. *explanation*: requests for an explanation, a
derivation or a worked calculation, kept when the rubric passes. Decontamination: MMLU-Pro (all categories) and
`evals/data/science_eval.jsonl`.

**Data.** `kinds: {sql: 1}`, `expand_to: 4000`. The teacher writes, from a label, a small SQLite schema with INSERT rows,
a question and the query. Everything runs with the standard library's `sqlite3` on an in-memory database
(`spike_train/sqlsandbox.py`): no file, no ATTACH, no extension, no PRAGMA but `foreign_keys`, a 2 s limit for building
and querying together, caps on the size of a value, the database, the script, the query and the result, one statement,
query phase read-only. A row is kept only when the schema and the query run, the result is not empty, a second teacher
answer to the same schema and question runs and returns the same result set (as a multiset; in order when either query
has a top-level ORDER BY), and the rubric passes. The row is the schema and question, then the query and the teacher's
short explanation. The sandbox stops the usual failures of model output (a runaway recursive query, a huge value, an
ATTACH); it is not a boundary against a hostile program. **Python and pandas are out of scope**: running model-written
Python needs a real sandbox, and no recipe asks for it. Rows longer than `max_seq_length` (768) are dropped by
`prepare.py`, which may remove the schemas with the most rows.

**Held-out evaluation.** Written by hand for this repository, never by the teacher, evaluation only (the first record of
each file says so and the loaders refuse a file without that header): `evals/data/science_eval.jsonl` has 60 four-option
questions (20 physics, 20 chemistry, 20 biology; 35 at secondary and 25 at undergraduate level; the keys are balanced, 15
per letter; every figure was recomputed when the file was written), `evals/data/data_eval.jsonl` has 5 small SQLite
databases (an observatory log, marathon results, greenhouse sensors, a bicycle repair shop, a ferry timetable; two or
three tables each) with 12 questions and a gold query each (60 in all). These files were written by an AI assistant (Claude) by hand at the
maintainer's request; they are not training data and are removed from training by 13-gram decontamination
(`decontaminate_files`). A SQL answer is scored by running it on the question's database and comparing the rows with the
gold query's (floats to six decimals; row order counts only when the gold query sorts). Suites in `evals/suites.yaml`:
`data` (40 questions, the acceptance suite of the Data recipe), `data-select` (the other 20, by `skip: 40` at the same
seed), and `science-local` (the 60 science questions, reported beside `science`, which stays the MMLU-Pro acceptance suite;
`science` and `science-select` are unchanged). `run_specialist.sh` runs `science,general` and `data,general`; add
`--suites science-local` or `data-select` by hand.

**Disjoint from training.** Each science question carries a `topic` and each database a `domain`; none is one of the
training labels or a close rewording of one (`tests/test_heldout_evals.py`: no label inside the other's content words, or
half of the words shared; no label appears as a phrase in any question), and a test finds any declared human seeds file
that shares a 13-gram with an eval prompt (none exists). That is a check on wording: the questions are still in the same
broad subjects as the labels (a question about the density of a gas is held out, "gas laws" is a label), which is what
measuring the specialist needs. The 13-gram decontamination at `prepare.py` removes overlapping text.

**What 40 data questions can show.** Acceptance asks for a gain of at least 3 points with McNemar's exact p ≤ 0.05 on
the `data` suite, and the general suite not dropping by more than 1.5 points. With 40 paired questions the exact test
needs at least 6 improved questions and no regression (p = 0.031; 5 gains give p = 0.0625): a gain of 15 points. A smaller
real improvement cannot be told from noise on this file, and a recipe rejected on it may not be a bad recipe. The
thresholds were not changed.

**Tested (no network, no model).** `tests/test_sql_sandbox.py` (limits, refusals, extraction, comparison),
`tests/test_distill_topics.py` (topic files and the lockdown of `seeds` in `distill.py` and `prepare.py`; a fake teacher
through every drop reason of the multiple-choice and SQL checks; no label in any row, `meta` or answer request; the license
gate on a fake Hub response for each recipe's teacher; marketing, science and data from `distill.py` to the training files
and the manifest with the real recipes and topic files), and `tests/test_heldout_evals.py` (the files, their disjointness
from the labels, the scorer, the suites, a scripted run of the harness, and one dry run of `evals/run_eval.py` on the
`science-local` suite against a real `llama-server` with the random-weight GGUF of the integration tests; the data prompts
are longer than that model's 2,048-token context, so the SQL path is the scripted run). **Not done:** no real teacher
was run, nothing was distilled and nothing trained, so how many rows a teacher keeps, the quality of its questions and
whether any recipe improves its suite are all unmeasured. That run is for the Mac:
`mlx_lm.server --model mlx-community/Qwen3.6-35B-A3B-4bit --port 8090`, then
`training/scripts/run_specialist.sh science ~/src/llama.cpp ~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf` (and `data`, `marketing`).

## 3. What makes a result valid

- Checkpoint sweeps now write `sweep/inputs.json` **before** any export/evaluation: SHA-256 of
  the base GGUF, selected checkpoints, adapter configuration, recipe, run record, suite definitions,
  converter, available local evaluation sources and exported GGUFs. A retry checks those bytes before
  reusing work. New candidates can be added; existing inputs cannot be silently replaced. A changed
  input/export or an old sweep without this receipt stops with a `sweep provenance` error and retains
  the evidence. Do not manufacture a receipt for an old result or delete it to bypass the check.
  Preserve the original experiment; a deliberate new experiment needs its own record and must respect
  the separation of selection and acceptance data. Hashing is streamed, including the base GGUF.
  This checks local input identity, not scientific correctness or a signed provenance chain; remote
  dataset/model repository revisions and runtime dependencies still need separate review.
- Direct `run_eval.py --resume` has its own `inputs.json`: it pins local model/adapter bytes,
  generation settings, dataset/suite definitions, the **actual selected questions and answers**,
  specialist instructions and the server build. Existing adapters must match; additional adapters
  can be evaluated without regenerating complete groups. A fresh `--out` cannot overwrite results.
  Each completed group is committed atomically, so a failure while adding another group retains
  the previous predictions. A legacy run without a receipt is preserved but cannot be resumed.
  `--server-url` remains available for fresh runs; resuming it is refused because an independently
  managed server's model name/build does not establish the identity of its weights. Acceptance
  requires a loaded adapter; a local server must report the adapters requested on the command line.
- `fix_forgetting.py` now pins its model, recipe, converter and workflow inputs before its first
  command. Every completed step records artifact hashes; they are checked before skipping work or
  reporting an accepted result, including after the first round has moved into its archive. Prepared
  data and replay files cannot silently change before training resumes. `--dry-run` validates existing
  receipts without writing them. Legacy step records need the intact original experiment, not a
  manufactured receipt. Existing replay files supplied at the start retain their original generation
  provenance; hashing them does not prove which teacher produced them. `--rescore` is a separate
  explicit operation, not covered by the resume contract. These local receipts are not signatures.
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
