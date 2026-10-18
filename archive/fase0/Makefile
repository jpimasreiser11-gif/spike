.PHONY: preflight bench eval test

# Phase 0 targets. They cannot certify product quality without real model evidence.
# BENCH_URL must reference an already running llama-server on localhost.
BENCH_URL ?= http://127.0.0.1:8080
BENCH_MODEL ?=
BENCH_SHA256 ?=
BENCH_REPOSITORY ?=
BENCH_REVISION ?=
BENCH_RUNS ?= 5
BENCH_DRAFT ?=
BENCH_DRAFT_SHA256 ?=

preflight:
	bash scripts/phase0/preflight.sh

bench:
	@if [ -n "$(BENCH_MODEL)" ]; then \
	  if [ -n "$(BENCH_DRAFT)" ]; then \
	    python3 scripts/phase0/run_cpu_benchmark.py \
	      --model "$(BENCH_MODEL)" --sha256 "$(BENCH_SHA256)" \
	      --upstream-repository "$(BENCH_REPOSITORY)" --upstream-revision "$(BENCH_REVISION)" \
	      --runs "$(BENCH_RUNS)" --draft "$(BENCH_DRAFT)" --draft-sha256 "$(BENCH_DRAFT_SHA256)"; \
	  else \
	    python3 scripts/phase0/run_cpu_benchmark.py \
	      --model "$(BENCH_MODEL)" --sha256 "$(BENCH_SHA256)" \
	      --upstream-repository "$(BENCH_REPOSITORY)" --upstream-revision "$(BENCH_REVISION)" \
	      --runs "$(BENCH_RUNS)"; \
	  fi; \
	else \
	  bash scripts/phase0/smoke_http.sh --url "$(BENCH_URL)"; \
	fi

eval:
	python3 scripts/phase0/gate_report.py

test:
	python3 -m unittest discover -s tests/gates -p 'test_*.py' -v
	python3 -m unittest discover -s tests/phase0 -p 'test_*.py' -v
