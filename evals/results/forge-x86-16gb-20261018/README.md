# Forge vs the core model alone, 16 GB x86, CPU only

Four runs: run 1 (this folder's `forge-eval.json`), run 2 (`run2/`), run 3 (`run3/`) and run 4 (`run4/`), the last
three with every task's files.

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

Both runs together, without run 1's cafeteria: Forge 15/19, the core model alone 16/19 (2 tasks only Forge passed,
3 only the core passed). No difference is shown; Forge costs 6.5–8.3 times the time.

## Run 3

SPIKE at commit `0d3b244`, after the fixes run 2 pointed to: the checker reads the saved text files and may call a
number wrong only by showing the calculation, the last allowed agent step answers without tools, a one-step plan
answers with its own summary, and the planner and steps keep the task's formats word for word.

| mode | passed | 95 % CI | total time |
|---|---|---|---|
| Forge | 8/10 | 49–94 % | 13,012 s (3.6 h) |
| core model alone | 9/10 | 60–98 % | 3,546 s (59 min) |

Forge failed `slug` (`NameError: name 'ACCENTOS' is not defined`, a typo for `ACENTOS` that the checker passed) and
`campana` (objects again). The core model alone failed `ventas` (it never saved ventas.csv). The checker sent work
back in one task (prestamo, once) instead of 4–5, so the false rejections are gone, but Forge's total time did not
drop: slug, cafeteria and ventas each took 34–50 minutes in a single round. The core model alone was slower than in
runs 1–2 (shared VM), so the 3.7× ratio is not a speed-up.

All three runs, without run 1's cafeteria: Forge 23/29, the core model alone 25/29 (3 task runs only Forge passed, 5
only the core passed; McNemar exact p ≈ 0.73). With this model Forge does not beat the model alone.


## Run 4

SPIKE at commit `35347ff`: before the checker, Forge now runs its own checks on the saved files (Python compiles,
reads no name it never defines and imports without its `__main__` block; JSON and CSV parse; text is not empty) and
sends a failure back for rework. Same machine and model. The container restarted during `campana`, so the run is in
two parts: `part1/` (fizzbuzz to email; the process died before writing its JSON, so these results come from its
log, with every task's files and traces kept) and `part2/` (`--only campana,quiz,cafeteria,ventas`, its own JSON;
campana run again in both modes). `forge-eval.json` merges them.

| mode | passed | total time |
|---|---|---|
| Forge | 9/10 | 8,471 s (2.4 h) |
| core model alone | 9/10 | 1,424 s (24 min) |

Both failed `campana` only: Forge's `canales` is again a list of objects (name, reason, format, frequency, budget
share), and the core model's message was too long. The program checks ran on every saved file in every round and
never failed, so they sent nothing back (slug.py was right this time). Forge's rework came from its checker: primos
once (the file was still empty), facturas twice, rejecting a CSV that the task's own check passes, which took
facturas to 3,266 s. Forge was 5.9 times slower.

All four runs, without run 1's cafeteria: Forge 32/39, the core model alone 34/39; run 4 has no task that only one
mode passed, so the paired test is unchanged (3 task runs only Forge passed, 5 only the core; McNemar exact
p ≈ 0.73). With this model Forge still does not beat the model alone, and it is not announced.
