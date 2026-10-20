#!/usr/bin/env bash
# SPIKE installer for macOS and Linux, run from a source checkout:
#
#   scripts/install.sh              # shows each command and asks before running it
#   scripts/install.sh --yes        # runs every step without asking
#   scripts/install.sh --no-model   # leaves out the model download (~2.7 GB), also with --yes
#
# It installs only what it names: pipx (if missing), the SPIKE app (pipx, isolated) and llama.cpp: through Homebrew when
# available, else (Linux x86_64 and aarch64) its official prebuilt CPU build from the ggml-org/llama.cpp releases at a
# pinned tag, SHA-256 checked, under ~/.local/share/spike. It never uses sudo and never downloads a model unless you
# accept that step.
# A step you accepted that fails stops it with exit 1. "Done." is printed only after `spike doctor --strict`
# passed: llama-server found and, unless the model was left out, a model on disk.
set -euo pipefail
cd "$(dirname "$0")/.."

yes=0
no_model=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) yes=1 ;;
    --no-model) no_model=1 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 64 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }
# step "description" cmd args...  -> prints the command, asks, runs it. Returns $skipped when the user declines,
# otherwise the command's own status.
skipped=99
step() {
  local what="$1"; shift
  printf '\n== %s\n   $ %s\n' "$what" "$*"
  if (( ! yes )); then
    local answer
    read -r -p "   Run it? [y/N] " answer </dev/tty || answer=""
    [[ "$answer" == [yY]* ]] || { echo "   skipped"; return "$skipped"; }
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
step "Install SPIKE with pipx" "${pipx_cmd[@]}" install --force ".[docs,finance,data,motion]" || die "SPIKE was not installed."
bin_dir="$("${pipx_cmd[@]}" environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
spike="$bin_dir/spike"
[[ -x "$spike" ]] || spike="spike"

# 5. llama.cpp (local inference). Optional: SPIKE also works with external providers only.
# Linux without Homebrew gets llama.cpp's official prebuilt CPU build. The tag and the SHA-256 of each asset are pinned
# here (sha256sum of <releases>/download/<tag>/llama-<tag>-bin-ubuntu-<arch>.tar.gz); change all three together.
# SPIKE looks for llama-server in $SPIKE_HOME/bin before PATH, so a link there is enough.
llama_tag=b11400
llama_sha_x64=dbad8cd850aa22dff8e50c4adeebeba5750eb80f05e70cd3c8921331db139d1e
llama_sha_arm64=df8e0d8111902f39fa9a697800e5a5ec11a69d69a2ee129c49459e1570257e3b
llama_releases=https://github.com/ggml-org/llama.cpp/releases
llama_link="${SPIKE_HOME:-$HOME/.spike}/bin/llama-server"
llama_root="${XDG_DATA_HOME:-$HOME/.local/share}/spike/llama.cpp"

llama_help() {
  cat <<EOF

llama-server was not found. Install llama.cpp with one of its official methods, then re-run 'spike doctor':
  conda install -c conda-forge llama.cpp      (Linux, macOS, Windows)
  nix profile install nixpkgs#llama-cpp       (Linux, macOS)
  prebuilt binaries: $llama_releases
or point SPIKE at an existing binary with SPIKE_LLAMA_SERVER=/path/to/llama-server.
EOF
}

# fetch_llama_prebuilt WORKDIR ARCH SHA256 -> download, verify, unpack, start once and link; keeps nothing on failure.
# It runs inside `step ... || rc=$?`, where `set -e` is off, so every failure returns explicitly.
fetch_llama_prebuilt() {
  local work="$1" arch="$2" sha="$3" dest="$llama_root/$llama_tag" got
  local asset="llama-$llama_tag-bin-ubuntu-$arch.tar.gz"
  local url="$llama_releases/download/$llama_tag/$asset"
  echo "   downloading $url"
  curl -fsSL --proto '=https' --tlsv1.2 --retry 3 -o "$work/$asset" "$url" || { echo "   the download failed"; return 1; }
  got="$(sha256sum "$work/$asset" | cut -d' ' -f1)"
  if [[ "$got" != "$sha" ]]; then
    printf '   SHA-256 mismatch, nothing was installed:\n     expected %s\n     got      %s\n' "$sha" "$got"
    return 1
  fi
  echo "   SHA-256 verified: $got"
  mkdir "$work/unpacked" && tar -xzf "$work/$asset" -C "$work/unpacked" --strip-components=1 \
    || { echo "   unpacking failed"; return 1; }
  [[ -x "$work/unpacked/llama-server" ]] || { echo "   $asset has no llama-server"; return 1; }
  # a build that cannot start here is worse than none: say what is missing before keeping it
  if ! "$work/unpacked/llama-server" --version >"$work/version.txt" 2>&1; then
    echo "   the downloaded llama-server does not start on this system:"
    sed 's/^/     /' "$work/version.txt"
    { ldd "$work/unpacked/llama-server" 2>&1 | sed -n 's/^[[:space:]]*\(.*\) => not found.*/     missing: \1/p' | sort -u; } || true
    cat <<'EOF'
   llama.cpp's prebuilt Linux build needs glibc 2.34 or newer (Debian 12, Ubuntu 22.04, Fedora 36 or newer; not Alpine)
   and the system libraries libstdc++6, libgomp1 and libssl3. Install what is missing with your package manager (for
   example 'sudo apt install libgomp1 libssl3'), or set SPIKE_LLAMA_SERVER to a llama-server you already have.
EOF
    return 1
  fi
  sed 's/^/   /' "$work/version.txt" | head -n 2
  rm -rf "$dest" && mkdir -p "$llama_root" "$(dirname "$llama_link")" && mv "$work/unpacked" "$dest" \
    && ln -sfn "$dest/llama-server" "$llama_link" || { echo "   could not put llama-server in place"; return 1; }
  echo "   llama-server: $llama_link -> $dest/llama-server"
}

# install_llama_prebuilt ARCH SHA256 -> fetch_llama_prebuilt in a scratch folder next to the destination, removed afterwards
install_llama_prebuilt() {
  local work rc=0
  mkdir -p "$llama_root" && work="$(mktemp -d "$llama_root/.download.XXXXXX")" || return 1
  fetch_llama_prebuilt "$work" "$@" || rc=$?
  rm -rf "$work"
  return "$rc"
}

if have llama-server || [[ -n "${SPIKE_LLAMA_SERVER:-}" ]] || [[ -x "$llama_link" ]]; then
  echo
  echo "llama-server: $(command -v llama-server || echo "${SPIKE_LLAMA_SERVER:-$llama_link}")"
elif have brew; then
  rc=0
  step "Install llama.cpp with Homebrew (official formula)" brew install llama.cpp || rc=$?
  (( rc == 0 || rc == skipped )) \
    || die "llama.cpp was not installed (see above). Fix that and re-run, or set SPIKE_LLAMA_SERVER to a llama-server."
else
  arch="" sha="" size=""
  if [[ "$(uname -s)" == Linux ]]; then
    case "$(uname -m)" in
      x86_64) arch=x64; sha="$llama_sha_x64"; size="~18 MB" ;;
      aarch64|arm64) arch=arm64; sha="$llama_sha_arm64"; size="~14 MB" ;;
    esac
  fi
  rc=$skipped
  if [[ -z "$arch" ]]; then
    :  # no prebuilt CPU build for this system: the instructions below
  elif have curl && have tar && have sha256sum; then
    rc=0
    step "Download llama.cpp $llama_tag from github.com/ggml-org/llama.cpp (official prebuilt CPU build, $size), check its SHA-256 and unpack it into $llama_root/$llama_tag" \
      install_llama_prebuilt "$arch" "$sha" || rc=$?
    (( rc == 0 || rc == skipped )) \
      || die "llama.cpp was not installed (see above). Fix that and re-run, or set SPIKE_LLAMA_SERVER to a llama-server."
  else
    echo
    echo "llama.cpp's prebuilt build is downloaded with curl, tar and sha256sum, and one of them is missing."
  fi
  (( rc == 0 )) || llama_help
fi

# 6. The base model (~2.7 GB, license and SHA-256 checked); --no-model leaves it out without asking
check=(doctor --strict)
if (( no_model )); then
  echo
  echo "Skipping the model download (--no-model)."
else
  rc=0
  step "Download the base model Qwen3.5-4B (Q4_K_M, ~2.7 GB)" "$spike" models pull qwen3.5-4b || rc=$?
  (( rc == 0 || rc == skipped )) \
    || die "the model download failed (see above). Re-run the installer, or run: $spike models pull qwen3.5-4b"
  (( rc == 0 )) || no_model=1  # declined: the final check does not ask for a model either
fi
(( ! no_model )) || check+=(--no-model-check)

# 7. Check the result: shows the memory plan, and fails when llama-server (or the model) is missing
rc=0
step "Check the install" "$spike" "${check[@]}" || rc=$?
(( rc == 0 || rc == skipped )) \
  || die "'spike doctor --strict' failed (see above); SPIKE itself is installed."

printf '\nDone. Start SPIKE with:  %s serve --open\n' "$spike"
[[ ":$PATH:" == *":$bin_dir:"* ]] || echo "Open a new terminal (or add $bin_dir to PATH) to use 'spike' directly."
