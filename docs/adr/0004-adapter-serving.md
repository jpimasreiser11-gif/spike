# ADR 0004: One llama-server, all adapters loaded, explicit per-request scales

Status: accepted (2026-10-17).

## Decision

The local runtime (`spike/runtime/llamacpp_server.py`) starts one `llama-server` with the base GGUF and
every specialist adapter (`--lora … --lora-init-without-apply`, `--parallel 1`). Each request selects its
specialist with an explicit scale for **every** loaded adapter (1.0 for the selected one, 0.0 for the
rest; `spike/providers/llamacpp.py`). At startup SPIKE resets the global adapter scales to 0.

## Why (verified in llama.cpp 62318cd source and tests)

- `lora: []` (or no field) does **not** mean "base model": the server falls back to the global scales,
  which are 1.0 for every `--lora` file (`tools/server/server-context.cpp`, `launch_slot_with_task`).
  An early SPIKE version sent `[]` for the base model and therefore ran it with all adapters applied;
  `tests/test_llamacpp_integration.py::test_empty_lora_list_is_not_the_base_model` documents this.
- With an explicit list the server clears the slot's prompt cache when the adapter set changes; on the
  fallback path it does not, so a cached prefix computed with an adapter could be reused without it.
  SPIKE additionally pins slot 0, serializes requests and enables `cache_prompt` only when the adapter is
  unchanged (defense in depth).
- The integration test compares every answer of an interleaved sequence (base, finance, medicine, cache
  hits, switches in both directions) with ground truth from fresh single-adapter servers.

## Consequences

Switching specialist costs no reload; memory grows by the adapter size only (computed ~40 MB at f16 for
rank 16 on the chosen targets; to be measured). Evaluation and benchmarks use the same explicit scales.
