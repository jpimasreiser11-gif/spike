# Desktop launcher (I1)

Run `python -m spike.launcher` in an installed SPIKE environment. It reserves a free IPv4 loopback port, waits for
`/api/health`, and opens pywebview when already installed, otherwise the default browser. No dependencies are added
or installed. In browser mode use **Salir de SPIKE / Quit SPIKE** (closing a browser tab does not stop a server), or
Ctrl-C in the terminal. Closing the native window gracefully stops the HTTP server, owned llama-server and embedding
server and cancels downloads. The OS lock permits one launcher per SPIKE_HOME and releases on crashes.

The first-run wizard checks local free disk and total/available RAM. Its conservative reservation is 6 GiB of disk
plus twice the selected adapter sizes, and 8 GiB total RAM; these are installation guards, not measured inference
requirements. Only **Descargar todo / Download all** contacts Hugging Face. The base model uses the same download,
license and SHA-256 implementation as `spike models pull`, with a mandatory hash and license for the wizard.
Partial files survive interruption; failed checksums are discarded. Completion configures paths without starting
inference. **Más tarde / Later** dismisses this session's wizard for users of external providers.

`spike/launcher/adapters.json` is deliberately empty: every built-in adapter is currently planned in the catalog;
no published repository, revision or checksum has been supplied. Claude can add reviewed entries keyed by specialist
id, each containing `repo`, immutable 40-character commit `revision`, catalog-matching `filename` (e.g.
`spike-code.gguf`), positive byte `size`, `sha256`, and allowed `license`. Until then the wizard explicitly labels
these as instruction profiles with no downloadable adapter. No weights were measured or downloaded for I1.

## Offline PyInstaller staging

Build separately on macOS, Windows and Linux using release tooling with PyInstaller already available. This task does
not install PyInstaller or pywebview and does not add the optional `desktop` extra because dependencies were forbidden.

1. Obtain the appropriate **b11709 CPU** archive from
   https://github.com/ggml-org/llama.cpp/releases/tag/b11709 and the MIT LICENSE from the same tag.
   The six exact asset names and SHA-256 pins live in `stage_llama.py`, verified against the upstream
   [b11709 attestation](https://github.com/ggml-org/llama.cpp/attestations/56945604). Linux pins also match
   `scripts/install.sh`. No hash override is allowed.
2. Stage the local archive, without executing it:
   `python packaging/stage_llama.py ARCHIVE packaging/vendor/TARGET/b11709 --target TARGET --license-file LICENSE`
   TARGET is one of Linux-x86_64, Linux-arm64, Darwin-x86_64, Darwin-arm64, Windows-AMD64, Windows-arm64.
   Staging rejects archive traversal, escaping/cyclic links and colliding flat paths and records hashes for every
   bundled file. Safe in-archive tar library aliases become regular copies, avoiding symlink privileges on Windows.
   Unsupported layouts fail closed and require release review.
3. Build `web/dist` with `cd web && npm run build`, then from the repository root run
   `pyinstaller packaging/spike.spec`. `SPIKE_LLAMA_STAGE` may point to another staging directory.
   The spec verifies the staged file hashes and platform/tag, bundles runtime libraries, LICENSE, manifest, static UI,
   catalog and adapter manifest, and detects pywebview if installed. The launcher selects its bundled llama-server.

The spec was not built with real upstream binaries: native startup, shared-library resolution, macOS bundle behavior
and installer signing remain release checks. DMG, Inno Setup and AppImage wrappers belong to later installer tasks.
