---
name: decision-simulator
description: Use for business decision simulation, comparing scenarios and sensitivity under uncertainty.
license: Apache-2.0
allowed-tools:
- calculator
- python
metadata:
  author: SPIKE contributors
  spike-specialists:
  - business
  spike-keywords: decisión empresarial, escenarios de decisión, decision scenarios, business decision, simula, simulate,
    sensibilidad, sensitivity
---

# Decision simulator

1. Establish the decision owner, options (including doing nothing), horizon, constraints and success criteria.
   Ask for missing facts before presenting a recommendation. Reply in the user's language.
2. Separate supplied evidence from assumptions. For each uncertain input record units, plausible range and source.
   Build a small table of downside, central and upside scenarios; these are scenarios, not forecasts.
3. Use calculator or python through the normal permission flow for weighted comparisons and sensitivity checks.
   Only use probabilities if the user supplied them or explicitly agreed to an assumption. Do not invent precision.
4. Show which assumption changes the preferred option and where information would have the highest value.
   Include irreversible costs, operational capacity and an exit condition.
5. Deliver an option matrix, the assumptions, a conditional recommendation and a reversible next experiment.
   Never execute purchases, contact people or change business systems as part of a simulation.
