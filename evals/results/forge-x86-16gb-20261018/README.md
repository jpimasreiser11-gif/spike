# Forge vs the core model alone, 16 GB x86, CPU only

Two runs: run 1 (this folder's `forge-eval.json`) and run 2 (`run2/`, with every task's files).

## Run 1

Measured 2026-10-18 on the same cloud VM as `../bench-x86-16gb-20261018/` (Intel Xeon with AVX-512, 4 cores,
15.7 GB RAM, no swap) with the same model, Qwen3.5-4B Q4_K_M, no adapter; SPIKE at commit `ecb38a0`.
`spike forge eval --baseline`: ten tasks, each mode in a new empty folder; SPIKE checks the saved files, no model
judges them.

| mode | passed | 95 % CI | total time |
|---|---|---|---|
| Forge (blueprint, specialists, checker) | 6/10 | 31–83 % | 14,221 s (3.9 h) |
| core model alone | 9/10 | 60–98 % | 1,708 s (28 min) |

Forge failed `slug`, `email`, `campana` and `cafeteria`; the core model alone failed only `campana` (its message
has 142 characters, the task asks for fewer than 140). Forge took 8.3 times as long: its checker sent the work
back in 4 of 10 tasks (3 rounds in fizzbuzz, facturas and prestamo, 2 in ventas), and those passed in the end.

What each Forge failure shows:
- `slug`: `slugify('¡Hola, Señor Pérez!')` returned `xa1hola-se-xf1or-p-xe9rez`, the output of escaping the
  accents (`\xa1`, `\xf1`, `\xe9`) instead of removing them. The checker passed it in one round (run 2 showed it
  never saw the files, only the summaries).
- `email`: the mail has none of the apology words the task asks for (disculpa, sentimos, lamento, perdón).
- `campana`: `canales` is a list of objects (name, reason, format), not a list of channel names.
- `cafeteria`: **a bug in the eval, fixed after this run**: the check read the amount from the table's last
  column, and this table had the amount in the middle and a description last. Whether its total was right is
  unknown, because the eval deleted each task's folder. The check now accepts any column that adds up, and
  `--keep DIR` saves each task's files.

`forge-eval-timing.json` is a two-task trial run before the full one (primos and email, 2/2 in both modes); email
passed there with Forge, so it does not fail every time.

Reading: with this model on this hardware Forge does not beat the core model alone and costs much more time, so
Forge is not announced. Ten tasks give wide intervals (they overlap); the next run keeps the files to see why.

## Run 2

Same machine and model, SPIKE at commit `9869f3e` (the cafeteria check fixed, `--keep run2/runs`).

| mode | passed | 95 % CI | total time |
|---|---|---|---|
| Forge | 9/10 | 60–98 % | 12,323 s (3.4 h) |
| core model alone | 8/10 | 49–94 % | 1,885 s (31 min) |

Forge failed `campana` again (`canales` as objects); the core model alone failed `slug` (`hola--senor-perez`, after
stopping at the 8-step tool limit) and `ventas`. Forge was 1.8 to 12.9 times slower per task, even in tasks it did
in one round, because it adds a plan, a checker and a final merge, each a model call over a long prompt.

`run2/runs/<task>-forge/_forge-trace.json` holds Forge's plan and each checker verdict. They show the checker only
saw the team's summaries and file sizes and re-did sums in its head: it rejected a correct loan payment (299.71 €)
in two of three rounds and a correct invoice total (569.30 €) once, sent back work that had hit the step limit with its file
saved, and asked for quiz.json's content because it could not see it.

Both runs together, without run 1's cafeteria: Forge 15/19, the core model alone 17/19 (2 tasks only Forge passed,
3 only the core passed). No difference is shown; Forge costs 6.5–8.3 times the time.

