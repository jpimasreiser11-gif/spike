#!/usr/bin/env bash
# Fase 0 Spike: inspección local, sin red, instalaciones ni modelos.
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "Uso: bash scripts/phase0/preflight.sh" >&2
  exit 2
fi

os_name=$(uname -s)
architecture=$(uname -m)
case "$os_name" in
  Darwin)
    ram_bytes=$(sysctl -n hw.memsize)
    cpu_count=$(sysctl -n hw.logicalcpu)
    ;;
  Linux)
    ram_bytes=$(awk '$1=="MemTotal:" {printf "%.0f", $2*1024}' /proc/meminfo)
    cpu_count=$(getconf _NPROCESSORS_ONLN)
    ;;
  *) echo "FAIL: sistema operativo no contemplado: $os_name" >&2; exit 1 ;;
esac

if [[ ! "$ram_bytes" =~ ^[0-9]+$ || "$ram_bytes" -eq 0 ]]; then
  echo "FAIL: no se pudo medir la memoria física" >&2
  exit 1
fi

echo "SO: $os_name / $architecture"
echo "CPU lógicas: $cpu_count"
echo "RAM física: $ram_bytes bytes"
echo "Objetivo CPU sin GPU dedicada y 16 GB: PENDIENTE de verificar en el hardware objetivo"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: falta Python 3 para la prueba HTTP" >&2
  exit 1
fi
python3 --version

if ! command -v llama-server >/dev/null 2>&1; then
  echo "FAIL: llama-server no está en PATH" >&2
  exit 1
fi
llama-server --version

if ! flags=$(llama-server --help 2>&1); then
  echo "FAIL: llama-server --help ha fallado" >&2
  exit 1
fi

missing=0
for option in --ctx-size --n-gpu-layers --parallel --lora --lora-init-without-apply --spec-draft-model --spec-type --cache-ram --no-cache-prompt --no-mmproj; do
  if [[ "$flags" == *"$option"* ]]; then
    echo "FLAG OK: $option"
  else
    echo "FLAG FAIL: $option" >&2
    missing=1
  fi
done

python3 - <<'PY'
from importlib import metadata
for name in ("mlx", "mlx-lm", "unsloth", "transformers", "peft"):
    try:
        print(f"DEPENDENCIA {name}: {metadata.version(name)}")
    except metadata.PackageNotFoundError:
        print(f"DEPENDENCIA {name}: no instalada en este intérprete (informativo)")
PY

if [[ "$missing" -ne 0 ]]; then
  echo "FAIL: faltan flags requeridas en llama-server" >&2
  exit 1
fi
echo "PASS: preflight de herramientas; NO acredita que el modelo funcione ni cumpla 16 GB"
