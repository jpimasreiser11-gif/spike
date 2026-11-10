# Practice case: the "DEMO" series in paper mode

> **Simulation only.** This case uses SPIKE's paper account (simulated money). There is no real order, no broker
> account and no key. The prices in `prices.csv` are invented: they come from no real market. None of this is
> financial advice.

## Situation

You have a paper account with simulated money and a series of 60 sessions of an invented asset called DEMO. The
price rises gently for the first seven weeks and then falls. You want to practise how to reason about a decision
before making it, not to make money.

## Suggested tasks

1. **Look at the series.** Ask for a summary: first and last price, high, low and the longest run of falls.
2. **Try a simple rule.** Ask for a backtest of a two-moving-average crossover, for example 5 and 20 sessions, on
   `prices.csv`, and compare it with buy and hold.
3. **Measure the risk.** Ask for the largest drop from a peak and the typical daily move.
4. **Trade on paper.** If the rule gives a signal, ask for a small paper order with `paper_order` (no more than
   10 % of the simulated account) and ask it to explain why, what would change its mind and when to review it.
5. **Write the journal.** A short note with the decision, the reason and what you would do differently.

## Limits of the case

- Maximum size of each paper order: 10 % of the simulated account.
- No margin and no short selling.
- If anything looks like a real order, stop and say so: this project does not allow them.
- Backtests do not promise future results; always say what was not measured.
