# SPIKE eval 20261020-202442

Model `Qwen3.5-4B-Q4_K_M.gguf`, llama.cpp `b11669-620d2225c`, greedy, thinking off, max_tokens 2048, host `macOS-27.0-arm64-arm-64bit`.

| task | variant | n | accuracy | 95% CI | Δ vs base (pts) | McNemar p | unparsed | truncated |
|---|---|---|---|---|---|---|---|---|
| medmcqa-val | base | 1000 | 0.280 | 0.253–0.309 |  |  | 405 | 23 |
| medmcqa-val | spike-medicine | 1000 | 0.613 | 0.582–0.643 | +33.30 | 0 | 54 | 54 |
| mmlu-pro-general | base | 800 | 0.639 | 0.605–0.671 |  |  | 15 | 34 |
| mmlu-pro-general | spike-medicine | 800 | 0.562 | 0.528–0.597 | -7.62 | 2.4e-05 | 27 | 27 |
| mmlu-pro-health | base | 818 | 0.309 | 0.279–0.342 |  |  | 241 | 27 |
| mmlu-pro-health | spike-medicine | 818 | 0.567 | 0.533–0.601 | +25.79 | 0 | 66 | 67 |
| pubmedqa-labeled | base | 500 | 0.428 | 0.385–0.472 |  |  | 0 | 0 |
| pubmedqa-labeled | spike-medicine | 500 | 0.820 | 0.784–0.851 | +39.20 | 0 | 0 | 0 |
| **general (pooled)** | base | 800 | 0.639 | 0.605–0.671 |  |  | 15 | 34 |
| **general (pooled)** | spike-medicine | 800 | 0.562 | 0.528–0.597 | -7.62 | 2.4e-05 | 27 | 27 |
| **medicine (pooled)** | base | 2318 | 0.322 | 0.303–0.342 |  |  | 646 | 50 |
| **medicine (pooled)** | spike-medicine | 2318 | 0.641 | 0.622–0.661 | +31.92 | 0 | 120 | 121 |

**spike-medicine: REJECTED**
- medicine: +31.92 pts (need ≥ 3.0), p = 0 (need ≤ 0.05)
- general: -7.62 pts (max drop 1.5)
