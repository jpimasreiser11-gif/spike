# SPIKE eval final

Model `Qwen3.5-4B-Q4_K_M.gguf`, llama.cpp `b11669-620d2225c`, greedy, thinking off, max_tokens 2048, host `macOS-27.0-arm64-arm-64bit`.

| task | variant | n | accuracy | 95% CI | Δ vs base (pts) | McNemar p | unparsed | truncated |
|---|---|---|---|---|---|---|---|---|
| medmcqa-val | base | 1000 | 0.276 | 0.249–0.304 |  |  | 409 | 24 |
| medmcqa-val | spike-medicine-it13270-s0.5 | 1000 | 0.643 | 0.613–0.672 | +36.70 | 0 | 26 | 34 |
| mmlu-pro-general | base | 800 | 0.637 | 0.604–0.670 |  |  | 10 | 37 |
| mmlu-pro-general | spike-medicine-it13270-s0.5 | 800 | 0.631 | 0.597–0.664 | -0.62 | 0.7433 | 1 | 26 |
| mmlu-pro-health | base | 818 | 0.309 | 0.279–0.342 |  |  | 241 | 27 |
| mmlu-pro-health | spike-medicine-it13270-s0.5 | 818 | 0.621 | 0.587–0.654 | +31.17 | 0 | 16 | 31 |
| pubmedqa-labeled | base | 500 | 0.422 | 0.380–0.466 |  |  | 0 | 1 |
| pubmedqa-labeled | spike-medicine-it13270-s0.5 | 500 | 0.804 | 0.767–0.836 | +38.20 | 0 | 1 | 1 |
| **general (pooled)** | base | 800 | 0.637 | 0.604–0.670 |  |  | 10 | 37 |
| **general (pooled)** | spike-medicine-it13270-s0.5 | 800 | 0.631 | 0.597–0.664 | -0.62 | 0.7433 | 1 | 26 |
| **medicine (pooled)** | base | 2318 | 0.319 | 0.301–0.339 |  |  | 650 | 52 |
| **medicine (pooled)** | spike-medicine-it13270-s0.5 | 2318 | 0.670 | 0.651–0.689 | +35.07 | 0 | 43 | 66 |

**spike-medicine-it13270-s0.5: ACCEPTED**
- medicine: +35.07 pts (need ≥ 3.0), p = 0 (need ≤ 0.05)
- general: -0.62 pts (max drop 1.5)
