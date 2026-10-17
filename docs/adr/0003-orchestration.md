# ADR 0003: Orchestration with a two-stage router, a validated plan DAG and synthesis

Status: accepted (2026-10-17).

## Context

The orchestrator must pick specialists, split multi-domain work, avoid unnecessary calls and keep
instructions, all on CPUs where each LLM call costs seconds.

## Decision

1. **Stage 1, lexical router** (`spike/orchestrator/router.py`): weighted EN/ES keywords per specialist,
   accent-insensitive; zero model calls. Output: direct (no specialist), single, or multi.
2. **Stage 2, LLM planner** (`planner.py`) only when stage 1 says multi-domain or ambiguous: the core model
   writes a JSON plan constrained by a JSON schema (temperature 0, thinking off). Plans are validated
   (known specialists, backward dependencies only, size cap) with a deterministic fallback plan.
3. **Execution** (`orchestrator.py`): subtasks run by topological level, each with its specialist's
   adapter and system prompt plus the user's custom instructions; sequential on the local model (one model
   in memory), optionally parallel on API providers.
4. **Synthesis** by core only when more than one specialist contributed.
5. Every step streams as events (route, plan, subtask deltas, tool calls) that the UI shows as a trace.

Added 2026-10-17 (Collective, C2): planner subtasks have a role (research or execute), and a checker runs after
every multi-step plan: one constrained-JSON call to core per pass, sending a result with a concrete fix (and what
used it) back at most twice; deliverable files are checked by SPIKE itself. The cost is one more short call per pass
on CPU; whether it improves answers is measured by `spike forge eval --baseline`, not assumed.

Rejected: an LLM routing call on every message (adds a full model call to every turn on CPU); several
full models in memory (each 4B Q4 model is ~2.7 GB plus its own KV cache, against ~40 MB per adapter).

## Evidence

- Router on 74 hand-labelled queries (`evals/router/labeled.jsonl`, since moved to `spike/evolution/router_labeled.jsonl`), test split never used for tuning:
  primary specialist correct 46/50 = 0.92 (Wilson 95 % CI 0.81–0.97), exact set 40/50 = 0.80 (0.67–0.89);
  dev split 22/24 primary. Measured by `tests/test_core.py`.
- Planner, plan validation, DAG execution and synthesis are covered by unit tests with scripted providers.
- **Not yet measured**: end-to-end quality of orchestrated answers vs. a single model with real weights.
