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
| Spike Core | general reasoning, planning, synthesis | no | none: it is the base model | `general` suite | base |
| Spike Medicine | clinical reasoning, pharmacology, physiology, diagnostics, EBM | **yes** | `training/configs/medicine.yaml`: MedMCQA train with explanations (24k) + PubMedQA artificial (6k) + 30 % replay | MedMCQA validation (1k), PubMedQA labeled (500), MMLU-Pro health; ≥ +3 pts, p < 0.05 | recipe ready, not trained |
| Spike Finance | analysis, accounting, valuation, corporate and personal finance | **yes** | `finance.yaml`: Sujet-Finance-Instruct (30k) + 30 % replay | MMLU-Pro business + economics; ≥ +3 pts, p < 0.05 | recipe ready, not trained; upstream licence audit of the 18 aggregated sources needed before release |
| Spike Marketing | strategy, positioning, copy, SEO, campaigns, analytics | no | `marketing.yaml`: 24 hand-written seeds expanded by the local teacher to ~6k tasks, rubric-filtered (score ≥ 8) + 35 % replay | 24 held-out prompts, position-debiased pairwise judge; win rate ≥ 0.60 and sign test p ≤ 0.05 | recipe ready, not trained |
| Spike Law | legal concepts, contracts, compliance, jurisdiction-aware | **yes** | not yet: needs a permissively licensed legal QA corpus | MMLU-Pro law (600) | prompt profile |
| Spike Math | algebra to proofs, step-by-step, verified | no | not yet (candidate: verified teacher distillation on numeric tasks, `distill.verify` numeric) | GSM8K (500), MMLU-Pro math (600) | prompt profile |
| Spike Science | physics, chemistry, biology, earth sciences | no | not yet | MMLU-Pro physics, chemistry, biology | prompt profile |
| Spike Code | writing, reviewing, debugging code | no | not yet | MMLU-Pro computer science; execution-based eval to add | prompt profile |
| Spike Data | SQL, modelling, analytics, statistics | no | not yet | to define (execution-based SQL eval) | prompt profile |
| Spike Education | adapted explanations, study plans, exercises | no | not yet | to define (pairwise) | prompt profile |
| Spike Writing | drafting, editing, summarizing, translating | no | not yet | to define (pairwise) | prompt profile |
| Spike Business | strategy, operations, pricing, startups | no | not yet | to define (pairwise) | prompt profile |
| Spike Security | secure design, vulnerability review, hardening, IR | **yes** | not yet | to define (CWE identification set) | prompt profile |

## Risks and limitations (12)

- **Medicine**: MedMCQA reflects Indian entrance exams; accuracy on exams is not clinical safety. The adapter
  must never be presented as a medical device; the UI notice says so.
- **Finance**: Sujet aggregates sources with their own terms; regulatory and market facts change over time
  and the model has no live data unless the user enables `web_fetch`.
- **Marketing**: the judge is also the teacher (possible self-preference bias); 24 prompts detect only large
  effects. Human review is required before release.
- **All**: a 4B model hallucinates; exact-answer evals bound how often, pairwise evals do not.

## Adding a specialist

1. Add an entry to `catalog.yaml` (id, prompt, keywords, tools) and labelled router queries to
   `spike/evolution/router_labeled.jsonl` (dev and test).
2. Register sources in `training/datasets.yaml` with license and role; write `training/configs/<id>.yaml`
   with a hypothesis and an `acceptance` block; add an eval suite to `evals/suites.yaml`.
3. Run `training/scripts/run_specialist.sh <id> …`; only an accepted run may set `adapter_status: trained`.
