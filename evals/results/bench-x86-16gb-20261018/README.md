# Qwen3.5-4B on a 16 GB x86 computer, CPU only

Measured 2026-10-17/18 on a shared cloud VM: Intel Xeon with AVX-512, 4 cores, 15.7 GB RAM, no swap, Linux x86_64.

- Model: `unsloth/Qwen3.5-4B-GGUF` `Qwen3.5-4B-Q4_K_M.gguf` (2.55 GiB), SHA-256 `00fe7986…ef11a4` checked against
  Hugging Face.
- llama.cpp `b11709-62318cd57` (the CI pin) built with `-DGGML_NATIVE=ON`, CPU only.
- `spike bench --gpu-layers 0 --kv q8_0 --gen 128 --server-context 33152`, 4 threads (the server context matches
  the Mac report, so memory is comparable across prompt lengths).

| prompt | runs | TTFT (median) | prompt tok/s | generation tok/s | peak RSS | peak anonymous RSS |
|---|---|---|---|---|---|---|
| 1K | 3 | 52 s | 19.6 | 6.2 | 6,274 MiB | 3,654 MiB |
| 8K | 3 | 773 s | 10.6 | 5.1 | 6,276 MiB | 3,656 MiB |
| 32K | 1 of 3 so far | 6,143 s | 5.3 | 1.3 | 6,295 MiB | 3,675 MiB |

Reading:
- Memory fits with room to spare: what must stay in RAM (anonymous) is 3.6 GiB even at 32K; total RSS (6.1 GiB)
  includes pages of the mapped GGUF that the kernel can drop.
- Speed: up to 8K is usable (5–6 tok/s generation); a 32K prompt is not interactive on 4 cores (over 1.5 h before
  the first word). SPIKE therefore starts CPU-only machines at an 8K context (`recommend`, `spike tune`).
- The VM is shared: 1K prompt speed varied 12–41 tok/s across runs; generation was stable (5.9–6.6 tok/s).

Method: 1K and 8K ran in one llama-server process; each 32K run used a fresh process because the container
restarted during long runs, and peak memory is the maximum over those processes. The JSON is copied from the
measurement thread's folder; the two remaining 32K runs will replace it when they finish.
