# M6: five remaining candidate recipes

These are **data contracts**, not trained specialists or measured improvements. Source cards and metadata were
inspected on 2026-10-30; Claude reviewed every source on 2026-11-02 (M7: license, card, Hub commit and every row; see
docs/TRAINING.md, "License review of the M5 and M6 sources") and all ten below are `license_status: verified`. Nothing
was trained.

| Specialist | Candidate / original provenance | Published license | Scope and held-out pool |
|---|---|---|---|
| Education | [QASC, Ai2](https://huggingface.co/datasets/allenai/qasc) | CC BY 4.0 | Eight-choice school science QA; train / validation |
| Core | [CommonsenseQA, TAU](https://huggingface.co/datasets/tau/commonsense_qa) | MIT | Crowd-authored common-sense QA; train / validation |
| Business | [BANKING77, PolyAI](https://huggingface.co/datasets/PolyAI/banking77) | CC BY 4.0 | Banking support intent classification; train / test |
| Security | [Phishing URL mirror](https://huggingface.co/datasets/pirocheto/phishing-url), Hannousse & Yahiouche (2021), [paper](https://arxiv.org/abs/2010.12847) | CC BY 4.0 | Historical URL-text classification; train / test |
| Writing | [BillSum, FiscalNote](https://huggingface.co/datasets/FiscalNote/billsum), [original repository](https://github.com/FiscalNote/BillSum) | CC0 1.0 | US legislative summary → title; train / test; no California split |

These published declarations are evidence for review, not a redistribution audit. BANKING77's 77 class names are
schema identifiers, taken from its card; credit Casanueva et al., *Efficient Intent Detection with Dual Sentence
Encoders* (2020), and [the upstream dataset](https://github.com/PolyAI-LDN/task-specific-datasets).
No third-party implementation or corpus is bundled. No teacher-generated answers are added. Inline test rows are
original fixtures for software tests only, never exported as training or acceptance data.

QASC facts and preformatted questions are omitted to avoid exposing annotated support. CommonsenseQA omits the
annotated concept. Business labels are not bank policy, financial advice or approved responses. The security
converter only formats stored strings: no URL is visited, HTML rendered, external feature requested or code run.
Do not infer live safety from a historical label. Check same-domain leakage and temporal validity before a real
security evaluation; 13-gram decontamination alone does not establish either. Validate the mirror against the
original grant and split. Review CommonsenseQA's upstream ConceptNet attribution.

Writing deliberately uses an existing human summary as input and its original title as target. Feeding a truncated
bill with a summary describing unseen sections would create unsupported supervision. This recipe instead drops
long chats through the existing 768-token limit. It is not a corpus for arbitrary creative writing or full-document
summarization. Coverage and retained counts require real-source review. The small-model memory target is unmeasured.

## Selection versus acceptance

| Pool | Acceptance sample | Selection sample after the acceptance slice |
|---|---:|---:|
| QASC validation | 600 | skip 600, n 250 |
| CommonsenseQA validation | 800 | skip 800, n 300 |
| BANKING77 test | 1,200 | skip 1,200, n 600 |
| Phishing URL test | 1,200 | skip 1,200, n 600 |
| BillSum test | 600 | skip 600, n 300 |

The same seed (default 0), source revision and formatter must be used for both pools. Budgets are configuration,
not observed valid row counts. The entire held-out source and the existing MMLU-Pro general pool are included in
training decontamination, not just the selected sample. Shared instructions and the business label list are removed
before 13-gram matching, so boilerplate does not reject all rows. Common data content is not removed from that index.
Human OASST2 replay, the general regression limit and the existing small-batch recipe remain intact.

## Writing uses pairwise review

Exact title equality is only a diagnostic and a way to load reproducible source prompts. It is not writing quality.
`run_eval.py --acceptance training/configs/writing.yaml` cannot accept the recipe from literal results or general
regression alone. The guard also prevents the same erroneous path for the existing marketing pairwise recipe;
no thresholds are changed. Use the existing pairwise evaluator and its swapped-order judgment, significance check,
and general regression. Only an authorized local/open judge is appropriate; no paid API is configured by this task.
Human review of factual faithfulness, useful compression and readability still belongs to final model acceptance.

After Claude has reviewed and enabled the sources, prepare two distinct prompt files (these commands were not run
against real sources or models):

```sh
python evals/export_prompts.py --suite writing-select --seed 0 --out evals/results/writing-select.jsonl
python evals/export_prompts.py --suite writing --seed 0 --out evals/results/writing-final.jsonl
```

The exporter refuses to replace an existing file. It saves source item IDs, prompts, suite and seed; no target title
enters the judge's prompt. Use `writing-select.jsonl` to choose a candidate, then the final file once. Run the
existing general suite for that adapter, then `evals/pairwise.py --specialist writing --prompts ... --acceptance
training/configs/writing.yaml --general-eval ...` with the reviewed model, adapter and judge options. The hypothesis
uses the existing marketing pattern: win rate ≥ 0.60, paired sign-test p ≤ 0.05, general drop ≤ 1.5 points. None of
these numbers is a measured result. The other four candidate recipes inherit M5's hypotheses unchanged.

## Science, Data and Marketing: distilled, seeded by topic labels (M10)

These three have no human-written domain source (OpenBookQA and WikiSQL were rejected by the M7 license review; Marketing
never had one), so their recipes keep `domain_sources: []` and take their domain data from verified distillation by an open
teacher (`training/distill.py`, `Qwen/Qwen3.6-35B-A3B` unless told otherwise; its Hub license is read before any task is
sent). The five recipes above add no teacher-generated answers; these three are the exception.

No text written by Claude, GPT, Gemini or Llama may become training data, and seeds or prompts written by an AI assistant
count as such text. None of the three therefore has seed prompts. Each has a file of short topic labels
(`training/topics/marketing.yaml`, `science.yaml`, `data.yaml`; 90, 107 and 64 labels) under a provenance saying that an
AI assistant chose them and that they are instructions to the teacher only: the teacher writes every task from a label and
then the answers, and no label is copied into a task, an answer, a row or its `meta`. The 24 AI-written marketing seeds
(`training/seeds/marketing.jsonl`) are removed. `distill.seeds` still exists, only for a file whose first line declares a
human author; `distill.py` and `prepare.py` refuse a seeds file without it.

- **Science** (`kinds: {mcq: 0.6, explanation: 0.4}`): multiple-choice rows are kept only when two independent teacher
  answers (the second with the options in another order) agree with the keyed option and the rubric passes; explanation
  rows when the rubric passes. Evaluated on MMLU-Pro physics, chemistry and biology as before, with
  `evals/data/science_eval.jsonl` (60 hand-written questions, suite `science-local`) beside them.
- **Data** (`kinds: {sql: 1}`): the teacher writes a SQLite schema with INSERT rows, a question and the query; a row is kept
  only when everything runs in an in-memory `sqlite3` database (no ATTACH, no extension, time limit), the result is not
  empty and an independent second answer returns the same rows. Python and pandas are out of scope (running model-written
  Python needs a real sandbox). Evaluated by executing the model's SQL on the 5 databases of `evals/data/data_eval.jsonl`
  (suite `data`: 40 questions; `data-select`: the other 20); 40 questions need at least 6 net improved questions for
  p ≤ 0.05.
- **Marketing** (`kinds: {open: 1}`): rubric-filtered answers to tasks the teacher wrote from the labels; evaluated by the
  pairwise judge as before.

The evaluation files are written by hand for this repository, never by the teacher, and evaluation only. The recipes are
tested with a fake teacher (`tests/test_distill_topics.py`); no real teacher run, distillation or training has happened.
Details and limits: docs/TRAINING.md, 2d.

## Candidates not selected

- WikiSplit has CC BY-SA 4.0, outside SPIKE's current training allowlist; that policy was not expanded.
- CodeXGLUE defect detection declares C-UDA, also outside the current allowlist.
- GLUE/CoLA declares `other`; UCI SMS Spam declares `unknown` in Hub metadata. Neither is silently overridden.
- WinoGrande lacks a license in the inspected Hub metadata; it was replaced by CommonsenseQA.
- Social IQa mentions machine-generated distractors; that provenance needs a separate review.
- PhiUSIIL cleaned separates labels/features into NumPy files; the existing loader does not safely join that schema.
- The combined phishing mirror requires `trust_remote_code=True`; no such execution is enabled.
- Poetry sentiment is a classifier, not a sufficient measure of writing quality; it does not gate Writing.

For actual training Claude must verify licenses, source revisions, labels, language coverage (these new sources are
English), duplication, retained counts and bias. Improving Spanish, full-domain quality and agent reliability needs
additional validated data and task evaluations. All specialists remain profiles until measured acceptance.
