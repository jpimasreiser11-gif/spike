# SPIKE specialists

The catalogue matches the 13 specialists of the brand proposal. Every specialist shares the same base
(Qwen3.5-4B) and differs by its LoRA adapter, system prompt, tools and routing keywords. A specialist
without an accepted adapter runs as a **prompt profile** and is shown with a β badge; the app never
presents it as trained.

## Points common to every specialist

| # | Point | Answer |
|---|---|---|
| 3 | Base model | Qwen3.5-4B ([ADR 0001](adr/0001-base-model.md)) |
| 4 | Method | bf16 LoRA r16/alpha 32 on mlx-lm, attention (full-attention layers) + MLP, prompt masked ([ADR 0002](adr/0002-training-method.md)) |
| 6 | Licenses | only allowlisted licenses (Apache-2.0, MIT, BSD, CC-BY-4.0, CC0, ODC-By, Llama 3.1 outputs with attribution); re-checked on the Hub per run |
| 7–8 | Quality and cleaning | format filters (e.g. MedMCQA explanations ≥ 40 chars), exact-dedupe, 13-gram decontamination against every eval set (templates excluded), length and encoding checks |
| 9 | Reasoning | explanation-rich targets; optional verified teacher reasoning (`--keep-reasoning`); thinking mode stays available at inference |
| 11 | Reliability | sensitive specialists show a limitations notice and their prompts require stating uncertainty; exact-answer evals report unparsed and truncated answers separately |
| 13 | Memory | one shared base in memory; each adapter ≈ 42 MB at f16 (computed); no reload on switch |
| 14 | Orchestrator | weighted EN/ES keywords for the router; tool allowlist; bindable to any provider/model |
| 15 | Maintenance | each adapter is reproducible from its config + manifest (data hashes) + `run.json`; retrain when the base changes |
| — | General ability | 30–35 % general replay in every training mix; acceptance requires ≤ 1.5 points drop on the general suite |

## Per specialist

