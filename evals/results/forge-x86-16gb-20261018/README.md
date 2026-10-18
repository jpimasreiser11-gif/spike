# Forge vs the core model alone, 16 GB x86, CPU only

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
  accents (`\xa1`, `\xf1`, `\xe9`) instead of removing them. The checker, which reads the files but does not run
  them, passed it in one round.
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
