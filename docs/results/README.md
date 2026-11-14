# Specialist results / Resultados de los especialistas

`specialists.json` holds every specialist's measured results, built by `python scripts/results_index.py` from the
evidence committed here (CI fails when it is out of date; schema:
[../schemas/specialist-results.schema.json](../schemas/specialist-results.schema.json)). Nothing in it is estimated.

- `benchmarks`: each eval task, with the public dataset, split, license, categories and the seeded sample size.
- `specialists.<id>.status`: `adapter_accepted` (an adapter passed its acceptance gate and is the one installed) or
  `base_profile` (it answers as an instruction profile on the base model).
- `specialists.<id>.rounds`: one entry per sweep of a training round (`round` counts training runs; two sweeps of one
  run share it): every candidate tried with its selection result, the chosen one, the verdict and its reasons.
- `rounds[].final`: the acceptance run on the chosen candidate: base and adapter on the same questions per suite and
  per task (`n`, `correct`, `accuracy`, `ci95`, `unparsed`, `truncated`), `delta_points` and the paired `p_value`,
  the protocol (model file, llama.cpp build, greedy, thinking off, max tokens, seed, zero-shot), and, when
  `evals/export_questions.py` has been run, `questions` (one line per answer: item id, variant, topic, gold, parsed,
  correct, truncated) and `topics` (per task and topic: `n`, `base_correct`, `adapter_correct`). A pairwise round
  (marketing) has `pairwise` instead: wins, losses, ties, win rate and sign test against the base model.
- `rounds[].final.rescored`: the same saved answers re-read by a later answer extractor (`run_eval.py --rescore` on a
  copy named `<final>-rescored`), with the same fields; `null` until that copy is committed. The verdict stays the
  original run's.

**Reading it next to other models.** Each number is a seeded sample of a public test, answered zero-shot with greedy
decoding and SPIKE's own answer extractor; `unparsed` answers count as wrong (for example 409 of 1000 base answers on
MedMCQA, which lowers the base score; `rescored` shows the numbers with the extractor of M14). A published score of another model is
comparable only on the same dataset, split, subset and metric, and its protocol (shots, chain of thought) should be
named next to it with its link and date; anything else is "no comparable data", not a comparison.

`specialists.json` reúne los resultados medidos de cada especialista, generado por `scripts/results_index.py` a partir
de las pruebas guardadas en el repositorio. Una puntuación publicada de otro modelo solo es comparable en el mismo
conjunto, partición, subconjunto y métrica, citada con su enlace, fecha y protocolo.
