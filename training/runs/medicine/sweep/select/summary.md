# SPIKE eval 20261102-185716

Model `Qwen3.5-4B-Q4_K_M.gguf`, llama.cpp `b11669-620d2225c`, greedy, thinking off, max_tokens 2048, host `macOS-27.0-arm64-arm-64bit`.

| task | variant | n | accuracy | 95% CI | Δ vs base (pts) | McNemar p | unparsed | truncated |
|---|---|---|---|---|---|---|---|---|
| medmcqa-val-select | base | 400 | 0.273 | 0.231–0.318 |  |  | 154 | 9 |
| medmcqa-val-select | spike-medicine-it13270-s0.5 | 400 | 0.615 | 0.566–0.661 | +34.25 | 0 | 10 | 12 |
| medmcqa-val-select | spike-medicine-it1600-s1 | 400 | 0.470 | 0.422–0.519 | +19.75 | 0 | 68 | 70 |
| medmcqa-val-select | spike-medicine-it3400-s1 | 400 | 0.570 | 0.521–0.618 | +29.75 | 0 | 19 | 19 |
| medmcqa-val-select | spike-medicine-it6600-s1 | 400 | 0.530 | 0.481–0.578 | +25.75 | 0 | 29 | 29 |
| mmlu-pro-general-select | base | 400 | 0.642 | 0.594–0.688 |  |  | 0 | 13 |
| mmlu-pro-general-select | spike-medicine-it13270-s0.5 | 400 | 0.642 | 0.594–0.688 | +0.00 | 1 | 0 | 22 |
| mmlu-pro-general-select | spike-medicine-it1600-s1 | 400 | 0.525 | 0.476–0.574 | -11.75 | 4e-06 | 19 | 19 |
| mmlu-pro-general-select | spike-medicine-it3400-s1 | 400 | 0.562 | 0.513–0.610 | -8.00 | 0.001601 | 8 | 8 |
| mmlu-pro-general-select | spike-medicine-it6600-s1 | 400 | 0.570 | 0.521–0.618 | -7.25 | 0.004226 | 15 | 17 |
| pubmedqa-labeled-select | base | 200 | 0.415 | 0.349–0.484 |  |  | 0 | 0 |
| pubmedqa-labeled-select | spike-medicine-it13270-s0.5 | 200 | 0.745 | 0.680–0.800 | +33.00 | 0 | 0 | 0 |
| pubmedqa-labeled-select | spike-medicine-it1600-s1 | 200 | 0.735 | 0.670–0.791 | +32.00 | 0 | 0 | 0 |
| pubmedqa-labeled-select | spike-medicine-it3400-s1 | 200 | 0.750 | 0.686–0.805 | +33.50 | 0 | 0 | 0 |
| pubmedqa-labeled-select | spike-medicine-it6600-s1 | 200 | 0.740 | 0.675–0.796 | +32.50 | 0 | 0 | 0 |
| **general-select (pooled)** | base | 400 | 0.642 | 0.594–0.688 |  |  | 0 | 13 |
| **general-select (pooled)** | spike-medicine-it13270-s0.5 | 400 | 0.642 | 0.594–0.688 | +0.00 | 1 | 0 | 22 |
| **general-select (pooled)** | spike-medicine-it1600-s1 | 400 | 0.525 | 0.476–0.574 | -11.75 | 4e-06 | 19 | 19 |
| **general-select (pooled)** | spike-medicine-it3400-s1 | 400 | 0.562 | 0.513–0.610 | -8.00 | 0.001601 | 8 | 8 |
| **general-select (pooled)** | spike-medicine-it6600-s1 | 400 | 0.570 | 0.521–0.618 | -7.25 | 0.004226 | 15 | 17 |
| **medicine-select (pooled)** | base | 600 | 0.320 | 0.284–0.358 |  |  | 154 | 9 |
| **medicine-select (pooled)** | spike-medicine-it13270-s0.5 | 600 | 0.658 | 0.620–0.695 | +33.83 | 0 | 10 | 12 |
| **medicine-select (pooled)** | spike-medicine-it1600-s1 | 600 | 0.558 | 0.518–0.598 | +23.83 | 0 | 68 | 70 |
| **medicine-select (pooled)** | spike-medicine-it3400-s1 | 600 | 0.630 | 0.591–0.668 | +31.00 | 0 | 19 | 19 |
| **medicine-select (pooled)** | spike-medicine-it6600-s1 | 600 | 0.600 | 0.560–0.638 | +28.00 | 0 | 29 | 29 |
