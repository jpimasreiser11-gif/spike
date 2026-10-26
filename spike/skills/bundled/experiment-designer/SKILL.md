---
name: experiment-designer
description: Use to design a controlled experiment with hypotheses, controls and a prespecified analysis.
license: Apache-2.0
allowed-tools:
- calculator
- python
metadata:
  author: SPIKE contributors
  spike-specialists:
  - science
  spike-keywords: experimento, experiment, hipótesis, hypotheses, controles, controls, aleatorización, randomization
---

# Experiment designer

1. State the research question, falsifiable hypothesis, experimental unit and primary outcome with units.
   Separate existing evidence from assumptions and reply in the user's language.
2. Define treatment and control, randomization, blinding where possible, inclusion/exclusion rules, confounders
   and contamination risks. Explain how repeated measures and clustering affect independence.
3. Prespecify the estimand, analysis, missing-data handling, multiplicity policy and stopping rule before results.
   Calculate sample size only with explicit effect size, variance, power and error-rate assumptions; otherwise
   provide a sensitivity table or request inputs. Use calculator/python only with normal permissions.
4. Define pilot checks, calibration, reproducible recording, provenance and ethics/consent requirements appropriate
   to the proposed experiment. Do not run interventions or recruit participants.
5. Deliver a protocol, measurement sheet and decision criteria. Label exploratory work and unmeasured assumptions.
   Do not invent observations or treat a proposed design as approved research.
