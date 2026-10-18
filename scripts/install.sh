#!/usr/bin/env bash
# SPIKE installer for macOS and Linux, run from a source checkout:
#
#   scripts/install.sh            # shows each command and asks before running it
#   scripts/install.sh --yes      # runs every step without asking
#
# It installs only what it names: pipx (if missing), the SPIKE app (pipx, isolated), and llama.cpp through
# Homebrew when available. It never uses sudo and never downloads a model unless you accept that step.
set -euo pipefail
cd "$(dirname "$0")/.."

yes=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) yes=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 64 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }
# step "description" cmd args...  -> prints the command, asks, runs it. Returns 1 when skipped.
step() {
  local what="$1"; shift
  printf '\n== %s\n   $ %s\n' "$what" "$*"
  if (( ! yes )); then
    local answer
    read -r -p "   Run it? [y/N] " answer </dev/tty || answer=""
    [[ "$answer" == [yY]* ]] || { echo "   skipped"; return 1; }
  fi
  "$@"
}

echo "SPIKE installer ($(uname -s) $(uname -m))"

# 1. Python 3.11+
py=""
for c in python3.13 python3.12 python3.11 python3; do
  if have "$c" && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then py="$c"; break; fi
done
[[ -n "$py" ]] || die "Python 3.11 or newer is required (https://www.python.org/downloads/ or 'brew install python@3.12')."
echo "Python: $("$py" --version) ($(command -v "$py"))"

# 2. pipx (installs SPIKE in its own environment, without touching system packages)
if ! have pipx; then
  if have brew; then
    step "Install pipx with Homebrew" brew install pipx || die "pipx is required."
  else
    step "Install pipx for this user" "$py" -m pip install --user pipx \
      || die "pipx could not be installed with pip. Install it with your package manager (for example 'sudo apt install pipx') and re-run."
  fi
  step "Add pipx's app folder to PATH" "$py" -m pipx ensurepath || true
fi
pipx_cmd=(pipx)
have pipx || pipx_cmd=("$py" -m pipx)

# 3. Web app (built once from source; release packages will ship it prebuilt)
if [[ ! -f web/dist/index.html ]]; then
  have npm || die "Node.js 18+ with npm is needed to build the web app (https://nodejs.org or 'brew install node')."
  step "Build the web app" bash -c "cd web && npm ci && npm run build" || die "the web app must be built before installing."
fi

# 4. SPIKE itself
step "Install SPIKE with pipx" "${pipx_cmd[@]}" install --force ".[docs,finance,data]" || die "SPIKE was not installed."
bin_dir="$("${pipx_cmd[@]}" environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
spike="$bin_dir/spike"
[[ -x "$spike" ]] || spike="spike"

# 5. llama.cpp (local inference). Optional: SPIKE also works with external providers only.
if have llama-server || [[ -n "${SPIKE_LLAMA_SERVER:-}" ]]; then
  echo
  echo "llama-server: $(command -v llama-server || echo "$SPIKE_LLAMA_SERVER")"
elif have brew; then
  step "Install llama.cpp with Homebrew (official formula)" brew install llama.cpp || true
else
  cat <<'EOF'

llama-server was not found. Install llama.cpp with one of its official methods, then re-run 'spike doctor':
  conda install -c conda-forge llama.cpp      (Linux, macOS, Windows)
  nix profile install nixpkgs#llama-cpp       (Linux, macOS)
  prebuilt binaries: https://github.com/ggml-org/llama.cpp/releases
or point SPIKE at an existing binary with SPIKE_LLAMA_SERVER=/path/to/llama-server.
EOF
fi

# 6. Check the machine and, if you want, download the base model (~2.7 GB, license and SHA-256 checked)
step "Check this machine" "$spike" doctor || true
step "Download the base model Qwen3.5-4B (Q4_K_M, ~2.7 GB)" "$spike" models pull qwen3.5-4b || true

printf '\nDone. Start SPIKE with:  %s serve --open\n' "$spike"
[[ ":$PATH:" == *":$bin_dir:"* ]] || echo "Open a new terminal (or add $bin_dir to PATH) to use 'spike' directly."
