#!/usr/bin/env bash
# Requiere llama-server YA iniciado. Solo conexiones HTTP a loopback.
set -euo pipefail
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: Python 3 no disponible" >&2
  exit 1
fi
exec python3 "$script_dir/http_probe.py" "$@"
