# SPIKE eval 20261017-172047

Model `Qwen3.5-4B-Q4_K_M.gguf`, llama.cpp `b11669-620d2225c`, greedy, thinking off, max_tokens 512, host `macOS-27.0-arm64-arm-64bit`.

| task | variant | n | accuracy | 95% CI | Δ vs base (pts) | McNemar p | unparsed | truncated |
|---|---|---|---|---|---|---|---|---|
| medmcqa-val | base | 1000 | 0.242 | 0.216–0.270 |  |  | 440 | 194 |
| mmlu-pro-general | base | 800 | 0.557 | 0.523–0.592 |  |  | 105 | 166 |
| mmlu-pro-health | base | 818 | 0.248 | 0.220–0.279 |  |  | 298 | 314 |
| pubmedqa-labeled | base | 500 | 0.426 | 0.383–0.470 |  |  | 0 | 470 |
| **general (pooled)** | base | 800 | 0.557 | 0.523–0.592 |  |  | 105 | 166 |
| **medicine (pooled)** | base | 2318 | 0.284 | 0.266–0.303 |  |  | 738 | 978 |
