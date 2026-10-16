.PHONY: preflight bench eval test

# Phase 0 targets. They cannot certify product quality without real model evidence.
# BENCH_URL must reference an already running llama-server on localhost.
BENCH_URL ?= http://127.0.0.1:8080

preflight:
	bash scripts/phase0/preflight.sh

bench:
	bash scripts/phase0/smoke_http.sh --url "$(BENCH_URL)"

eval:
	python3 scripts/phase0/gate_report.py

test:
	python3 -m unittest discover -s tests/gates -p 'test_*.py' -v
	python3 -m unittest discover -s tests/phase0 -p 'test_*.py' -v
