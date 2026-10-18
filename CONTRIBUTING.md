# Contributing to SPIKE

SPIKE follows the [Superpowers](https://github.com/obra/superpowers) way of working: design before code,
small verifiable steps, tests first, and no claim without evidence.

## Workflow

1. **Brainstorm**: open an issue describing the problem, the user-visible behaviour you want and the
   alternatives you considered. For model work include the hypothesis and how it will be measured.
2. **Plan**: list the files you will touch and how each step will be verified.
3. **Test first**: write the failing test (or eval) that shows the bug or the missing behaviour, watch it
   fail, then implement until it passes. Bug fixes without a reproducing test are not merged.
4. **Verify before claiming**: run `ruff check .`, `pytest`, and in `web/` `npx vitest run && npm run build`.
   If your change touches llama.cpp integration or adapter export, also run the integration tests
   (see below). Paste the commands and results in the PR.
5. **Review**: PRs are reviewed against the plan; critical findings block the merge.

## Integration tests

```bash
export SPIKE_LLAMA_SERVER=/path/to/llama-server           # real server, tiny random model
export SPIKE_LLAMA_CPP=/path/to/llama.cpp                  # checkout with convert_lora_to_gguf.py
export SPIKE_CONVERT_PYTHON=/path/to/python                # interpreter with torch, transformers, gguf
pytest tests/test_llamacpp_integration.py tests/test_export_integration.py
```

## Rules for model and data contributions

- Every data source goes in `training/datasets.yaml` with its license and role; only allowlisted licenses
  may be used for training (`training/spike_train/licenses.py`). No outputs of models whose terms forbid
  training competing models.
- Every adapter has a config with a hypothesis and an `acceptance` block, written before training.
- Results are reported with hardware, versions and settings, as produced by the scripts. Never edit numbers
  by hand, never report smoke runs as results, and keep measured, computed and third-party figures apart.
- Evaluation data must never be trained on; `prepare.py` decontaminates automatically, do not bypass it.

## Style

Python 3.11+, Ruff (`pyproject.toml`), type hints on public functions, comments only where the code is not
self-explanatory. TypeScript strict mode. Keep the UI honest: every control must be wired to real behaviour.

## Reverse engineering

Use [REA](https://github.com/morluto/rea) only on software you own or are authorized to analyse (for example
SPIKE's own builds). Do not copy proprietary code, assets or branding from other products.