| Specialist | Scope (1–2) | Sensitive | Training recipe (5) | Evaluation (10) | Status |
|---|---|---|---|---|---|
| Spike Core | general reasoning, planning, synthesis | no | none shipped: it is the base model (`core.yaml`, CommonsenseQA, is an M6 candidate only, never trained) | `general` suite; `core` / `core-select` for that candidate | base |
| Spike Medicine | clinical reasoning, pharmacology, physiology, diagnostics, EBM | **yes** | `training/configs/medicine.yaml`: MedMCQA train with explanations (24k) + PubMedQA artificial (6k) + 30 % replay | MedMCQA validation (1k), PubMedQA labeled (500), MMLU-Pro health; ≥ +3 pts, p < 0.05 | round 1 **rejected** (medicine +31.9 pts, general −7.6, limit −1.5); round 2 **accepted** 2026-11-05: medicine +35.07 pts, general −0.62, with self-generated replay, the domain sampled to keep 30 % replay and LoRA scale 0.5 in the GGUF; not published yet ([STATUS](STATUS.md)) |
| Spike Finance | analysis, accounting, valuation, corporate and personal finance | **yes** | `finance.yaml`: FinQA train (MIT, 5,367 chats after the checks below) + TAT-QA train (MIT, 7,064) + up to 8,000 Sujet-Finance rows (the 4 of its 18 upstream datasets whose licenses were audited: 2,000 each) + 30 % replay (`max_seq_length: 1536` in round 2). FinQA and TAT-QA come from files pinned by commit and sha256; FinQA rows whose own arithmetic is wrong (385 of 6,251) are dropped | FinQA test (600, gold-facts setting: the supporting facts are in the prompt, so not comparable with retriever-based leaderboards) and TAT-QA test (600), exact answers; MMLU-Pro business + economics; ≥ +3 pts, p < 0.05; general suite may drop ≤ 1.5 | round 1 (768-token window) **rejected** 2026-11-09 (best candidate +5.17 finance, −3.00 general, limit −1.5); round 2 (1536-token window) running on the Mac ([STATUS](STATUS.md)) |
| Spike Marketing | strategy, positioning, copy, SEO, campaigns, analytics | no | `marketing.yaml`: the local teacher writes ~6k tasks from 90 short topic labels (`training/topics/marketing.yaml`; no seed prompts, because no AI-written text may become training data), answers them, rubric-filtered (score ≥ 8) + 35 % replay | 24 held-out prompts, position-debiased pairwise judge, greedy answers; win rate ≥ 0.60 and sign test p ≤ 0.05, and the general suite may drop ≤ 1.5 pts (both required) | recipe ready, not trained; no teacher run yet |
| Spike Law | legal concepts, contracts, compliance, jurisdiction-aware | **yes** | `law.yaml`: CaseHOLD (`coastalcph/lex_glue`, `case_hold`, CC-BY-4.0, 45,000 train rows verified in M7) + 30 % replay | `law` suite: CaseHOLD test (600) + MMLU-Pro law (600); `law-select` (300); ≥ +3 pts, p < 0.05, general drop ≤ 1.5 | recipe ready, source verified on the Hub (M7), not trained |
| Spike Math | algebra to proofs, step-by-step, verified | no | `math.yaml`: GSM8K train (`openai/gsm8k`, MIT, 7,473 human-written rows verified in M7) + 30 % replay | `math` suite: GSM8K test (500) + MMLU-Pro math (600); `math-select` (300); ≥ +3 pts, p < 0.05, general drop ≤ 1.5 | recipe ready, source verified on the Hub (M7), not trained |
| Spike Science | physics, chemistry, biology, earth sciences | no | `science.yaml`: the local teacher writes ~6k multiple-choice and explanation tasks from 107 topic labels; a multiple-choice row is kept only when two independent answers agree with the keyed option and the rubric passes (OpenBookQA was rejected by the license review) + 30 % replay | MMLU-Pro physics, chemistry, biology; ≥ +3 pts, p < 0.05; general suite may drop ≤ 1.5; also reported: 60 hand-written questions (`science-local`) | recipe ready, not trained; no teacher run yet |
| Spike Code | writing, reviewing, debugging code | no | `code.yaml`: MBPP (`google-research-datasets/mbpp`, CC-BY-4.0, 374 train rows verified in M7) + 30 % replay | `code` suite: MBPP test (300) + MMLU-Pro computer science; `code-select` (150); ≥ +3 pts, p < 0.05, general drop ≤ 1.5 | recipe ready, source verified on the Hub (M7), not trained |
| Spike Data | SQL, modelling, analytics, statistics | no | `data.yaml`: the local teacher writes ~4k SQLite exercises (schema with rows, question, query) from 64 topic labels; a row is kept only when schema and query run in an in-memory sqlite3 database, the result is not empty and a second answer returns the same rows (WikiSQL was rejected by the license review; Python and pandas are out of scope) + 30 % replay | 40 hand-written questions over 5 small databases, scored by executing the model's SQL (`data`; 20 more in `data-select`); ≥ +3 pts, p < 0.05 (needs ≥ 6 net improved questions); general suite may drop ≤ 1.5 | recipe ready, not trained; no teacher run yet |
| Spike Education | adapted explanations, study plans, exercises | no | `education.yaml`: QASC (`allenai/qasc`, CC-BY-4.0, 8,134 train rows verified in M7) + 30 % replay | `education` suite: QASC eval (600); `education-select` (250); ≥ +3 pts, p < 0.05, general drop ≤ 1.5 | recipe ready, source verified on the Hub (M7), not trained |
| Spike Writing | drafting, editing, summarizing, translating | no | `writing.yaml`: BillSum (`FiscalNote/billsum`, CC0-1.0, 18,949 train rows verified in M7) + 30 % replay | `writing` diagnostic pool: BillSum eval (600, `writing-select` 300); acceptance requires pairwise comparison + general drop ≤ 1.5 | recipe ready, source verified on the Hub (M7), not trained; its held-out pairwise prompts (`evals/data/writing_eval.jsonl`) are not written yet, so it cannot be accepted until they are |
| Spike Business | strategy, operations, pricing, startups | no | `business.yaml`: BANKING77 (`PolyAI/banking77`, CC-BY-4.0, 10,003 train rows verified in M7) + 30 % replay | `business` suite: BANKING77 eval (1,200); `business-select` (600); ≥ +3 pts, p < 0.05, general drop ≤ 1.5 | recipe ready, source verified on the Hub (M7), not trained |
| Spike Security | secure design, vulnerability review, hardening, IR | **yes** | `security.yaml`: `pirocheto/phishing-url` (CC-BY-4.0, 7,658 train rows verified in M7, decontaminated) + 30 % replay | `security` suite: phishing-url eval (1,200); `security-select` (600); ≥ +3 pts, p < 0.05, general drop ≤ 1.5 | recipe ready, source verified on the Hub (M7), not trained |

## Risks and limitations (12)

- **Medicine**: MedMCQA reflects Indian entrance exams; accuracy on exams is not clinical safety. The adapter
  must never be presented as a medical device; the UI notice says so.
- **Finance**: Sujet aggregates sources with their own terms, so only the 4 audited upstream datasets are
  used (the exclusions are written in `datasets.yaml`); at the 768-token window (round 1, rejected) TAT-QA lost 35 % of its
  questions and 6,313 of 9,063 self-replay answers, so round 2 uses a 1536-token window; FinQA is scored with the facts
  given; regulatory and market facts change over time and the model has no live data unless the user enables `web_fetch`.
- **Marketing**: the judge is also the teacher (possible self-preference bias); 24 prompts detect only large
  effects. Human review is required before release.
- **All**: a 4B model hallucinates; exact-answer evals bound how often, pairwise evals do not.

## Adding a specialist

1. Add an entry to `catalog.yaml` (id, prompt, keywords, tools) and labelled router queries to
   `spike/evolution/router_labeled.jsonl` (dev and test). Keywords match whole words, so list the inflected forms; the
   weight scale (4 jargon, 3 the domain, 2 ambiguous, 1-1.5 only together with another cue) is in the catalog header.
2. Register sources in `training/datasets.yaml` with license and role; write `training/configs/<id>.yaml`
   with a hypothesis and an `acceptance` block; add an eval suite to `evals/suites.yaml`.
3. Run `training/scripts/run_specialist.sh <id> …`; only an accepted run may set `adapter_status: trained`.
